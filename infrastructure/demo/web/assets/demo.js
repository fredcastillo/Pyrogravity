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
const catalogSelect = document.querySelector("#catalog-dataset");
const catalogCount = document.querySelector("#catalog-count");
const catalogResults = document.querySelector("#catalog-results");
const catalogColumns = document.querySelector("#catalog-columns");
const catalogRows = document.querySelector("#catalog-rows");
const catalogPrevious = document.querySelector("#catalog-previous");
const catalogNext = document.querySelector("#catalog-next");
const catalogTables = new Map();
const pageSize = 10;
let firstRow = 0;
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

function renderCatalog() {
  const table = catalogTables.get(catalogSelect.value);
  const label = scopeLabels[table.scope] ?? "Tabla de NASA";
  document.querySelector("#catalog-details").textContent =
    `${table.title} · ${label} · ${table.rows.length} de ${table.row_count} filas con datos`;

  const headers = table.columns.map(({ label, unit }) =>
    unit && !label.includes(unit) ? `${label} (${unit})` : label);
  catalogColumns.replaceChildren(...["Fila del CSV", ...headers].map((title) => {
    const heading = textElement("th", title);
    heading.scope = "col";
    return heading;
  }));

  const lastRow = Math.min(firstRow + pageSize, table.rows.length);
  catalogRows.replaceChildren(...table.rows.slice(firstRow, lastRow).map((row) => {
    const line = document.createElement("tr");
    line.append(...row.map((cell) => textElement("td", cell === "" || cell === null ? "—" : cell)));
    return line;
  }));

  document.querySelector("#catalog-page").textContent = table.rows.length
    ? `Filas con datos ${firstRow + 1}–${lastRow} de ${table.rows.length}`
    : "Este CSV no tiene filas con datos.";
  catalogPrevious.disabled = firstRow === 0;
  catalogNext.disabled = lastRow >= table.rows.length;

  const source = document.querySelector("#catalog-source");
  source.href = table.source;
  source.textContent = `NASA · ${table.study}`;
  document.querySelector("#catalog-file").textContent = table.source_path.split("/").at(-1);
  catalogResults.hidden = false;
}

async function loadCatalog() {
  try {
    const tables = await getJson(catalogUrl);
    for (const table of tables) {
      catalogTables.set(table.id, table);
      catalogSelect.add(new Option(`${table.study} · ${table.label}`, table.id));
    }
    const studies = new Set(tables.map((table) => table.study));
    catalogCount.textContent = `${tables.length} tablas de ${studies.size} investigaciones`;
    catalogSelect.disabled = false;
    renderCatalog();
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
