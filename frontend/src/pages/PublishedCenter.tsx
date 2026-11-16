import { Database, ExternalLink } from 'lucide-react'
import { useEffect, useState } from 'react'
import { AiCopilot } from '../components/AiCopilot'
import { PageHeader } from '../components/PageHeader'
import { scientificCatalogUrl } from '../scientificCatalog'

interface Analysis {
  analysis_id: string
  analysis_name: string
  psi_code: string
  description: string
  variables: { name: string; unit: string }[]
}

export function PublishedCenter() {
  const [analyses, setAnalyses] = useState<Analysis[]>([])
  const [error, setError] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    async function loadCatalog() {
      try {
        const response = await fetch('/api/v1/analyses', { signal: controller.signal })
        if (!response.ok) throw new Error('El catálogo no está disponible.')
        setAnalyses(await response.json())
      } catch {
        if (!controller.signal.aborted) setError(true)
      }
    }
    void loadCatalog()
    return () => controller.abort()
  }, [])

  return (
    <div className="page page--published">
      <PageHeader eyebrow="PYROGRAVITY" title="Flame Intelligence Center" description="Consulta los análisis de combustión y sigue cada resultado hasta su fuente científica." />
      <div className="analysis-grid">
        <section className="panel chart-panel" aria-labelledby="published-analysis-title">
          <div className="panel__header"><h2 id="published-analysis-title">Análisis científicos</h2><Database aria-hidden="true" /></div>
          {error && <p role="alert">No se pudo cargar el catálogo. Puedes abrir la publicación científica directamente.</p>}
          {!error && !analyses.length && <p role="status">Cargando análisis…</p>}
          <ul className="published-analysis-list">
            {analyses.map((item) => (
              <li key={item.analysis_id}>
                <strong>{item.analysis_name}</strong> · {item.psi_code}
                <p>{item.description}</p>
                <p>{item.variables.map(({ name, unit }) => `${name} (${unit})`).join(' · ')}</p>
                <a className="text-link" href={`/api/v1/analyses/${encodeURIComponent(item.analysis_id)}`}>Ver resultado y procedencia <ExternalLink aria-hidden="true" /></a>
              </li>
            ))}
          </ul>
          <a className="button button--primary" href={scientificCatalogUrl('science-title')}>Explorar gráficas y metodologías</a>
        </section>
        <AiCopilot experimentId="catalogo" experimentName="Fuentes NASA" />
      </div>
    </div>
  )
}
