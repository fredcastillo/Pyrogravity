import { ArrowRight, Database, ExternalLink, Telescope } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { AiCopilot } from '../components/AiCopilot'
import { scientificCatalogUrl } from '../scientificCatalog'
import { reveal } from '../space/motion'
import flameLab from '../assets/microgravity-flame-lab.jpg'

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
  const page = useRef<HTMLDivElement>(null)

  useEffect(() => {
    return reveal(page.current?.querySelectorAll('[data-reveal]') ?? [])
  }, [])

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
    <div className="page page--published" ref={page}>
      <header className="page-header published-hero">
        <img className="published-hero__image" src={flameLab} alt="" fetchPriority="high" data-orbital-art />
        <div className="published-hero__copy" data-reveal>
          <p className="eyebrow published-kicker"><Telescope aria-hidden="true" /> Observatorio de combustión</p>
          <h1>Flame Intelligence <span>Center</span></h1>
          <p>Explora cómo se comporta el fuego en microgravedad con datos de experimentos de NASA.</p>
          <div className="published-hero__actions">
            <a className="published-primary" href={scientificCatalogUrl('catalog-title')}>Abrir el Atlas <ArrowRight aria-hidden="true" /></a>
            <a className="published-secondary" href="#scientific-query">Consultar fuentes</a>
          </div>
        </div>
      </header>
      <div className="analysis-grid published-grid">
        <section className="panel published-catalog" aria-labelledby="published-analysis-title" data-reveal>
          <div className="panel__header">
            <div><p className="eyebrow">Datos experimentales</p><h2 id="published-analysis-title">Análisis científicos</h2></div>
            <Database aria-hidden="true" />
          </div>
          {error && <p className="published-status" role="alert">No se pudo cargar la lista. Abre el Atlas para consultar el catálogo.</p>}
          {!error && !analyses.length && <p role="status">Cargando análisis…</p>}
          <ul className="published-analysis-list">
            {analyses.map((item) => (
              <li key={item.analysis_id}>
                <div className="published-analysis-title"><h3>{item.analysis_name}</h3><span>{item.psi_code}</span></div>
                <p>{item.description}</p>
                <ul className="published-variables" aria-label="Variables y unidades">
                  {item.variables.map(({ name, unit }) => <li key={name}>{name} <span>{unit}</span></li>)}
                </ul>
                <a className="text-link" href={`/api/v1/analyses/${encodeURIComponent(item.analysis_id)}`}>Ver resultado y procedencia <ExternalLink aria-hidden="true" /></a>
              </li>
            ))}
          </ul>
          <a className="published-analysis-link" href={scientificCatalogUrl('science-title')}>Explorar gráficas y metodologías <ArrowRight aria-hidden="true" /></a>
        </section>
        <div id="scientific-query" data-reveal><AiCopilot experimentId="catalogo" experimentName="Fuentes NASA" /></div>
      </div>
    </div>
  )
}
