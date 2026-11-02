from app.schemas import ProductInput, CardDraft
from app.validation import build_result, find_unverified_numbers, validate_draft
from app.service import _generate_with_one_repair


def make_draft(**overrides):
    data = {
        "seo_title": "Манометр для измерения давления",
        "seo_description": "Описание товара. " * 60,
        "key_queries": ["манометр", "манометр давления", "купить манометр"],
        "commercial_block": "Назначение и совместимость следует сверить с паспортом.",
        "missing_data": ["Материал корпуса"],
        "content_notes": ["Проверить назначение по паспорту."],
    }
    data.update(overrides)
    return CardDraft(**data)


def test_characteristics_are_copied_from_input():
    product = ProductInput(
        name="Манометр",
        manufacturer="Завод",
        specs={"диапазон": "0–1,6 МПа", "класс": "1,5"},
        description="Измерение давления.",
    )
    result = build_result(product, make_draft())
    assert [(x.name, x.value) for x in result.characteristics] == [
        ("диапазон", "0–1,6 МПа"), ("класс", "1,5")
    ]


def test_whitespace_and_null_optional_fields_are_normalized():
    product = ProductInput(
        name=" Прибор ", manufacturer="  ", description=None,
        specs={" диапазон ": "   ", "класс": None, "": "не должно попасть", "диаметр": "100 мм"},
    )
    result = build_result(product, make_draft())
    assert product.name == "Прибор"
    assert product.manufacturer == ""
    assert product.description == ""
    assert [(item.name, item.value) for item in result.characteristics] == [
        ("диапазон", "данных нет"), ("класс", "данных нет"), ("диаметр", "100 мм")
    ]
    assert result.manufacturer == "данных нет"
    assert "Производитель" in result.missing_data


def test_null_specs_are_treated_as_empty_object():
    product = ProductInput(name="Прибор", specs=None)
    result = build_result(product, make_draft())
    assert product.specs == {}
    assert result.characteristics[0].value == "данных нет"


def test_invalid_specs_type_is_rejected():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ProductInput(name="Прибор", specs=["не объект"])


def test_number_audit_finds_new_values():
    suspicious = find_unverified_numbers(
        "Диапазон 0–10 МПа, питание 220 В", "Диапазон 0–1,6 МПа"
    )
    assert any("10" in value for value in suspicious)
    assert any("220" in value for value in suspicious)


def test_number_audit_accepts_source_numbers_and_decimal_separator():
    suspicious = find_unverified_numbers(
        "Класс точности 1.5, диапазон 0–1,6 МПа",
        "Класс точности 1,5; диапазон 0–1,6 МПа",
    )
    assert suspicious == []


def test_validator_reports_formal_limits_and_duplicate_queries():
    product = ProductInput(name="Манометр", specs={"диапазон": "0–1,6 МПа"})
    draft = make_draft(
        seo_title="Слишком длинный заголовок " * 4,
        seo_description="Коротко",
        key_queries=["манометр", "манометр", "давление"],
    )
    warnings = validate_draft(draft, product)
    assert any("SEO-заголовок длиннее" in warning for warning in warnings)
    assert any("SEO-описание" in warning for warning in warnings)
    assert any("дубликаты" in warning for warning in warnings)


def test_final_title_is_limited_to_70_chars_and_query_list_is_repaired():
    product = ProductInput(name="Манометр DM 02", manufacturer="Манотомь")
    result = build_result(
        product,
        make_draft(seo_title="Очень длинный заголовок " * 6, key_queries=["манометр", " ", "манометр"]),
    )
    assert len(result.seo_title) <= 70
    assert 3 <= len(result.key_queries) <= 5
    assert any("сокращён" in warning for warning in result.validation_warnings)
    assert any("дополнен" in warning for warning in result.validation_warnings)


def test_very_long_description_is_truncated_to_1200_chars():
    product = ProductInput(name="Манометр")
    result = build_result(product, make_draft(seo_description=("Проверенный текст. " * 100)))
    assert result.seo_description_length == len(result.seo_description)
    assert result.seo_description_length <= 1200
    assert result.seo_description_length >= 800


def test_short_description_is_not_padded_with_invented_text():
    product = ProductInput(name="Манометр")
    result = build_result(product, make_draft(seo_description="Короткое описание."))
    assert result.seo_description == "Короткое описание."
    assert any("короче 800" in warning for warning in result.validation_warnings)


def test_repair_is_attempted_exactly_once_if_first_draft_is_invalid():
    product = ProductInput(name="Манометр")
    calls = []

    def fake_request(issues):
        calls.append(issues)
        if issues is None:
            return make_draft(seo_title="Слишком длинный заголовок " * 5)
        return make_draft()

    result = _generate_with_one_repair(product, fake_request)
    assert len(calls) == 2
    assert calls[0] is None
    assert calls[1]
    assert len(result.seo_title) <= 70


def test_valid_draft_does_not_trigger_repair():
    product = ProductInput(name="Манометр")
    calls = []

    def fake_request(issues):
        calls.append(issues)
        return make_draft()

    _generate_with_one_repair(product, fake_request)
    assert calls == [None]


def test_response_parser_accepts_parsed_dict():
    from types import SimpleNamespace
    from app.service import _parse_model_response

    response = SimpleNamespace(parsed={
        "seo_title": "Манометр",
        "seo_description": "Описание",
        "key_queries": ["манометр", "давление", "прибор"],
        "commercial_block": "Назначение уточнить.",
        "missing_data": [],
        "content_notes": [],
    })
    parsed = _parse_model_response(response)
    assert parsed.seo_title == "Манометр"
    assert len(parsed.key_queries) == 3


def test_response_parser_rejects_invalid_json():
    from types import SimpleNamespace
    import pytest
    from app.service import _parse_model_response, GenerationError

    with pytest.raises(GenerationError, match="корректным JSON"):
        _parse_model_response(SimpleNamespace(parsed=None, text="это не JSON"))


def test_empty_title_falls_back_to_product_name():
    product = ProductInput(name="Название прибора")
    result = build_result(product, make_draft(seo_title=""))
    assert result.seo_title == "Название прибора"
    assert any("заменён названием" in warning for warning in result.validation_warnings)


def test_more_than_five_queries_are_limited():
    product = ProductInput(name="Манометр")
    result = build_result(
        product,
        make_draft(key_queries=["запрос 1", "запрос 2", "запрос 3", "запрос 4", "запрос 5", "запрос 6"]),
    )
    assert len(result.key_queries) == 5
    assert any("сокращено до пяти" in warning for warning in result.validation_warnings)


def test_empty_spec_values_are_reported_as_missing_data():
    product = ProductInput(name="Прибор", specs={"диапазон": "   ", "класс": "1,5"})
    result = build_result(product, make_draft())
    assert "Значение характеристики «диапазон»" in result.missing_data


def test_completely_missing_specs_are_reported():
    product = ProductInput(name="Прибор", specs={})
    result = build_result(product, make_draft())
    assert "Технические характеристики" in result.missing_data


def test_missing_api_key_is_reported_before_sdk_call(monkeypatch):
    import pytest
    from app.service import generate_card, ConfigurationError

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(ConfigurationError, match="GEMINI_API_KEY"):
        generate_card(ProductInput(name="Манометр"))


def test_generation_fails_if_description_is_still_too_short_after_repair():
    import pytest
    from app.service import _generate_with_one_repair, GenerationError

    product = ProductInput(name="Манометр")
    calls = []

    def fake_request(issues):
        calls.append(issues)
        return make_draft(seo_description="Слишком короткий текст.")

    with pytest.raises(GenerationError, match="800–1200 символов"):
        _generate_with_one_repair(product, fake_request)
    assert len(calls) == 2
