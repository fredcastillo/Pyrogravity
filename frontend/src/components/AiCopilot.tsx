import { AlertTriangle, BookOpen, CheckCircle2, Clock3, Database, FileBarChart, LockKeyhole, Send, ShieldAlert, Sparkles } from 'lucide-react'
import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import type { AiResponse, AiResponseStatus, AnalysisId, Evidence } from '../contracts/ai'
import { buildAiQuery, queryAi } from '../services/ai'

interface AiCopilotProps {
  experimentId: string
  experimentName: string
}

const analysisByExperiment: Record<string, AnalysisId | undefined> = {
  flex: 'flex',
  'bass-ii': 'bass-ii',
  cfi: 'cfi-g',
}

const statusCopy: Record<AiResponseStatus, { label: string; detail: string; icon: typeof CheckCircle2 }> = {
  supported: { label: 'Respaldada', detail: 'Todas las afirmaciones tienen evidencia vinculada.', icon: CheckCircle2 },
  partially_supported: { label: 'Parcialmente respaldada', detail: 'Existen límites o evidencia indirecta que debes revisar.', icon: AlertTriangle },
  insufficient_evidence: { label: 'Sin evidencia suficiente', detail: 'No hay evidencia verificable para responder.', icon: ShieldAlert },
  invalid_request: { label: 'Solicitud inválida', detail: 'La pregunta no cumple el contrato de consulta.', icon: ShieldAlert },
  upstream_unavailable: { label: 'Servicio no disponible', detail: 'Una dependencia del backend no respondió.', icon: ShieldAlert },
}

function citationLabel(evidence: Evidence) {
  if (evidence.kind === 'document') return `Documento · p. ${evidence.page_number}`
  return `${evidence.dataset.psi_code} · ${evidence.datum.variable_code} ${evidence.datum.value} ${evidence.datum.unit}`
}

function safeExternalUrl(value: string) {
  try {
    const url = new URL(value)
    return url.protocol === 'https:' || url.protocol === 'http:' ? url.href : null
  } catch {
    return null
  }
}

export function AiCopilot({ experimentId, experimentName }: AiCopilotProps) {
  const [question, setQuestion] = useState('')
  const [response, setResponse] = useState<AiResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const abortRef = useRef<AbortController | null>(null)
  const evidenceMap = useMemo(() => new Map(response?.evidence.map((item) => [item.evidence_id, item]) ?? []), [response])

  useEffect(() => () => abortRef.current?.abort(), [])

  async function ask(event: FormEvent) {
    event.preventDefault()
    if (!question.trim() || loading) return
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    setLoading(true)
    setError(null)
    try {
      const request = buildAiQuery(question, analysisByExperiment[experimentId] ?? null)
      setResponse(await queryAi(request, controller.signal))
      setQuestion('')
    } catch (cause) {
      if ((cause as Error).name !== 'AbortError') setError(cause instanceof Error ? cause.message : 'No fue posible completar la consulta.')
    } finally {
      if (!controller.signal.aborted) setLoading(false)
    }
  }

  const currentStatus = response ? statusCopy[response.status] : null
  const StatusIcon = currentStatus?.icon
  const limitations = [...(response?.limitations ?? []), ...(response?.visualizations.flatMap((chart) => chart.limitations) ?? [])]

  return (
    <section className="panel copilot-panel copilot-panel--contract" aria-labelledby="ai-copilot-title">
      <div className="panel__header">
        <div><p className="eyebrow">AI EVIDENCE PROTOCOL · V1.0</p><h2 id="ai-copilot-title">Consulta científica verificable</h2></div>
        <Sparkles aria-hidden="true" />
      </div>

      <div className="ai-context"><span>Contexto activo</span><strong>{experimentName}</strong><small>{analysisByExperiment[experimentId] ? `analysis_id: ${analysisByExperiment[experimentId]}` : 'Sin analysis_id directo · se exigirá evidencia explícita'}</small></div>

      <div className="ai-suggestions" aria-label="Preguntas sugeridas">
        {['¿Qué evidencia respalda la extinción?', 'Resume las limitaciones', '¿Qué gráfico está disponible?'].map((suggestion) => <button type="button" key={suggestion} onClick={() => setQuestion(suggestion)}>{suggestion}</button>)}
      </div>

      <form className="ai-query-form" onSubmit={ask}>
        <label htmlFor="copilot-question" className="sr-only">Pregunta para el copiloto</label>
        <input id="copilot-question" value={question} onChange={(event) => setQuestion(event.target.value)} placeholder={`Pregunta sobre ${experimentName}…`} aria-describedby="ai-query-note" />
        <button type="submit" disabled={!question.trim() || loading} aria-label="Enviar pregunta">{loading ? <span className="ai-spinner" /> : <Send />}</button>
      </form>
      <small id="ai-query-note" className="ai-query-note">El backend debe responder con AiResponse 1.0. La interfaz no mezcla evidencia ausente con hechos validados.</small>

      {loading && <div className="ai-loading" role="status"><span /><div><strong>Consultando evidencia</strong><small>Correlacionando afirmaciones, fuentes y ChartSpec…</small></div></div>}
      {error && <div className="ai-error" role="alert"><ShieldAlert /><div><strong>Error de contrato o transporte</strong><p>{error}</p></div></div>}

      {response && currentStatus && StatusIcon && (
        <div className="ai-response" data-status={response.status}>
          <header className="ai-response__status"><StatusIcon /><div><strong>{currentStatus.label}</strong><span>{currentStatus.detail}</span></div><small>{response.intent.replaceAll('_', ' ')} · {response.metrics.latency_ms ?? '—'} ms</small></header>
          <div className="ai-answer"><Sparkles /><p>{response.answer}</p></div>

          {limitations.length > 0 && <section className="ai-limitations"><AlertTriangle /><div><strong>Limitaciones que condicionan la respuesta</strong><ul>{limitations.map((item) => <li key={item}>{item}</li>)}</ul></div></section>}

          {response.claims.length > 0 && <section className="ai-section"><div className="ai-section__title"><CheckCircle2 /><h3>Afirmaciones y respaldo</h3><span>{response.claims.length}</span></div><ol className="claim-list">{response.claims.map((claim) => <li key={claim.claim_id}><p>{claim.text}</p><div className="claim-citations">{claim.evidence_ids.map((id) => { const evidence = evidenceMap.get(id); return evidence ? <span key={id} className={`citation-chip citation-chip--${evidence.kind}`}>{evidence.kind === 'document' ? <BookOpen /> : <Database />}{citationLabel(evidence)}</span> : <span key={id} className="citation-chip citation-chip--missing"><ShieldAlert />Evidencia {id} no recibida</span> })}</div></li>)}</ol></section>}

          {response.evidence.length > 0 && <section className="ai-section"><div className="ai-section__title"><Database /><h3>Fuentes trazables</h3><span>{response.evidence.length}</span></div><div className="evidence-grid">{response.evidence.map((item) => item.kind === 'document' ? <article key={item.evidence_id} className="evidence-card"><BookOpen /><div><span>Fuente documental</span><strong>{item.source_id}</strong><dl><div><dt>Página</dt><dd>{item.page_number}</dd></div><div><dt>DOI</dt><dd>{item.doi ?? 'No informado'}</dd></div><div><dt>Hash</dt><dd>{item.chunk_sha256.slice(0, 12)}…</dd></div></dl>{safeExternalUrl(item.source_url) ? <a href={safeExternalUrl(item.source_url) ?? undefined} target="_blank" rel="noreferrer">Abrir fuente</a> : <small>URL de fuente no válida</small>}</div></article> : <article key={item.evidence_id} className="evidence-card"><Database /><div><span>Dato científico validado</span><strong>{item.dataset.psi_code} · {item.datum.variable_code}</strong><dl><div><dt>Medición</dt><dd>{item.datum.value} {item.datum.unit}</dd></div><div><dt>Tipo</dt><dd>{item.datum.kind}</dd></div><div><dt>Dataset</dt><dd>{item.dataset.relative_path}</dd></div><div><dt>Muestras</dt><dd>{item.datum.sample_count ?? '—'}</dd></div></dl></div></article>)}</div></section>}

          {response.visualizations.length > 0 && <section className="ai-section"><div className="ai-section__title"><FileBarChart /><h3>Gráficos solicitados</h3><span>{response.visualizations.length}</span></div><div className="chart-spec-list">{response.visualizations.map((chart) => <article key={chart.chart_id} className="chart-spec-card"><div><FileBarChart /><span>{chart.type}</span></div><h4>{chart.title}</h4><dl><div><dt>Eje X</dt><dd>{chart.x.label}{chart.x.unit ? ` (${chart.x.unit})` : ''}</dd></div><div><dt>Eje Y</dt><dd>{chart.y.label}{chart.y.unit ? ` (${chart.y.unit})` : ''}</dd></div></dl><div className="chart-data-lock"><LockKeyhole /><span><strong>Datos no solicitados</strong><small>Esperando endpoint autorizado por backend · <code>{chart.data_ref}</code></small></span></div></article>)}</div></section>}

          <footer className="ai-response__meta"><Clock3 /><span>request_id</span><code>{response.request_id}</code><span>schema</span><code>{response.schema_version}</code></footer>
        </div>
      )}
    </section>
  )
}
