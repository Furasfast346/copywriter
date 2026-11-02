"""Постобработка и проверки результата LLM.

Проверки формата автоматизированы, но семантическая достоверность текста
не может быть гарантирована регулярными выражениями. Карточка остаётся черновиком.
"""

import re
from .schemas import ProductInput, CardDraft, GeneratedCard, ProductSpec

MAX_TITLE_LENGTH = 70
MIN_DESCRIPTION_LENGTH = 800
MAX_DESCRIPTION_LENGTH = 1200
MIN_QUERIES = 3
MAX_QUERIES = 5

NUMBER_WITH_UNIT = re.compile(
    r"(?<![\w])[-+]?\d+(?:[.,]\d+)?\s*(?:%|мм|см|мкм|м|кПа|МПа|Па|бар|атм|В|мВ|А|мА|Вт|кВт|Гц|кГц|МГц|°C|К|кг|г|л|мл|с|мин|ч|об/мин|IP\s*\d{2}|[A-Za-zА-Яа-яЁёµμ/²³]+)?",
    re.IGNORECASE,
)
NUMBER_ONLY = re.compile(r"(?<![\w])[-+]?\d+(?:[.,]\d+)?")


def _normalize_number(value: str) -> str:
    """Сводит десятичную запятую и точку к одному формату."""
    return value.replace(" ", "").replace(",", ".").lower()


def source_text(product: ProductInput) -> str:
    """Собирает значения, которые разрешено использовать как факты."""
    parts = [product.name, product.manufacturer, product.description]
    parts.extend(f"{key}: {value}" for key, value in product.specs.items())
    return " ".join(str(part) for part in parts if part is not None)


def find_unverified_numbers(text: str, source: str) -> list[str]:
    """Ищет в сгенерированном тексте числа/единицы, отсутствующие во входе.

    Это только эвристика: она не понимает смысл значений и диапазонов,
    поэтому каждое совпадение должно проверяться редактором.
    """
    source_normalized = _normalize_number(source)
    suspicious: list[str] = []

    for match in NUMBER_WITH_UNIT.finditer(text):
        token = match.group(0).strip()
        token_normalized = _normalize_number(token)
        if token_normalized in source_normalized:
            continue

        number_match = NUMBER_ONLY.search(token)
        number = _normalize_number(number_match.group(0)) if number_match else ""
        if number and number in source_normalized:
            continue
        if token and token not in suspicious:
            suspicious.append(token)

    return suspicious


def validate_draft(draft: CardDraft, product: ProductInput) -> list[str]:
    """Проверяет ограничения ТЗ до сборки итоговой карточки."""
    warnings: list[str] = []
    title = draft.seo_title.strip()
    description = draft.seo_description.strip()

    if not title:
        warnings.append("SEO-заголовок пустой.")
    elif len(title) > MAX_TITLE_LENGTH:
        warnings.append(f"SEO-заголовок длиннее 70 символов: {len(title)}.")

    if not MIN_DESCRIPTION_LENGTH <= len(description) <= MAX_DESCRIPTION_LENGTH:
        warnings.append(
            f"SEO-описание содержит {len(description)} символов; целевой диапазон — 800–1200."
        )

    if not MIN_QUERIES <= len(draft.key_queries) <= MAX_QUERIES:
        warnings.append("Количество поисковых запросов должно быть от 3 до 5.")
    if any(not query.strip() for query in draft.key_queries):
        warnings.append("В списке поисковых запросов есть пустой элемент.")
    normalized_queries = [query.strip().casefold() for query in draft.key_queries]
    if len(normalized_queries) != len(set(normalized_queries)):
        warnings.append("В списке поисковых запросов есть дубликаты.")

    if not draft.commercial_block.strip():
        warnings.append("Коммерческий блок пустой.")

    generated_text = " ".join(
        [draft.seo_title, draft.seo_description, draft.commercial_block, *draft.key_queries]
    )
    unverified = find_unverified_numbers(generated_text, source_text(product))
    if unverified:
        warnings.append(
            "Обнаружены числа/единицы, не найденные в исходных данных: "
            + ", ".join(unverified)
            + ". Проверьте их вручную."
        )

    return warnings


def _truncate_title(value: str) -> str:
    """Безопасно ограничивает заголовок 70 символами, не обрезая слово без нужды."""
    value = value.strip()
    if len(value) <= MAX_TITLE_LENGTH:
        return value
    shortened = value[:MAX_TITLE_LENGTH]
    if " " in shortened:
        shortened = shortened.rsplit(" ", 1)[0]
    return shortened.rstrip(" ,;:-") or value[:MAX_TITLE_LENGTH]


def _truncate_description(value: str) -> str:
    """Ограничивает слишком длинное описание, по возможности сохраняя целое предложение."""
    value = value.strip()
    if len(value) <= MAX_DESCRIPTION_LENGTH:
        return value

    shortened = value[:MAX_DESCRIPTION_LENGTH]
    # Ищем конец предложения ближе к лимиту. Не укорачиваем слишком сильно:
    # если целого предложения нет, используем последнюю границу слова.
    endings = [shortened.rfind(mark) for mark in (". ", "! ", "? ", ".\n", "!\n", "?\n")]
    sentence_end = max(endings)
    if sentence_end >= MIN_DESCRIPTION_LENGTH:
        return shortened[: sentence_end + 1].rstrip()
    return shortened.rsplit(" ", 1)[0].rstrip()


def _fallback_queries(product: ProductInput) -> list[str]:
    """Составляет безопасные поисковые фразы только из известных входных данных."""
    name = product.name.strip()
    candidates = [name]
    if product.manufacturer:
        candidates.append(f"{name} {product.manufacturer}")
    candidates.extend(
        [
            f"{name} технические характеристики",
            f"{name} паспорт",
            f"купить {name}",
        ]
    )
    # Характеристики используются только в качестве поисковых слов.
    for key, value in product.specs.items():
        if value not in (None, ""):
            candidates.append(f"{name} {key} {value}")
    unique: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        cleaned = " ".join(candidate.split())
        normalized = cleaned.casefold()
        if cleaned and normalized not in seen:
            seen.add(normalized)
            unique.append(cleaned)
        if len(unique) == MAX_QUERIES:
            break
    return unique


def build_result(product: ProductInput, draft: CardDraft) -> GeneratedCard:
    """Собирает финальную карточку и применяет безопасные форматные исправления."""
    warnings = validate_draft(draft, product)

    # Если модель так и не исправила длину заголовка, лучше явно сократить его,
    # чем вернуть нарушение ТЗ. Предупреждение остаётся в ответе.
    title = draft.seo_title.strip() or product.name
    if not draft.seo_title.strip():
        warnings.append("Пустой SEO-заголовок заменён названием товара.")
    if len(title) > MAX_TITLE_LENGTH:
        title = _truncate_title(title)
        warnings.append("SEO-заголовок автоматически сокращён до 70 символов; проверьте формулировку.")

    description = _truncate_description(draft.seo_description)
    if len(draft.seo_description.strip()) > MAX_DESCRIPTION_LENGTH:
        warnings.append("SEO-описание автоматически сокращено до 1200 символов.")
    # Короткое описание не дополняем догадками: это может создать ложные факты.
    if len(description) < MIN_DESCRIPTION_LENGTH:
        warnings.append("SEO-описание короче 800 символов; требуется дополнить по документации товара.")

    # Убираем пустые и повторные запросы. Если осталось меньше трёх,
    # дополняем поисковыми фразами, составленными из известных данных товара.
    queries: list[str] = []
    seen_queries: set[str] = set()
    for query in draft.key_queries:
        cleaned = " ".join(query.strip().split())
        normalized = cleaned.casefold()
        if cleaned and normalized not in seen_queries:
            seen_queries.add(normalized)
            queries.append(cleaned)
    if len(queries) < MIN_QUERIES:
        for candidate in _fallback_queries(product):
            normalized = candidate.casefold()
            if normalized not in seen_queries:
                seen_queries.add(normalized)
                queries.append(candidate)
            if len(queries) == MIN_QUERIES:
                break
        warnings.append("Список поисковых запросов дополнен фразами из исходных данных.")
    if len(queries) > MAX_QUERIES:
        queries = queries[:MAX_QUERIES]
        warnings.append("Количество поисковых запросов сокращено до пяти.")

    commercial_block = draft.commercial_block.strip()
    if not commercial_block:
        commercial_block = (
            "Недостаточно исходных данных для коммерческой рекомендации. "
            "Перед предложением заказчику уточните назначение и параметры по документации производителя."
        )
        warnings.append("Пустой коммерческий блок заменён нейтральной рекомендацией уточнить данные.")

    # Таблица характеристик всегда строится из исходного JSON, не из LLM.
    characteristics = [
        ProductSpec(
            name=str(key),
            value=str(value).strip() if value is not None and str(value).strip() else "данных нет",
        )
        for key, value in product.specs.items()
    ]
    if not characteristics:
        characteristics = [ProductSpec(name="Технические характеристики", value="данных нет")]

    missing = [item.strip() for item in draft.missing_data if item and item.strip()]
    if not product.manufacturer:
        missing.insert(0, "Производитель")
    if not product.description:
        missing.append("Описание или фрагмент технического паспорта")
    if not product.specs:
        missing.append("Технические характеристики")
    else:
        # Пустое значение в конкретном свойстве должно быть видно не только
        # в таблице характеристик, но и в отдельном списке недостающих данных.
        for key, value in product.specs.items():
            if value is None or (isinstance(value, str) and not value.strip()):
                missing.append(f"Значение характеристики «{key}»")

    return GeneratedCard(
        product_name=product.name,
        manufacturer=product.manufacturer or "данных нет",
        seo_title=title,
        seo_description=description,
        seo_description_length=len(description),
        characteristics=characteristics,
        key_queries=queries,
        commercial_block=commercial_block,
        missing_data=list(dict.fromkeys(missing)),
        content_notes=list(dict.fromkeys(note.strip() for note in draft.content_notes if note and note.strip())),
        validation_warnings=list(dict.fromkeys(warnings)),
        review_required=True,
    )
