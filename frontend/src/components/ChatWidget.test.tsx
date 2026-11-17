import { beforeEach, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { ChatWidget } from './ChatWidget'
import { queryAi } from '../services/ai'
import type { AiResponse } from '../contracts/ai'

vi.mock('../services/ai', async importOriginal => ({ ...await importOriginal<typeof import('../services/ai')>(), queryAi: vi.fn() }))

beforeEach(() => {
  sessionStorage.clear()
  vi.clearAllMocks()
  window.history.replaceState({}, '', '/')
  window.matchMedia = vi.fn().mockReturnValue({ matches: true })
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', '') }
})

it('muestra la identidad, guía verificable y aviso de IA persistente', async () => {
  render(<ChatWidget autoOpen />)
  expect(screen.getByText(/Una pregunta abre/)).toBeVisible()
  expect(screen.getByText(/Estás hablando con una IA/)).toBeVisible()
  fireEvent.click(screen.getByRole('button', { name: /Seguir la evidencia/ }))
  expect(screen.getByText(/Puedo cometer errores. Abre las citas/)).toBeVisible()
  expect(queryAi).not.toHaveBeenCalled()
  const clipboard = { writeText: vi.fn().mockResolvedValue(undefined) }
  Object.defineProperty(navigator, 'clipboard', { value: clipboard, configurable: true })
  fireEvent.click(screen.getByRole('button', { name: 'Copiar respuesta' }))
  await waitFor(() => expect(screen.getByRole('button', { name: 'Respuesta copiada' })).toBeVisible())
  expect(clipboard.writeText).toHaveBeenCalledWith(expect.stringContaining('puede contener errores'))
})

it('cancela una consulta en curso sin mostrar una respuesta tardía', async () => {
  vi.mocked(queryAi).mockImplementation((_request, signal) => new Promise((_resolve, reject) => {
    signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
  }))
  render(<ChatWidget autoOpen />)
  fireEvent.change(screen.getByRole('textbox'), { target: { value: '¿Qué ocurre con una gota de metanol en FLEX?' } })
  fireEvent.click(screen.getByRole('button', { name: 'Enviar mensaje' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Detener consulta' }))
  expect(screen.getByText(/Consulta detenida/)).toBeVisible()
  await waitFor(() => expect(screen.queryByText(/Buscando evidencia/)).not.toBeInTheDocument())
  expect(screen.getByText(/Estás hablando con una IA/)).toBeVisible()
})

it('conserva la respuesta del backend aunque una cita tenga un resumen editorial conocido', async () => {
  vi.mocked(queryAi).mockResolvedValue({
    schema_version: 'public-1.1', id: 'request-1', status: 'supported',
    answer: 'Respuesta del backend a la pregunta actual.', claims: [],
    citations: [{ id: 'citation-1', kind: 'document', title: 'Informe BASS-II', url: 'https://ntrs.nasa.gov/report',
      page: 18, snippet: 'plastic rods blowoff and quenching extinction limits', source: 'ntrs:20160000593' }],
    limitations: [], charts: [], provenance: 'live',
  } satisfies AiResponse)
  render(<ChatWidget autoOpen />)
  fireEvent.change(screen.getByLabelText('Estudio del chat'), { target: { value: 'bass-ii' } })
  fireEvent.change(screen.getByRole('textbox'), { target: { value: '¿Qué es la microgravedad y la combustión?' } })
  fireEvent.click(screen.getByRole('button', { name: 'Enviar mensaje' }))
  await waitFor(() => expect(queryAi).toHaveBeenCalledWith(expect.objectContaining({ question: '¿Qué es la microgravedad y la combustión?' }), expect.anything()))
  expect(await screen.findByText('Respuesta del backend a la pregunta actual.')).toBeVisible()
  expect(screen.queryByText(/quemaron varillas de plástico/)).not.toBeInTheDocument()
  expect(screen.getByLabelText('Estudio del chat')).toHaveValue('')
})
