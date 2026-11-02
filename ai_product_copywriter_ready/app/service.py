"""Интеграция с Gemini API и однократная попытка исправить формат ответа."""

import json
import os

from pydantic import ValidationError

from .prompts import SYSTEM_PROMPT, build_user_prompt, build_repair_prompt
from .schemas import CardDraft, GeneratedCard, ProductInput
from .validation import (
    MAX_DESCRIPTION_LENGTH,
    MIN_DESCRIPTION_LENGTH,
    build_result,
    validate_draft,
)


class ConfigurationError(RuntimeError):
    """Ошибка локальной конфигурации приложения."""


class GenerationError(RuntimeError):
    """Ошибка обращения к модели или разбора её ответа."""


def _parse_model_response(response) -> CardDraft:
    """Проверяет, что ответ модели — JSON, соответствующий Pydantic-схеме."""
    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, CardDraft):
        return parsed
    if isinstance(parsed, dict):
        try:
            return CardDraft.model_validate(parsed)
        except ValidationError as exc:
            raise GenerationError(f"Ответ модели не соответствует схеме: {exc}") from exc

    raw_text = getattr(response, "text", None)
    if not raw_text:
        raise GenerationError("Модель вернула пустой ответ.")
    try:
        payload = json.loads(raw_text)
        return CardDraft.model_validate(payload)
    except json.JSONDecodeError as exc:
        raise GenerationError("Модель вернула ответ, который не является корректным JSON.") from exc
    except ValidationError as exc:
        raise GenerationError(f"JSON модели не соответствует ожидаемой схеме: {exc}") from exc


def _generate_with_one_repair(product: ProductInput, request_draft) -> GeneratedCard:
    """Вызывает модель один раз и повторяет запрос лишь при ошибках валидации."""
    draft = request_draft(None)
    issues = validate_draft(draft, product)
    if issues:
        # Только одна корректирующая попытка: не допускаем бесконечные вызовы API.
        draft = request_draft(issues)

    result = build_result(product, draft)
    if not MIN_DESCRIPTION_LENGTH <= result.seo_description_length <= MAX_DESCRIPTION_LENGTH:
        # Не возвращаем карточку, которая явно нарушает главное требование ТЗ.
        # Короткий текст нельзя безопасно «дополнить» без риска выдумать факты.
        raise GenerationError(
            "Gemini не смогла подготовить SEO-описание длиной 800–1200 символов "
            "даже после одной попытки исправления. Добавьте факты в исходное описание "
            "или повторите генерацию. Текст не был дополнен предположениями."
        )
    return result


def generate_card(product: ProductInput) -> GeneratedCard:
    """Генерирует черновик, проверяет его и при необходимости просит исправить."""
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise ConfigurationError(
            "Не задан GEMINI_API_KEY. Создайте .env по примеру .env.example "
            "и добавьте ключ Google AI Studio."
        )

    try:
        from google import genai
        from google.genai import errors, types
    except ImportError as exc:
        raise ConfigurationError(
            "Не установлен пакет google-genai. Выполните: pip install -r requirements.txt"
        ) from exc

    model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite").strip()
    if not model:
        raise ConfigurationError("Не задана модель Gemini. Укажите GEMINI_MODEL в .env.")
    try:
        timeout_seconds = int(os.getenv("GEMINI_TIMEOUT", "60"))
        if timeout_seconds <= 0:
            raise ValueError
    except ValueError as exc:
        raise ConfigurationError("GEMINI_TIMEOUT должен быть положительным целым числом.") from exc

    client = None
    try:
        client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=timeout_seconds * 1000),
        )

        current_draft: CardDraft | None = None

        def request_draft(validation_issues: list[str] | None) -> CardDraft:
            nonlocal current_draft
            if validation_issues:
                # В корректирующий запрос передаём первый ответ и точный список нарушений.
                if current_draft is None:
                    raise GenerationError("Не найден исходный черновик для корректирующего запроса.")
                prompt = build_repair_prompt(
                    product.model_dump(),
                    previous_draft=current_draft.model_dump(),
                    validation_issues=validation_issues,
                )
            else:
                prompt = build_user_prompt(product.model_dump())

            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    response_mime_type="application/json",
                    response_schema=CardDraft,
                    # Для Gemini 3.5 Flash-Lite используем настройки температуры по умолчанию.
                    max_output_tokens=4096,
                ),
            )
            if not getattr(response, "text", None) and not getattr(response, "parsed", None):
                raise GenerationError(
                    "Модель не вернула текст. Возможно, запрос остановлен фильтром безопасности."
                )
            current_draft = _parse_model_response(response)
            return current_draft

        return _generate_with_one_repair(product, request_draft)

    except (ConfigurationError, GenerationError):
        raise
    except errors.APIError as exc:
        message = str(exc)
        lowered = message.lower()
        if "429" in message or "resource_exhausted" in lowered or "quota" in lowered:
            raise GenerationError(
                "Бесплатная квота Gemini исчерпана или превышен лимит запросов. "
                "Проверьте квоты проекта в Google AI Studio и повторите позже."
            ) from exc
        if "api key" in lowered or "permission_denied" in lowered or "401" in message:
            raise GenerationError(
                "Gemini отклонил API-ключ. Проверьте GEMINI_API_KEY и доступ проекта к модели."
            ) from exc
        if "404" in message or "not_found" in lowered:
            raise GenerationError(
                f"Модель Gemini «{model}» не найдена или недоступна этому проекту. "
                "Проверьте значение GEMINI_MODEL и доступность модели в AI Studio."
            ) from exc
        raise GenerationError(f"Ошибка Gemini API: {message}") from exc
    except (TimeoutError, OSError) as exc:
        raise GenerationError(
            "Не удалось дождаться ответа Gemini API. Проверьте соединение и повторите."
        ) from exc
    except Exception as exc:
        raise GenerationError(f"Не удалось сформировать карточку: {exc}") from exc
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
