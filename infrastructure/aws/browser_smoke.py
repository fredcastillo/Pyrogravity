"""Exercise scientific selectors, charts and pagination in a real browser."""
import argparse
import csv
import json
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlsplit
from xml.etree import ElementTree
from playwright.sync_api import sync_playwright, expect


def verify_analysis_links(page, home_url):
    selector = page.get_by_role("link", name="Ver resultado y procedencia")
    expect(selector).to_have_count(5)
    visited = set()
    for index in range(5):
        link = selector.nth(index)
        expected_psi = link.locator("xpath=ancestor::li[1]").locator(".published-analysis-title span").inner_text()
        link.click()
        path = urlsplit(page.url).path
        assert path.startswith("/estudios/"), page.url
        analysis = path.split("/")[-1]
        visited.add(analysis)
        expect(page.locator("#resultados")).to_be_visible()
        expect(page.locator(".study-hero")).to_contain_text(expected_psi)
        expect(page.locator(".study-chart circle").first).to_be_attached()
        expect(page.locator("#fuentes")).to_contain_text("SHA-256")
        expect(page.locator("#fuentes a")).to_have_attribute(
            "href", f"https://psi.nasa.gov/physci/repo/data/investigations/{expected_psi}",
        )
        page.goto(home_url)
    assert visited == {"bass-ii", "flex", "flame-design", "cfi-g", "spice"}


def verify_study_features(page, home_url):
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(urljoin(home_url, "/estudios/spice?cohorte=available"))
    cohort = page.get_by_label("Configuración o cohorte")
    expect(cohort).to_have_value("available")
    group = page.get_by_role("combobox", name="Combustible", exact=True)
    group_value = group.locator("option").nth(1).get_attribute("value")
    assert group_value
    group.select_option(group_value)
    assert parse_qs(urlsplit(page.url).query) == {"cohorte": ["available"], "grupo": [group_value]}
    page.reload()
    expect(cohort).to_have_value("available")
    expect(group).to_have_value(group_value)
    expect(page.locator("[data-study-series]")).to_be_attached()
    expect(page.locator(".study-chart svg")).to_have_attribute("data-view", "line")
    page.get_by_role("button", name="Relación entre variables").click()
    expect(page.locator(".study-chart svg")).to_have_attribute("data-view", "scatter")
    expect(page.locator("[data-study-series]")).to_have_count(0)
    page.get_by_role("button", name="Líneas por fila").click()
    expect(page.locator("[data-study-series]")).to_be_attached()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert not page.evaluate(r"""() => performance.getEntriesByType('resource')
        .some(entry => /nasa-flame-design|three\.module/.test(entry.name))""")
    page.locator(".study-column-choice summary").click()
    page.get_by_role("checkbox", name="Combustible", exact=True).check()
    expect(page.get_by_role("columnheader", name="Combustible", exact=True)).to_be_visible()
    page.locator(".study-table tbody summary").first.click()
    expect(page.locator(".study-table tbody dl").first).to_be_visible()
    with page.expect_download() as pending:
        page.get_by_role("button", name="Descargar CSV").click()
    with Path(pending.value.path()).open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    assert rows
    assert all(row["fuel"] == group_value and row["pyrogravity_cohort"] == "available"
               and len(row["pyrogravity_sha256"]) == 64 for row in rows)
    with page.expect_download() as pending:
        page.get_by_role("button", name="Descargar gráfica SVG").click()
    saved = ElementTree.parse(pending.value.path()).getroot()
    assert saved.tag == "{http://www.w3.org/2000/svg}svg"
    page.get_by_role("button", name="¿De dónde salen los datos?").click()
    expect(page.locator(".study-lookup-answer")).to_contain_text("NASA PSI-107")
    page.goto(urljoin(home_url, "/estudios/bass-ii"))
    page.get_by_role("button", name="Consultar estudio").click()
    panel = page.get_by_role("dialog", name="Pyrogravity")
    expect(panel).to_be_visible()
    expect(panel.get_by_role("combobox", name="Estudio del chat")).to_have_value("bass-ii")
    assert panel.bounding_box()["width"] <= 390
    if urlsplit(home_url).hostname == "127.0.0.1":
        path = "**/api/v1/ai/query"
        page.route(path, lambda route: route.fulfill(status=503, json={}))
        with page.expect_request(lambda request: request.url.endswith("/api/v1/ai/query")) as request:
            panel.get_by_role("button", name="¿Cómo hicieron el experimento?").click()
        assert request.value.post_data_json["question"] == "Metodología de BASS-II"
        expect(panel.get_by_text("La biblioteca tarda en responder", exact=False)).to_be_visible()
        page.unroute(path)
    page.keyboard.press("Escape")
    expect(panel).to_be_hidden()
    page.set_viewport_size({"width": 1280, "height": 1000})
    page.goto(home_url)


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


def verify_chat(page, trigger):
    trigger.click()
    panel = page.get_by_role("dialog", name="Pyrogravity")
    expect(panel).to_be_visible()
    panel.get_by_role("combobox", name="Estudio del chat").select_option("")
    panel.get_by_role("button", name="¿Qué estudios hay?").click()
    expect(panel.get_by_text("Puedes explorar cinco análisis", exact=False).last).to_be_visible()
    expect(panel.get_by_role("link", name="Flame Design").last).to_have_attribute("href", urljoin(page.url, "/estudios/flame-design"))
    page.keyboard.press("Escape")
    expect(panel).to_be_hidden()
    expect(trigger).to_be_focused()


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
            verify_chat(page, page.get_by_role("button", name="Consultar fuentes"))
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
            page.get_by_role("link", name="Abrir el Atlas").click()
        search = page.get_by_role("searchbox", name="Buscar en el catálogo")
        expect(search).to_be_enabled()
        if command_center:
            verify_chat(page, page.get_by_role("button", name="Consultar fuentes"))
        search.fill("psi-69")
        expect(page.locator("#catalog-study")).to_have_text("PSI-69")
        expect(page.locator("#catalog-source")).to_have_attribute("href", "https://psi.nasa.gov/physci/repo/data/investigations/PSI-69")
        first_row = page.locator("#catalog-rows th").first
        expect(first_row).to_have_text("1")
        page.locator("#catalog-rows button").first.click()
        expect(page.get_by_role("dialog")).to_be_visible()
        expect(page.get_by_role("heading", name="Fila 1 del CSV")).to_be_visible()
        page.get_by_role("button", name="Cerrar", exact=True).click()
        expect(page.get_by_role("dialog")).to_be_hidden()
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
            if width == 390:
                expect(page.locator("#catalog-columns th:visible")).to_have_count(3)
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
            verify_study_features(page, page.url)
            page.get_by_role("button", name="Abrir chat científico").click()
            panel = page.get_by_role("dialog", name="Pyrogravity")
            panel.get_by_role("textbox", name="Escribe tu pregunta").fill("Explica el resultado de los ensayos de combustión de antimateria de BASS-II.")
            panel.get_by_role("button", name="Enviar mensaje").click()
            expect(panel.get_by_text("No encontré una fuente que respalde ese detalle", exact=False)).to_be_visible(timeout=25000)
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
