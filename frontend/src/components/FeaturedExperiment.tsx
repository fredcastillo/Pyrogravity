import { ArrowRight, ArrowUpRight } from 'lucide-react'
import { useEffect, useState } from 'react'
import { scientificCatalogUrl } from '../scientificCatalog'

const experiments = {
  flex: { label: 'FLEX', code: 'PSI-69', trials: '1,2,3' },
  bass_ii: { label: 'BASS-II', code: 'PSI-25', trials: 'B1,B2,B3' },
}
type Experiment = keyof typeof experiments

interface Reading {
  trial: string
  value: string | null
  status: string
  source_record: number
}

interface Comparison {
  dataset: { metric_label: string; unit: string; source: string }
  measurements: Reading[]
}

export function FeaturedExperiment() {
  const [selected, setSelected] = useState<Experiment>('flex')
  const [result, setResult] = useState<Comparison | null>(null)
  const [failed, setFailed] = useState(false)
  const experiment = experiments[selected]

  useEffect(() => {
    const controller = new AbortController()
    const query = new URLSearchParams({ dataset: selected, trials: experiment.trials })
    async function loadComparison() {
      try {
        const response = await fetch(`/api/v1/compare?${query}`, { signal: controller.signal })
        if (!response.ok) throw new Error('Comparación no disponible')
        setResult(await response.json())
      } catch {
        if (!controller.signal.aborted) setFailed(true)
      }
    }
    void loadComparison()
    return () => controller.abort()
  }, [selected, experiment.trials])

  function selectExperiment(next: Experiment) {
    if (next === selected) return
    setResult(null)
    setFailed(false)
    setSelected(next)
  }

  const readings = result?.measurements.filter((row): row is Reading & { value: string } =>
    row.status === 'exact' && row.value !== null && row.value.trim() !== '' &&
    Number.isFinite(Number(row.value)) && Number(row.value) >= 0
  ) ?? []
  const maximum = Math.max(1, ...readings.map((row) => Number(row.value)))
  const unit = result?.dataset.unit === '% by vol' ? '% vol.' : result?.dataset.unit

  return (
    <section className="feature-experiment" aria-labelledby="featured-title" id="primer-experimento">
      <div className="feature-experiment__intro">
        <p className="editorial-label">FLEX y BASS-II</p>
        <h2 id="featured-title">¿Qué muestran tres ensayos?</h2>
        <p>Elige una investigación para comparar mediciones registradas por NASA. Cada valor conserva la fila de su tabla de origen.</p>
        <a className="published-analysis-link" href={scientificCatalogUrl('comparison-title', { dataset: selected })}>
          Abrir comparador <ArrowRight aria-hidden="true" />
        </a>
      </div>
      <div className="feature-chart">
        <div className="feature-chart__controls">
          <fieldset className="feature-tabs">
            <legend className="sr-only">Investigación para comparar</legend>
            {(Object.keys(experiments) as Experiment[]).map((key) =>
              <label key={key}>
                <input className="sr-only" type="radio" name="featured-study" value={key}
                  checked={selected === key} onChange={() => selectExperiment(key)} />
                <span>{experiments[key].label}</span>
              </label>
            )}
          </fieldset>
          <span className="feature-chart__code">{experiment.code}</span>
        </div>
        <div className="feature-chart__body" aria-live="polite" aria-busy={!result && !failed}>
          {failed && <p role="alert">La comparación no está disponible en este momento.</p>}
          {!result && !failed && <p role="status">Cargando mediciones…</p>}
          {result && <>
            <h3>{result.dataset.metric_label}</h3>
            {readings.length ? <ul className="feature-readings">{readings.map((row) =>
              <li key={row.source_record}>
                <span>Ensayo {row.trial}<small>Fila {row.source_record}</small></span>
                <meter min={0} max={maximum} value={Number(row.value)} aria-hidden="true" />
                <strong>{row.value.replace('.', ',')} <span>{unit}</span></strong>
              </li>
            )}</ul> : <p>Esta selección no contiene mediciones exactas.</p>}
            <a className="feature-chart__source" href={result.dataset.source}>
              Consultar investigación en NASA <ArrowUpRight aria-hidden="true" />
            </a>
          </>}
        </div>
      </div>
    </section>
  )
}
