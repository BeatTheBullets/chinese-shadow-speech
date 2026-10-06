import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import Settings from './pages/Settings'
import Shell from './components/Shell'
import Library from './pages/Library'
import Practice from './pages/Practice'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Navigate to="/library" replace />} />
        <Route path="/library" element={<Library />} />
        <Route path="/practice/:id" element={<Practice />} />
        <Route path="/settings" element={<Shell><Settings /></Shell>} />
        <Route path="*" element={<div className="p-8 text-fgdim">Not found</div>} />
      </Routes>
    </BrowserRouter>
  )
}
