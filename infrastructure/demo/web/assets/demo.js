const datasetSelect = document.querySelector("#dataset");
const trialsInput = document.querySelector("#trials");
const submit = document.querySelector("#submit");
const message = document.querySelector("#message");
const results = document.querySelector("#results");
const bars = document.querySelector("#bars");
const measurements = document.querySelector("#measurements");
const datasets = new Map();
let activeRequest;
const catalogUrl = new URL("catalog.json", document.currentScript.src);
const catalogSearch = document.querySelector("#catalog-search");
const catalogSelect = document.querySelector("#catalog-dataset");
const catalogCount = document.querySelector("#catalog-count");
const catalogResults = document.querySelector("#catalog-results");
const catalogColumns = document.querySelector("#catalog-columns");
const catalogRows = document.querySelector("#catalog-rows");
const catalogSurface = document.querySelector(".catalog-table");
const catalogScrollNote = document.querySelector("#catalog-scroll-note");
const catalogPrevious = document.querySelector("#catalog-previous");
const catalogNext = document.querySelector("#catalog-next");
const catalogColumnOptions = document.querySelector("#catalog-column-options");
const catalogRowDialog = document.querySelector("#catalog-row-dialog");
const compactCatalog = window.matchMedia("(max-width: 730px)");
const catalogTables = new Map();
const pageSize = 10;
let firstRow = 0;
let catalogSummary = "";
let chosenColumns = null;
let renderedTable = "";
const scopeLabels = {
  experimental_summary: "Resumen experimental",
  conditions_only: "Condiciones experimentales",
  conditions_and_counts: "Condiciones y recuentos",
  metadata_only: "Metadatos",
};

async function getJson(url, signal) {
  const response = await fetch(url, { signal });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    if (response.status === 422) {
      throw new Error(typeof body.detail === "string" ? body.detail : "Revisa los ensayos ingresados.");
    }
    throw new Error("No pudimos consultar los datos. Intenta de nuevo.");
  }
  return response.json();
}

function exact(measurement) {
  return measurement.status === "exact" && measurement.value !== null;
}

function labels(dataset) {
  trialsInput.value = datasets.get(dataset).examples.join(", ");
}

function render(comparison) {
  const dataset = comparison.dataset;
  document.querySelector("#metric").textContent = `${dataset.label} · ${dataset.metric_label} (${dataset.unit})`;
  const chartRows = comparison.measurements.filter(exact);
  const maximum = Math.max(1, ...chartRows.map((row) => Number(row.value)));
  bars.replaceChildren();
  for (const row of chartRows) {
    const item = document.createElement("li");
    const label = document.createElement("span");
    label.textContent = row.trial;
    const bar = document.createElement("meter");
    bar.max = maximum;
    bar.value = Number(row.value);
    bar.setAttribute("aria-label", `Ensayo ${row.trial}, fila ${row.source_record}`);
    const value = document.createElement("span");
    value.textContent = `${row.value} ${dataset.unit}`;
    item.append(label, bar, value);
    bars.append(item);
  }

  measurements.replaceChildren();
  for (const row of comparison.measurements) {
    const line = document.createElement("tr");
    for (const field of [row.trial, exact(row) ? `${row.value} ${dataset.unit}` : `Sin valor exacto (${row.status})`, row.material ?? "Sin dato", row.source_record]) {
      const cell = document.createElement("td");
      cell.textContent = field;
      line.append(cell);
    }
    measurements.append(line);
  }

  const source = document.querySelector("#source");
  source.href = dataset.source;
  source.textContent = `NASA · ${dataset.study}`;
  document.querySelector("#source-file").textContent =
    `${dataset.source_path.split("/").at(-1)} · Filas de datos contadas desde 1, tras el encabezado.`;
  const notes = [];
  if (comparison.status === "insufficient_evidence") notes.push("No hay mediciones exactas para esta selección.");
  if (comparison.status === "partial") notes.push("Algunos ensayos no tienen una medición exacta.");
  if (comparison.missing_trials.length) notes.push(`Sin registro: ${comparison.missing_trials.join(", ")}.`);
  message.textContent = notes.join(" ");
  results.hidden = false;
}

async function compare() {
  activeRequest?.abort();
  const request = new AbortController();
  activeRequest = request;
  submit.disabled = true;
  results.hidden = true;
  message.textContent = "Consultando los datos…";
  const parameters = new URLSearchParams({ dataset: datasetSelect.value, trials: trialsInput.value });
  try {
    render(await getJson(`/api/v1/compare?${parameters}`, request.signal));
  } catch (error) {
    if (error.name !== "AbortError") message.textContent = error.message;
  } finally {
    if (request === activeRequest) submit.disabled = false;
  }
}

async function start() {
  try {
    for (const dataset of await getJson("/api/v1/datasets")) {
      datasets.set(dataset.id, dataset);
      datasetSelect.add(new Option(`${dataset.label} · ${dataset.study}`, dataset.id));
    }
    const requestedDataset = new URLSearchParams(window.location.search).get("dataset");
    if (datasets.has(requestedDataset)) datasetSelect.value = requestedDataset;
    labels(datasetSelect.value);
    await compare();
  } catch (error) {
    message.textContent = error.message;
  }
}

function textElement(tag, value) {
  const element = document.createElement(tag);
  element.textContent = value;
  return element;
}

function showCatalogRow(headers, row) {
  document.querySelector("#catalog-row-title").textContent = `Fila ${row[0]} del CSV`;
  document.querySelector("#catalog-row-fields").replaceChildren(...headers.map((label, index) => {
    const field = document.createElement("div");
    const value = row[index + 1];
    field.append(textElement("dt", label), textElement("dd", value === "" || value == null ? "—" : value));
    return field;
  }));
  catalogRowDialog.showModal();
}

function updateCatalogColumns() {
  const defaults = index => !compactCatalog.matches || index < 2;
  const visible = index => chosenColumns ? chosenColumns.has(index) : defaults(index);
  for (const node of catalogSurface.querySelectorAll("[data-column]")) node.hidden = !visible(Number(node.dataset.column));
  for (const input of catalogColumnOptions.querySelectorAll("input")) input.checked = visible(Number(input.value));
  updateCatalogScrollNote();
}

function renderCatalog() {
  const table = catalogTables.get(catalogSelect.value);
  if (!table) {
    catalogResults.hidden = true;
    return;
  }
  const label = scopeLabels[table.scope] ?? "Tabla de NASA";
  document.querySelector("#catalog-study").textContent = table.study;
  document.querySelector("#catalog-name").textContent = table.label;
  document.querySelector("#catalog-details").textContent =
    `${table.title} · ${label} · ${table.rows.length} de ${table.row_count} filas con datos`;

  const headers = table.columns.map(({ label, unit }) =>
    unit && !label.includes(unit) ? `${label} (${unit})` : label);
  document.querySelector("#catalog-table-caption").textContent = `${table.study} · ${table.label}`;
  if (renderedTable !== table.id) {
    renderedTable = table.id;
    chosenColumns = null;
    catalogColumnOptions.replaceChildren(textElement("legend", "Columnas visibles"), ...headers.map((title, index) => {
      const label = document.createElement("label");
      const input = document.createElement("input");
      input.type = "checkbox";
      input.value = String(index);
      label.append(input, textElement("span", title));
      return label;
    }));
  }
  catalogColumns.replaceChildren(...["Fila del CSV", ...headers].map((title, index) => {
    const heading = textElement("th", title);
    heading.scope = "col";
    if (index) heading.dataset.column = String(index - 1);
    return heading;
  }));

  const lastRow = Math.min(firstRow + pageSize, table.rows.length);
  catalogRows.replaceChildren(...table.rows.slice(firstRow, lastRow).map((row) => {
    const line = document.createElement("tr");
    const origin = document.createElement("th");
    origin.scope = "row";
    const button = textElement("button", row[0]);
    button.type = "button";
    button.className = "catalog-row-number";
    button.setAttribute("aria-label", `Ver fila ${row[0]}`);
    button.addEventListener("click", () => showCatalogRow(headers, row));
    origin.append(button);
    line.append(origin, ...headers.map((_, index) => {
      const cell = row[index + 1];
      const node = textElement("td", cell === "" || cell == null ? "—" : cell);
      node.dataset.column = String(index);
      return node;
    }));
    return line;
  }));

  document.querySelector("#catalog-page").textContent = table.rows.length
    ? `Filas con datos ${firstRow + 1}–${lastRow} de ${table.rows.length}`
    : "Este CSV no tiene filas con datos.";
  catalogPrevious.disabled = firstRow === 0;
  catalogNext.disabled = lastRow >= table.rows.length;

  const source = document.querySelector("#catalog-source");
  source.href = table.source;
  source.textContent = "Ver fuente NASA ↗";
  document.querySelector("#catalog-file").textContent = table.source_path.split("/").at(-1);
  document.querySelector("#catalog-sha").textContent = table.source_sha256;
  catalogResults.hidden = false;
  catalogSurface.scrollLeft = 0;
  updateCatalogColumns();
}

function updateCatalogScrollNote() {
  catalogScrollNote.hidden = catalogSurface.scrollWidth <= catalogSurface.clientWidth;
}

function searchText(value) {
  return value.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase();
}

function filterCatalog() {
  const previous = catalogSelect.value;
  const terms = searchText(catalogSearch.value).trim().split(/\s+/).filter(Boolean);
  const matches = [...catalogTables.values()].filter((table) => {
    const haystack = searchText(`${table.study} ${table.label} ${table.title} ${table.source_path}`);
    return terms.every((term) => haystack.includes(term));
  });
  catalogSelect.replaceChildren(...matches.map((table) => new Option(`${table.study} · ${table.label}`, table.id)));
  catalogSelect.disabled = matches.length === 0;
  if (!matches.length) catalogSelect.add(new Option("Sin tablas que coincidan", ""));
  if (matches.some((table) => table.id === previous)) catalogSelect.value = previous;
  catalogCount.textContent = terms.length
    ? (matches.length === 1 ? "1 tabla encontrada" : `${matches.length} tablas encontradas`)
    : catalogSummary;
  firstRow = 0;
  renderCatalog();
}

async function loadCatalog() {
  try {
    const tables = await getJson(catalogUrl);
    for (const table of tables) {
      catalogTables.set(table.id, table);
    }
    const studies = new Set(tables.map((table) => table.study));
    catalogSummary = `${tables.length} tablas · ${studies.size} investigaciones`;
    document.querySelector("#atlas-table-count").textContent = tables.length;
    document.querySelector("#atlas-study-count").textContent = studies.size;
    catalogSearch.disabled = false;
    filterCatalog();
  } catch (error) {
    catalogCount.textContent = error.message;
  }
}

document.querySelector("#comparison").addEventListener("submit", (event) => {
  event.preventDefault();
  void compare();
});
datasetSelect.addEventListener("change", () => {
  labels(datasetSelect.value);
  void compare();
});
catalogSelect.addEventListener("change", () => {
  firstRow = 0;
  renderCatalog();
});
catalogSearch.addEventListener("input", filterCatalog);
catalogColumnOptions.addEventListener("change", () => {
  chosenColumns = new Set([...catalogColumnOptions.querySelectorAll("input:checked")].map(input => Number(input.value)));
  updateCatalogColumns();
});
compactCatalog.addEventListener("change", updateCatalogColumns);
new ResizeObserver(updateCatalogScrollNote).observe(catalogSurface);
catalogPrevious.addEventListener("click", () => {
  firstRow -= pageSize;
  renderCatalog();
});
catalogNext.addEventListener("click", () => {
  firstRow += pageSize;
  renderCatalog();
});
void start();
void loadCatalog();

const atlasLinks = document.querySelectorAll(".atlas-nav a");
function updateNavigation(target) {
  for (const link of atlasLinks) {
    if (link.hash === target) link.setAttribute("aria-current", "location");
    else link.removeAttribute("aria-current");
  }
}
const readSection = () => updateNavigation(window.location.hash || "#catalog-title");
for (const link of atlasLinks) link.addEventListener("click", () => updateNavigation(link.hash));
window.addEventListener("hashchange", readSection);
readSection();
