import { Database, ExternalLink, FileCheck2 } from 'lucide-react'
import { Link } from 'react-router-dom'
import { PageHeader } from '../components/PageHeader'
import { experiments } from '../data/experiments'

export function Sources() {
  return (
    <div className="page">
      <PageHeader eyebrow="TRAZABILIDAD" title="Fuentes científicas" description="Cada salida visual debe poder regresar al dataset, versión, DOI y localizador que la respalda." />
      <section className="source-grid">
        {experiments.map((item) => <article key={item.id} className="panel source-card"><div className="source-card__icon" style={{ color: item.color }}><Database /></div><div><p className="eyebrow">{item.code}</p><h2>{item.shortName}</h2><p>{item.title}</p></div><dl><div><dt>Repositorio</dt><dd>{item.source}</dd></div><div><dt>Identificador</dt><dd>{item.doi}</dd></div><div><dt>Registros</dt><dd>{item.sampleCount}</dd></div><div><dt>Estado</dt><dd><FileCheck2 /> {item.completeness}% normalizado</dd></div></dl><Link className="button button--ghost" to={`/explorer?experiment=${item.id}`}>Abrir ficha científica <ExternalLink /></Link></article>)}
      </section>
    </div>
  )
}
