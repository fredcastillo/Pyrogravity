import { getStudy, studyIds, studies, type StudyId } from './studies'
import { studyQuestion } from './studyQuestions'

export type ChatLink = { title: string; href: string }

const aliases: Record<StudyId, RegExp> = {
  'bass-ii': /\b(?:bass\s*(?:ii|2)|psi\s*25|burning and suppression of solids)\b/,
  flex: /\b(?:flex|psi\s*69|flame extinguishment experiment)\b/,
  'flame-design': /\b(?:flame design|psi\s*10)\b/,
  'cfi-g': /\b(?:cfi\s*g|psi\s*159|cool flames investigation with gases)\b/,
  spice: /\b(?:spice|psi\s*107|smoke point in co flow experiment)\b/,
}

export const catalogLinks = studyIds.map(id => ({ title: studies[id].name, href: `/estudios/${id}` }))
const navigation: ChatLink[] = [{ title: 'Explorar estudios', href: '/#estudios' }]
const psiLinks: ChatLink[] = [
  { title: 'BASS-II · NASA PSI-25', href: 'https://psi.nasa.gov/physci/repo/data/investigations/PSI-25' },
  { title: 'FLEX · NASA PSI-69', href: 'https://psi.nasa.gov/physci/repo/data/investigations/PSI-69' },
]

function fold(value: string) {
  return (value.toLowerCase().normalize('NFD').replace(/\p{M}/gu, '').match(/[\p{L}\p{N}]+/gu) ?? []).join(' ')
}

export function studyOnPage() {
  const match = /^\/estudios\/([a-z0-9-]+)\/?$/.exec(window.location.pathname)
  if (match && getStudy(match[1])) return match[1] as StudyId
  const selected = document.querySelector<HTMLSelectElement>('#science-analysis')?.value
  if (window.location.hash === '#science-title' && selected && getStudy(selected)) return selected as StudyId
  return undefined
}

type ChatPlan = { study?: StudyId; text: string; links?: ChatLink[] } |
  { study?: StudyId; question: string; source?: string }

export function planChat(input: string, previous?: StudyId): ChatPlan {
  const query = fold(input)
  const mentioned = studyIds.filter(id => aliases[id].test(query))
  const current = mentioned.length === 1 ? mentioned[0] : mentioned.length ? undefined : previous
  const study = current ? getStudy(current) : undefined

  if (/^(?:hola|hey|buenas)(?: como estas| que tal| de nuevo)$|^(?:como estas|que tal|quien eres|eres una ia)$/.test(query))
    return { study: current, text: 'Hola, soy el asistente de IA de Pyrogravity. Te acompaño a explorar los estudios, entender sus métodos y localizar evidencia. ¿Prefieres empezar por una pregunta sobre microgravedad o por las mediciones de un estudio?', links: navigation }

  if (/^(?:ayudame a explorar los datos|quiero explorar los datos|por donde empiezo|no se por donde empezar)$/.test(query))
    return { study: current, text: 'Podemos empezar por lo que quieres observar: CO₂ en BASS-II, gotas de combustible en FLEX, presión en Flame Design, duración en CFI-G o flujos en SPICE. Elige una ficha para ver su gráfica y los registros que la respaldan. Después podemos revisar el método o las fuentes.', links: catalogLinks }

  if (/^(?:como verifico (?:una respuesta|estos datos|la fuente de estos datos)|puedo confiar en ti|puedes cometer errores)$/.test(query))
    return { study: current, text: 'Puedo cometer errores. Abre las citas, comprueba el documento y la página, y contrasta el fragmento con lo que se afirma. Para una cifra, revisa también el ensayo, la variable, la unidad y la fila original en la ficha. Una medición trazable no demuestra por sí sola una causa física.', links: current ? [{ title: `Revisar las fuentes de ${study?.name}`, href: `/estudios/${current}#fuentes` }] : catalogLinks }

  if (/^(?:que significa|explicame)(?: la)? (?:evidencia insuficiente|falta de evidencia)$/.test(query))
    return { study: current, text: 'Significa que la evidencia disponible no alcanza para respaldar la respuesta. No significa que el fenómeno no exista. Podemos precisar el estudio, revisar otra variable o abrir la fuente original.', links: current ? [{ title: 'Ver los datos disponibles', href: `/estudios/${current}#datos` }] : catalogLinks }

  if (/^(?:fuentes|ver fuentes)$/.test(query) && current)
    return { study: current, text: `Puedes revisar la procedencia de ${study?.name} en su ficha. Allí se conservan las referencias y el método; las citas de mis respuestas documentales también se pueden desplegar en el chat.`, links: [{ title: `Fuentes de ${study?.name}`, href: `/estudios/${current}#fuentes` }] }

  if (/^(hola|hey|buenas|buenos dias|buenas tardes|buenas noches)( que tal)?$/.test(query))
    return { study: current, text: '¡Hola! Soy el asistente de Pyrogravity. Puedo explicarte qué se estudia en microgravedad, ayudarte a encontrar mediciones o revisar una fuente de NASA.', links: navigation }

  if (/^(gracias|muchas gracias|perfecto|entendido)$/.test(query))
    return { study: current, text: '¡Con gusto! Puedes seguir con el mismo estudio o cambiar de investigación en el menú del chat.' }

  if (/^(que (?:estudios|investigaciones|experimentos)(?: tienen| hay| puedo ver)?|que datos puedo ver|que puedes hacer|ayuda|como funciona|muestrame el catalogo|resumen general|que es pyrogravity|que hay en esta pagina)$/.test(query))
    return { study: current, text: 'Puedes explorar cinco análisis de combustión en microgravedad. Las fichas muestran CO₂ en BASS-II, combustión de gotas en FLEX, presión en Flame Design, duración en CFI-G y flujos en SPICE. Abre una para ver la gráfica, las filas originales y el método.', links: catalogLinks }

  if (!mentioned.length && /^(?:(?:explicame|que es|que me puedes contar de|cuentame sobre|hablame de|como es|como funciona) )?(?:la |el |las )?(?:combustion en microgravedad|fuego (?:en microgravedad|en el espacio)|llamas en el espacio)$/.test(query))
    return { study: current, text: 'Pyrogravity explora cómo arden los combustibles en microgravedad. BASS-II estudió la ignición, propagación y extinción de llamas en sólidos. FLEX estudió la quema de gotas de combustible bajo distintas condiciones. Puedes seguir esas dos pistas en las fichas de NASA.', links: psiLinks }

  if (!current && !mentioned.length && /^(?:y )?(?:(?:para que|que|como|quien(?:es)?|de donde) [a-z ]{1,50}|resultados?|metodologia|fuentes|objetivos|detalles)$/.test(query) &&
    /(?:investigaron|descubrieron|encontraron|experimento|estos datos|resultados?|metodologia|fuentes|objetivos|detalles|estudio)$/.test(query))
    return { text: 'Puedo buscarlo. Elige un estudio o dime si quieres un panorama general de la combustión en microgravedad.', links: catalogLinks }

  if (current && study && !study.document) {
    const links = [{ title: `Ver ${study.name} y su procedencia`, href: `/estudios/${current}#fuentes` }]
    const overview = query.replace(aliases[current], '').replace(/\s+/g, ' ').trim()
    if (/^(?:|que es|que se analizo|que investigaron|que investigo|resultados?(?: de)?|hablame (?:de|sobre)|cuentame (?:de|sobre))$/.test(overview))
      return { study: current, text: study.description + ' La ficha muestra las mediciones registradas y la selección aplicada.', links }
    if (/^(?:metodologia(?: de)?|metodo(?: de)?|como hicieron el experimento|como se seleccionaron los datos)$/.test(overview))
      return { study: current, text: study.method.join(' '), links }
    return { study: current, text: `La ficha de ${study.name} tiene la metodología, la gráfica y la fuente original. Todavía no hay un documento de ese estudio en la biblioteca de IA para verificar detalles adicionales.`, links }
  }

  return { study: current, question: study && !mentioned.length ? studyQuestion(input, study.name) : input, source: study?.document }
}
