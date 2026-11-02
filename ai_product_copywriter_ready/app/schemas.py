from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProductInput(BaseModel):
    """Входные данные товара. Пустые необязательные поля нормализуются заранее."""

    model_config = ConfigDict(extra="ignore")

    name: str = Field(..., min_length=1, description="Название товара")
    manufacturer: str = Field(default="", description="Производитель")
    specs: dict[str, Any] = Field(default_factory=dict)
    description: str = Field(default="", description="Описание или фрагмент паспорта")

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Название товара не может быть пустым")
        return value.strip()

    @field_validator("manufacturer", "description", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: Any) -> str:
        # В реальных JSON null и строки из пробелов часто означают отсутствие значения.
        if value is None:
            return ""
        if not isinstance(value, str):
            raise ValueError("Ожидается строковое значение")
        return value.strip()

    @field_validator("specs", mode="before")
    @classmethod
    def normalize_specs(cls, value: Any) -> dict[str, Any]:
        # Не даём null сломать обработку; несуществующие/пустые названия свойств
        # пропускаем, а пустые значения сохраняем как None для вывода «данных нет».
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise ValueError("Поле specs должно быть JSON-объектом")

        normalized: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            key = str(raw_key).strip()
            if not key:
                continue
            if isinstance(raw_value, str):
                cleaned = raw_value.strip()
                normalized[key] = cleaned if cleaned else None
            elif raw_value is None or raw_value == [] or raw_value == {}:
                normalized[key] = None
            else:
                normalized[key] = raw_value
        return normalized


class ProductSpec(BaseModel):
    name: str
    value: str


class CardDraft(BaseModel):
    seo_title: str = Field(description="SEO-заголовок не длиннее 70 символов")
    seo_description: str = Field(description="SEO-описание на русском языке, 800–1200 символов")
    key_queries: list[str] = Field(description="От 3 до 5 поисковых запросов")
    commercial_block: str = Field(description="Краткий B2B-блок для менеджера")
    missing_data: list[str] = Field(description="Что необходимо уточнить")
    content_notes: list[str] = Field(description="Редакторские замечания и ограничения")


class GeneratedCard(BaseModel):
    product_name: str
    manufacturer: str
    seo_title: str
    seo_description: str
    seo_description_length: int
    characteristics: list[ProductSpec]
    key_queries: list[str]
    commercial_block: str
    missing_data: list[str]
    content_notes: list[str]
    validation_warnings: list[str] = Field(default_factory=list)
    review_required: bool = True
