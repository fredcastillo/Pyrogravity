/* Render only validated, precomputed scientific results; never infer missing values. */
(() => {
  const $ = id => document.getElementById(`science-${id}`);
  const specs = {
    'bass-ii': ['initial_co2', 'final_co2', '% by vol', '% by vol', 'fuel_sample_material'],
    flex: ['droplet_initial_diameter', 'burn_time', 'mm', 's', 'fuel'],
    'flame-design': ['pinit_atm', 'pfinal_atm', 'atm', 'atm', 'fuel'],
    'cfi-g': ['source_record', 'duration', 'fila (no tiempo)', 'sec', 'termination'],
    spice: ['air_rate_cm_s', 'fuel_rate_mg_s', 'cm/s', 'mg/s', 'fuel'],
  };
  let result, rows = [], page = 0, generation = 0;
  function option(select, value, label) { select.add(new Option(label, value)); }
  function cell(row, text, tag = 'td') {
    const node = document.createElement(tag); node.textContent = text ?? '—'; row.append(node);
  }
  async function fetchJSON(path) {
    const response = await fetch(path);
    if (!response.ok) throw new Error(`No se pudo consultar el análisis (${response.status}). Referencia: ${response.headers.get('X-Request-Id') || 'no disponible'}`);
    return response.json();
  }
  function selectCohort() {
    const r = result.result, cohort = $('cohort').value;
    const part = r.configurations ? r.configurations[cohort] : r;
    const dataset = part.dataset;
    rows = part.pairs || part.included || part.records || [];
    if (r.cohorts) {
      const included = new Set(r.cohorts[cohort].source_records);
      rows = rows.filter(row => included.has(row.source_record));
    }
    const groupKey = specs[result.analysis_id][4];
    $('group').replaceChildren(); option($('group'), '', 'Todos los grupos (descriptivo)');
    [...new Set(rows.map(row => row[groupKey] ?? 'Sin etiqueta'))].sort().forEach(label => option($('group'), label, label));
    const link = document.createElement('a'); link.href = dataset.nasa_psi_url;
    link.target = '_blank'; link.rel = 'noopener noreferrer'; link.textContent = `NASA ${dataset.psi_code} · ${dataset.investigation_name}`;
    const source = document.createElement('span'); source.textContent = `CSV: ${dataset.relative_path}`;
    const version = document.createElement('span'); version.textContent = `SHA-256 ${dataset.sha256} · Método ${r.method_version}`;
    $('source').replaceChildren(link, source, version);
    $('method').textContent = JSON.stringify({criteria: r.criteria, warnings: r.warnings, statistics: part.statistics, quality: part.quality || r.quality}, null, 2);
    page = 0; render();
  }
  function render() {
    const [x, y, xu, yu, group] = specs[result.analysis_id];
    const selected = rows.filter(row => !$('group').value || (row[group] ?? 'Sin etiqueta') === $('group').value);
    const visible = selected.slice(page * 12, (page + 1) * 12);
    $('columns').replaceChildren();
    ['Fila de origen', group, `${x} (${xu})`, `${y} (${yu})`, 'Alertas'].forEach(label => cell($('columns'), label, 'th'));
    $('rows').replaceChildren();
    visible.forEach(row => {
      const tr = document.createElement('tr');
      [row.source_record, row[group], row[x], row[y], [...(row.quality_flags || []), ...(row.review_flags || []), ...(row.duration_outlier ? ['duration_outlier'] : [])].join(', ') || '—'].forEach(value => cell(tr, value));
      $('rows').append(tr);
    });
    $('page').textContent = `${selected.length} registros · Página ${page + 1} de ${Math.max(1, Math.ceil(selected.length / 12))}`;
    $('prev').disabled = page === 0; $('next').disabled = (page + 1) * 12 >= selected.length;
    $('status').textContent = selected.length ? `${rows.length} registros incluidos por el motor científico; ${selected.length} en el grupo seleccionado.` : 'Evidencia insuficiente para esta selección.';
    const chart = $('chart'); chart.replaceChildren();
    const points = selected.filter(row => row[x] !== null && row[y] !== null && Number.isFinite(Number(row[x])) && Number.isFinite(Number(row[y])));
    function svg(tag, attrs, text) {
      const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
      Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, value));
      if (text !== undefined) node.textContent = text;
      chart.append(node); return node;
    }
    if (points.length) {
      const xs = points.map(row => Number(row[x])), ys = points.map(row => Number(row[y]));
      let xmin = Math.min(...xs), xmax = Math.max(...xs), ymin = Math.min(...ys), ymax = Math.max(...ys);
      if (xmin === xmax) { xmin -= 1; xmax += 1; } if (ymin === ymax) { ymin -= 1; ymax += 1; }
      for (let i = 0; i <= 4; i++) {
        const xTick = 96 + i * 138
        const yTick = 290 - i * 67.5
        svg('path', {d: `M96 ${yTick}H648 M${xTick} 20V290`, fill: 'none', stroke: '#293d58'});
        svg('text', {x: xTick, y: 322, 'text-anchor': 'middle'}, (xmin + (xmax - xmin) * i / 4).toPrecision(4));
        svg('text', {x: 87, y: yTick + 5, 'text-anchor': 'end'}, (ymin + (ymax - ymin) * i / 4).toPrecision(4));
      }
      svg('path', {d: 'M96 20V290H648', fill: 'none', stroke: '#6685a5'});
      points.forEach(row => {
        const dot = svg('circle', {cx: 96 + (Number(row[x]) - xmin) / (xmax - xmin) * 552, cy: 290 - (Number(row[y]) - ymin) / (ymax - ymin) * 270, r: 4.7, fill: '#84e4f8', opacity: .78});
        const title = document.createElementNS('http://www.w3.org/2000/svg', 'title');
        title.textContent = `Fila ${row.source_record} · ${row[group] ?? ''} · ${row[x]} ${xu}; ${row[y]} ${yu}`; dot.append(title);
      });
    }
    $('caption').textContent = `X: ${x} (${xu}) · Y: ${y} (${yu}). ${points.length} puntos. Vista descriptiva; no implica causalidad ni equivalencia de condiciones.`;
  }
  async function load() {
    const token = ++generation; $('result').hidden = true; $('status').textContent = 'Cargando resultado…';
    $('cohort').disabled = true;
    try {
      const id = $('analysis').value, path = `/api/v1/analyses/${encodeURIComponent(id)}`;
      const next = await fetchJSON(path); if (token !== generation) return;
      if (next.analysis_id !== id) throw new Error('El resultado recibido no corresponde al análisis seleccionado.');
      result = next; $('download').href = path;
      $('description').textContent = `${result.analysis_name} · ${result.psi_code}`;
      $('cohort').replaceChildren();
      const cohorts = Object.keys(result.result.configurations || result.result.cohorts || {all: true});
      cohorts.forEach(key => option($('cohort'), key, key === 'all' ? 'Selección validada' : key));
      if (cohorts.includes('conservative')) $('cohort').value = 'conservative';
      selectCohort();
      $('cohort').disabled = cohorts.length === 1; $('result').hidden = false;
    } catch (error) {
      if (token === generation) $('status').textContent = `No se pudo mostrar el resultado y su procedencia. ${error.message}`;
    }
  }
  $('analysis').addEventListener('change', load); $('cohort').addEventListener('change', selectCohort);
  $('group').addEventListener('change', () => { page = 0; render(); });
  $('prev').addEventListener('click', () => { page--; render(); });
  $('next').addEventListener('click', () => { page++; render(); });
  fetchJSON('/api/v1/analyses').then(catalog => {
    document.querySelector('#atlas-analysis-count').textContent = catalog.length;
    catalog.forEach(item => option($('analysis'), item.analysis_id, `${item.analysis_name} · ${item.psi_code}`));
    const requestedAnalysis = new URLSearchParams(window.location.search).get('analysis');
    if (!catalog.length) {
      $('status').textContent = 'No hay análisis disponibles.';
      return;
    }
    $('analysis').disabled = false;
    if (requestedAnalysis && !catalog.some(item => item.analysis_id === requestedAnalysis)) {
      $('analysis').selectedIndex = -1;
      $('status').textContent = 'El análisis solicitado no está disponible. Puedes elegir otro en la lista.';
      return;
    }
    if (requestedAnalysis) $('analysis').value = requestedAnalysis;
    return load();
  }).catch(error => { $('status').textContent = `No se pudo cargar el catálogo de análisis. ${error.message}`; });
})();
