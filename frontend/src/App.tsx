import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import Settings from './pages/Settings'
import Library from './pages/Library'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Navigate to="/library" replace />} />
        <Route path="/library" element={<Library />} />
        <Route path="/practice/:id" element={<div className="p-8 text-fgdim">Practice (coming in Task 9)</div>} />
        <Route path="/settings" element={<Settings />} />
        <Route path="*" element={<div className="p-8 text-fgdim">Not found</div>} />
      </Routes>
    </BrowserRouter>
  )
}
