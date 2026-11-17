import { describe, expect, it } from 'vitest'
import { makeCsv, csvCell, getStudy } from './studies'
import { spanishCitationSummary, studyQuestion } from './studyQuestions'
import type { ResolvedCitation } from './contracts/ai'

describe('fichas científicas', () => {
  it('mantiene la precisión decimal, las filas y la procedencia al exportar', () => {
    const data = makeCsv([{ source_record: 3, p: '-1.0020', label: '=1+1' }],
      { relative_path: 'raw/table.csv', sha256: 'a'.repeat(64), nasa_psi_url: 'https://psi.nasa.gov/', investigation_name: 'Estudio' },
      'normal', 'grupo', 'v1')
    expect(data).toContain('"source_record","p","label","pyrogravity_csv","pyrogravity_sha256"')
    expect(data).toContain('"3","-1.0020","\'=1+1","raw/table.csv"')
    expect(csvCell('texto, "literal"')).toBe('"texto, ""literal"""')
    expect(getStudy('__proto__')).toBeUndefined()
  })

  it('mantiene las condiciones de la pregunta al añadir el estudio', () => {
    expect(studyQuestion('¿Cómo hicieron el experimento?', 'BASS-II')).toBe('Metodología de BASS-II')
    expect(studyQuestion('¿Quemaron antimateria?', 'BASS-II')).toBe('¿Quemaron antimateria en BASS-II?')
    expect(studyQuestion('Resultados de BASS–II', 'BASS-II')).toBe('Resultados de BASS–II')
  })

  it('solo resume pasajes verificados por fuente, página y contenido', () => {
    const citation: ResolvedCitation = {
      id: 'cite_1', kind: 'document', title: 'BASS-II', url: 'https://ntrs.nasa.gov/citations/20160000593',
      source: 'ntrs:20160000593', page: 2,
      snippet: 'Study the ignition, flame growth, flame spread, and extinction limits for solid fuels burning in low-velocity forced flows in microgravity.',
    }
    expect(spanishCitationSummary(citation)).toContain('combustibles sólidos')
    expect(spanishCitationSummary({ ...citation, page: 1 })).toBeUndefined()
    expect(spanishCitationSummary({ ...citation, snippet: 'Unrelated passage' })).toBeUndefined()
  })
})
