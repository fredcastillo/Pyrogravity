import { describe, expect, it, vi } from 'vitest'
import type { AiResponse } from '../contracts/ai'
import { AiHttpError, buildAiQuery, isAiResponse, queryAi } from './ai'

function responseFor(id: string, overrides: Partial<AiResponse> = {}): AiResponse {
  return {
    schema_version: '1.0', id, status: 'supported', answer: 'Respuesta respaldada.', provenance: 'live', limitations: [],
    claims: [{ id: 'claim-1', text: 'La temperatura aumentó.', citation_ids: ['citation-1'] }],
    citations: [{ id: 'citation-1', kind: 'scientific', title: 'Dataset FLEX', url: 'https://example.org/flex', page: null, snippet: 'Registro validado.', source: 'NASA PSI', measurement: { variable: 'temperature', value: 812, unit: 'K', provenance: 'live' } }],
    charts: [{ id: 'chart-1', type: 'line', title: 'Temperatura', x_label: 'Tiempo', y_label: 'K', provenance: 'live', data_ref: '/api/v1/charts/chart-1', limitations: [], series: [{ id: 'temperature', label: 'Temperatura', unit: 'K', validated: true, points: [{ x: 0, y: 300 }, { x: 1, y: 812 }] }] }],
    ...overrides,
  }
}

function fetchJson(payload: unknown, status = 200) {
  return vi.fn<typeof fetch>().mockResolvedValue(new Response(JSON.stringify(payload), { status, headers: { 'Content-Type': 'application/json' } }))
}

describe('contrato público de consultas IA', () => {
  it('envía ensayos, variables y preferencia de gráfico solo a /api/v1', async () => {
    const request = buildAiQuery('¿Qué ocurre?', { experimentIds: ['flex'], variables: ['temperature'], chartPreference: 'line' })
    const fetcher = fetchJson(responseFor(request.id))
    await queryAi(request, undefined, { fetcher })
    expect(request).toMatchObject({ experiment_ids: ['flex'], variables: ['temperature'], chart_preference: 'line' })
    expect(fetcher).toHaveBeenCalledWith('/api/v1/ai/query', expect.objectContaining({ method: 'POST', credentials: 'same-origin' }))
  })

  it('acepta una respuesta completa con citas, cifras y puntos validados', async () => {
    const request = buildAiQuery('Resume', { experimentIds: ['flex'] })
    const response = await queryAi(request, undefined, { fetcher: fetchJson(responseFor(request.id)) })
    expect(response.status).toBe('supported')
    expect(response.citations[0].measurement).toMatchObject({ value: 812, unit: 'K', provenance: 'live' })
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
    await expect(queryAi(request, undefined, { fetcher: fetchJson({ detail: 'upstream unavailable' }, 503) })).rejects.toMatchObject<Partial<AiHttpError>>({ name: 'AiHttpError', status: 503 })
  })

  it('marca la demostración inequívocamente y no fabrica mediciones', async () => {
    const request = buildAiQuery('Consulta demo')
    const response = await queryAi(request, undefined, { demo: true })
    expect(response).toMatchObject({ status: 'insufficient_evidence', provenance: 'demo', claims: [], citations: [], charts: [] })
    expect(response.answer).toContain('Modo demostración')
  })

  it('acepta un gráfico sin puntos autorizados y rechaza referencias externas', () => {
    const locked = responseFor('req-1', { charts: [{ id: 'chart-locked', type: 'line', title: 'Pendiente', x_label: 'x', y_label: 'y', provenance: 'cache', data_ref: '/api/v1/charts/locked', limitations: [], series: [] }] })
    expect(isAiResponse(locked)).toBe(true)
    expect(isAiResponse({ ...locked, charts: [{ ...locked.charts[0], data_ref: 'https://cohere.example/chart' }] })).toBe(false)
  })
})
