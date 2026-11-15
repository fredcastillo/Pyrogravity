import { render, screen } from '@testing-library/react'
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
})
