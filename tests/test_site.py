"""Browser tests for the static site: page behaviour, accessibility and the bid portfolio maths.

They need Playwright with Chromium (`pip install playwright && python -m playwright install chromium`) and are
skipped without it. The page runs on the committed `site/data/site.json`, so the checks are invariants that hold
for any day's data; the maths tests use fixed inputs and compare against brute force.
"""

import functools
import threading
import unittest
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    raise unittest.SkipTest("Playwright is not installed")

SITE_DIR = Path(__file__).resolve().parents[1] / "site"
AXE_URL = "https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.9.1/axe.min.js"

# Every subset of `cands` checked against the risk limit; returns the best total expected value.
BRUTE_FORCE_JS = """
([cands, modeName, capUnits, riskLimit]) => {
  const mode = PLAN_MODES[modeName];
  const value = (t) => t.score * winChance(t);
  const fits = (set) => overRisk(sizeDistribution(set.map((c) => ({ p: winChance(c), size: mode.size(c) }))), capUnits) <= riskLimit;
  let best = 0;
  for (let mask = 0; mask < 1 << cands.length; mask++) {
    const set = cands.filter((_, i) => mask & (1 << i));
    const total = set.reduce((s, t) => s + value(t), 0);
    if (total > best && fits(set)) best = total;
  }
  const chosen = planPortfolio(cands, mode, capUnits, riskLimit);
  return { best, planned: chosen.reduce((s, t) => s + value(t), 0), plannedFits: fits(chosen) };
}
"""

# Deterministic candidates: scores 30-90, win chances 0.15-0.65, road lengths 300-1 300 km.
CANDIDATES = [
    {"score": 30 + (i * 37) % 61, "win_chance": 0.15 + ((i * 7) % 11) / 20, "road_km": 300 + (i * 433) % 1001,
     "days_left": i}
    for i in range(11)
]


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


class SiteTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        handler = functools.partial(_QuietHandler, directory=str(SITE_DIR))
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.server.server_address[1]}/"
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.server.shutdown()

    def open(self, width=1280, height=900):
        page = self.browser.new_page(viewport={"width": width, "height": height})
        self.addCleanup(page.close)
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.goto(self.url)
        page.wait_for_selector("#tender-list li")
        return page, errors

    def test_loads_without_errors(self):
        page, errors = self.open()
        self.assertEqual(errors, [])
        self.assertEqual(page.locator("[role=alert]").count(), 0)
        self.assertIn("Päivitetty", page.locator(".hero-period").inner_text())

    def test_recommendation_filter_shows_only_matching_cards(self):
        page, _ = self.open()
        recs = page.eval_on_selector_all("#tender-rec option", "os => os.map(o => o.value).filter(Boolean)")
        self.assertTrue(recs)
        for rec in recs:
            page.select_option("#tender-rec", rec)
            badges = page.eval_on_selector_all("#tender-list .badge", "bs => bs.map(b => b.dataset.rec)")
            self.assertTrue(set(badges) <= {rec}, rec)

    def test_show_all_lists_every_card(self):
        page, _ = self.open()
        more = page.locator(".show-more")
        if more.is_hidden():
            self.skipTest("too few open tenders to collapse")
        total = int(more.inner_text().split()[-1])
        more.click()
        self.assertEqual(page.locator("#tender-list > li").count(), total)
        self.assertEqual(more.get_attribute("aria-expanded"), "true")

    def test_planner_stays_within_risk_limit(self):
        page, _ = self.open()
        if page.locator("#planner").is_hidden():
            self.skipTest("no year with enough candidates")
        for unit in ("count", "km"):
            page.select_option("#plan-unit", unit)
            tiles = page.locator("#plan-stats dd").all_inner_texts()
            self.assertEqual(len(tiles), 4, unit)
            over = int(tiles[3].replace("\xa0", "").rstrip("%"))
            limit = round(float(page.eval_on_selector("#plan-risk", "s => s.value")) * 100)
            self.assertLessEqual(over, limit, unit)
            self.assertEqual(page.locator("#plan-list li").count(), int(tiles[0]), unit)

    def test_table_views_open(self):
        page, _ = self.open()
        for details in page.locator("details.table-view").all():
            details.locator("summary").click()
            self.assertGreater(details.locator("table tr").count(), 1)

    def test_no_horizontal_scroll_on_phone(self):
        page, _ = self.open(width=375, height=800)
        overflow = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
        self.assertLessEqual(overflow, 0)

    def test_no_accessibility_violations(self):
        page, _ = self.open()
        # Cards fade in; half-transparent text mid-animation would read as low contrast
        page.evaluate("Promise.all(document.getAnimations().map((a) => a.finished))")
        page.add_script_tag(url=AXE_URL)
        violations = page.evaluate(
            "async () => (await axe.run(document, {runOnly: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'best-practice']}))"
            ".violations.map(v => `${v.id}: ${v.nodes.length}`)")
        self.assertEqual(violations, [])

    def test_size_distribution_matches_enumeration(self):
        page, _ = self.open()
        diff = page.evaluate("""() => {
          const bids = [{p: 0.3, size: 2}, {p: 0.55, size: 1}, {p: 0.1, size: 3}, {p: 0.8, size: 2}];
          const dist = sizeDistribution(bids);
          const brute = new Array(dist.length).fill(0);
          for (let mask = 0; mask < 1 << bids.length; mask++) {
            let prob = 1, size = 0;
            bids.forEach((b, i) => { if (mask & (1 << i)) { prob *= b.p; size += b.size; } else prob *= 1 - b.p; });
            brute[size] += prob;
          }
          return Math.max(...dist.map((v, i) => Math.abs(v - brute[i])), Math.abs(dist.reduce((a, b) => a + b) - 1));
        }""")
        self.assertLess(diff, 1e-12)

    def test_portfolio_is_optimal_for_contract_counts(self):
        page, _ = self.open()
        for cap in (1, 2, 3):
            for risk in (0.05, 0.1, 0.2):
                r = page.evaluate(BRUTE_FORCE_JS, [CANDIDATES, "count", cap, risk])
                self.assertTrue(r["plannedFits"])
                self.assertAlmostEqual(r["planned"], r["best"], places=9, msg=f"cap {cap}, risk {risk}")

    def test_portfolio_is_near_optimal_for_road_km(self):
        page, _ = self.open()
        for cap_km in (1000, 2000, 3000):
            r = page.evaluate(BRUTE_FORCE_JS, [CANDIDATES, "km", cap_km / 10, 0.1])
            self.assertTrue(r["plannedFits"])
            # Knapsack-type: the heuristic is checked to stay within 2 % of the optimum
            self.assertGreaterEqual(r["planned"], 0.98 * r["best"], f"{cap_km} km")


if __name__ == "__main__":
    unittest.main()
