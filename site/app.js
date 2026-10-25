"use strict";

const fmtInt = new Intl.NumberFormat("fi-FI");
const fmtDec = new Intl.NumberFormat("fi-FI", { maximumFractionDigits: 1 });
const fmtPct = new Intl.NumberFormat("fi-FI", { style: "percent", maximumFractionDigits: 0 });
const fmtDate = new Intl.DateTimeFormat("fi-FI", { day: "numeric", month: "numeric", year: "numeric" });

function fmtEur(v) {
  if (v == null) return "–";
  if (v >= 1e9) return `${fmtDec.format(v / 1e9)} mrd €`;
  if (v >= 1e6) return `${fmtDec.format(v / 1e6)} M€`;
  return `${fmtInt.format(Math.round(v))} €`;
}

// Build DOM with text nodes only: all data is inserted as text, never as HTML.
function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else node.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) if (c != null) node.append(c instanceof Node ? c : document.createTextNode(c));
  return node;
}

/* ---------- Tooltip ---------- */
const tooltip = document.getElementById("tooltip");
function showTip(evt, text) {
  tooltip.textContent = text;
  tooltip.hidden = false;
  const r = evt.currentTarget.getBoundingClientRect();
  const x = evt.clientX ?? r.left + r.width / 2;
  const y = evt.clientY ?? r.top;
  tooltip.style.left = `${Math.min(x + 14, window.innerWidth - tooltip.offsetWidth - 8)}px`;
  tooltip.style.top = `${Math.max(y - tooltip.offsetHeight - 10, 8)}px`;
}
function hideTip() { tooltip.hidden = true; }

/* ---------- Horizontal bar chart (single series) ---------- */
function hbar(container, rows, { value, label, display, tip, muted = () => false }) {
  const max = Math.max(...rows.map((r) => value(r) ?? 0), 0) || 1;
  container.replaceChildren(
    ...rows.map((r) => {
      const v = value(r);
      const row = el("div", { class: "hbar-row", tabindex: "0", "data-muted": muted(r) ? "true" : null },
        el("span", { class: "hbar-label", title: label(r), text: label(r) }),
        el("span", { class: "hbar-track" },
          el("span", { class: "hbar-bar", style: `width:${v == null ? 0 : (v / max) * 82}%` }),
          el("span", { class: "hbar-value", text: display(r) })));
      row.addEventListener("mousemove", (e) => showTip(e, tip(r)));
      row.addEventListener("mouseleave", hideTip);
      row.addEventListener("focus", (e) => showTip(e, tip(r)));
      row.addEventListener("blur", hideTip);
      return row;
    }),
  );
}

function table(container, columns, rows) {
  const t = el("table", { class: "data-table" },
    el("thead", {}, el("tr", {}, columns.map((c) => el("th", { class: c.num ? "num" : null, scope: "col", text: c.title })))),
    el("tbody", {}, rows.map((r) => el("tr", {}, columns.map((c) => el("td", { class: c.num ? "num" : null, text: c.get(r) }))))));
  if (container.tagName === "TABLE") container.replaceWith(Object.assign(t, { id: container.id }));
  else container.replaceChildren(t);
}

/* ---------- Sections ---------- */
function renderMeta(data) {
  document.getElementById("sample-banner").hidden = !data.meta.sample;
  document.querySelectorAll("[data-meta]").forEach((n) => {
    const v = data.meta[n.dataset.meta];
    n.textContent = Array.isArray(v) ? v.join(", ") : n.dataset.meta === "generated_at" ? fmtDate.format(new Date(v)) : v;
  });
  const k = data.kpis;
  const values = {
    single_winner_value_eur: fmtEur(k.single_winner_value_eur),
    notices: fmtInt.format(k.notices),
    awards: fmtInt.format(k.awards),
    avg_bids: fmtDec.format(k.avg_bids),
    share_low_competition: fmtPct.format(k.share_low_competition),
  };
  document.querySelectorAll("[data-kpi]").forEach((n) => { n.textContent = values[n.dataset.kpi] ?? "–"; });
}

const REC_ORDER = ["Tarjoa", "Harkitse", "Ei tarjota"];

function tenderCard(t) {
  const factor = (name, value, hint) => el("div", { class: "factor" },
    `${name} ${value}/5`, el("div", { class: "meter", title: hint }, el("span", { style: `width:${(value / 5) * 100}%` })));
  const winners = t.past_winners?.length
    ? t.past_winners.map((w) => `${w.company} (${w.wins})`).join(", ")
    : "ei aiempia voittoja tiedossa";
  return el("li", { class: "tender" },
    el("div", {},
      el("h3", { text: t.title }),
      el("div", { class: "tender-meta" },
        el("span", { text: t.buyer }),
        el("span", { text: t.category }),
        t.region ? el("span", {}, t.region, t.region_from_llm ? el("span", { class: "llm", text: " · AI-päätelty" }) : null) : null,
        el("span", { text: `Jätettävä ${fmtDate.format(new Date(t.deadline))} (${t.days_left} pv)` }),
        t.period ? el("span", { text: `Kausi ${t.period}${t.option_years ? ` + ${fmtDec.format(t.option_years)} v optio` : ""}` }) : null)),
    el("div", { class: "verdict" },
      el("span", { class: "badge", "data-rec": t.recommendation, text: t.recommendation }),
      el("div", { class: "score" }, String(t.score), el("small", { text: " / 100" }))),
    el("div", { class: "factors" },
      factor("Soveltuvuus", t.fit, "Tekoälyn arvio"),
      factor("Kilpailu", t.competition, `Laskettu historiasta: odotettu ${t.expected_bids ?? "?"} tarjousta`),
      factor("Riski (5 = matala)", t.risk, "Tekoälyn arvio")),
    el("details", {},
      el("summary", { text: "Perustelut ja historia" }),
      el("p", { text: t.summary }),
      el("p", {}, el("strong", { text: "Soveltuvuus: " }), t.fit_reason),
      el("p", {}, el("strong", { text: "Riskit: " }), t.risk_reason),
      el("p", {}, el("strong", { text: "Aiemmat voittajat: " }), winners),
      t.questions?.length ? el("ul", {}, t.questions.map((q) => el("li", { text: q }))) : null,
      el("p", {}, el("a", { href: t.url, target: "_blank", rel: "noopener", text: "Ilmoitus TEDissä ↗" }))));
}

function renderTenders(data) {
  const catSel = document.getElementById("tender-category");
  const recSel = document.getElementById("tender-rec");
  const cats = [...new Set(data.open_tenders.map((t) => t.category))].sort();
  catSel.replaceChildren(el("option", { value: "", text: "Kaikki" }), ...cats.map((c) => el("option", { value: c, text: c })));
  recSel.replaceChildren(el("option", { value: "", text: "Kaikki" }), ...REC_ORDER.map((r) => el("option", { value: r, text: r })));
  const list = document.getElementById("tender-list");
  const draw = () => {
    const rows = data.open_tenders
      .filter((t) => (!catSel.value || t.category === catSel.value) && (!recSel.value || t.recommendation === recSel.value))
      .sort((a, b) => b.score - a.score);
    list.replaceChildren(...(rows.length ? rows.map(tenderCard) : [el("li", { class: "empty", text: "Ei kilpailutuksia valinnoilla." })]));
  };
  catSel.addEventListener("change", draw);
  recSel.addEventListener("change", draw);
  draw();
}

function renderMarket(data) {
  const rows = data.market_share.filter((r) => r.category === "Kaikki");
  const chart = document.getElementById("market-chart");
  const caption = document.getElementById("market-caption");
  const buttons = document.querySelectorAll("[data-measure]");
  const draw = (measure) => {
    const sorted = [...rows].sort((a, b) => (b[measure] ?? -1) - (a[measure] ?? -1));
    const isValue = measure === "won_value_eur";
    caption.textContent = isValue ? "Voitettujen yhden voittajan sopimusten arvo" : "Voitetut hankinnat";
    hbar(chart, sorted, {
      value: (r) => r[measure],
      label: (r) => r.company,
      display: (r) => (isValue ? fmtEur(r.won_value_eur) : fmtInt.format(r.wins)),
      tip: (r) => `${r.company}: ${fmtInt.format(r.wins)} voittoa, ${fmtEur(r.won_value_eur)} (${fmtPct.format(r.share_of_wins)} voitoista)`,
      muted: (r) => r.company === "Muut toimijat",
    });
    buttons.forEach((b) => b.setAttribute("aria-checked", String(b.dataset.measure === measure)));
  };
  buttons.forEach((b) => b.addEventListener("click", () => draw(b.dataset.measure)));
  draw("wins");
  table(document.getElementById("market-table"), [
    { title: "Yritys", get: (r) => r.company },
    { title: "Voitot", num: true, get: (r) => fmtInt.format(r.wins) },
    { title: "Sopimusarvo", num: true, get: (r) => fmtEur(r.won_value_eur) },
    { title: "Osuus voitoista", num: true, get: (r) => fmtPct.format(r.share_of_wins) },
  ], rows);
}

function renderCompetition(data) {
  const byLow = (a, b) => b.share_low_competition - a.share_low_competition;
  const opts = (key) => ({
    value: (r) => r.share_low_competition,
    label: (r) => r[key],
    display: (r) => fmtPct.format(r.share_low_competition),
    tip: (r) => `${r[key]}: ${fmtInt.format(r.awards)} hankintaa, keskimäärin ${fmtDec.format(r.avg_bids)} tarjousta`,
  });
  hbar(document.getElementById("competition-chart"), [...data.competition].sort(byLow), opts("category"));
  hbar(document.getElementById("region-chart"), [...data.regions].sort(byLow), opts("region"));
  const cols = (key, title) => [
    { title, get: (r) => r[key] },
    { title: "Hankinnat", num: true, get: (r) => fmtInt.format(r.awards) },
    { title: "Tarjouksia ka.", num: true, get: (r) => fmtDec.format(r.avg_bids) },
    { title: "≤ 2 tarjousta", num: true, get: (r) => fmtPct.format(r.share_low_competition) },
  ];
  table(document.getElementById("competition-table"), cols("category", "Luokka"), data.competition);
  table(document.getElementById("region-table"), cols("region", "Maakunta"), data.regions);
  const s = data.price_spread;
  document.getElementById("spread-callout").textContent =
    `Hintahaarukka: kun sekä alin että ylin tarjous on ilmoitettu (${s.n} hankintaa), ylin tarjous on mediaanina ${fmtPct.format(s.median_spread)} alinta kalliimpi.`;
}

function renderBuyers(data) {
  table(document.getElementById("buyer-table"), [
    { title: "Tilaaja", get: (r) => r.buyer },
    { title: "Ilmoitukset", num: true, get: (r) => fmtInt.format(r.notices) },
    { title: "Hankinnat", num: true, get: (r) => fmtInt.format(r.awards) },
    { title: "Sopimusarvo", num: true, get: (r) => fmtEur(r.awarded_value_eur) },
    { title: "Pääluokka", get: (r) => r.main_category },
    { title: "Tarjouksia ka.", num: true, get: (r) => fmtDec.format(r.avg_bids) },
    { title: "Useimmin voittanut", get: (r) => (r.top_winner ? `${r.top_winner} (${fmtPct.format(r.top_winner_share)})` : "–") },
  ], data.buyers);
}

function renderEval(data) {
  document.getElementById("eval-tiles").replaceChildren(...data.llm_eval.map((m) =>
    el("div", { class: "tile" },
      el("dt", { text: m.label }),
      el("dd", {}, m.value == null ? "–" : fmtPct.format(m.value),
        el("small", { text: m.n == null ? "odottaa ajoa" : `n = ${fmtInt.format(m.n)}` })))));
}

/* ---------- Theme ---------- */
function initTheme() {
  const root = document.documentElement;
  try { const saved = localStorage.getItem("theme"); if (saved) root.dataset.theme = saved; } catch { /* storage unavailable */ }
  document.querySelector("[data-action=theme]").addEventListener("click", () => {
    const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    root.dataset.theme = dark ? "light" : "dark";
    try { localStorage.setItem("theme", root.dataset.theme); } catch { /* ignore */ }
  });
}

async function main() {
  initTheme();
  const res = await fetch("data/site.json", { cache: "no-cache" });
  if (!res.ok) throw new Error(`site.json: ${res.status}`);
  const data = await res.json();
  renderMeta(data);
  renderTenders(data);
  renderMarket(data);
  renderCompetition(data);
  renderBuyers(data);
  renderEval(data);
}

main().catch((e) => {
  document.querySelector("main").prepend(el("p", { class: "callout", text: `Datan lataus epäonnistui: ${e.message}` }));
});
