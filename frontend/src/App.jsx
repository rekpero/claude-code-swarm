import { useState } from 'react'
import { Header } from './components/layout/Header'
import { TabNav } from './components/layout/TabNav'
import { MetricsBar } from './components/metrics/MetricsBar'
import { ActiveAgents } from './components/agents/ActiveAgents'
import { IssueQueue } from './components/issues/IssueQueue'
import { PRTracker } from './components/prs/PRTracker'
import { AddWorkspaceModal } from './components/modals/AddWorkspaceModal'
import { WorkspaceSettingsModal } from './components/modals/WorkspaceSettingsModal'
import { PlannerModal } from './components/planner/PlannerModal'
import { useMetrics } from './hooks/useMetrics'
import { useAgents } from './hooks/useAgents'
import { useIssues } from './hooks/useIssues'
import { usePRs } from './hooks/usePRs'
import { useWorkspaceContext } from './context/WorkspaceContext'
import { useAuth } from './context/AuthContext'
import { LoginPage } from './components/auth/LoginPage'

function ErrorBanner({ error }) {
  if (!error) return null
  return (
    <div className="bg-[var(--red-dim)] border-b border-[rgba(248,113,113,0.15)] px-6 py-2 text-[11px] text-[var(--red)] font-mono">
      Cannot connect to backend \u2014 {error.message}
    </div>
  )
}

export function App() {
  const { isAuthenticated, isChecking } = useAuth()
  const [activeTab, setActiveTab] = useState('agents')
  const [addWorkspaceOpen, setAddWorkspaceOpen] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [plannerOpen, setPlannerOpen] = useState(false)
  const { selectedWorkspaceId } = useWorkspaceContext()
  const { error: metricsError } = useMetrics(selectedWorkspaceId)
  const { data: agentsData } = useAgents(selectedWorkspaceId)
  const { data: issuesData } = useIssues(selectedWorkspaceId)
  const { data: prsData } = usePRs(selectedWorkspaceId)

  if (isChecking) {
    return <div className="min-h-screen bg-[var(--bg)]" />
  }

  if (!isAuthenticated) {
    return <LoginPage />
  }

  const counts = {
    agents: agentsData?.total ?? 0,
    issues: issuesData?.issues?.length ?? 0,
    prs: prsData?.prs?.length ?? 0,
  }

  return (
    <div className="min-h-screen flex flex-col bg-[var(--bg)]">
      <Header
        onAddWorkspace={() => setAddWorkspaceOpen(true)}
        onOpenSettings={() => setSettingsOpen(true)}
        onOpenPlanner={() => setPlannerOpen(true)}
      />
      <ErrorBanner error={metricsError} />
      <MetricsBar />
      <TabNav activeTab={activeTab} onTabChange={setActiveTab} counts={counts} />

      <main className="flex-1 overflow-auto">
        <div style={{ display: activeTab === 'agents' ? undefined : 'none' }}>
          <ActiveAgents />
        </div>
        <div style={{ display: activeTab === 'issues' ? undefined : 'none' }}>
          <IssueQueue />
        </div>
        <div style={{ display: activeTab === 'prs' ? undefined : 'none' }}>
          <PRTracker />
        </div>
      </main>

      <AddWorkspaceModal open={addWorkspaceOpen} onClose={() => setAddWorkspaceOpen(false)} />
      <WorkspaceSettingsModal open={settingsOpen} onClose={() => setSettingsOpen(false)} />
      <PlannerModal open={plannerOpen} onClose={() => setPlannerOpen(false)} />
    </div>
  )
}
