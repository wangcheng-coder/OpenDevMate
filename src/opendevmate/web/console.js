const lang = new URLSearchParams(location.search).get("lang") === "en" ? "en" : "zh";
document.documentElement.lang = lang === "en" ? "en" : "zh-CN";
document.querySelectorAll("[data-lang]").forEach((button) => {
  button.addEventListener("click", () => {
    const next = new URL(location.href);
    next.searchParams.set("lang", button.dataset.lang);
    location.assign(next);
  });
});
async function api(path, options) {
  const headers = Object.assign({"Accept-Language": lang === "en" ? "en" : "zh"}, (options && options.headers) || {});
  const join = path.includes("?") ? "&" : "?";
  const response = await fetch(path + join + "lang=" + lang, Object.assign({}, options, {headers}));
  const text = await response.text();
  let body = text;
  try { body = JSON.parse(text); } catch (error) { body = text; }
  if (!response.ok) {
    const detail = body && body.detail ? body.detail : text;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return body;
}
function show(value) {
  document.getElementById("out").textContent = typeof value === "string" ? value : JSON.stringify(value, null, 2);
}
async function run(action) {
  try { show(await action()); }
  catch (error) { show(error.message); }
}
