from fastapi.testclient import TestClient

from app.main import app
from app.schemas import ProductInput, CardDraft
from app.validation import build_result

client = TestClient(app)


def _fake_card():
    product = ProductInput(name="Тестовый манометр")
    draft = CardDraft(
        seo_title="Тестовый манометр",
        seo_description="Описание товара. " * 60,
        key_queries=["тестовый манометр", "манометр тест", "прибор для давления"],
        commercial_block="Перед предложением проверьте параметры по паспорту.",
        missing_data=[],
        content_notes=[],
    )
    return build_result(product, draft)


def test_health_endpoint_returns_ok():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_generate_rejects_missing_product_name():
    response = client.post("/api/generate", json={"manufacturer": "Завод"})
    assert response.status_code == 422


def test_generate_returns_json_when_generator_is_stubbed(monkeypatch):
    monkeypatch.setattr("app.main.generate_card", lambda product: _fake_card())
    response = client.post("/api/generate", json={"name": "Тестовый манометр"})
    assert response.status_code == 200
    data = response.json()
    assert data["product_name"] == "Тестовый манометр"
    assert 3 <= len(data["key_queries"]) <= 5


def test_generate_maps_missing_api_key_to_503(monkeypatch):
    from app.service import ConfigurationError

    def fail(_product):
        raise ConfigurationError("Не задан API-ключ")

    monkeypatch.setattr("app.main.generate_card", fail)
    response = client.post("/api/generate", json={"name": "Тестовый манометр"})
    assert response.status_code == 503
    assert "API-ключ" in response.json()["detail"]


def test_generate_maps_provider_error_to_502(monkeypatch):
    from app.service import GenerationError

    def fail(_product):
        raise GenerationError("Ошибка провайдера")

    monkeypatch.setattr("app.main.generate_card", fail)
    response = client.post("/api/generate", json={"name": "Тестовый манометр"})
    assert response.status_code == 502
    assert "провайдера" in response.json()["detail"]


def test_generate_markdown_returns_plain_text_when_generator_is_stubbed(monkeypatch):
    monkeypatch.setattr("app.main.generate_card", lambda product: _fake_card())
    response = client.post("/api/generate/markdown", json={"name": "Тестовый манометр"})
    assert response.status_code == 200
    assert "# Тестовый манометр" in response.text
    assert "## SEO" in response.text
