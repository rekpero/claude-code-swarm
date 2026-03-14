import { useState } from 'react'
import { Header } from './components/layout/Header'
import { TabNav } from './components/layout/TabNav'
import { MetricsBar } from './components/metrics/MetricsBar'
import { ActiveAgents } from './components/agents/ActiveAgents'
import { IssueQueue } from './components/issues/IssueQueue'
import { PRTracker } from './components/prs/PRTracker'
import { AddWorkspaceModal } from './components/modals/AddWorkspaceModal'
import { WorkspaceSettingsModal } from './components/modals/WorkspaceSettingsModal'
import { useMetrics } from './hooks/useMetrics'
import { useAgents } from './hooks/useAgents'
import { useIssues } from './hooks/useIssues'
import { usePRs } from './hooks/usePRs'
import { useWorkspaceContext } from './context/WorkspaceContext'

function ErrorBanner({ error }) {
  if (!error) return null
  return (
    <div className="bg-[rgba(225,112,85,0.1)] border-b border-[rgba(225,112,85,0.3)] px-5 py-2 text-[12px] text-[var(--red)]">
      Cannot connect to backend — {error.message}
    </div>
  )
}

export function App() {
  const [activeTab, setActiveTab] = useState('agents')
  const [addWorkspaceOpen, setAddWorkspaceOpen] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const { selectedWorkspaceId } = useWorkspaceContext()

  const { error: metricsError } = useMetrics(selectedWorkspaceId)
  const { data: agentsData } = useAgents(selectedWorkspaceId)
  const { data: issuesData } = useIssues(selectedWorkspaceId)
  const { data: prsData } = usePRs(selectedWorkspaceId)

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
      />
      <ErrorBanner error={metricsError} />
      <MetricsBar />
      <TabNav activeTab={activeTab} onTabChange={setActiveTab} counts={counts} />

      <main className="flex-1 overflow-auto">
        {activeTab === 'agents' && <ActiveAgents />}
        {activeTab === 'issues' && <IssueQueue />}
        {activeTab === 'prs' && <PRTracker />}
      </main>

      <AddWorkspaceModal open={addWorkspaceOpen} onClose={() => setAddWorkspaceOpen(false)} />
      <WorkspaceSettingsModal open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </div>
  )
}
