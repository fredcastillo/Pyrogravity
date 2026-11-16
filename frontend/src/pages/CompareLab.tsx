import { AlertTriangle, CheckCircle2, GitCompareArrows } from 'lucide-react'
import { useMemo, useState } from 'react'
import { LineChart } from '../components/LineChart'
import { PageHeader } from '../components/PageHeader'
import { experiments } from '../data/experiments'

export function CompareLab() {
  const [leftId, setLeftId] = useState('flex')
  const [rightId, setRightId] = useState('cfi')
  const left = useMemo(() => experiments.find((item) => item.id === leftId) ?? experiments[0], [leftId])
  const right = useMemo(() => experiments.find((item) => item.id === rightId) ?? experiments[1], [rightId])
  const compatible = left.field === right.field
  return (
    <div className="page">
      <PageHeader eyebrow="LABORATORIO DE COMPARACIÓN" title="Comparador de ensayos" description="Contrasta series compatibles y conserva unidades, filtros y procedencia en la misma vista." />
      <section className="comparison-selectors panel">
        <label><span>Ensayo A</span><select value={leftId} onChange={(event) => setLeftId(event.target.value)}>{experiments.map((item) => <option key={item.id} value={item.id}>{item.shortName} · {item.code}</option>)}</select></label>
        <GitCompareArrows aria-hidden="true" />
        <label><span>Ensayo B</span><select value={rightId} onChange={(event) => setRightId(event.target.value)}>{experiments.filter((item) => item.id !== leftId).map((item) => <option key={item.id} value={item.id}>{item.shortName} · {item.code}</option>)}</select></label>
      </section>
      <div className={compatible ? 'compatibility compatibility--ok' : 'compatibility compatibility--warning'}>{compatible ? <CheckCircle2 /> : <AlertTriangle />}<div><strong>{compatible ? 'Comparación exploratoria compatible' : 'Condiciones no equivalentes'}</strong><p>{compatible ? 'Ambos ensayos pertenecen a la misma familia. La escala se normaliza solo para inspección visual.' : 'Las familias de combustible difieren. No se calcularán diferencias cuantitativas hasta recibir una regla científica explícita.'}</p></div></div>
      <section className="panel comparison-chart"><div className="panel__header"><div><p className="eyebrow">SERIES NORMALIZADAS</p><h2>{left.shortName} × {right.shortName}</h2></div><span className="status-tag status-tag--partial">Modo snapshot</span></div><LineChart series={left.series} color={left.color} label={left.shortName} secondary={{ series: right.series, color: right.color, label: right.shortName }} /></section>
      <div className="comparison-grid">
        {[left, right].map((item) => <article key={item.id} className="panel comparison-card" style={{ '--accent': item.color } as React.CSSProperties}><p className="eyebrow">{item.code}</p><h2>{item.shortName}</h2><dl className="metadata-list"><div><dt>Material</dt><dd>{item.material}</dd></div><div><dt>Oxígeno</dt><dd>{item.oxygen}</dd></div><div><dt>Duración</dt><dd>{item.duration}</dd></div><div><dt>Muestras</dt><dd>{item.sampleCount}</dd></div></dl><p className="source-inline">{item.source}<br /><small>DOI {item.doi}</small></p></article>)}
      </div>
    </div>
  )
}
