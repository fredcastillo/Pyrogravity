import { Navigate, Route, Routes } from 'react-router-dom'
import { AppShell } from './components/AppShell'
import { CommandCenter } from './pages/CommandCenter'
import { CompareLab } from './pages/CompareLab'
import { Explorer } from './pages/Explorer'
import { Sources } from './pages/Sources'
import { Status } from './pages/Status'

export default function App() {
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
