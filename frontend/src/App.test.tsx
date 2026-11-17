import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'

vi.mock('./components/GalaxyScene', () => ({
  GalaxyScene: () => <div aria-label="Cámara tridimensional interactiva de combustión en microgravedad">Vista 3D</div>,
}))

describe('Pyrogravity frontend', () => {
  beforeEach(() => vi.stubEnv('VITE_AI_DEMO_MODE', 'true'))
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.unstubAllEnvs()
  })
  it('muestra el Command Center y sus indicadores científicos', async () => {
    render(<MemoryRouter initialEntries={['/']}><App /></MemoryRouter>)
    expect(screen.getByRole('heading', { name: 'Flame Intelligence Center' })).toBeInTheDocument()
    expect(screen.getByText('Datasets activos')).toBeInTheDocument()
    expect(await screen.findByLabelText('Cámara tridimensional interactiva de combustión en microgravedad')).toBeInTheDocument()
  })

  it('permite abrir el explorador mediante una ruta directa', () => {
    render(<MemoryRouter initialEntries={['/explorer?experiment=bass-ii']}><App /></MemoryRouter>)
    expect(screen.getByRole('heading', { name: 'Explorador de experimentos' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Burning and Suppression of Solids II' })).toBeInTheDocument()
  })

  it('mantiene operativos los controles y renderiza evidencia contractual', async () => {
    render(<MemoryRouter initialEntries={['/']}><App /></MemoryRouter>)
    const moon = screen.getByRole('button', { name: /Luna/ })
    fireEvent.click(moon)
    expect(moon).toHaveAttribute('aria-pressed', 'true')

    fireEvent.change(screen.getByLabelText('Pregunta para el copiloto'), { target: { value: '¿Cuántas muestras hay?' } })
    fireEvent.click(screen.getByRole('button', { name: 'Enviar pregunta' }))
    expect(await screen.findByText('Evidencia insuficiente')).toBeInTheDocument()
    expect(screen.getByText('DEMOSTRACIÓN · contenido no científico')).toBeInTheDocument()
    expect(screen.getByText(/No representa datos de NASA/)).toBeInTheDocument()
    expect(screen.queryByText('812', { exact: true })).not.toBeInTheDocument()
  })

  it('expone fichas navegables en lugar de botones deshabilitados', () => {
    render(<MemoryRouter initialEntries={['/sources']}><App /></MemoryRouter>)
    const links = screen.getAllByRole('link', { name: /Abrir ficha científica/ })
    expect(links).toHaveLength(5)
    expect(links[0]).toHaveAttribute('href', '/explorer?experiment=flex')
    expect(screen.queryByRole('button', { name: /Localizador NASA/ })).not.toBeInTheDocument()
  })

  it('muestra AI_UNAVAILABLE con trazabilidad sin confundirlo con evidencia insuficiente', async () => {
    vi.stubEnv('VITE_AI_DEMO_MODE', 'false')
    const fetcher = vi.fn<typeof fetch>(async (_input, init) => {
      const request = JSON.parse(String(init?.body)) as { id: string; experiment_ids: string[]; variables: string[] }
      expect(request.experiment_ids).toEqual(['PSI-69:psi-69_flex:1'])
      expect(request.variables).toEqual(['burn_time'])
      return new Response(JSON.stringify({ error: { code: 'AI_UNAVAILABLE', message: 'El proveedor de IA está desactivado hasta completar autenticación y rol lector.', request_id: request.id, details: { schema_version: 'public-1.1' } } }), { status: 503, headers: { 'Content-Type': 'application/json', 'X-Request-ID': request.id } })
    })
    vi.stubGlobal('fetch', fetcher)

    render(<MemoryRouter initialEntries={['/']}><App /></MemoryRouter>)
    fireEvent.change(screen.getByLabelText('Pregunta para el copiloto'), { target: { value: '¿Cuál fue el burn_time del ensayo 1?' } })
    fireEvent.click(screen.getByRole('button', { name: 'Enviar pregunta' }))

    expect(await screen.findByText('AI_UNAVAILABLE · HTTP 503')).toBeInTheDocument()
    expect(screen.getByText('El proveedor de IA está desactivado hasta completar autenticación y rol lector.')).toBeInTheDocument()
    expect(screen.getByText(/request_id/)).toBeInTheDocument()
    expect(screen.queryByText('Evidencia insuficiente')).not.toBeInTheDocument()
  })
})
