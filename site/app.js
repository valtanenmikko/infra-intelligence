"use strict";

const fmtInt = new Intl.NumberFormat("fi-FI");
const fmtDec = new Intl.NumberFormat("fi-FI", { maximumFractionDigits: 1 });
const fmtPct = new Intl.NumberFormat("fi-FI", { style: "percent", maximumFractionDigits: 0 });
const fmtDate = new Intl.DateTimeFormat("fi-FI", { day: "numeric", month: "numeric", year: "numeric" });
const fmtShortDate = new Intl.DateTimeFormat("fi-FI", { day: "numeric", month: "numeric" });
const fmtMonth = new Intl.DateTimeFormat("fi-FI", { month: "short" });

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
  // Scope as stated in the notice text (LLM-extracted); empty when the notice gives no figures
  const km = (v) => `${fmtInt.format(Math.round(v))} km`;
  const scope = [
    ["Tiestö", t.road_km, km], ["Sorateitä", t.gravel_road_km, km], ["Talvihoito Ise/Is", t.high_class_winter_km, km],
    ["Kävely ja pyöräily", t.cycleway_km, km], ["Vaativuus", t.difficulty, (v) => v],
    ["Hinnan paino", t.price_share, (v) => fmtPct.format(v)],
  ].filter(([, v]) => v != null);
  const criteria = (t.award_criteria || []).map((c) => `${c.name} ${fmtPct.format(c.share)}`).join(" · ");
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
    scope.length ? el("dl", { class: "scope", "aria-label": "Laajuus ilmoituksen mukaan" },
      scope.map(([label, v, fmt]) => el("div", {}, el("dt", { text: label }), el("dd", { text: fmt(v) })))) : null,
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
      criteria ? el("p", {}, el("strong", { text: "Vertailuperusteet: " }), criteria) : null,
      t.resource_notes?.length ? el("p", {}, el("strong", { text: "Resurssitarve: " }), t.resource_notes.join(" · ")) : null,
      el("p", {}, el("strong", { text: "Aiemmat voittajat: " }), winners),
      t.questions?.length ? el("ul", {}, t.questions.map((q) => el("li", { text: q }))) : null,
      t.url ? el("p", {}, el("a", { href: t.url, target: "_blank", rel: "noopener", text: "Ilmoitus TEDissä ↗" })) : null));
}

// Bid recommendations are made one tender at a time; a contractor still has to choose between contracts
// that start together. Summarise the largest group of bid-worthy contracts with the same start year.
function renderCapacity(openTenders) {
  const box = document.getElementById("capacity");
  const recommended = openTenders.filter((t) => t.recommendation !== "Ei tarjota");
  const byStart = new Map();
  recommended.forEach((t) => {
    const start = parseInt(t.period, 10);
    if (start) byStart.set(start, [...(byStart.get(start) || []), t]);
  });
  const [year, group] = [...byStart.entries()].sort((a, b) => b[1].length - a[1].length)[0] || [];
  box.hidden = !group || group.length < 3;
  if (box.hidden) return null;
  const roads = group.reduce((sum, t) => sum + (t.road_km || 0), 0);
  const deadlines = group.map((t) => t.deadline).sort();
  box.replaceChildren(
    el("strong", { text: `${group.length} tarjoamisen arvoista urakkaa (Tarjoa tai Harkitse) alkaa vuonna ${year}` }),
    ` – ${roads ? `yhteensä noin ${fmtInt.format(Math.round(roads / 100) * 100)} km tiestöä, ` : ""}tarjousten takarajat ` +
    `${fmtDate.format(new Date(deadlines[0]))}–${fmtDate.format(new Date(deadlines[deadlines.length - 1]))}. ` +
    "Suositus arvioi jokaisen urakan erikseen, joten kalusto ja henkilöstö riittävät harvoin kaikkiin. " +
    "Alla oleva suunnittelija valitsee, mihin niistä kannattaa tarjota.");
  return { year, group };
}

/** Probability of winning exactly k contracts, k = 0..n (Poisson binomial, independent tenders). */
function winDistribution(probs) {
  let dist = [1];
  probs.forEach((p) => {
    dist = [...dist, 0].map((v, k) => v * (1 - p) + (k > 0 ? dist[k - 1] * p : 0));
  });
  return dist;
}

/** Win chance in an even contest, from history (winners per bidder); 1 / expected bids only as a fallback. */
const winChance = (t) => t.win_chance ?? 1 / Math.max(t.expected_bids || 3, 1);

/**
 * Greedy bid portfolio: add tenders by expected value (score x win chance), skipping any that would push the
 * chance of winning more contracts than the capacity above the risk limit. Bidding more tenders than the
 * capacity is the point: most bids are lost.
 */
function planPortfolio(candidates, capacity, riskLimit) {
  const ranked = [...candidates].sort((a, b) => b.score * winChance(b) - a.score * winChance(a) || a.days_left - b.days_left);
  const chosen = [];
  ranked.forEach((t) => {
    const dist = winDistribution([...chosen, t].map(winChance));
    const overRisk = dist.slice(capacity + 1).reduce((a, b) => a + b, 0);
    if (overRisk <= riskLimit) chosen.push(t);
  });
  return chosen;
}

function renderPlanner(capacityGroup) {
  const card = document.getElementById("planner");
  card.hidden = !capacityGroup;
  if (!capacityGroup) return;
  const capSel = document.getElementById("plan-capacity");
  const riskSel = document.getElementById("plan-risk");
  capSel.replaceChildren(...[1, 2, 3, 4, 5].map((n) => el("option", { value: n, text: String(n), selected: n === 2 ? "" : null })));
  riskSel.replaceChildren(...[0.05, 0.1, 0.2].map((r) => el("option", { value: r, text: fmtPct.format(r), selected: r === 0.1 ? "" : null })));
  document.getElementById("plan-caption").textContent =
    `Tarjousportfolio: vuonna ${capacityGroup.year} alkavat urakat (${capacityGroup.group.length} ehdokasta)`;
  const draw = () => {
    const capacity = Number(capSel.value);
    const chosen = planPortfolio(capacityGroup.group, capacity, Number(riskSel.value));
    const dist = winDistribution(chosen.map(winChance));
    const expected = chosen.reduce((sum, t) => sum + winChance(t), 0);
    const over = dist.slice(capacity + 1).reduce((a, b) => a + b, 0);
    const atLeastOne = 1 - dist[0];
    document.getElementById("plan-stats").replaceChildren(
      el("div", { class: "tile" }, el("dt", { text: "Tarjottavia urakoita" }), el("dd", { text: fmtInt.format(chosen.length) })),
      el("div", { class: "tile" }, el("dt", { text: "Voittoja keskimäärin" }), el("dd", { text: fmtDec.format(expected) })),
      el("div", { class: "tile" }, el("dt", { text: "Vähintään yksi voitto" }), el("dd", { text: fmtPct.format(atLeastOne) })),
      el("div", { class: "tile" }, el("dt", { text: "Kapasiteetti ylittyy" }), el("dd", { text: fmtPct.format(over) })));
    // Long tails are merged into one "k+" column so the chart stays readable on narrow screens
    const lastShown = Math.min(dist.length - 1, capacity + 3);
    const shown = [...dist.slice(0, lastShown), dist.slice(lastShown).reduce((a, v) => a + v, 0)];
    const max = Math.max(...shown);
    const chart = document.getElementById("plan-dist");
    chart.replaceChildren(...shown.map((v, k) => el("div", { class: "week" },
      el("span", { class: "week-count", text: fmtPct.format(v) }),
      el("div", { class: `week-bar${k > capacity ? " over" : ""}`, style: `height:${(v / max) * 100}%` }, el("span", { style: "flex:1" })),
      el("span", { class: "week-label", text: k === lastShown && lastShown < dist.length - 1 ? `${k}+` : `${k}` }))));
    chart.setAttribute("aria-label", `Voittojen määrän todennäköisyydet: ${dist.map((v, k) => `${k}: ${fmtPct.format(v)}`).join(", ")}`);
    document.getElementById("plan-list").replaceChildren(...[...chosen]
      .sort((a, b) => a.deadline.localeCompare(b.deadline))
      .map((t) => el("li", {},
        el("span", { class: "plan-title", text: t.title }),
        el("span", { class: "plan-meta", text: `${t.score} p · voittomahdollisuus ${fmtPct.format(winChance(t))} · takaraja ${fmtDate.format(new Date(t.deadline))}` }))));
  };
  capSel.addEventListener("change", draw);
  riskSel.addEventListener("change", draw);
  draw();
}

// Open tenders per deadline week (Monday-based), stacked by recommendation, so bid-team peaks are visible
function renderDeadlines(openTenders) {
  const card = document.getElementById("deadline-card");
  card.hidden = openTenders.length === 0;
  if (card.hidden) return;
  const monday = (d) => { const m = new Date(d); m.setHours(0, 0, 0, 0); m.setDate(m.getDate() - ((m.getDay() + 6) % 7)); return m; };
  const weeks = [];
  const last = monday(openTenders.map((t) => t.deadline).sort().at(-1));
  for (let w = monday(new Date()); w <= last; w = new Date(w.getFullYear(), w.getMonth(), w.getDate() + 7)) weeks.push(w);
  const counts = weeks.map((w) => REC_ORDER.map((r) =>
    openTenders.filter((t) => t.recommendation === r && monday(t.deadline).getTime() === w.getTime()).length));
  const max = Math.max(...counts.map((c) => c.reduce((a, b) => a + b, 0)));
  const busiest = weeks[counts.findIndex((c) => c.reduce((a, b) => a + b, 0) === max)];
  document.getElementById("deadline-chart").replaceChildren(...weeks.map((w, i) => {
    const total = counts[i].reduce((a, b) => a + b, 0);
    return el("div", { class: "week", title: `Viikko ${fmtShortDate.format(w)} alkaen: ${total} takarajaa` },
      el("span", { class: "week-count", text: total ? String(total) : "" }),
      el("div", { class: "week-bar", style: `height:${(total / max) * 100}%` },
        ...REC_ORDER.map((r, j) => counts[i][j]
          ? el("span", { "data-rec": r, style: `flex:${counts[i][j]}` }) : null)),
      // Month name on the first week of each month keeps labels readable on narrow screens
      el("span", { class: "week-label", text: w.getDate() <= 7 ? fmtMonth.format(w) : "" }));
  }));
  document.getElementById("deadline-chart").setAttribute("aria-label",
    `Takarajoja ${weeks.length} viikon aikana, eniten (${max}) viikolla ${fmtShortDate.format(busiest)} alkaen`);
}

function renderTenders(openTenders) {
  const catSel = document.getElementById("tender-category");
  const recSel = document.getElementById("tender-rec");
  options(catSel, [...new Set(openTenders.map((t) => t.category))].sort());
  const recCount = (r) => openTenders.filter((t) => t.recommendation === r).length;
  recSel.replaceChildren(el("option", { value: "", text: "Kaikki" }),
    ...REC_ORDER.map((r) => el("option", { value: r, text: `${r} (${recCount(r)})` })));
  const list = document.getElementById("tender-list");
  const more = el("button", { type: "button", class: "show-more" });
  list.after(more);
  let expanded = false;
  const draw = () => {
    const rows = openTenders
      .filter((t) => (!catSel.value || t.category === catSel.value) && (!recSel.value || t.recommendation === recSel.value))
      // Equal scores are common (similar maintenance contracts), so the nearest deadline comes first
      .sort((a, b) => b.score - a.score || a.days_left - b.days_left);
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
      display: (r) => (isValue ? fmtEur(r.won_value_eur) : `${fmtPct.format(r.share_of_awards)} (${fmtInt.format(r.wins)} voittoa)`),
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
  const criteria = (data.criteria || []).filter((r) => r.awards >= 5);  // a band of one or two awards says nothing
  document.getElementById("criteria-card").hidden = criteria.length === 0;
  hbar(document.getElementById("criteria-chart"), criteria, opts("band"));
  table(document.getElementById("criteria-table"), "Kilpailu hinnan painon mukaan", cols("band", "Vertailuperuste"), criteria);
  const s = data.price_spread;
  document.getElementById("spread-callout").textContent =
    `Hintahaarukka: kun sekä alin että ylin tarjous on ilmoitettu (${s.n} hankintaa), ylin tarjous on mediaanina ${fmtPct.format(s.median_spread)} alinta kalliimpi.`;
}

function renderBuyers(data) {
  table(document.getElementById("buyer-table"), "Suurimmat tilaajat", [
    { title: "Tilaaja", cls: "sticky", get: (r) => r.buyer },
    { title: "Ilmoitukset", cls: "num hide-sm", get: (r) => fmtInt.format(r.notices) },
    { title: "Hankinnat", cls: "num", get: (r) => fmtInt.format(r.awards) },
    // Zero means only framework awards, whose value is not attributed
    { title: "Sopimusarvo", cls: "num", get: (r) => (r.awarded_value_eur ? fmtEur(r.awarded_value_eur) : "–") },
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

function renderBacktest(data) {
  const b = data.bid_backtest || {};
  const mae = b.bids_mae_shrunk, cat = b.bids_mae_category, rewin = b.incumbent_rewin_rate, rand = b.random_bidder_win_rate;
  const parts = [];
  if (mae && cat) {
    parts.push(`Takautuva testi: tarjousmäärän ennuste osui keskimäärin ${fmtDec.format(mae.value)} tarjouksen päähän toteutuneesta (${fmtInt.format(mae.n)} ratkaistua hankintaa, pelkällä luokan keskiarvolla ${fmtDec.format(cat.value)}).`);
  }
  if (rewin && rand) {
    parts.push(`Edellinen voittaja voitti seuraavan vastaavan hankinnan ${fmtPct.format(rewin.value)} tapauksista, kun satunnaisen tarjoajan odotusarvo on ${fmtPct.format(rand.value)} (n = ${fmtInt.format(rewin.n)}), joten vakiotoimittajalle ei anneta pisteissä etua.`);
  }
  const note = document.getElementById("backtest-note");
  note.textContent = parts.join(" ");
  note.hidden = parts.length === 0;
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
  renderPlanner(renderCapacity(openTenders));
  renderDeadlines(openTenders);
  renderTenders(openTenders);
  renderMarket(data);
  renderCompetition(data);
  renderBuyers(data);
  renderEval(data);
  renderBacktest(data);
}

main().catch((e) => {
  document.querySelector("main").prepend(el("p", { class: "callout", role: "alert", text: `Datan lataus epäonnistui: ${e.message}` }));
});
