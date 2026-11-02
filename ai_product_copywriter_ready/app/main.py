from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi import Request
from pydantic import ValidationError

from .schemas import ProductInput
from .service import generate_card, ConfigurationError, GenerationError

app = FastAPI(
    title="AI-помощник товарных описаний",
    description="Прототип генерации B2B-карточек контрольно-измерительных приборов.",
    version="1.1.0",
)

BASE_DIR = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@app.get("/", response_class=HTMLResponse)
def index():
    return (BASE_DIR / "templates" / "index.html").read_text(encoding="utf-8")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/generate")
def generate(payload: dict, request: Request):
    try:
        product = ProductInput.model_validate(payload)
        result = generate_card(product)
        accept = request.headers.get("accept", "")
        if "text/markdown" in accept:
            return PlainTextResponse(to_markdown(result.model_dump()))
        return JSONResponse(result.model_dump())
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors(include_url=False)) from exc
    except ConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except GenerationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/generate/markdown", response_class=PlainTextResponse)
def generate_markdown(payload: dict):
    try:
        product = ProductInput.model_validate(payload)
        result = generate_card(product)
        return to_markdown(result.model_dump())
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors(include_url=False)) from exc
    except ConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except GenerationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


def to_markdown(data: dict) -> str:
    lines = [
        f"# {data['product_name']}",
        f"**Производитель:** {data['manufacturer']}",
        "",
        "## SEO",
        f"**Заголовок:** {data['seo_title']}",
        "",
        data["seo_description"],
        "",
        "## Ключевые характеристики",
    ]
    lines.extend(f"- **{item['name']}:** {item['value']}" for item in data["characteristics"])
    lines += ["", "## Поисковые запросы"]
    lines.extend(f"- {item}" for item in data["key_queries"])
    lines += ["", "## Коммерческий блок", data["commercial_block"], "", "## Требует уточнения"]
    lines.extend(f"- {item}" for item in data["missing_data"] or ["Нет"])
    lines += ["", "## Замечания редактору"]
    lines.extend(f"- {item}" for item in data["content_notes"] or ["Нет"])
    lines += ["", "## Автоматические проверки"]
    lines.extend(f"- {item}" for item in data["validation_warnings"] or ["Предупреждений нет"])
    lines += ["", "> Черновик требует проверки контент-менеджером перед публикацией."]
    return "\n".join(lines)
