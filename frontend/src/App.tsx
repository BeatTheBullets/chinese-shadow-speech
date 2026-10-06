import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Navigate to="/library" replace />} />
        <Route path="*" element={<div className="p-8 text-fgdim">Not found</div>} />
      </Routes>
    </BrowserRouter>
  )
}
