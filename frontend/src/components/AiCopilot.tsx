import { AlertTriangle, BookOpen, CheckCircle2, Database, ExternalLink, FileBarChart, LockKeyhole, Send, ShieldAlert, Sparkles } from 'lucide-react'
import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import type { AiResponse, AiSupportStatus, HydratedChart, ResolvedCitation, ValidatedChartPoint } from '../contracts/ai'
import { AiHttpError, buildAiQuery, queryAi } from '../services/ai'

interface AiCopilotProps {
  experimentId: string
  experimentName: string
  aiContext?: { experimentIds: string[]; variables: string[] }
}

const statusCopy: Record<AiSupportStatus, { label: string; detail: string; icon: typeof CheckCircle2 }> = {
  supported: { label: 'Respaldada', detail: 'Las afirmaciones están vinculadas a evidencia resuelta.', icon: CheckCircle2 },
  partially_supported: { label: 'Parcialmente respaldada', detail: 'La respuesta es útil, pero está condicionada por limitaciones explícitas.', icon: AlertTriangle },
  insufficient_evidence: { label: 'Evidencia insuficiente', detail: 'Las fuentes consultadas no permiten responder con certeza.', icon: ShieldAlert },
}

const provenanceCopy = { live: 'Datos en vivo', cache: 'Caché validada', demo: 'Demostración', degraded: 'Servicio degradado' } as const
const catalogQuestions = ['BASS-II', '¿Qué investigó BASS-II?', 'Metodología de BASS-II']
const experimentQuestions = ['¿Qué evidencia respalda la extinción?', 'Resume las limitaciones', '¿Qué gráfico validado está disponible?']

function safeExternalUrl(value: string) {
  try {
    const url = new URL(value)
    return url.protocol === 'https:' || url.protocol === 'http:' ? url.href : null
  } catch { return null }
}

function pointCoordinates(points: ValidatedChartPoint[]) {
  if (!points.length) return []
  const numericX = points.every((point) => typeof point.x === 'number')
  const xs = points.map((point, index) => numericX ? Number(point.x) : index)
  const ys = points.map((point) => point.y)
  const minX = Math.min(...xs); const maxX = Math.max(...xs); const minY = Math.min(...ys); const maxY = Math.max(...ys)
  return points.map((point, index) => ({
    ...point,
    px: 24 + ((xs[index] - minX) / (maxX - minX || 1)) * 552,
    py: 174 - ((point.y - minY) / (maxY - minY || 1)) * 142,
  }))
}

function ValidatedChart({ chart }: { chart: HydratedChart }) {
  const series = chart.series.filter((item) => item.validated && item.points.length > 0)
  if (!series.length) return <div className="chart-data-lock"><LockKeyhole /><span><strong>Gráfico sin datos autorizados</strong><small>La interfaz no generará puntos. {chart.data_ref ? `Referencia backend: ${chart.data_ref}` : 'El backend no envió una serie hidratada.'}</small></span></div>
  return <div className="hydrated-chart" aria-label={`Gráfico validado: ${chart.title}`}>
    <svg viewBox="0 0 600 200" role="img">
      <title>{chart.title}</title>
      {[0, 1, 2, 3].map((line) => <line key={line} x1="24" x2="576" y1={32 + line * 46} y2={32 + line * 46} className="chart-grid-line" />)}
      {series.map((item, seriesIndex) => {
        const points = pointCoordinates(item.points)
        const color = ['#ff9850', '#50d8ff', '#43f0b6'][seriesIndex % 3]
        if (chart.type === 'bar') return <g key={item.id}>{points.map((point) => <rect key={`${point.x}`} x={point.px - 10} y={point.py} width="20" height={174 - point.py} rx="4" fill={color} />)}</g>
        return <g key={item.id}>{chart.type === 'line' && <polyline points={points.map((point) => `${point.px},${point.py}`).join(' ')} fill="none" stroke={color} strokeWidth="4" strokeLinecap="round" strokeLinejoin="round" />}{points.map((point) => <circle key={`${point.x}`} cx={point.px} cy={point.py} r="5" fill={color}><title>{`${point.x}: ${point.y} ${item.unit ?? ''}`}</title></circle>)}</g>
      })}
    </svg>
    <div className="hydrated-chart__legend">{series.map((item, index) => <span key={item.id}><i style={{ background: ['#ff9850', '#50d8ff', '#43f0b6'][index % 3] }} />{item.label}{item.unit ? ` · ${item.unit}` : ''}</span>)}</div>
  </div>
}

function CitationCard({ citation }: { citation: ResolvedCitation }) {
  const url = safeExternalUrl(citation.url)
  return <article className="evidence-card"><div className="evidence-card__icon">{citation.kind === 'document' ? <BookOpen /> : <Database />}</div><div><span>{citation.kind === 'document' ? 'Fuente documental' : 'Fuente científica'}</span><strong>{citation.title}</strong><p className="citation-snippet">“{citation.snippet}”</p><dl><div><dt>Fuente</dt><dd>{citation.source}</dd></div><div><dt>Página</dt><dd>{citation.page ?? 'No aplica'}</dd></div>{citation.measurement && <><div><dt>Cifra</dt><dd>{citation.measurement.value} {citation.measurement.unit}</dd></div><div><dt>Procedencia</dt><dd>{provenanceCopy[citation.measurement.provenance]}</dd></div></>}</dl>{url ? <a href={url} target="_blank" rel="noreferrer">Abrir fuente <ExternalLink /></a> : <small>URL no válida</small>}</div></article>
}

export function AiCopilot({ experimentId, experimentName, aiContext }: AiCopilotProps) {
  const [question, setQuestion] = useState('')
  const [response, setResponse] = useState<AiResponse | null>(null)
  const [error, setError] = useState<{ status: number; code: string; message: string; requestId?: string } | null>(null)
  const [loading, setLoading] = useState(false)
  const abortRef = useRef<AbortController | null>(null)
  const citationMap = useMemo(() => new Map(response?.citations.map((item) => [item.id, item]) ?? []), [response])
  useEffect(() => () => abortRef.current?.abort(), [])

  async function ask(event: FormEvent) {
    event.preventDefault()
    if (!question.trim() || loading) return
    abortRef.current?.abort()
    const controller = new AbortController(); abortRef.current = controller
    setLoading(true); setError(null); setResponse(null)
    try {
      const request = buildAiQuery(question, { experimentIds: aiContext?.experimentIds ?? [], variables: aiContext?.variables ?? [], chartPreference: 'line' })
      setResponse(await queryAi(request, controller.signal)); setQuestion('')
    } catch (cause) {
      if ((cause as Error).name !== 'AbortError') setError(cause instanceof AiHttpError
        ? { status: cause.status, code: cause.code, message: cause.message, requestId: cause.requestId }
        : { status: 0, code: 'CONTRACT_ERROR', message: cause instanceof Error ? cause.message : 'No fue posible completar la consulta.' })
    } finally { if (!controller.signal.aborted) setLoading(false) }
  }

  const currentStatus = response ? statusCopy[response.status] : null
  const StatusIcon = currentStatus?.icon
  const catalogQuery = experimentId === 'catalogo'
  return <section className="panel copilot-panel copilot-panel--contract" aria-labelledby="ai-copilot-title">
    <div className="panel__header"><div><p className="eyebrow">Biblioteca científica</p><h2 id="ai-copilot-title">Consulta científica verificable</h2></div><Sparkles aria-hidden="true" /></div>
    {catalogQuery ? <p className="published-query-intro">Escribe el nombre de un estudio o pregunta por sus objetivos, método o resultados. Abre las citas para consultar la fuente.</p> :
      <div className="ai-context"><span>Investigación seleccionada</span><strong>{experimentName}</strong><small>{aiContext ? `Ensayos: ${aiContext.experimentIds.join(', ')} · variables: ${aiContext.variables.join(', ')}` : 'La consulta se limita a las fuentes documentales disponibles.'}</small></div>}
    <div className="ai-suggestions" aria-label="Preguntas sugeridas">{(catalogQuery ? catalogQuestions : experimentQuestions).map((suggestion) => <button type="button" key={suggestion} onClick={() => setQuestion(suggestion)}>{suggestion}</button>)}</div>
    <form className="ai-query-form" onSubmit={ask}><label htmlFor="copilot-question" className="sr-only">Pregunta para el copiloto</label><input id="copilot-question" value={question} onChange={(event) => setQuestion(event.target.value)} placeholder={catalogQuery ? '¿Qué te gustaría investigar?' : `Pregunta sobre ${experimentName}…`} aria-describedby="ai-query-note" /><button type="submit" disabled={!question.trim() || loading} aria-label="Enviar pregunta">{loading ? <span className="ai-spinner" /> : <Send />}</button></form>
    <small id="ai-query-note" className="ai-query-note">{catalogQuery ? 'Puedes escribir sin tildes. Incluye el nombre del estudio si buscas un hallazgo concreto.' : 'El alcance de la respuesta depende de las fuentes disponibles.'}</small>
    {loading && <div className="ai-loading" role="status"><span /><div><strong>Buscando evidencia</strong><small>Consultando las fuentes disponibles…</small></div></div>}
    {error && <div className="ai-error" role="alert"><ShieldAlert /><div><strong>{error.code}{error.status ? ` · HTTP ${error.status}` : ''}</strong><p>{error.message}</p>{error.requestId && <small>request_id · <code>{error.requestId}</code></small>}</div></div>}
    {response && currentStatus && StatusIcon && <div className="ai-response" data-status={response.status} data-provenance={response.provenance}>
      {response.provenance === 'demo' && <div className="ai-demo-banner"><AlertTriangle /><strong>DEMOSTRACIÓN · contenido no científico</strong></div>}
      <header className="ai-response__status"><StatusIcon /><div><strong>{currentStatus.label}</strong><span>{currentStatus.detail}</span></div><small>{provenanceCopy[response.provenance]}</small></header>
      <div className="ai-answer"><Sparkles /><div><p>{response.answer}</p>{response.limitations.length > 0 && <div className="ai-limitations-inline"><strong>Limitaciones</strong><ul>{response.limitations.map((item) => <li key={item}>{item}</li>)}</ul></div>}</div></div>
      {response.claims.length > 0 && <section className="ai-section"><div className="ai-section__title"><CheckCircle2 /><h3>Afirmaciones y citas</h3><span>{response.claims.length}</span></div><ol className="claim-list">{response.claims.map((claim) => <li key={claim.id}><p>{claim.text}</p><div className="claim-citations">{claim.citation_ids.map((id) => { const citation = citationMap.get(id); return citation ? <span key={id} className={`citation-chip citation-chip--${citation.kind}`}>{citation.kind === 'document' ? <BookOpen /> : <Database />}{citation.title}{citation.page ? ` · p. ${citation.page}` : ''}</span> : <span key={id} className="citation-chip citation-chip--missing"><ShieldAlert />Cita {id} no recibida</span> })}</div></li>)}</ol></section>}
      {response.citations.length > 0 && <section className="ai-section"><div className="ai-section__title"><Database /><h3>Citas resueltas</h3><span>{response.citations.length}</span></div><div className="evidence-grid">{response.citations.map((citation) => <CitationCard key={citation.id} citation={citation} />)}</div></section>}
      {response.charts.length > 0 && <section className="ai-section"><div className="ai-section__title"><FileBarChart /><h3>Gráficos validados</h3><span>{response.charts.length}</span></div><div className="chart-spec-list">{response.charts.map((chart) => <article key={chart.id} className="chart-spec-card"><div><FileBarChart /><span>{chart.type} · {provenanceCopy[chart.provenance]}</span></div><h4>{chart.title}</h4><ValidatedChart chart={chart} />{chart.limitations.length > 0 && <ul className="chart-limitations">{chart.limitations.map((item) => <li key={item}>{item}</li>)}</ul>}</article>)}</div></section>}
      <footer className="ai-response__meta"><span>id</span><code>{response.id}</code><span>schema</span><code>{response.schema_version}</code><span>provenance</span><code>{response.provenance}</code></footer>
    </div>}
  </section>
}
