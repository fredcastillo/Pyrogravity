import type { ResolvedCitation } from './contracts/ai'

function fold(value: string) {
  return (value.toLowerCase().normalize('NFD').replace(/\p{M}/gu, '').match(/[\p{L}\p{N}]+/gu) ?? []).join(' ')
}

export function studyQuestion(input: string, study: string) {
  const question = input.trim()
  const normalized = fold(question)
  if (normalized.includes(fold(study))) return question
  if (/^(que (investigaron|estudiaron)|objetivos?|proposito)$/.test(normalized)) return `¿Qué investigó ${study}?`
  if (/^(como (lo hicieron|hicieron el experimento|hicieron la investigacion|se hizo el experimento)|metodologia|metodo)$/.test(normalized)) return `Metodología de ${study}`
  if (/^(que descubrieron|cuales fueron los resultados|resultados|hallazgos)$/.test(normalized)) return `Resultados de ${study}`
  if (/^(de donde salen (estos|los) datos|fuentes|procedencia|referencias)$/.test(normalized)) return `Fuentes de ${study}`
  if (/^(quien(es)? realiz(o|aron) el estudio|autores)$/.test(normalized)) return `¿Quién realizó el estudio ${study}?`
  return `${question.replace(/[?.!]+$/, '')} en ${study}?`
}

// Editorial source summaries stay attached to a reviewed document, page, and literal markers.
export function spanishCitationSummary(citation: ResolvedCitation) {
  if (citation.kind !== 'document') return undefined
  const text = citation.snippet.toLowerCase().replace(/\s+/g, ' ')
  const excerpts = [
    ['ntrs:20160000593', 2, ['ignition, flame growth, flame spread', 'extinction limits', 'solid fuels', 'low-velocity forced flows in microgravity'],
      'BASS-II estudió la ignición, el crecimiento, la propagación y los límites de extinción de llamas en combustibles sólidos con flujo forzado lento en microgravedad.'],
    ['ntrs:20160000593', 3, ['small wind tunnel', 'microgravity science glovebox'],
      'El equipo montó las muestras en un túnel de viento pequeño, instalado dentro de la Microgravity Science Glovebox.'],
    ['ntrs:20160000593', 7, ['small flow tunnel', 'solid samples were installed', 'extinguished, and recorded'],
      'El equipo instaló muestras sólidas en un túnel de flujo y registró la ignición, la combustión y la extinción.'],
    ['ntrs:20160000593', 18, ['plastic rods', 'blowoff and quenching extinction limits'],
      'Los investigadores quemaron varillas de plástico y midieron límites de extinción por soplado y por enfriamiento.'],
    ['ntrs:20160000593', 1, ['paul v. ferkul', 'sandra l. olson'],
      'La publicación identifica a Paul V. Ferkul y Sandra L. Olson entre sus autores. La cita muestra la lista de participantes y sus instituciones.'],
    ['ntrs:20130014061', 2, ['methanol, as a non-sooting fuel', 'droplet combustion and extinction'],
      'La publicación estudia la combustión y extinción de gotas de metanol. El metanol permite examinar un caso simplificado porque no produce hollín.'],
  ] as const

  return excerpts.find(([source, page, markers]) =>
    citation.source === source && citation.page === page && markers.every(marker => text.includes(marker)),
  )?.[3]
}
