import {
  Activity,
  Atom,
  Database,
  GitCompareArrows,
  LayoutDashboard,
  Menu,
  Search,
  ShieldCheck,
  X,
} from 'lucide-react'
import { useState, type PropsWithChildren } from 'react'
import { NavLink } from 'react-router-dom'
import pyrogravityLogo from '../assets/pyrogravity-logo.png'
import pyrogravityMark from '../assets/pyrogravity-mark.png'
import { scientificCatalogUrl } from '../scientificCatalog'

const navigation = [
  { to: '/', label: 'Command Center', icon: LayoutDashboard, end: true },
  { to: '/explorer', label: 'Explorador', icon: Search },
  { to: '/compare', label: 'Comparador', icon: GitCompareArrows },
  { to: '/sources', label: 'Fuentes', icon: Database },
  { to: '/status', label: 'Estado', icon: Activity },
]

const publishedNavigation = [
  { href: scientificCatalogUrl('catalog-title'), label: 'Tablas NASA', icon: Database },
  { href: scientificCatalogUrl('science-title'), label: 'Análisis y gráficas', icon: Search },
  { href: scientificCatalogUrl('comparison-title'), label: 'Comparador de ensayos', icon: GitCompareArrows },
]

export function AppShell({ children }: PropsWithChildren) {
  const [open, setOpen] = useState(false)
  const published = import.meta.env.VITE_STATIC_HOST === 'true'

  return (
    <div className="app-shell">
      <div className="ambient-field" aria-hidden="true">
        <span className="ambient-field__stars ambient-field__stars--far" />
        <span className="ambient-field__stars ambient-field__stars--near" />
        <i className="meteor-streak meteor-streak--one" />
        <i className="meteor-streak meteor-streak--two" />
        <i className="meteor-streak meteor-streak--three" />
      </div>
      <a className="skip-link" href="#main-content">Saltar al contenido</a>
      <header className="mobile-header">
        <div className="brand brand--compact"><img src={pyrogravityMark} alt="" /><span><b>Pyro</b>Gravity</span></div>
        <button type="button" className="icon-button" onClick={() => setOpen((value) => !value)} aria-label={open ? 'Cerrar navegación' : 'Abrir navegación'} aria-expanded={open} aria-controls="primary-sidebar">
          {open ? <X /> : <Menu />}
        </button>
      </header>
      {open && <button type="button" className="sidebar-scrim" aria-label="Cerrar navegación" onClick={() => setOpen(false)} />}
      <aside id="primary-sidebar" className={`sidebar ${open ? 'sidebar--open' : ''}`}>
        <div className="brand">
          <img src={pyrogravityLogo} alt="PyroGravity" className="brand__logo" />
          <span className="brand__descriptor">MICROGRAVITY FIRE INTELLIGENCE</span>
        </div>
        <nav aria-label="Navegación principal">
          <p className="eyebrow">OPERACIONES</p>
          {published ? publishedNavigation.map(({ href, label, icon: Icon }) => (
            <a key={href} href={href} className="nav-link"><Icon aria-hidden="true" /><span>{label}</span></a>
          )) : navigation.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end} onClick={() => setOpen(false)} className={({ isActive }) => isActive ? 'nav-link nav-link--active' : 'nav-link'}>
              <Icon aria-hidden="true" /><span>{label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="sidebar__footer">
          {!published && <div className="system-pill"><span className="status-dot" /> Sistemas nominales</div>}
          <div className="sidebar__meta"><ShieldCheck aria-hidden="true" /><span>Snapshot científico<br /><strong>NASA</strong></span></div>
        </div>
      </aside>
      <main id="main-content" className="main-content">{children}</main>
      <div className="background-orbit background-orbit--one" />
      <div className="background-orbit background-orbit--two" />
      <Atom className="background-atom" aria-hidden="true" />
    </div>
  )
}
