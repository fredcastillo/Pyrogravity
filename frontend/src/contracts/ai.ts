export const AI_QUERY_PATH = '/api/v1/ai/query' as const

export type AiSupportStatus = 'supported' | 'partially_supported' | 'insufficient_evidence'
export type AiProvenance = 'live' | 'cache' | 'demo' | 'degraded'
export type ChartType = 'line' | 'bar' | 'scatter'

export type AiQueryRequest = {
  id: string
  question: string
  language: 'es' | 'en'
  experiment_ids: string[]
  variables: string[]
  chart_preference: ChartType | null
}

export type ResolvedCitation = {
  id: string
  kind: 'document' | 'scientific'
  title: string
  url: string
  page: number | null
  snippet: string
  source: string
  measurement?: {
    variable: string
    value: number | string
    unit: string
    provenance: AiProvenance
  } | null
}

export type ValidatedChartPoint = { x: number | string; y: number }

export type ValidatedChartSeries = {
  id: string
  label: string
  unit: string | null
  validated: true
  points: ValidatedChartPoint[]
}

export type HydratedChart = {
  id: string
  type: ChartType
  title: string
  x_label: string
  y_label: string
  provenance: AiProvenance
  data_ref: string | null
  series: ValidatedChartSeries[]
  limitations: string[]
}

export type AiResponse = {
  schema_version: string
  id: string
  status: AiSupportStatus
  answer: string
  claims: Array<{ id: string; text: string; citation_ids: string[] }>
  citations: ResolvedCitation[]
  limitations: string[]
  charts: HydratedChart[]
  provenance: AiProvenance
}
