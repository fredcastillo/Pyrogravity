import { describe, expect, it } from 'vitest'
import { buildAiQuery, queryAi } from './ai'

describe('contrato de consultas IA', () => {
  it('construye solicitudes AiQueryRequest 1.0 correlacionables', () => {
    const request = buildAiQuery('¿Qué ocurre con la llama?', 'flex')
    expect(request).toMatchObject({ schema_version: '1.0', language: 'es', analysis_id: 'flex', question: '¿Qué ocurre con la llama?' })
    expect(request.request_id).toBeTruthy()
  })

  it('preserva claims, evidencia, ChartSpec y request_id en respuestas respaldadas', async () => {
    const request = buildAiQuery('Resume la evidencia', 'flex')
    const response = await queryAi(request)
    expect(response.status).toBe('supported')
    expect(response.request_id).toBe(request.request_id)
    expect(response.claims[0].evidence_ids[0]).toBe(response.evidence[0].evidence_id)
    expect(response.visualizations[0]).toMatchObject({ schema_version: '1.0', type: 'line' })
  })

  it('expone limitaciones cuando la evidencia es parcial', async () => {
    const request = buildAiQuery('¿La medición es concluyente?', 'cfi-g')
    const response = await queryAi(request)
    expect(response.status).toBe('partially_supported')
    expect(response.limitations.length).toBeGreaterThan(0)
  })
})
