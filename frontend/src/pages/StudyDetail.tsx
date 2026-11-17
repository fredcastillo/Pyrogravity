import { ArrowLeft, ArrowUpRight, Copy, Download } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { scientificCatalogUrl } from '../scientificCatalog'
import { getStudy, groupValue, makeCsv, measureLabel, studyIds, studies, valuesFor, variableNames, variableUnits, type StudyResult, type StudyRow } from '../studies'
import './studyDetail.css'

const cohortLabels: Record<string, string> = {
  all: 'Selección validada', normal: 'Llama normal', inverse: 'Llama inversa', available: 'Lecturas disponibles', conservative: 'Selección conservadora',
}
const decimal = new Intl.NumberFormat('es', { maximumSignificantDigits: 4 })
const perPage = 12
const recordAxis = { key: 'source_record', label: 'Fila del CSV' }

function display(value: unknown) {
  if (value == null || value === '') return '—'
  return typeof value === 'object' ? JSON.stringify(value) : String(value)
}

function number(value: unknown) {
  if (typeof value !== 'number' && (typeof value !== 'string' || !value.trim())) return NaN
  return Number(value)
}

function bounds(values: number[]) {
  if (!values.length) return [0, 1]
  const low = Math.min(...values)
  const high = Math.max(...values)
  return low === high ? [low - 1, high + 1] : [low, high]
}

function download(name: string, data: string, type: string) {
  const url = URL.createObjectURL(new Blob([data], { type }))
  const link = document.createElement('a')
  link.href = url
  link.download = name
  document.body.append(link)
  link.click()
  link.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

function StudyResults({ id, data }: { id: string; data: StudyResult }) {
  const study = getStudy(id)!
  const [selection, setSelection] = useState(() => {
    const params = new URLSearchParams(window.location.search)
    return { cohort: params.get('cohorte') || '', group: params.get('grupo') || '' }
  })
  const [columns, setColumns] = useState<string[] | null>(null)
  const [page, setPage] = useState(0)
  const [message, setMessage] = useState('')
  const [manualLink, setManualLink] = useState(false)
  const [question, setQuestion] = useState('resultado')
  const [view, setView] = useState<'line' | 'scatter'>(() => new URLSearchParams(location.search).get('grafica') === 'dispersion' ? 'scatter' : 'line')
  const [highlight, setHighlight] = useState(0)
  const chart = useRef<SVGSVGElement>(null)
  const result = data.result
  const cohorts = Object.keys(result.configurations ?? result.cohorts ?? { all: true })
  const cohort = cohorts.includes(selection.cohort) ? selection.cohort : cohorts.includes('conservative') ? 'conservative' : cohorts[0]
  const part = result.configurations?.[cohort] ?? result
  const cohortRecords = result.cohorts?.[cohort]
  const included = cohortRecords ? new Set(cohortRecords.source_records) : null
  const allRows = valuesFor(part).filter(row => !included || included.has(row.source_record))
  const groups = [...new Set(allRows.map(row => groupValue(row, study.group.key)))].sort()
  const group = groups.includes(selection.group) ? selection.group : ''
  const rows = group ? allRows.filter(row => groupValue(row, study.group.key) === group) : allRows
  const [x, y] = study.axes
  const horizontal = view === 'line' ? recordAxis : x
  const fields = [study.group, ...study.axes.filter(axis => axis.key !== 'source_record'),
    ...Object.entries(variableNames).filter(([key]) => allRows.some(row => row[key] != null)).map(([key, label]) => ({ key, label, unit: variableUnits[key] }))]
  const fieldLabels = new Map(fields.map(field => [field.key, measureLabel(field)]))
  const selectedKeys = columns ?? study.axes.map(axis => axis.key)
  const visibleFields = fields.filter(field => selectedKeys.includes(field.key))
  const points = rows.map(row => ({ row, x: number(row[horizontal.key]), y: number(row[y.key]) }))
    .filter(point => Number.isFinite(point.x) && Number.isFinite(point.y))
  if (view === 'line') points.sort((a, b) => a.x - b.x)
  const [xmin, xmax] = bounds(points.map(point => point.x))
  const [ymin, ymax] = bounds(points.map(point => point.y))
  const label = `${measureLabel(y)} por ${measureLabel(horizontal)}`
  const plotted = points.map(point => ({ ...point, px: 78 + (point.x - xmin) / (xmax - xmin) * 576,
    py: 278 - (point.y - ymin) / (ymax - ymin) * 232 }))
  const trend = plotted.map((point, index) => `${index ? 'L' : 'M'}${point.px} ${point.py}`).join(' ')
  const activeIndex = Math.min(highlight, Math.max(0, plotted.length - 1))
  const active = plotted[activeIndex]
  const filename = `pyrogravity-${id}-${cohort}`
  const totalPages = Math.max(1, Math.ceil(rows.length / perPage))
  const records = rows.slice(page * perPage, (page + 1) * perPage)

  function setFilters(nextCohort: string, nextGroup: string) {
    const url = new URL(window.location.href)
    if (nextCohort !== 'all') url.searchParams.set('cohorte', nextCohort)
    else url.searchParams.delete('cohorte')
    if (nextGroup) url.searchParams.set('grupo', nextGroup)
    else url.searchParams.delete('grupo')
    window.history.replaceState(window.history.state, '', url)
    setSelection({ cohort: nextCohort, group: nextGroup })
    setManualLink(false)
    setMessage('')
    setPage(0)
    setHighlight(0)
  }

  function changeChart(next: 'line' | 'scatter') {
    const url = new URL(window.location.href)
    if (next === 'scatter') url.searchParams.set('grafica', 'dispersion')
    else url.searchParams.delete('grafica')
    window.history.replaceState(window.history.state, '', url)
    setView(next)
    setHighlight(0)
  }

  async function copyLink() {
    try {
      await navigator.clipboard.writeText(window.location.href.split('#')[0])
      setMessage('Enlace copiado con la selección.')
    } catch {
      setManualLink(true)
      setMessage('Copia el enlace con la selección.')
    }
  }

  function exportChart() {
    if (chart.current) download(`${filename}.svg`, new XMLSerializer().serializeToString(chart.current), 'image/svg+xml;charset=utf-8')
  }

  function fieldValue(row: StudyRow, key: string) {
    return key === study.group.key ? groupValue(row, key) : display(row[key])
  }

  return <>
    <section className="study-controls" aria-label="Selección de datos">
      {cohorts.length > 1 && <label>Configuración o cohorte<select value={cohort} onChange={event => setFilters(event.target.value, '')}>
        {cohorts.map(value => <option key={value} value={value}>{cohortLabels[value] ?? value}</option>)}
      </select></label>}
      <label>{study.group.label}<select aria-label={study.group.label} id="study-group" value={group} onChange={event => setFilters(cohort, event.target.value)}>
        <option value="">Todos</option>{groups.map(value => <option key={value} value={value}>{value}</option>)}
      </select></label>
      <div className="study-tools">
        <button type="button" onClick={() => void copyLink()}><Copy aria-hidden="true" /> Copiar enlace</button>
        <button type="button" disabled={!rows.length} onClick={() => download(`${filename}.csv`, makeCsv(rows, part.dataset, cohort, group, result.method_version), 'text/csv;charset=utf-8')}><Download aria-hidden="true" /> Descargar CSV</button>
      </div>
      {message && <p role="status">{message}</p>}
      {manualLink && <input aria-label="Enlace a la selección" readOnly value={window.location.href.split('#')[0]} onFocus={event => event.currentTarget.select()} />}
    </section>

    <section id="resultados" className="study-card study-result" aria-labelledby="study-result-title" data-reveal>
      <div className="study-section-heading"><div><h2 id="study-result-title">Resultados</h2><p>{rows.length} de {allRows.length} registros de la selección · {cohortLabels[cohort] ?? cohort}</p></div>
        <button type="button" disabled={!points.length} onClick={exportChart}><Download aria-hidden="true" /> Descargar gráfica SVG</button>
      </div>
      <div className="study-plot-controls" role="group" aria-label="Tipo de gráfica">
        <button type="button" aria-pressed={view === 'line'} onClick={() => changeChart('line')}>Líneas por fila</button>
        <button type="button" aria-pressed={view === 'scatter'} onClick={() => changeChart('scatter')}>Relación entre variables</button>
      </div>
      {points.length ? <figure className="study-chart">
        <svg ref={chart} xmlns="http://www.w3.org/2000/svg" viewBox="0 0 680 354" role="img" aria-labelledby="study-chart-title study-chart-caption" data-view={view}>
          <title id="study-chart-title">{study.name} · {label}</title>
          <defs>
            <linearGradient id="study-plot-background" x2="0%" y2="100%"><stop stopColor="#162d43" /><stop offset="100%" stopColor="#0a1321" /></linearGradient>
            <linearGradient id="study-plot-line"><stop stopColor="#6cafff" /><stop offset="100%" stopColor="#b5fbff" /></linearGradient>
          </defs>
          <rect width="680" height="354" rx="12" fill="url(#study-plot-background)" />
          {Array.from({ length: 5 }, (_, step) => {
            const xx = 78 + step * 144
            const yy = 278 - step * 58
            return <g key={step} fontSize="14" fontFamily="system-ui" fill="#a9bdd1">
              <path d={`M78 ${yy}H654 M${xx} 46V278`} stroke="#263a51" />
              <text x={xx} y="301" textAnchor="middle">{decimal.format(view === 'line' ? Math.round(xmin + step * (xmax - xmin) / 4) : xmin + step * (xmax - xmin) / 4)}</text>
              <text x="68" y={yy + 5} textAnchor="end">{decimal.format(ymin + step * (ymax - ymin) / 4)}</text>
            </g>
          })}
          <path d="M78 46V278H654" fill="none" stroke="#64809a" />
          <g fill="#d0e2ef" fontFamily="system-ui" fontSize="15">
            <text x="78" y="26">{measureLabel(y)}</text>
            <text x="366" y="331" textAnchor="middle">{measureLabel(horizontal)}</text>
          </g>
          {view === 'line' && plotted.length > 1 && <g key={`${cohort}:${group}`}>
            <path d={trend} fill="none" stroke="#50a7fc" opacity=".22" strokeWidth="9" strokeLinejoin="round" />
            <path className="study-series-line" data-study-series d={trend} pathLength="1" fill="none" stroke="url(#study-plot-line)" strokeWidth="2.4" strokeLinejoin="round" />
          </g>}
          {plotted.map((point, index) => <circle key={point.row.source_record} cx={point.px} cy={point.py}
            r={index === activeIndex ? 5.3 : view === 'line' ? 2.2 : 4} fill={index === activeIndex ? '#ffc98e' : '#81d7f7'}
            fillOpacity={index === activeIndex ? 1 : .72} onPointerDown={() => setHighlight(index)}>
            <title>Fila {point.row.source_record} · {measureLabel(y)}: {display(point.row[y.key])}</title>
          </circle>)}
        </svg>
        <figcaption id="study-chart-caption">{label}. {points.length} puntos observados. {view === 'line'
          ? 'La línea sigue el orden de las filas del CSV. El eje horizontal muestra filas y el intervalo entre ellas puede incluir registros excluidos.'
          : 'Cada punto muestra dos mediciones de la misma fila.'}</figcaption>
        {active && <div className="study-plot-inspect">
          <label>Inspeccionar punto<input type="range" min={0} max={points.length - 1} value={activeIndex} disabled={points.length < 2}
            onChange={event => setHighlight(Number(event.target.value))} /></label>
          <output>Fila {active.row.source_record} · {y.label}: {display(active.row[y.key])} {y.unit}</output>
        </div>}
      </figure> : <p role="status">La selección no contiene pares de mediciones que se puedan graficar.</p>}
    </section>

    <section id="datos" className="study-card study-table" aria-labelledby="study-table-title" data-reveal>
      <div className="study-section-heading"><div><h2 id="study-table-title">Mediciones por fila</h2><p>Abre una fila para consultar todas sus variables y alertas.</p></div></div>
      <details className="study-column-choice"><summary>Elegir columnas</summary><fieldset><legend className="sr-only">Columnas visibles</legend>
        {fields.map(field => <label key={field.key}><input type="checkbox" checked={selectedKeys.includes(field.key)}
          onChange={event => setColumns(event.target.checked ? [...selectedKeys, field.key] : selectedKeys.filter(key => key !== field.key))} />{measureLabel(field)}</label>)}
      </fieldset></details>
      <div className="study-table-scroll" role="region" aria-label="Tabla de mediciones" tabIndex={0}>
        <table><caption className="sr-only">Mediciones de {study.name} en la selección actual</caption><thead><tr>
          <th scope="col">Fila</th>{visibleFields.map(field => <th key={field.key} scope="col">{measureLabel(field)}</th>)}
        </tr></thead><tbody>{records.map(row => <tr key={row.source_record}>
          <th scope="row"><details><summary>Fila {row.source_record}</summary>
            <dl>{Object.entries(row).filter(([key]) => key !== 'source_record').map(([key, value]) => <div key={key}>
              <dt>{fieldLabels.get(key) ?? key}</dt><dd>{display(value)}</dd>
            </div>)}</dl>
          </details></th>
          {visibleFields.map(field => <td key={field.key}>{fieldValue(row, field.key)}</td>)}
        </tr>)}</tbody></table>
      </div>
      <nav className="study-pagination" aria-label="Paginación de las mediciones">
        <button type="button" disabled={page === 0} onClick={() => setPage(page - 1)}>Anterior</button>
        <span aria-live="polite">Página {page + 1} de {totalPages}</span>
        <button type="button" disabled={page + 1 >= totalPages} onClick={() => setPage(page + 1)}>Siguiente</button>
      </nav>
    </section>

    <div className="study-evidence-grid" data-reveal>
      <section id="metodo" className="study-card" aria-labelledby="study-method-title">
        <h2 id="study-method-title">Metodología</h2>
        <ul className="study-method-list">{study.method.map(step => <li key={step}>{step}</li>)}</ul>
        <a className="study-link" href={`/api/v1/analyses/${id}`}>Consultar criterios y resultados originales (JSON) <ArrowUpRight aria-hidden="true" /></a>
      </section>
      <section id="fuentes" className="study-card study-source" aria-labelledby="study-source-title">
        <h2 id="study-source-title">Procedencia</h2>
        <a className="study-link" href={part.dataset.nasa_psi_url} target="_blank" rel="noreferrer">{data.psi_code} · {part.dataset.investigation_name} <ArrowUpRight aria-hidden="true" /></a>
        <dl><dt>Archivo CSV</dt><dd>{part.dataset.relative_path}</dd><dt>Huella SHA-256</dt><dd><code>{part.dataset.sha256}</code></dd>
          <dt>Versión del método</dt><dd>{result.method_version}</dd>
          {part.excluded_count != null && <><dt>Registros descartados por el método</dt><dd>{part.excluded_count} en esta configuración</dd></>}
        </dl>
      </section>
    </div>

    {!study.document && <div id="scientific-query" className="study-query" tabIndex={-1} data-reveal>
        <section className="study-card" aria-labelledby="study-lookup-title">
          <h2 id="study-lookup-title">Consulta del estudio</h2>
          <p>Consulta la ficha verificada. La biblioteca de IA todavía no tiene un documento indexado para {study.name}.</p>
          <div className="study-tools" aria-label="Preguntas sobre la ficha">
            {[['resultado', '¿Qué se analizó?'], ['metodo', '¿Cómo se seleccionaron los datos?'], ['fuente', '¿De dónde salen los datos?']].map(([key, questionLabel]) =>
              <button type="button" aria-pressed={question === key} key={key} onClick={() => setQuestion(key)}>{questionLabel}</button>)}
          </div>
          <div className="study-lookup-answer" aria-live="polite">
            {question === 'resultado' && <p>{study.description} La selección actual contiene {rows.length} registros. <a href="#resultados">Ver resultados</a></p>}
            {question === 'metodo' && <p>{study.method[0]} <a href="#metodo">Leer metodología</a></p>}
            {question === 'fuente' && <p>El conjunto procede de <a href={part.dataset.nasa_psi_url}>NASA {data.psi_code}</a>. <a href="#fuentes">Ver el CSV y su huella</a></p>}
          </div>
        </section>
    </div>}
  </>
}

export function StudyDetail({ id }: { id: string }) {
  const study = getStudy(id)
  const [data, setData] = useState<StudyResult | null>(null)
  const [failed, setFailed] = useState(false)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    if (!study) return
    document.title = `${study.name} · Pyrogravity`
    const canonical = document.querySelector<HTMLLinkElement>('link[rel="canonical"]')
    if (canonical) canonical.href = `/estudios/${id}`
    const controller = new AbortController()
    async function load() {
      try {
        const response = await fetch(`/api/v1/analyses/${id}`, { signal: controller.signal })
        if (!response.ok) throw new Error('El estudio no está disponible.')
        const result: StudyResult = await response.json()
        if (result.analysis_id !== id || !result.result.method_version) throw new Error('Resultado inesperado.')
        setData(result)
      } catch {
        if (!controller.signal.aborted) setFailed(true)
      }
    }
    void load()
    return () => controller.abort()
  }, [id, study, attempt])

  return <div className="observatory-content study-page">
    <nav className="study-breadcrumb" aria-label="Ubicación">
      <a href="/#estudios"><ArrowLeft aria-hidden="true" /> Todos los estudios</a>
      <a href={scientificCatalogUrl('catalog-title')}>Tablas NASA <ArrowUpRight aria-hidden="true" /></a>
    </nav>
    {study ? <>
      <header className="study-hero"><p className="editorial-label">{study.name}{data ? ` / ${data.psi_code}` : ''}</p>
        <h1>{study.title}</h1><p>{study.description}</p>
        <nav aria-label="Secciones del estudio">
          <a href="#resultados">Resultados</a><a href="#datos">Mediciones</a><a href="#metodo">Metodología</a>
          <a href="#fuentes">Procedencia</a><button type="button" data-open-pyrogravity-chat aria-haspopup="dialog">Consultar estudio</button>
        </nav>
      </header>
      {failed && <div className="study-card" role="alert"><p>No pudimos cargar el estudio.</p>
        <button type="button" onClick={() => { setFailed(false); setAttempt(attempt + 1) }}>Reintentar</button></div>}
      {!data && !failed && <p role="status">Cargando los datos de {study.name}…</p>}
      {data && <StudyResults id={id} data={data} />}
      <nav className="study-related" aria-label="Otros estudios">{studyIds.filter(next => next !== id).map(next =>
        <a key={next} href={`/estudios/${next}`}>{studies[next].name} <ArrowUpRight aria-hidden="true" /></a>)}</nav>
    </> : <section className="study-card"><h1>Estudio no encontrado</h1><p>Elige una investigación del catálogo de Pyrogravity.</p></section>}
  </div>
}
