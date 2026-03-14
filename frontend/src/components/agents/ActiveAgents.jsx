import { useState, useEffect } from 'react'
import { Bot, ChevronLeft, ChevronRight } from 'lucide-react'
import { AgentCard } from './AgentCard'
import { EmptyState } from '../ui/EmptyState'
import { Button } from '../ui/Button'
import { Spinner } from '../ui/Spinner'
import { useAgents } from '../../hooks/useAgents'
import { useWorkspaceContext } from '../../context/WorkspaceContext'
import { useWorkspaces } from '../../hooks/useWorkspaces'

const PAGE_SIZE = 20

export function ActiveAgents() {
  const [offset, setOffset] = useState(0)
  const { selectedWorkspaceId } = useWorkspaceContext()
  const { data: wsData } = useWorkspaces()
  const wsMap = Object.fromEntries((wsData?.workspaces || []).map(w => [w.id, w.name || w.repo_url]))
  const showWorkspace = !selectedWorkspaceId

  useEffect(() => { setOffset(0) }, [selectedWorkspaceId])
  const { data, isLoading } = useAgents(selectedWorkspaceId, { limit: PAGE_SIZE, offset })

  const agents = data?.agents || []
  const total = data?.total ?? 0
  const totalPages = Math.ceil(total / PAGE_SIZE)
  const currentPage = Math.floor(offset / PAGE_SIZE) + 1

  return (
    <div className="px-6 py-5">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-[13px] font-semibold tracking-tight">
          Active Agents
          {total > 0 && <span className="ml-2 text-[var(--text-muted)] font-normal text-[11px]">({total})</span>}
        </h2>
        {totalPages > 1 && (
          <div className="flex items-center gap-1.5">
            <Button
              size="sm"
              variant="ghost"
              disabled={offset === 0}
              onClick={() => setOffset((v) => Math.max(0, v - PAGE_SIZE))}
            >
              <ChevronLeft size={11} />
            </Button>
            <span className="text-[10px] text-[var(--text-muted)] font-mono tabular-nums px-1">
              {currentPage} / {totalPages}
            </span>
            <Button
              size="sm"
              variant="ghost"
              disabled={offset + PAGE_SIZE >= total}
              onClick={() => setOffset((v) => v + PAGE_SIZE)}
            >
              <ChevronRight size={11} />
            </Button>
          </div>
        )}
      </div>

      {isLoading ? (
        <div className="flex justify-center py-12">
          <Spinner />
        </div>
      ) : agents.length === 0 ? (
        <EmptyState icon={Bot} message="No agents running" description="Agents will appear here when issues are dispatched" />
      ) : (
        <div className="flex flex-col gap-2">
          {agents.map((agent) => (
            <AgentCard key={agent.agent_id} agent={agent} workspaceName={showWorkspace ? wsMap[agent.workspace_id] : null} onRestarted={() => {}} />
          ))}
        </div>
      )}
    </div>
  )
}
