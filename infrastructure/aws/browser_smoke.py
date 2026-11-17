"""Exercise scientific selectors, charts and pagination in a real browser."""
import argparse
import json
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlsplit
from playwright.sync_api import sync_playwright, expect


def verify_analysis_links(page, home_url):
    selector = page.get_by_role("link", name="Ver resultado y procedencia")
    expect(selector).to_have_count(5)
    visited = set()
    for index in range(5):
        link = selector.nth(index)
        expected_psi = link.locator("xpath=ancestor::li[1]").locator(".published-analysis-title span").inner_text()
        link.click()
        analysis = parse_qs(urlsplit(page.url).query)["analysis"][0]
        visited.add(analysis)
        expect(page.locator("#science-analysis")).to_have_value(analysis)
        expect(page.locator("#science-result")).to_be_visible()
        expect(page.locator("#science-description")).to_contain_text(expected_psi)
        expect(page.locator("#science-chart circle").first).to_be_attached()
        expect(page.locator("#science-source")).to_contain_text("SHA-256")
        expect(page.locator("#science-source a")).to_have_attribute(
            "href", f"https://psi.nasa.gov/physci/repo/data/investigations/{expected_psi}",
        )
        page.goto(home_url)
    assert visited == {"bass-ii", "flex", "flame-design", "cfi-g", "spice"}


def verify_home_layout(page):
    for width in (320, 390, 850, 1024, 1280, 1885, 2560):
        page.set_viewport_size({"width": width, "height": 1000})
        assert page.evaluate("""() => {
            const copy = document.querySelector('.published-hero__copy').getBoundingClientRect()
            const photo = document.querySelector('.published-hero__figure').getBoundingClientRect()
            const content = document.querySelector('.observatory-content').getBoundingClientRect()
            const range = document.createRange()
            range.selectNodeContents(document.querySelector('#home-title span'))
            return content.width >= innerWidth - 130
                && document.documentElement.scrollWidth <= innerWidth
                && [...range.getClientRects()].every(rect => rect.right <= copy.right + 1
                    && (rect.right <= photo.left + 1 || rect.bottom <= photo.top + 1))
        }"""), f"El título o la portada excede su espacio a {width}px"
    page.set_viewport_size({"width": 1280, "height": 1000})


def verify(url, executable=None, screenshots=None, command_center=False):
    errors = []
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=executable, headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 1000})
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(url, wait_until="networkidle")
        if page.locator('meta[name="pyrogravity-science"]').count():
            expect(page.get_by_role("heading", name="El fuego en microgravedad.")).to_be_visible()
            verify_home_layout(page)
            verify_analysis_links(page, url)
            featured = page.locator(".feature-chart")
            expect(featured.get_by_text("4,30 s", exact=True)).to_be_visible()
            featured.locator("label").filter(has_text="BASS-II").click()
            expect(featured.get_by_role("radio", name="BASS-II")).to_be_checked()
            expect(featured.get_by_role("heading", name="Oxígeno inicial calibrado")).to_be_visible()
            expect(featured.get_by_text("22,20 % vol.", exact=True)).to_have_count(3)
            page.get_by_role("link", name="Abrir comparador", exact=True).click()
            expect(page.locator("#dataset")).to_have_value("bass_ii")
            page.goto(url, wait_until="networkidle")
            page.locator(".published-analysis-list li").filter(has_text="Combustión de gotas en FLEX").get_by_role(
                "link", name="Ver resultado y procedencia",
            ).click()
            expect(page.locator("#science-analysis")).to_have_value("flex")
        search = page.get_by_role("searchbox", name="Buscar en el catálogo")
        expect(search).to_be_enabled()
        search.fill("psi-69")
        expect(page.locator("#catalog-study")).to_have_text("PSI-69")
        expect(page.locator("#catalog-source")).to_have_attribute("href", "https://psi.nasa.gov/physci/repo/data/investigations/PSI-69")
        first_row = page.locator("#catalog-rows th").first
        expect(first_row).to_have_text("1")
        page.locator("#catalog-next").click()
        expect(first_row).to_have_text("11")
        page.locator("#catalog-previous").click()
        expect(first_row).to_have_text("1")
        search.fill("sin coincidencia de prueba")
        expect(page.locator("#catalog-count")).to_have_text("0 tablas encontradas")
        expect(page.locator("#catalog-results")).to_be_hidden()
        search.fill("")
        expect(page.locator("#catalog-dataset")).to_be_enabled()
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
        for width in (1885, 1280, 390):
            page.set_viewport_size({"width": width, "height": 1000})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), f"Horizontal overflow at {width}px"
            assert page.locator("main").bounding_box()["width"] >= width - 130
            if screenshots:
                Path(screenshots).mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(Path(screenshots) / f"science-{width}.png"), full_page=True)
        if command_center:
            page.set_viewport_size({"width": 1280, "height": 1000})
            legacy_home = urljoin(page.url, "../command-center/index.html")
            page.get_by_role("link", name="Inicio", exact=True).click()
            assert urlsplit(page.url).path == "/"
            expect(page.get_by_role("heading", name="El fuego en microgravedad.")).to_be_visible()
            page.goto(legacy_home, wait_until="domcontentloaded")
            expect(page.get_by_role("heading", name="El fuego en microgravedad.")).to_be_visible()
            assert urlsplit(page.url).path == "/"
            verify_analysis_links(page, page.url)
            page.get_by_role("textbox", name="Pregunta para el copiloto").fill("Explica el resultado de los ensayos de combustión de antimateria de BASS-II.")
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
