import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import App from './App'

vi.mock('./components/GalaxyScene', () => ({
  GalaxyScene: () => <div aria-label="Cámara tridimensional interactiva de combustión en microgravedad">Vista 3D</div>,
}))

describe('Pyrogravity frontend', () => {
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
    expect(await screen.findByText('Respaldada')).toBeInTheDocument()
    expect(screen.getByText(/El perfil validado contiene 184 muestras/)).toBeInTheDocument()
    expect(screen.getByText('Documento · p. 42')).toBeInTheDocument()
    expect(screen.getByText('Datos no solicitados')).toBeInTheDocument()
  })

  it('expone fichas navegables en lugar de botones deshabilitados', () => {
    render(<MemoryRouter initialEntries={['/sources']}><App /></MemoryRouter>)
    const links = screen.getAllByRole('link', { name: /Abrir ficha científica/ })
    expect(links).toHaveLength(5)
    expect(links[0]).toHaveAttribute('href', '/explorer?experiment=flex')
    expect(screen.queryByRole('button', { name: /Localizador NASA/ })).not.toBeInTheDocument()
  })
})
