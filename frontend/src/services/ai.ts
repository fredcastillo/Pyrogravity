import type { AiQueryRequest, AiResponse, AnalysisId, Evidence } from '../contracts/ai'

const endpoint = import.meta.env.VITE_AI_QUERY_ENDPOINT as string | undefined

function requestId() {
  return globalThis.crypto?.randomUUID?.() ?? `req-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

export function buildAiQuery(question: string, analysisId?: AnalysisId | null): AiQueryRequest {
  return {
    schema_version: '1.0',
    request_id: requestId(),
    question: question.trim(),
    language: 'es',
    analysis_id: analysisId ?? null,
    filters: {},
  }
}

function isAiResponse(value: unknown): value is AiResponse {
  if (!value || typeof value !== 'object') return false
  const candidate = value as Partial<AiResponse>
  const statuses = ['supported', 'partially_supported', 'insufficient_evidence', 'invalid_request', 'upstream_unavailable']
  const intents = ['scientific_analysis', 'document_question', 'combined', 'unknown']
  const chartTypes = ['bar', 'line', 'scatter', 'histogram', 'box', 'heatmap']
  return candidate.schema_version === '1.0'
    && typeof candidate.request_id === 'string'
    && statuses.includes(candidate.status ?? '')
    && intents.includes(candidate.intent ?? '')
    && typeof candidate.answer === 'string'
    && Array.isArray(candidate.claims) && candidate.claims.every((claim) => typeof claim.claim_id === 'string' && typeof claim.text === 'string' && Array.isArray(claim.evidence_ids) && claim.evidence_ids.every((id) => typeof id === 'string'))
    && Array.isArray(candidate.evidence) && candidate.evidence.every((item) => item.kind === 'document'
      ? typeof item.evidence_id === 'string' && typeof item.source_id === 'string' && Number.isInteger(item.page_number) && typeof item.source_url === 'string'
      : item.kind === 'scientific' && typeof item.evidence_id === 'string' && typeof item.dataset?.ref_id === 'string' && typeof item.datum?.datum_id === 'string' && item.datum?.validation_status === 'validated')
    && Array.isArray(candidate.visualizations) && candidate.visualizations.every((chart) => chart.schema_version === '1.0' && typeof chart.chart_id === 'string' && chartTypes.includes(chart.type) && typeof chart.data_ref === 'string' && Array.isArray(chart.dataset_ref_ids) && Array.isArray(chart.limitations))
    && Array.isArray(candidate.limitations) && candidate.limitations.every((item) => typeof item === 'string')
    && !!candidate.metrics && typeof candidate.metrics === 'object'
}

function demoEvidence(): Evidence[] {
  return [
    {
      kind: 'document',
      evidence_id: 'ev-doc-flex-01',
      source_id: 'nasa-flex-overview',
      document_sha256: 'd4af36c17b29c6c165248ce88dbb99620dc7b681424f0d31079e3adb7d0b54b1',
      chunk_sha256: '33f2967cd9c24312dc727eb9f3e44bc9ed11d968c2df51d58a1e670849ce2047',
      page_number: 42,
      source_url: 'https://www.nasa.gov/',
      doi: '10.60555/mbq8-0451',
    },
    {
      kind: 'scientific',
      evidence_id: 'ev-data-flex-01',
      dataset: {
        ref_id: 'dataset-flex-v5',
        psi_code: 'PSI-69',
        relative_path: 'normalized/flex/temperature_profile.csv',
        sha256: '065aa6f851566fcf9d89be0e780848b6ab64ff7ffb0d785f304bd7a51447d574',
        nasa_psi_url: 'https://www.nasa.gov/',
        database_dataset_id: null,
      },
      datum: {
        datum_id: 'datum-flex-temp-peak',
        dataset_ref_id: 'dataset-flex-v5',
        variable_code: 'TEMP_PEAK',
        value: '812.4',
        unit: 'K',
        validation_status: 'validated',
        kind: 'measurement',
        source_record: 'FLEX_RUN_184',
        column_ordinal: 7,
        sample_count: 184,
      },
    },
  ]
}

function demoResponse(request: AiQueryRequest): AiResponse {
  const evidence = demoEvidence()
  const partial = request.analysis_id !== 'flex' && request.analysis_id !== 'bass-ii'
  return {
    schema_version: '1.0',
    request_id: request.request_id,
    status: partial ? 'partially_supported' : 'supported',
    intent: 'combined',
    answer: partial
      ? 'La evidencia disponible permite describir el comportamiento general, pero no atribuir una magnitud definitiva al ensayo seleccionado.'
      : 'La evidencia disponible respalda una llama más esférica y una evolución térmica prolongada bajo microgravedad.',
    claims: [
      { claim_id: 'claim-01', text: 'La microgravedad reduce el transporte convectivo dominante alrededor de la llama.', evidence_ids: ['ev-doc-flex-01'] },
      { claim_id: 'claim-02', text: 'El perfil validado contiene 184 muestras y registra un máximo de 812.4 K.', evidence_ids: ['ev-data-flex-01'] },
    ],
    evidence,
    visualizations: [{
      schema_version: '1.0',
      chart_id: 'chart-flex-temperature',
      type: 'line',
      title: 'Evolución térmica validada',
      data_ref: '/v1/authorized-chart-data/chart-flex-temperature',
      x: { field: 'elapsed_time', label: 'Tiempo', kind: 'numeric', unit: 's' },
      y: { field: 'temperature', label: 'Temperatura', kind: 'numeric', unit: 'K' },
      filters: { validation_status: 'validated' },
      dataset_ref_ids: ['dataset-flex-v5'],
      limitations: ['La escala definitiva depende del endpoint autorizado de datos de gráficos.'],
    }],
    limitations: partial ? ['No existe una correspondencia directa entre el análisis seleccionado y todas las mediciones citadas.', 'No deben calcularse diferencias cuantitativas hasta validar compatibilidad de datasets.'] : [],
    metrics: { latency_ms: 286 },
  }
}

export async function queryAi(request: AiQueryRequest, signal?: AbortSignal): Promise<AiResponse> {
  if (!request.question) throw new Error('La pregunta no puede estar vacía.')
  if (!endpoint) {
    await new Promise<void>((resolve, reject) => {
      const timer = window.setTimeout(resolve, 180)
      signal?.addEventListener('abort', () => { window.clearTimeout(timer); reject(new DOMException('Aborted', 'AbortError')) }, { once: true })
    })
    return demoResponse(request)
  }

  const response = await fetch(endpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify(request),
    signal,
  })
  if (!response.ok) throw new Error(`El servicio de IA respondió con HTTP ${response.status}.`)
  const payload: unknown = await response.json()
  if (!isAiResponse(payload)) throw new Error('La respuesta no cumple el contrato AiResponse 1.0.')
  if (payload.request_id !== request.request_id) throw new Error('El request_id de la respuesta no coincide con la solicitud.')
  return payload
}
