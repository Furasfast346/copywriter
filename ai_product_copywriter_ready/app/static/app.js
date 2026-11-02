const $ = (id) => document.getElementById(id);
let lastResult = null;

const sample = {
  name: "Манометр показывающий DM 02",
  manufacturer: "Манотомь",
  specs: {
    "диапазон измерений": "0–1,6 МПа",
    "класс точности": "1,5",
    "присоединение": "G1/2",
    "диаметр корпуса": "100 мм"
  },
  description: "Прибор предназначен для измерения избыточного давления."
};

$("example").addEventListener("click", () => {
  $("payload").value = JSON.stringify(sample, null, 2);
  $("status").textContent = "Пример загружен.";
});

$("generate").addEventListener("click", async () => {
  $("status").textContent = "Генерируем…";
  $("generate").disabled = true;
  $("result").textContent = "";
  try {
    const payload = JSON.parse($("payload").value);
    const response = await fetch("/api/generate", {
      method: "POST",
      headers: {"Content-Type":"application/json", "Accept":"application/json"},
      body: JSON.stringify(payload)
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail ? JSON.stringify(data.detail) : "Ошибка сервера");
    lastResult = data;
    render(data);
    $("copy").disabled = false;
    $("download").disabled = false;
    $("status").textContent = "Готово. Проверьте предупреждения перед публикацией.";
  } catch (error) {
    $("result").innerHTML = `<div class="notice"></div>`;
    $("result").firstChild.textContent = error instanceof SyntaxError
      ? "Некорректный JSON. Проверьте запятые, кавычки и скобки."
      : error.message;
    $("status").textContent = "Не удалось сформировать карточку.";
  } finally {
    $("generate").disabled = false;
  }
});

function section(title, content) {
  const el = document.createElement("section");
  const h = document.createElement("h3"); h.textContent = title;
  el.append(h, content);
  return el;
}
function paragraph(text) {
  const p = document.createElement("p"); p.textContent = text || "—"; return p;
}
function list(items) {
  const ul = document.createElement("ul");
  (items || []).forEach(item => { const li=document.createElement("li"); li.textContent=item; ul.append(li); });
  if (!items || !items.length) { const li=document.createElement("li"); li.textContent="Нет"; ul.append(li); }
  return ul;
}
function render(d) {
  const root = document.createElement("div"); root.className = "result";
  root.append(section("SEO-заголовок", paragraph(d.seo_title)));
  const desc = document.createElement("div");
  desc.append(paragraph(d.seo_description));
  const metric = document.createElement("div"); metric.className="metric";
  metric.textContent = `${d.seo_description_length} символов`;
  desc.append(metric); root.append(section("SEO-описание", desc));
  const specs = document.createElement("ul");
  d.characteristics.forEach(s => { const li=document.createElement("li"); li.textContent=`${s.name}: ${s.value}`; specs.append(li); });
  root.append(section("Ключевые характеристики", specs));
  root.append(section("Поисковые запросы", list(d.key_queries)));
  root.append(section("Коммерческий блок", paragraph(d.commercial_block)));
  root.append(section("Требует уточнения", list(d.missing_data)));
  root.append(section("Заметки редактору", list(d.content_notes)));
  if (d.validation_warnings.length) root.append(section("Предупреждения проверки", list(d.validation_warnings)));
  const notice = document.createElement("div"); notice.className="notice";
  notice.textContent = "Черновик требует проверки контент-менеджером. Автоматическая проверка чисел не заменяет экспертную проверку смысла.";
  root.append(notice);
  $("result").replaceChildren(root);
}
$("copy").addEventListener("click", async () => {
  if (lastResult) { await navigator.clipboard.writeText(JSON.stringify(lastResult, null, 2)); $("status").textContent="JSON скопирован."; }
});
$("download").addEventListener("click", () => {
  if (!lastResult) return;
  const blob = new Blob([JSON.stringify(lastResult, null, 2)], {type:"application/json"});
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a"); a.href=url; a.download="product-card-draft.json"; a.click();
  URL.revokeObjectURL(url);
});
