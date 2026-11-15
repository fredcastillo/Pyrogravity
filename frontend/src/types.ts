export type ExperimentStatus = 'verified' | 'partial' | 'processing'

export interface DataPoint {
  time: number
  value: number
}

export interface Experiment {
  id: string
  code: string
  shortName: string
  title: string
  field: 'liquid' | 'solid' | 'spacecraft'
  status: ExperimentStatus
  color: string
  position: [number, number, number]
  gravity: string
  oxygen: string
  material: string
  duration: string
  completeness: number
  sampleCount: number
  source: string
  doi: string
  updated: string
  summary: string
  series: DataPoint[]
}

export interface MissionContext {
  id: string
  name: string
  label: string
  gravity: string
  atmosphere: string
  accent: string
}
