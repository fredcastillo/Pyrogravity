import { ArrowRight, CircleGauge, DatabaseZap, Orbit, Sparkles } from 'lucide-react'
import { lazy, Suspense, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { AiCopilot } from '../components/AiCopilot'
import { LineChart } from '../components/LineChart'
import { PageHeader } from '../components/PageHeader'
import { experiments, missionContexts, statusLabel } from '../data/experiments'
import flameLab from '../assets/microgravity-flame-lab.jpg'

const GalaxyScene = lazy(() => import('../components/GalaxyScene').then((module) => ({ default: module.GalaxyScene })))

export function CommandCenter() {
  const [selectedId, setSelectedId] = useState('flex')
  const [mission, setMission] = useState('iss')
  const selected = useMemo(() => experiments.find((item) => item.id === selectedId) ?? experiments[0], [selectedId])

  return (
    <div className="page page--command">
      <PageHeader
        eyebrow="PYROGRAPH / COMBUSTION DIGITAL TWIN"
        title="Flame Intelligence Center"
        description="Observa, compara y comprende el fuego en microgravedad mediante un gemelo visual 4D conectado a evidencia científica."
        actions={<><span className="live-badge"><span /> DATA LINK</span><span className="utc-clock">UTC · 05:42:18</span></>}
      />

      <section className="kpi-grid" aria-label="Indicadores generales">
        <article className="kpi-card"><DatabaseZap /><div><span>Datasets activos</span><strong>21</strong><small>+5 normalizados</small></div></article>
        <article className="kpi-card"><Orbit /><div><span>Investigaciones</span><strong>16</strong><small>NASA PSI</small></div></article>
        <article className="kpi-card"><CircleGauge /><div><span>Cobertura media</span><strong>78%</strong><small>metadatos útiles</small></div></article>
        <article className="kpi-card kpi-card--accent"><Sparkles /><div><span>Evidencia IA</span><strong>92%</strong><small>con fuente vinculada</small></div></article>
      </section>

      <div className="command-grid">
        <section className="panel panel--galaxy" style={{ '--flame-lab': `url(${flameLab})` } as React.CSSProperties}>
          <div className="combustion-backdrop" aria-hidden="true" />
          <div className="panel__header">
            <div><p className="eyebrow">VOLUMETRIC COMBUSTION LAB</p><h2>Cámara experimental 4D</h2></div>
            <div className="legend"><span><i className="legend__verified" /> Flujo térmico</span><span><i className="legend__partial" /> Sondas activas</span></div>
          </div>
          <Suspense fallback={<div className="galaxy-loading"><span /> Inicializando navegación orbital…</div>}>
            <GalaxyScene experiments={experiments} selectedId={selectedId} onSelect={setSelectedId} />
          </Suspense>
        </section>

        <aside className="panel detail-panel" style={{ '--accent': selected.color } as React.CSSProperties}>
          <div className="detail-panel__top"><span className={`status-tag status-tag--${selected.status}`}>{statusLabel[selected.status]}</span><span>{selected.code}</span></div>
          <p className="eyebrow">ENSAYO SELECCIONADO</p>
          <h2>{selected.shortName}</h2>
          <p className="detail-panel__title">{selected.title}</p>
          <p className="muted">{selected.summary}</p>
          <div className="metric-pairs">
            <div><span>Gravedad</span><strong>{selected.gravity}</strong></div>
            <div><span>Oxígeno</span><strong>{selected.oxygen}</strong></div>
            <div><span>Material</span><strong>{selected.material}</strong></div>
            <div><span>Duración</span><strong>{selected.duration}</strong></div>
          </div>
          <div className="coverage"><div><span>Cobertura de datos</span><strong>{selected.completeness}%</strong></div><div className="progress"><span style={{ width: `${selected.completeness}%` }} /></div></div>
          <Link className="button button--primary" to={`/explorer?experiment=${selected.id}`}>Abrir investigación <ArrowRight /></Link>
          <div className="source-note"><DatabaseZap /><span>{selected.source}<small>DOI {selected.doi}</small></span></div>
        </aside>
      </div>

      <section className="mission-strip panel">
        <div><p className="eyebrow">CONTEXTO OPERATIVO</p><h2>Entornos de misión</h2></div>
        <div className="mission-list">
          {missionContexts.map((item) => (
            <button type="button" key={item.id} aria-pressed={mission === item.id} className={mission === item.id ? 'mission-card mission-card--active' : 'mission-card'} onClick={() => setMission(item.id)} style={{ '--mission-accent': item.accent } as React.CSSProperties}>
              <span className="mission-card__planet" /><span><strong>{item.name}</strong><small>{item.label}</small></span><span><b>{item.gravity}</b><small>{item.atmosphere}</small></span>
            </button>
          ))}
        </div>
      </section>

      <div className="analysis-grid">
        <section className="panel chart-panel">
          <div className="panel__header"><div><p className="eyebrow">TELEMETRÍA AUTORIZADA</p><h2>Perfil temporal · {selected.shortName}</h2></div><Link to="/compare" className="text-link">Comparar <ArrowRight /></Link></div>
          <LineChart series={selected.series} color={selected.color} label={selected.shortName} />
          <p className="chart-caption">Visualización normalizada para exploración. Consulta la unidad y la variable original en el detalle de la fuente.</p>
        </section>
        <AiCopilot key={selected.id} experimentId={selected.id} experimentName={selected.shortName} />
      </div>
    </div>
  )
}
