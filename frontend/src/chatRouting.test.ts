import { expect, it } from 'vitest'
import { planChat } from './chatRouting'

it('responde saludos, temas amplios y preguntas por el catálogo', () => {
  expect(planChat('¡Hola!')).toHaveProperty('text')
  expect(planChat('¿Qué estudios hay?')).toHaveProperty('links', expect.arrayContaining([{ title: 'FLEX', href: '/estudios/flex' }]))
  expect(planChat('Explícame la combustión en microgravedad')).toHaveProperty('links', expect.arrayContaining([
    { title: 'BASS-II · NASA PSI-25', href: 'https://psi.nasa.gov/physci/repo/data/investigations/PSI-25' },
  ]))
})

it('conserva el contexto de seguimiento y respeta un cambio de estudio', () => {
  expect(planChat('¿Cómo hicieron el experimento?', 'bass-ii')).toEqual({
    study: 'bass-ii', question: 'Metodología de BASS-II', source: 'ntrs:20160000593',
  })
  expect(planChat('FLEX', 'bass-ii')).toEqual({ study: 'flex', question: 'FLEX', source: 'ntrs:20130014061' })
  expect(planChat('¿Probaron antimateria?', 'bass-ii')).toHaveProperty('question', '¿Probaron antimateria en BASS-II?')
})

it('pide precisar una referencia ambigua y enlaza los estudios sin documentos indexados', () => {
  expect(planChat('¿Qué investigaron?')).toHaveProperty('text', expect.stringContaining('Elige un estudio'))
  expect(planChat('PSI-107')).toHaveProperty('links', [{ title: 'Ver SPICE y su procedencia', href: '/estudios/spice#fuentes' }])
  expect(planChat('¿Cuánto metano hubo en la fila 999?', 'spice')).toHaveProperty('text', expect.stringContaining('Todavía no hay un documento'))
})
