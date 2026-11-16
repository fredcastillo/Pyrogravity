"""Exercise scientific selectors, charts and pagination in a real browser."""
import argparse
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, expect


def verify(url, executable=None, screenshots=None, command_center=False):
    errors = []
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=executable, headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 1000})
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(url, wait_until="networkidle")
        expect(page.locator("#science-analysis")).to_be_enabled()
        catalog = page.locator("#science-analysis option").evaluate_all("nodes => nodes.map(n => ({id:n.value,label:n.textContent}))")
        assert len(catalog) == 5
        for item in catalog:
            page.select_option("#science-analysis", item["id"])
            expect(page.locator("#science-description")).to_contain_text(item["label"].split(" · ")[0])
            expect(page.locator("#science-result")).to_be_visible()
            cohorts = page.locator("#science-cohort option").evaluate_all("nodes => nodes.map(n => n.value)")
            for cohort in cohorts:
                if len(cohorts) > 1:
                    page.select_option("#science-cohort", cohort)
                count = page.locator("#science-chart circle").count()
                assert count > 0, (item["id"], cohort, page.locator("#science-status").inner_text())
                assert page.locator("#science-rows tr").count() > 0
                assert "SHA-256" in page.locator("#science-source").inner_text()
                if page.locator("#science-next").is_enabled():
                    before = page.locator("#science-rows tr").first.inner_text()
                    page.click("#science-next")
                    assert page.locator("#science-rows tr").first.inner_text() != before
                    page.click("#science-prev")
                results.append({"analysis": item["id"], "cohort": cohort, "points": count})
        for width in (1280, 390):
            page.set_viewport_size({"width": width, "height": 1000})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), f"Horizontal overflow at {width}px"
            if screenshots:
                Path(screenshots).mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(Path(screenshots) / f"science-{width}.png"), full_page=True)
        if command_center:
            page.set_viewport_size({"width": 1280, "height": 1000})
            page.get_by_role("link", name="Abrir Command Center").click()
            expect(page.get_by_role("heading", name="Flame Intelligence Center")).to_be_visible()
            expect(page.get_by_role("link", name="Ver resultado y procedencia")).to_have_count(5)
            page.get_by_role("textbox", name="Pregunta para el copiloto").fill("¿Hay evidencia documental?")
            page.get_by_role("button", name="Enviar pregunta").click()
            expect(page.get_by_text("Evidencia insuficiente", exact=True)).to_be_visible()
        assert not errors, errors
        browser.close()
    print(json.dumps(results))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("--executable")
    parser.add_argument("--screenshots")
    parser.add_argument("--command-center", action="store_true")
    args = parser.parse_args()
    verify(args.url, args.executable, args.screenshots, args.command_center)
