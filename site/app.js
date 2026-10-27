"use strict";

const fmtInt = new Intl.NumberFormat("fi-FI");
const fmtDec = new Intl.NumberFormat("fi-FI", { maximumFractionDigits: 1 });
const fmtPct = new Intl.NumberFormat("fi-FI", { style: "percent", maximumFractionDigits: 0 });
const fmtDate = new Intl.DateTimeFormat("fi-FI", { day: "numeric", month: "numeric", year: "numeric" });
const fmtShortDate = new Intl.DateTimeFormat("fi-FI", { day: "numeric", month: "numeric" });

const OTHERS = "Muut toimijat";
const SMALL_SAMPLE = 15;
const TENDERS_COLLAPSED = 6;
const REC_ORDER = ["Tarjoa", "Harkitse", "Ei tarjota"];

function fmtEur(v) {
  if (v == null) return "–";
  if (v >= 1e9) return `${fmtDec.format(v / 1e9)} mrd €`;
  if (v >= 1e6) return `${fmtDec.format(v / 1e6)} M€`;
  return `${fmtInt.format(Math.round(v))} €`;
}

/** Whole days until the end of the deadline day (Finnish time); negative when passed. */
function daysLeft(deadline) {
  return Math.ceil((new Date(`${deadline}T23:59:59+02:00`) - Date.now()) / 864e5);
}

// Build DOM with text nodes only: data is always inserted as text, never as HTML.
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

/* ---------- Tooltip (mouse only; every value is also in the row label and the table view) ---------- */
const tooltip = document.getElementById("tooltip");
function showTip(evt, text) {
  tooltip.textContent = text;
  tooltip.hidden = false;
  tooltip.style.left = `${Math.min(evt.clientX + 14, window.innerWidth - tooltip.offsetWidth - 8)}px`;
  tooltip.style.top = `${Math.max(evt.clientY - tooltip.offsetHeight - 10, 8)}px`;
}
function hideTip() { tooltip.hidden = true; }

/* ---------- Horizontal bar chart (single series) ---------- */
function hbar(container, rows, { value, label, display, tip, muted = () => false }) {
  const max = Math.max(...rows.map((r) => value(r) ?? 0), 0) || 1;
  container.replaceChildren(
    ...rows.map((r) => {
      const v = value(r);
      const row = el("div", { class: "hbar-row", role: "listitem", "aria-label": `${label(r)}: ${display(r)}`, "data-muted": muted(r) ? "true" : null },
        el("span", { class: "hbar-label", title: label(r), text: label(r), "aria-hidden": "true" }),
        el("span", { class: "hbar-track", "aria-hidden": "true" },
          el("span", { class: "hbar-bar", style: `width:${v == null ? 0 : (v / max) * 82}%` }),
          el("span", { class: "hbar-value", text: display(r) })));
      row.addEventListener("mousemove", (e) => showTip(e, tip(r)));
      row.addEventListener("mouseleave", hideTip);
      return row;
    }),
  );
}

function table(container, caption, columns, rows) {
  container.replaceChildren(el("table", { class: "data-table" },
    el("caption", { class: "visually-hidden", text: caption }),
    el("thead", {}, el("tr", {}, columns.map((c) => el("th", { class: c.cls, scope: "col", text: c.title })))),
    el("tbody", {}, rows.map((r) => el("tr", {}, columns.map((c) => el("td", { class: c.cls, text: c.get(r) })))))));
}

function options(select, values, allLabel = "Kaikki") {
  select.replaceChildren(el("option", { value: "", text: allLabel }), ...values.map((v) => el("option", { value: v, text: v })));
}

/* ---------- Sections ---------- */
function renderMeta(data, openTenders) {
  document.getElementById("sample-banner").hidden = !data.meta.sample;
  document.querySelectorAll("[data-meta]").forEach((n) => {
    const v = data.meta[n.dataset.meta];
    n.textContent = n.dataset.meta === "generated_at" ? fmtDate.format(new Date(v)) : v;
  });
  const k = data.kpis;
  const next = openTenders.map((t) => t.deadline).sort()[0];
  const values = {
    open_now: fmtInt.format(openTenders.length),
    next_deadline: next ? ` · seuraava takaraja ${fmtShortDate.format(new Date(next))}` : "",
    single_winner_value_eur: fmtEur(k.single_winner_value_eur),
    notices: fmtInt.format(k.notices),
    awards: fmtInt.format(k.awards),
    avg_bids: fmtDec.format(k.avg_bids),
    share_low_competition: fmtPct.format(k.share_low_competition),
  };
  document.querySelectorAll("[data-kpi]").forEach((n) => { n.textContent = values[n.dataset.kpi] ?? "–"; });
}

function tenderCard(t) {
  const factor = (name, value, note) => el("div", { class: "factor" },
    el("span", { class: "factor-name", text: `${name} ${value}/5` }),
    el("div", { class: "meter", "aria-hidden": "true" }, el("span", { style: `width:${(value / 5) * 100}%` })),
    note ? el("span", { class: "factor-note", text: note }) : null);
  const winners = t.past_winners?.length
    ? t.past_winners.map((w) => `${w.company} (${w.wins})`).join(", ")
    : "ei aiempia voittoja tiedossa";
  const days = t.days_left;
  return el("li", { class: "tender" },
    el("div", {},
      el("h3", { text: t.title }),
      el("div", { class: "tender-meta" },
        el("span", { text: t.buyer }),
        el("span", { text: t.category }),
        t.region ? el("span", {}, t.region, t.region_from_llm ? el("span", { class: "llm", text: " · AI-päätelty" }) : null) : null,
        el("span", { class: days <= 14 ? "urgent" : null, text: `Takaraja ${fmtDate.format(new Date(t.deadline))} (${days} pv)` }),
        t.period ? el("span", { text: `Kausi ${t.period}${t.option_years ? ` + ${fmtDec.format(t.option_years)} v optio` : ""}` }) : null)),
    el("div", { class: "verdict" },
      el("span", { class: "badge", "data-rec": t.recommendation, text: t.recommendation }),
      el("div", { class: "score" }, String(t.score), el("small", { text: " / 100" }))),
    el("div", { class: "factors" },
      factor("Soveltuvuus", t.fit, "tekoälyn arvio"),
      factor("Kilpailu (5 = vähäinen)", t.competition,
        t.expected_bids != null ? `odotettu ${fmtDec.format(t.expected_bids)} tarjousta` : "ei historiaa"),
      factor("Riski (5 = matala)", t.risk, "tekoälyn arvio")),
    el("details", {},
      el("summary", { text: "Perustelut ja historia" }),
      el("p", { text: t.summary }),
      el("p", {}, el("strong", { text: "Soveltuvuus: " }), t.fit_reason),
      el("p", {}, el("strong", { text: "Riskit: " }), t.risk_reason),
      el("p", {}, el("strong", { text: "Aiemmat voittajat: " }), winners),
      t.questions?.length ? el("ul", {}, t.questions.map((q) => el("li", { text: q }))) : null,
      t.url ? el("p", {}, el("a", { href: t.url, target: "_blank", rel: "noopener", text: "Ilmoitus TEDissä ↗" })) : null));
}

function renderTenders(openTenders) {
  const catSel = document.getElementById("tender-category");
  const recSel = document.getElementById("tender-rec");
  options(catSel, [...new Set(openTenders.map((t) => t.category))].sort());
  options(recSel, REC_ORDER);
  const list = document.getElementById("tender-list");
  const more = el("button", { type: "button", class: "show-more" });
  list.after(more);
  let expanded = false;
  const draw = () => {
    const rows = openTenders
      .filter((t) => (!catSel.value || t.category === catSel.value) && (!recSel.value || t.recommendation === recSel.value))
      .sort((a, b) => b.score - a.score);
    const shown = expanded ? rows : rows.slice(0, TENDERS_COLLAPSED);
    list.replaceChildren(...(rows.length ? shown.map(tenderCard) : [el("li", { class: "empty", text: "Ei avoimia kilpailutuksia valinnoilla." })]));
    more.hidden = rows.length <= TENDERS_COLLAPSED;
    more.textContent = expanded ? "Näytä vähemmän" : `Näytä kaikki ${rows.length}`;
    more.setAttribute("aria-expanded", String(expanded));
  };
  more.addEventListener("click", () => {
    expanded = !expanded;
    draw();
    if (!expanded) document.getElementById("tenders").scrollIntoView();
  });
  const reset = () => { expanded = false; draw(); };
  catSel.addEventListener("change", reset);
  recSel.addEventListener("change", reset);
  draw();
}

function renderMarket(data) {
  const catSel = document.getElementById("market-category");
  const categories = [...new Set(data.market_share.map((r) => r.category))].filter((c) => c !== "Kaikki").sort();
  options(catSel, categories, "Kaikki luokat");
  document.getElementById("market-category-label").hidden = categories.length === 0;
  const buttons = document.querySelectorAll("[data-measure]");
  let measure = "wins";

  const draw = () => {
    const category = catSel.value || "Kaikki";
    const all = data.market_share.filter((r) => r.category === category);
    const isValue = measure === "won_value_eur";
    const shown = all.filter((r) => !isValue || r.won_value_eur != null);
    const companies = shown.filter((r) => r.company !== OTHERS).sort((a, b) => b[measure] - a[measure]);
    const others = shown.filter((r) => r.company === OTHERS);
    const n = all[0]?.slice_awards;
    document.getElementById("market-caption").textContent = isValue
      ? "Voitettujen yhden voittajan sopimusten arvo"
      : `Voitetut hankinnat${n ? ` (yhteensä ${fmtInt.format(n)} hankintaa)` : ""}`;
    hbar(document.getElementById("market-chart"), [...companies, ...others], {
      value: (r) => r[measure],
      label: (r) => r.company,
      display: (r) => (isValue ? fmtEur(r.won_value_eur) : `${fmtInt.format(r.wins)} · ${fmtPct.format(r.share_of_awards)}`),
      tip: (r) => `${r.company}: ${fmtInt.format(r.wins)} voittoa (${fmtPct.format(r.share_of_awards)} hankinnoista), ${fmtEur(r.won_value_eur)}`,
      muted: (r) => r.company === OTHERS,
    });
    const missing = all.length - shown.length;
    document.getElementById("market-note").textContent = [
      others.length ? `${OTHERS} = yksityiset elinkeinonharjoittajat ja tunnistamattomat voittajat, nimet piilotettu.` : "",
      missing ? `${missing} yrityksen sopimusarvo ei tiedossa (vain puitejärjestelyjä).` : "",
    ].join(" ");
    buttons.forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.measure === measure)));
    table(document.getElementById("market-table"), "Markkinaosuudet", [
      { title: "Yritys", get: (r) => r.company },
      { title: "Voitot", cls: "num", get: (r) => fmtInt.format(r.wins) },
      { title: "Osuus hankinnoista", cls: "num", get: (r) => fmtPct.format(r.share_of_awards) },
      { title: "Sopimusarvo", cls: "num", get: (r) => fmtEur(r.won_value_eur) },
    ], [...all.filter((r) => r.company !== OTHERS).sort((a, b) => b.wins - a.wins), ...all.filter((r) => r.company === OTHERS)]);
  };
  buttons.forEach((b) => b.addEventListener("click", () => { measure = b.dataset.measure; draw(); }));
  catSel.addEventListener("change", draw);
  draw();
}

function renderCompetition(data) {
  const byLow = (a, b) => b.share_low_competition - a.share_low_competition;
  const opts = (key) => ({
    value: (r) => r.share_low_competition,
    label: (r) => `${r[key]} (${fmtInt.format(r.awards)})`,
    display: (r) => fmtPct.format(r.share_low_competition),
    tip: (r) => `${r[key]}: ${fmtInt.format(r.awards)} hankintaa, keskimäärin ${fmtDec.format(r.avg_bids)} tarjousta`,
    muted: (r) => r.awards < SMALL_SAMPLE,
  });
  hbar(document.getElementById("competition-chart"), [...data.competition].sort(byLow), opts("category"));
  hbar(document.getElementById("region-chart"), [...data.regions].sort(byLow), opts("region"));
  const minRegion = Math.min(...data.regions.map((r) => r.awards));
  document.getElementById("region-caption").textContent =
    `Maakunnittain (${data.regions.length} maakuntaa, joissa vähintään ${minRegion} hankintaa)`;
  const cols = (key, title) => [
    { title, get: (r) => r[key] },
    { title: "Hankinnat", cls: "num", get: (r) => fmtInt.format(r.awards) },
    { title: "Tarjouksia ka.", cls: "num", get: (r) => fmtDec.format(r.avg_bids) },
    { title: "≤ 2 tarjousta", cls: "num", get: (r) => fmtPct.format(r.share_low_competition) },
  ];
  table(document.getElementById("competition-table"), "Kilpailu hankintaluokittain", cols("category", "Luokka"), data.competition);
  table(document.getElementById("region-table"), "Kilpailu maakunnittain", cols("region", "Maakunta"), data.regions);
  const s = data.price_spread;
  document.getElementById("spread-callout").textContent =
    `Hintahaarukka: kun sekä alin että ylin tarjous on ilmoitettu (${s.n} hankintaa), ylin tarjous on mediaanina ${fmtPct.format(s.median_spread)} alinta kalliimpi.`;
}

function renderBuyers(data) {
  table(document.getElementById("buyer-table"), "Suurimmat tilaajat", [
    { title: "Tilaaja", cls: "sticky", get: (r) => r.buyer },
    { title: "Ilmoitukset", cls: "num hide-sm", get: (r) => fmtInt.format(r.notices) },
    { title: "Hankinnat", cls: "num", get: (r) => fmtInt.format(r.awards) },
    { title: "Sopimusarvo", cls: "num", get: (r) => fmtEur(r.awarded_value_eur) },
    { title: "Pääluokka", cls: "hide-sm", get: (r) => r.main_category },
    { title: "Tarjouksia ka.", cls: "num", get: (r) => fmtDec.format(r.avg_bids) },
    { title: "Useimmin voittanut", get: (r) => (r.top_winner ? `${r.top_winner} (${fmtPct.format(r.top_winner_share)})` : "–") },
  ], data.buyers);
}

function renderEval(data) {
  const metrics = data.llm_eval.filter((m) => m.value != null);
  document.getElementById("eval-block").hidden = metrics.length === 0;
  document.getElementById("eval-tiles").replaceChildren(...metrics.map((m) =>
    el("div", { class: "tile" },
      el("dt", { text: m.label }),
      el("dd", {}, fmtPct.format(m.value), el("small", { text: `n = ${fmtInt.format(m.n)}` })))));
}

async function main() {
  const res = await fetch("data/site.json", { cache: "no-cache" });
  if (!res.ok) throw new Error(`site.json: ${res.status}`);
  const data = await res.json();
  // Deadlines are evaluated in the browser so the static page never shows expired tenders or stale day counts
  const openTenders = data.open_tenders
    .map((t) => ({ ...t, days_left: daysLeft(t.deadline) }))
    .filter((t) => t.days_left >= 0);
  renderMeta(data, openTenders);
  renderTenders(openTenders);
  renderMarket(data);
  renderCompetition(data);
  renderBuyers(data);
  renderEval(data);
}

main().catch((e) => {
  document.querySelector("main").prepend(el("p", { class: "callout", role: "alert", text: `Datan lataus epäonnistui: ${e.message}` }));
});
