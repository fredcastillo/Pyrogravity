import { ArrowRight, ArrowUpRight, Database } from 'lucide-react'
import { useEffect, useState } from 'react'
import { AiCopilot } from '../components/AiCopilot'
import { FeaturedExperiment } from '../components/FeaturedExperiment'
import { scientificCatalogUrl } from '../scientificCatalog'
import flame from '../assets/nasa-flame-design.webp'
import smallFlame from '../assets/nasa-flame-design-small.webp'

interface Analysis {
  analysis_id: string
  analysis_name: string
  psi_code: string
  description: string
  variables: { name: string; unit: string }[]
}

const editorial: Record<string, [string, string]> = {
  'bass-ii': ['CO₂ en BASS-II', 'Compara la concentración de CO₂ al inicio y al final de los ensayos.'],
  flex: ['Combustión de gotas en FLEX', 'Explora la duración, el diámetro inicial de la gota y la presión ambiente.'],
  'flame-design': ['Presión en Flame Design', 'Compara los cambios de presión en configuraciones de llama normal e inversa.'],
  'cfi-g': ['Duración en CFI-G', 'Consulta cuánto duró la combustión por configuración y tipo de terminación.'],
  spice: ['Flujos en SPICE', 'Explora los ajustes del flujo de aire y combustible por boquilla y tipo de combustible.'],
}

export function PublishedCenter() {
  const [analyses, setAnalyses] = useState<Analysis[] | null>(null)
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
    <div className="observatory-content">
      <section className="published-hero" aria-labelledby="home-title">
        <div className="published-hero__copy">
          <p className="editorial-label">Observatorio de combustión</p>
          <h1 id="home-title">El fuego en <span>microgravedad.</span></h1>
          <p>Mira cómo arde una llama en órbita, compara ensayos y sigue cada medición hasta el archivo de NASA.</p>
          <div className="published-hero__actions">
            <a className="published-primary" href={scientificCatalogUrl('catalog-title')}>Abrir el Atlas <ArrowRight aria-hidden="true" /></a>
            <a className="published-secondary" href="#primer-experimento">Ver un experimento</a>
          </div>
        </div>
        <figure className="published-hero__figure">
          <div className="published-hero__image">
            <picture data-orbital-art>
              <source media="(max-width: 650px)" srcSet={smallFlame} />
              <img src={flame} width="1041" height="952" fetchPriority="high"
                alt="Una llama azul redondeada con puntos de hollín incandescente en su interior" />
            </picture>
          </div>
          <figcaption>
            <span>Flame Design · Estación Espacial Internacional, 2020</span>
            <a href="https://www.nasa.gov/image-article/studying-flames-microgravity/">Foto de NASA <ArrowUpRight aria-hidden="true" /></a>
          </figcaption>
        </figure>
      </section>
      <FeaturedExperiment />
      <div className="published-grid">
        <section className="panel published-catalog" aria-labelledby="published-analysis-title">
          <div className="panel__header">
            <div><p className="eyebrow">Datos experimentales</p><h2 id="published-analysis-title">Análisis científicos</h2></div>
            <Database aria-hidden="true" />
          </div>
          {error && <p className="published-status" role="alert">No se pudo cargar la lista. Abre el Atlas para consultar el catálogo.</p>}
          {!error && analyses === null && <p role="status">Cargando análisis…</p>}
          {analyses?.length === 0 && <p role="status">No hay análisis publicados disponibles.</p>}
          <ul className="published-analysis-list">
            {analyses?.map((item) => {
              const [title, description] = editorial[item.analysis_id] ?? [item.analysis_name, item.description]
              return <li key={item.analysis_id}>
                <div className="published-analysis-title"><h3>{title}</h3><span>{item.psi_code}</span></div>
                <p>{description}</p>
                <div className="published-analysis-actions">
                  <a className="text-link" href={scientificCatalogUrl('science-title', { analysis: item.analysis_id })}>
                    Ver resultado y procedencia <ArrowRight aria-hidden="true" />
                  </a>
                  <details>
                    <summary>Variables y unidades</summary>
                    <ul className="published-variables" aria-label="Variables y unidades">
                      {item.variables.map(({ name, unit }) => <li key={name}>{name} <span>{unit}</span></li>)}
                    </ul>
                  </details>
                </div>
              </li>
            })}
          </ul>
          <a className="published-analysis-link" href={scientificCatalogUrl('science-title')}>Explorar gráficas y metodologías <ArrowRight aria-hidden="true" /></a>
        </section>
        <div id="scientific-query" tabIndex={-1}><AiCopilot experimentId="catalogo" experimentName="Fuentes NASA" /></div>
      </div>
    </div>
  )
}
