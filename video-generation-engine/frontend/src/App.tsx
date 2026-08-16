import { Routes, Route } from 'react-router-dom'
import { AppShell } from '@/components/AppShell'
import { ProjectList } from '@/pages/ProjectList'
import { NewProject } from '@/pages/NewProject'
import { ProjectEntry } from '@/pages/ProjectEntry'
import { Progress } from '@/pages/Progress'
import { Gate1AssetReview } from '@/pages/Gate1AssetReview'
import { Gate2GeneratedReview } from '@/pages/Gate2GeneratedReview'
import { Result } from '@/pages/Result'

function App() {
  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<ProjectList />} />
        <Route path="/new" element={<NewProject />} />
        <Route path="/projects/:projectId" element={<ProjectEntry />} />
        <Route path="/projects/:projectId/progress" element={<Progress />} />
        <Route path="/projects/:projectId/review" element={<Gate1AssetReview />} />
        <Route path="/projects/:projectId/generated-review" element={<Gate2GeneratedReview />} />
        <Route path="/projects/:projectId/result" element={<Result />} />
      </Routes>
    </AppShell>
  )
}

export default App
