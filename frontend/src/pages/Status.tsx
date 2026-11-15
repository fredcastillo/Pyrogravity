import { Activity, CheckCircle2, CloudCog, Database, HardDrive, RefreshCw } from 'lucide-react'
import { PageHeader } from '../components/PageHeader'

const services = [
  { name: 'Frontend', detail: 'React · snapshot local', state: 'Operativo', icon: Activity },
  { name: 'Datos científicos', detail: '21 datasets indexados', state: 'Operativo', icon: Database },
  { name: 'API FastAPI', detail: 'Contrato v1 pendiente', state: 'Modo mock', icon: CloudCog },
  { name: 'Copiloto IA', detail: 'Respuestas verificadas locales', state: 'Modo mock', icon: RefreshCw },
  { name: 'Recuperación', detail: 'Snapshot 15 NOV 2026', state: 'Disponible', icon: HardDrive },
]

export function Status() {
  return (
    <div className="page">
      <PageHeader eyebrow="OBSERVABILIDAD" title="Estado del sistema" description="La demo conserva un recorrido verificable incluso cuando los servicios externos no responden." actions={<span className="live-badge"><span /> SNAPSHOT ACTIVO</span>} />
      <section className="status-overview panel"><div><CheckCircle2 /><span><strong>Todos los recorridos críticos disponibles</strong><small>Última comprobación · hace 38 s</small></span></div><span>99.98% UI</span></section>
      <section className="service-list panel">{services.map(({ name, detail, state, icon: Icon }) => <article key={name}><Icon /><div><strong>{name}</strong><span>{detail}</span></div><span className={state === 'Operativo' || state === 'Disponible' ? 'service-state service-state--ok' : 'service-state'}>{state}</span></article>)}</section>
      <section className="panel scientific-note"><strong>Política de degradación</strong><p>El frontend identifica con una etiqueta persistente cuándo los valores provienen del snapshot. Los datos simulados no se mezclan con mediciones reales y las credenciales nunca se exponen en el navegador.</p></section>
    </div>
  )
}
