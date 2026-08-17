import { Routes, Route } from 'react-router-dom'
import { AppShell } from '@/components/AppShell'
import { ProjectList } from '@/pages/ProjectList'
import { NewProject } from '@/pages/NewProject'
import { ProjectEntry } from '@/pages/ProjectEntry'
import { Progress } from '@/pages/Progress'
import { AssetReviewGate } from '@/pages/AssetReviewGate'
import { Result } from '@/pages/Result'

function App() {
  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<ProjectList />} />
        <Route path="/new" element={<NewProject />} />
        <Route path="/projects/:projectId" element={<ProjectEntry />} />
        <Route path="/projects/:projectId/progress" element={<Progress />} />
        <Route path="/projects/:projectId/review" element={<AssetReviewGate />} />
        <Route path="/projects/:projectId/result" element={<Result />} />
      </Routes>
    </AppShell>
  )
}

export default App
