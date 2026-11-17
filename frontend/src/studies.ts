type Measure = { key: string; label: string; unit?: string }

interface Study {
  name: string
  title: string
  description: string
  method: readonly string[]
  axes: readonly [Measure, Measure]
  group: Measure
  document?: string
}

export const studies = {
  'bass-ii': {
    name: 'BASS-II',
    title: 'CO₂ antes y después de la combustión',
    description: 'Compara la concentración de dióxido de carbono al inicio y al final de cada ensayo.',
    method: [
      'Se emparejan lecturas exactas de la misma fila y versión del CSV. Ambas deben estar entre 0 y 5 % en volumen.',
      'El cambio se calcula restando la concentración inicial de la final, en puntos porcentuales.',
      'Los cambios por debajo de la resolución del sensor no demuestran un cambio físico. Las muestras repetidas se conservan y las observaciones pueden depender entre sí.',
    ],
    axes: [{ key: 'initial_co2', label: 'CO₂ inicial', unit: '% en volumen' }, { key: 'final_co2', label: 'CO₂ final', unit: '% en volumen' }],
    group: { key: 'fuel_sample_material', label: 'Material de la muestra' },
    document: 'ntrs:20160000593',
  },
  flex: {
    name: 'FLEX',
    title: 'Cómo arden las gotas de combustible',
    description: 'Explora la relación entre el diámetro inicial de una gota y su duración de combustión registrada.',
    method: [
      'Se requieren lecturas exactas y positivas de diámetro, duración y presión, junto con las etiquetas del ensayo. Se excluyen los identificadores repetidos.',
      'El tiempo de combustión es la duración registrada. Solo los ensayos marcados como Extinction están identificados como extinción en el CSV.',
      'Los resultados describen asociaciones entre mediciones, sin controlar todas las condiciones experimentales.',
    ],
    axes: [{ key: 'droplet_initial_diameter', label: 'Diámetro inicial', unit: 'mm' }, { key: 'burn_time', label: 'Duración de combustión', unit: 's' }],
    group: { key: 'fuel', label: 'Combustible' },
    document: 'ntrs:20130014061',
  },
  'flame-design': {
    name: 'Flame Design',
    title: 'Presión en llamas normales e inversas',
    description: 'Explora las lecturas de presión al inicio y al final de ensayos con distintas configuraciones de llama.',
    method: [
      'Cada par de presiones exactas y positivas pertenece al mismo ensayo, fila y versión de la tabla.',
      'Se excluyen los identificadores repetidos y las filas idénticas dentro de cada conjunto de datos.',
      'Normal e inversa identifican configuraciones de llama. Las lecturas de inicio y fin describen una diferencia dentro del ensayo.',
    ],
    axes: [{ key: 'pinit_atm', label: 'Presión inicial', unit: 'atm' }, { key: 'pfinal_atm', label: 'Presión final', unit: 'atm' }],
    group: { key: 'fuel', label: 'Combustible' },
  },
  'cfi-g': {
    name: 'CFI-G',
    title: 'Cuánto dura una llama fría',
    description: 'Revisa la duración registrada según la configuración y el código de terminación del ensayo.',
    method: [
      'Se seleccionan duraciones exactas y positivas con ignición caliente y código de terminación SE o FT. Se excluyen ensayos repetidos dentro del mismo conjunto de datos.',
      'Las duraciones atípicas se marcan por configuración y código cuando hay suficientes observaciones.',
      'SE y FT son códigos del CSV. La duración registrada puede incluir una intervención y no certifica un tiempo de extinción natural.',
    ],
    axes: [{ key: 'source_record', label: 'Fila de origen' }, { key: 'duration', label: 'Duración registrada', unit: 's' }],
    group: { key: 'termination', label: 'Terminación' },
  },
  spice: {
    name: 'SPICE',
    title: 'Aire y combustible en llamas de coflujo',
    description: 'Explora los ajustes de flujo de aire y combustible registrados por boquilla y combustible.',
    method: [
      'La selección disponible requiere lecturas exactas y finitas de boquilla y ambos flujos.',
      'La selección conservadora excluye todas las filas de cada grupo idéntico, como prueba de sensibilidad.',
      'Los valores negativos o cero se conservan como se registraron. El CSV no identifica el punto de humo para cada fila.',
    ],
    axes: [{ key: 'air_rate_cm_s', label: 'Flujo de aire', unit: 'cm/s' }, { key: 'fuel_rate_mg_s', label: 'Flujo de combustible', unit: 'mg/s' }],
    group: { key: 'fuel', label: 'Combustible' },
  },
} satisfies Record<string, Study>

export type StudyId = keyof typeof studies
export const studyIds = Object.keys(studies) as StudyId[]

export function getStudy(value: string): Study | undefined {
  return Object.prototype.hasOwnProperty.call(studies, value) ? studies[value as StudyId] : undefined
}

export function measureLabel(measure: Measure) {
  return measure.unit ? `${measure.label} (${measure.unit})` : measure.label
}

export const variableNames: Record<string, string> = {
  delta_co2: 'Cambio de CO₂', ambient_pressure: 'Presión ambiente',
  delta_pressure: 'Cambio de presión', nozzle_mm: 'Diámetro de la boquilla',
}
export const variableUnits: Record<string, string> = {
  delta_co2: 'puntos porcentuales', ambient_pressure: 'mmHg', delta_pressure: 'atm', nozzle_mm: 'mm',
}

export type StudyRow = Record<string, unknown> & { source_record: number }
export type Dataset = { relative_path: string; sha256: string; nasa_psi_url: string; investigation_name: string }
export type StudyPart = { dataset: Dataset; pairs?: StudyRow[]; included?: StudyRow[]; records?: StudyRow[]; excluded_count?: number }
export type StudyResult = {
  analysis_id: StudyId
  psi_code: string
  result: StudyPart & {
    method_version: string
    configurations?: Record<string, StudyPart>
    cohorts?: Record<string, { source_records: number[] }>
  }
}

export function valuesFor(part: StudyPart) {
  return part.pairs ?? part.included ?? part.records ?? []
}

export function groupValue(row: StudyRow, key: string) {
  return row[key] == null ? 'Sin etiqueta' : String(row[key])
}

export function csvCell(value: unknown) {
  let text = value == null ? '' : typeof value === 'object' ? JSON.stringify(value) : String(value)
  // Keep numeric data intact while preventing textual spreadsheet formulas.
  if (/^[\t\r\n]|^\s*[=+\-@]/.test(text) && !/^[+-]?\d+(?:\.\d+)?(?:e[+-]?\d+)?$/i.test(text)) text = "'" + text
  return '"' + text.replaceAll('"', '""') + '"'
}

export function makeCsv(rows: readonly StudyRow[], source: Dataset, cohort: string, group: string, method: string) {
  const keys = Array.from(new Set(rows.flatMap(row => Object.keys(row)))).filter(key => key !== 'source_record')
  const headers = ['source_record', ...keys, 'pyrogravity_csv', 'pyrogravity_sha256', 'pyrogravity_nasa', 'pyrogravity_cohort', 'pyrogravity_group', 'pyrogravity_method']
  const lines = rows.map(row => [row.source_record, ...keys.map(key => row[key]), source.relative_path, source.sha256, source.nasa_psi_url, cohort, group, method])
  return '\uFEFF' + [headers, ...lines].map(line => line.map(csvCell).join(',')).join('\r\n')
}
