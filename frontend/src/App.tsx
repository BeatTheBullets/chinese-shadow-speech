import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import Settings from './pages/Settings'
import Shell from './components/Shell'
import Library from './pages/Library'
import Practice from './pages/Practice'
import Review from './pages/Review'
import Drill from './pages/Drill'
import Overview from './pages/stats/Overview'
import Activity from './pages/stats/Activity'
import Characters from './pages/stats/Characters'
import Drills from './pages/stats/Drills'
import Sentences from './pages/stats/Sentences'
import Sounds from './pages/stats/Sounds'
import Tones from './pages/stats/Tones'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Navigate to="/library" replace />} />
        <Route path="/library" element={<Library />} />
        <Route path="/practice/:id" element={<Practice />} />
        <Route path="/review" element={<Review />} />
        <Route path="/drill" element={<Drill />} />
        <Route path="/stats" element={<Overview />} />
        <Route path="/stats/characters" element={<Characters />} />
        <Route path="/stats/tones" element={<Tones />} />
        <Route path="/stats/sounds" element={<Sounds />} />
        <Route path="/stats/sentences" element={<Sentences />} />
        <Route path="/stats/activity" element={<Activity />} />
        <Route path="/stats/drills" element={<Drills />} />
        <Route path="/settings" element={<Shell><Settings /></Shell>} />
        <Route path="*" element={<div className="p-8 text-fgdim">Not found</div>} />
      </Routes>
    </BrowserRouter>
  )
}
