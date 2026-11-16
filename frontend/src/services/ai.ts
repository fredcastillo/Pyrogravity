import { AI_PUBLIC_CONTRACT_VERSION, AI_QUERY_PATH, type AiProvenance, type AiQueryRequest, type AiResponse, type ApiErrorEnvelope, type ChartType } from '../contracts/ai'

type QueryContext = { experimentIds?: string[]; variables?: string[]; chartPreference?: ChartType | null }
type QueryOptions = { fetcher?: typeof fetch; demo?: boolean }

export class AiHttpError extends Error {
  constructor(
    public readonly status: number,
    message: string,
    public readonly code = 'HTTP_ERROR',
    public readonly requestId?: string,
    public readonly details: Record<string, unknown> = {},
  ) {
    super(message)
    this.name = 'AiHttpError'
  }
}

function requestId() {
  return globalThis.crypto?.randomUUID?.() ?? `req-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

export function buildAiQuery(question: string, context: QueryContext = {}): AiQueryRequest {
  return {
    id: requestId(),
    question: question.trim(),
    language: 'es',
    experiment_ids: context.experimentIds ?? [],
    variables: context.variables ?? [],
    chart_preference: context.chartPreference ?? null,
  }
}

function isProvenance(value: unknown): value is AiProvenance {
  return ['live', 'cache', 'demo', 'degraded'].includes(String(value))
}

function isSafeBackendRef(value: string | null) {
  return value === null || value.startsWith('/api/v1/')
}

export function isAiResponse(value: unknown): value is AiResponse {
  if (!value || typeof value !== 'object') return false
  const candidate = value as Partial<AiResponse>
  const statuses = ['supported', 'partially_supported', 'insufficient_evidence']
  const chartTypes = ['line', 'bar', 'scatter']
  return candidate.schema_version === AI_PUBLIC_CONTRACT_VERSION
    && typeof candidate.id === 'string'
    && statuses.includes(candidate.status ?? '')
    && typeof candidate.answer === 'string'
    && isProvenance(candidate.provenance)
    && Array.isArray(candidate.claims) && candidate.claims.every((claim) => typeof claim.id === 'string' && typeof claim.text === 'string' && Array.isArray(claim.citation_ids))
    && Array.isArray(candidate.citations) && candidate.citations.every((citation) => typeof citation.id === 'string' && ['document', 'scientific'].includes(citation.kind) && typeof citation.title === 'string' && typeof citation.url === 'string' && (citation.page === null || Number.isInteger(citation.page)) && typeof citation.snippet === 'string')
    && Array.isArray(candidate.limitations) && candidate.limitations.every((item) => typeof item === 'string')
    && Array.isArray(candidate.charts) && candidate.charts.every((chart) => typeof chart.id === 'string' && chartTypes.includes(chart.type) && isProvenance(chart.provenance) && isSafeBackendRef(chart.data_ref) && Array.isArray(chart.series) && chart.series.every((series) => series.validated === true && Array.isArray(series.points) && series.points.every((point) => ['string', 'number'].includes(typeof point.x) && typeof point.y === 'number' && Number.isFinite(point.y))))
}

export function isApiErrorEnvelope(value: unknown): value is ApiErrorEnvelope {
  if (!value || typeof value !== 'object' || !('error' in value)) return false
  const error = (value as Partial<ApiErrorEnvelope>).error
  return !!error && typeof error.code === 'string' && typeof error.message === 'string' && typeof error.request_id === 'string' && !!error.details && typeof error.details === 'object'
}

function demoResponse(request: AiQueryRequest): AiResponse {
  return {
    schema_version: AI_PUBLIC_CONTRACT_VERSION,
    id: request.id,
    status: 'insufficient_evidence',
    answer: 'Modo demostración: no hay conexión con el backend y no se presentan mediciones ni conclusiones científicas.',
    claims: [],
    citations: [],
    limitations: ['Contenido sintético de interfaz. No representa datos de NASA ni resultados de un ensayo.', 'El modo demo no consulta el endpoint público del backend.'],
    charts: [],
    provenance: 'demo',
  }
}

function messageFromHttp(status: number) {
  if (status === 400) return 'El backend rechazó la estructura de la consulta.'
  if (status === 401 || status === 403) return 'La consulta no está autorizada.'
  if (status === 404) return 'El contrato público de IA todavía no está disponible.'
  if (status >= 500) return 'El servicio de evidencia no está disponible temporalmente.'
  return `La consulta falló con HTTP ${status}.`
}

export async function queryAi(request: AiQueryRequest, signal?: AbortSignal, options: QueryOptions = {}): Promise<AiResponse> {
  if (!request.question) throw new Error('La pregunta no puede estar vacía.')
  if (options.demo ?? import.meta.env.VITE_AI_DEMO_MODE === 'true') return demoResponse(request)

  let response: Response
  try {
    response = await (options.fetcher ?? fetch)(AI_QUERY_PATH, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify(request),
      credentials: 'same-origin',
      signal,
    })
  } catch (cause) {
    if ((cause as Error).name === 'AbortError') throw cause
    throw new AiHttpError(0, 'No fue posible conectar con /api/v1/ai/query.')
  }
  const payload: unknown = await response.json().catch(() => null)
  if (!response.ok) {
    const headerRequestId = response.headers.get('X-Request-ID') ?? undefined
    if (isApiErrorEnvelope(payload)) {
      throw new AiHttpError(response.status, payload.error.message, payload.error.code, payload.error.request_id || headerRequestId, payload.error.details)
    }
    throw new AiHttpError(response.status, messageFromHttp(response.status), 'HTTP_ERROR', headerRequestId)
  }
  if (!isAiResponse(payload)) throw new Error('La respuesta no cumple el contrato público versionado del backend.')
  if (payload.id !== request.id) throw new Error('El id de la respuesta no coincide con la solicitud.')
  return payload
}
