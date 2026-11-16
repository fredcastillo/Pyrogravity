import { describe, expect, it, vi } from 'vitest'
import type { AiResponse } from '../contracts/ai'
import { AiHttpError, buildAiQuery, isAiResponse, queryAi } from './ai'

function responseFor(id: string, overrides: Partial<AiResponse> = {}): AiResponse {
  return {
    schema_version: 'public-1.1', id, status: 'supported', answer: 'Ejemplo sintético de contrato: el ensayo 1 registró burn_time de 4.30 s.', provenance: 'demo', limitations: ['Ejemplo sintético de contrato; no usar como resultado científico.'],
    claims: [{ id: 'claim-1', text: 'Ejemplo sintético: burn_time = 4.30 s en el ensayo 1.', citation_ids: ['citation-1'] }],
    citations: [{ id: 'citation-1', kind: 'scientific', title: 'PSI-69 FLEX source record 1 (sintético de ejemplo)', url: '', page: null, snippet: 'Ejemplo sintético de estructura; no es evidencia verificada.', source: 'sintético de ejemplo', measurement: { variable: 'burn_time', value: 4.3, unit: 's', provenance: 'demo' } }],
    charts: [{ id: 'chart-1', type: 'line', title: 'Burn time', x_label: 'Ensayo', y_label: 'Tiempo', provenance: 'demo', data_ref: '/api/v1/ai/request-1/charts/chart-1', limitations: [], series: [{ id: 'burn-time', label: 'Burn time', unit: 's', validated: true, points: [{ x: '1', y: 4.3 }] }] }],
    ...overrides,
  }
}

function fetchJson(payload: unknown, status = 200, headers: Record<string, string> = {}) {
  return vi.fn<typeof fetch>().mockResolvedValue(new Response(JSON.stringify(payload), { status, headers: { 'Content-Type': 'application/json', ...headers } }))
}

describe('contrato público de consultas IA', () => {
  it('envía ensayos, variables y preferencia de gráfico solo a /api/v1', async () => {
    const request = buildAiQuery('¿Cuál fue el burn_time del ensayo 1?', { experimentIds: ['PSI-69:psi-69_flex:1'], variables: ['burn_time'], chartPreference: 'line' })
    const fetcher = fetchJson(responseFor(request.id))
    await queryAi(request, undefined, { fetcher })
    expect(request).toMatchObject({ experiment_ids: ['PSI-69:psi-69_flex:1'], variables: ['burn_time'], chart_preference: 'line' })
    expect(fetcher).toHaveBeenCalledWith('/api/v1/ai/query', expect.objectContaining({ method: 'POST', credentials: 'same-origin' }))
  })

  it('acepta una respuesta completa con citas, cifras y puntos validados', async () => {
    const request = buildAiQuery('Resume', { experimentIds: ['flex'] })
    const response = await queryAi(request, undefined, { fetcher: fetchJson(responseFor(request.id)) })
    expect(response.status).toBe('supported')
    expect(response.schema_version).toBe('public-1.1')
    expect(response.citations[0].measurement).toMatchObject({ value: 4.3, unit: 's', provenance: 'demo' })
    expect(response.charts[0].series[0].validated).toBe(true)
  })

  it('preserva limitaciones en evidencia parcial', async () => {
    const request = buildAiQuery('¿Es concluyente?')
    const response = await queryAi(request, undefined, { fetcher: fetchJson(responseFor(request.id, { status: 'partially_supported', limitations: ['Cobertura temporal incompleta.'], provenance: 'degraded' })) })
    expect(response.status).toBe('partially_supported')
    expect(response.limitations).toEqual(['Cobertura temporal incompleta.'])
  })

  it('trata insufficient_evidence como respuesta válida', async () => {
    const request = buildAiQuery('¿Hay evidencia?')
    const payload = responseFor(request.id, { status: 'insufficient_evidence', answer: 'No hay evidencia suficiente.', claims: [], citations: [], charts: [] })
    await expect(queryAi(request, undefined, { fetcher: fetchJson(payload) })).resolves.toMatchObject({ status: 'insufficient_evidence' })
  })

  it('separa los errores HTTP de los estados de soporte', async () => {
    const request = buildAiQuery('Consulta')
    const error = { error: { code: 'AI_UNAVAILABLE', message: 'El proveedor de IA está desactivado hasta completar autenticación y rol lector.', request_id: request.id, details: { schema_version: 'public-1.1' } } }
    await expect(queryAi(request, undefined, { fetcher: fetchJson(error, 503, { 'X-Request-ID': request.id }) })).rejects.toMatchObject<Partial<AiHttpError>>({ name: 'AiHttpError', status: 503, code: 'AI_UNAVAILABLE', requestId: request.id })
  })

  it('marca la demostración inequívocamente y no fabrica mediciones', async () => {
    const request = buildAiQuery('Consulta demo')
    const response = await queryAi(request, undefined, { demo: true })
    expect(response).toMatchObject({ status: 'insufficient_evidence', provenance: 'demo', claims: [], citations: [], charts: [] })
    expect(response.schema_version).toBe('public-1.1')
    expect(response.answer).toContain('Modo demostración')
  })

  it('acepta un gráfico sin puntos autorizados y rechaza referencias externas', () => {
    const locked = responseFor('req-1', { charts: [{ id: 'chart-locked', type: 'line', title: 'Pendiente', x_label: 'x', y_label: 'y', provenance: 'cache', data_ref: '/api/v1/charts/locked', limitations: [], series: [] }] })
    expect(isAiResponse(locked)).toBe(true)
    expect(isAiResponse({ ...locked, charts: [{ ...locked.charts[0], data_ref: 'https://cohere.example/chart' }] })).toBe(false)
  })

  it('rechaza respuestas de una versión pública distinta', () => {
    expect(isAiResponse({ ...responseFor('req-version'), schema_version: 'public-1.0' })).toBe(false)
  })
})
