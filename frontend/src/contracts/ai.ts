export type AnalysisId = 'bass-ii' | 'flex' | 'flame-design' | 'cfi-g' | 'spice'

export type AiQueryRequest = {
  schema_version: '1.0'
  request_id: string
  question: string
  language: 'es' | 'en'
  analysis_id?: AnalysisId | null
  filters?: Record<string, string | null>
}

export type DatasetRef = {
  ref_id: string
  psi_code: string
  relative_path: string
  sha256: string
  nasa_psi_url: string
  database_dataset_id?: number | null
}

export type ScientificDatum = {
  datum_id: string
  dataset_ref_id: string
  variable_code: string
  value: string
  unit: string
  validation_status: 'validated'
  kind: 'measurement' | 'derived'
  source_record?: string | null
  column_ordinal?: number | null
  method?: string | null
  sample_count?: number | null
}

export type DocumentEvidence = {
  kind: 'document'
  evidence_id: string
  source_id: string
  document_sha256: string
  chunk_sha256: string
  page_number: number
  source_url: string
  doi?: string | null
}

export type ScientificEvidence = {
  kind: 'scientific'
  evidence_id: string
  dataset: DatasetRef
  datum: ScientificDatum
}

export type Evidence = DocumentEvidence | ScientificEvidence

export type ChartSpec = {
  schema_version: '1.0'
  chart_id: string
  type: 'bar' | 'line' | 'scatter' | 'histogram' | 'box' | 'heatmap'
  title: string
  data_ref: string
  x: { field: string; label: string; kind: 'categorical' | 'numeric' | 'temporal'; unit?: string | null }
  y: { field: string; label: string; kind: 'categorical' | 'numeric' | 'temporal'; unit?: string | null }
  filters: Record<string, string>
  dataset_ref_ids: string[]
  limitations: string[]
}

export type AiResponseStatus = 'supported' | 'partially_supported' | 'insufficient_evidence' | 'invalid_request' | 'upstream_unavailable'
export type AiIntent = 'scientific_analysis' | 'document_question' | 'combined' | 'unknown'

export type AiResponse = {
  schema_version: '1.0'
  request_id: string
  status: AiResponseStatus
  intent: AiIntent
  answer: string
  claims: Array<{ claim_id: string; text: string; evidence_ids: string[] }>
  evidence: Evidence[]
  visualizations: ChartSpec[]
  limitations: string[]
  metrics: { latency_ms?: number | null }
}
