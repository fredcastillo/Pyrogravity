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
