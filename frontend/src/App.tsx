import { Navigate, Route, Routes } from 'react-router-dom'
import { lazy, Suspense } from 'react'
import { AppShell } from './components/AppShell'
import { CommandCenter } from './pages/CommandCenter'
import { CompareLab } from './pages/CompareLab'
import { Explorer } from './pages/Explorer'
import { PublishedCenter } from './pages/PublishedCenter'
import { Sources } from './pages/Sources'
import { Status } from './pages/Status'

const StudyDetail = lazy(() => import('./pages/StudyDetail').then(module => ({ default: module.StudyDetail })))

export default function App() {
  if (import.meta.env.VITE_STATIC_HOST === 'true') {
    const match = /^\/estudios\/([a-z0-9-]+)\/?$/.exec(window.location.pathname)
    if (match) return <AppShell><Suspense fallback={<p className="observatory-content" role="status">Cargando estudio…</p>}><StudyDetail id={match[1]} /></Suspense></AppShell>
    return <AppShell><PublishedCenter /></AppShell>
  }
  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<CommandCenter />} />
        <Route path="/explorer" element={<Explorer />} />
        <Route path="/compare" element={<CompareLab />} />
        <Route path="/sources" element={<Sources />} />
        <Route path="/status" element={<Status />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AppShell>
  )
}
