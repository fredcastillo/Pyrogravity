import { ArrowUpRight, Filter, Search } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { LineChart } from '../components/LineChart'
import { PageHeader } from '../components/PageHeader'
import { experiments, statusLabel } from '../data/experiments'

export function Explorer() {
  const [params] = useSearchParams()
  const [query, setQuery] = useState('')
  const [field, setField] = useState('all')
  const [selectedId, setSelectedId] = useState(params.get('experiment') ?? experiments[0].id)
  const filtered = useMemo(() => experiments.filter((item) => (field === 'all' || item.field === field) && `${item.shortName} ${item.title} ${item.code}`.toLowerCase().includes(query.toLowerCase())), [field, query])
  const selected = experiments.find((item) => item.id === selectedId) ?? filtered[0] ?? experiments[0]

  return (
    <div className="page">
      <PageHeader eyebrow="CATÁLOGO CIENTÍFICO" title="Explorador de experimentos" description="Busca, filtra e inspecciona datasets sin separar los valores de su procedencia." />
      <section className="filter-bar panel">
        <label className="search-field"><Search /><span className="sr-only">Buscar experimentos</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Buscar por misión, código o material" /></label>
        <label className="select-field"><Filter /><span>Familia</span><select value={field} onChange={(event) => setField(event.target.value)}><option value="all">Todas</option><option value="liquid">Combustible líquido</option><option value="solid">Combustible sólido</option><option value="spacecraft">Incendio en nave</option></select></label>
        <span className="results-count">{filtered.length} resultados</span>
      </section>
      <div className="explorer-layout">
        <section className="experiment-list" aria-label="Resultados de experimentos">
          {filtered.map((item) => (
            <button key={item.id} onClick={() => setSelectedId(item.id)} className={item.id === selected.id ? 'experiment-row experiment-row--active' : 'experiment-row'} style={{ '--accent': item.color } as React.CSSProperties}>
              <span className="experiment-row__orb" /><span><small>{item.code}</small><strong>{item.shortName}</strong><span>{item.title}</span></span><span><span className={`status-tag status-tag--${item.status}`}>{statusLabel[item.status]}</span><small>{item.sampleCount} muestras</small></span><ArrowUpRight />
            </button>
          ))}
          {filtered.length === 0 && <div className="empty-state"><Search /><h2>Sin coincidencias</h2><p>Prueba con otra familia o elimina parte de la búsqueda.</p></div>}
        </section>
        <aside className="panel explorer-detail" style={{ '--accent': selected.color } as React.CSSProperties}>
          <p className="eyebrow">{selected.code} · {selected.source}</p><h2>{selected.title}</h2><p>{selected.summary}</p>
          <LineChart series={selected.series} color={selected.color} label={selected.shortName} />
          <dl className="metadata-list"><div><dt>Material</dt><dd>{selected.material}</dd></div><div><dt>Condición</dt><dd>{selected.gravity}</dd></div><div><dt>Muestras</dt><dd>{selected.sampleCount}</dd></div><div><dt>Actualizado</dt><dd>{selected.updated}</dd></div><div><dt>DOI</dt><dd>{selected.doi}</dd></div><div><dt>Cobertura</dt><dd>{selected.completeness}%</dd></div></dl>
          <div className="scientific-note"><strong>Límite científico</strong><p>El gráfico muestra una serie normalizada para navegación. La visualización definitiva debe consumir variable, unidad y método de reducción desde ChartSpec.</p></div>
        </aside>
      </div>
    </div>
  )
}
