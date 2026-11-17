import { ArrowUpRight, Menu, X } from 'lucide-react'
import { useEffect, useRef, useState, type PropsWithChildren } from 'react'
import mark from '../assets/pyrogravity-mark-small.webp'
import { scientificCatalogUrl } from '../scientificCatalog'
import { enableOrbitalField } from '../space/motion'

const destinations = [
  ['Tablas NASA', 'catalog-title'],
  ['Análisis y gráficas', 'science-title'],
  ['Comparador', 'comparison-title'],
]

export function PublishedShell({ children }: PropsWithChildren) {
  const orbit = useRef<HTMLCanvasElement>(null)
  const menuButton = useRef<HTMLButtonElement>(null)
  const [open, setOpen] = useState(false)

  useEffect(() => {
    if (orbit.current) return enableOrbitalField(orbit.current)
  }, [])

  return (
    <div className="observatory">
      <div className="orbital-backdrop" aria-hidden="true"><canvas className="orbital-canvas" ref={orbit} /></div>
      <a className="skip-link" href="#main-content">Saltar al contenido</a>
      <header className="observatory-header" onKeyDown={(event) => {
        if (event.key === 'Escape' && open) {
          setOpen(false)
          menuButton.current?.focus()
        }
      }}>
        <div className="observatory-header__inner">
          <a className="observatory-brand" href="/" aria-label="Pyrogravity · inicio">
            <img src={mark} alt="" width="34" height="34" />
            <span>Pyrogravity</span>
          </a>
          <button className="observatory-menu" type="button" ref={menuButton} aria-expanded={open}
            aria-controls="observatory-navigation" aria-label={open ? 'Cerrar navegación' : 'Abrir navegación'}
            onClick={() => setOpen(!open)}>{open ? <X aria-hidden="true" /> : <Menu aria-hidden="true" />}</button>
          <nav id="observatory-navigation" className="observatory-navigation" data-open={open} aria-label="Navegación principal">
            {destinations.map(([label, id]) => <a key={id} href={id === 'science-title' ? '/#estudios' : scientificCatalogUrl(id)} onClick={() => setOpen(false)}>{label}</a>)}
            <a className="observatory-query-link" href="#scientific-query" onClick={() => setOpen(false)}>Consultar fuentes <ArrowUpRight aria-hidden="true" /></a>
          </nav>
        </div>
      </header>
      <main id="main-content">{children}</main>
      <footer className="observatory-footer">
        <a className="observatory-brand" href="/"><img src={mark} alt="" width="28" height="28" /><span>Pyrogravity</span></a>
        <a href={scientificCatalogUrl('catalog-title')}>Explorar el catálogo</a>
        <a href="https://psi.nasa.gov/">Repositorio NASA PSI <ArrowUpRight aria-hidden="true" /></a>
      </footer>
    </div>
  )
}
