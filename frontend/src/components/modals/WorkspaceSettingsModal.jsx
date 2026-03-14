import { useState, useEffect } from 'react'
import { FolderTree, GitBranch, FileCode, Package, RefreshCw, Check, AlertTriangle, ArrowDown } from 'lucide-react'
import { Modal } from '../ui/Modal'
import { Button } from '../ui/Button'
import { Badge } from '../ui/Badge'
import { Spinner } from '../ui/Spinner'
import { EnvEditor } from './EnvEditor'
import { useUpdateWorkspace, useDeleteWorkspace, useWorkspaces } from '../../hooks/useWorkspaces'
import { useWorkspaceContext } from '../../context/WorkspaceContext'
import { useGitSync } from '../../hooks/useGitSync'
import { getWorkspaceStructure } from '../../api/client'

const TABS = ['General', 'Env Files', 'Structure']

function GitPullSection({ workspace }) {
  const { data: syncStatus, isLoading, refetch, pull } = useGitSync(workspace?.id)

  const isSynced = syncStatus?.synced
  const behind = syncStatus?.behind || 0
  const ahead = syncStatus?.ahead || 0

  return (
    <div className="bg-[var(--bg)] border border-[var(--border-subtle)] rounded-lg p-3.5 space-y-2.5">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <GitBranch size={12} className="text-[var(--text-muted)]" />
          <span className="text-[9px] uppercase tracking-widest text-[var(--text-muted)] font-semibold">Git Sync</span>
        </div>
        <button
          onClick={() => refetch()}
          disabled={isLoading}
          className="p-1 rounded text-[var(--text-muted)] hover:text-[var(--text-dim)] hover:bg-[var(--surface-hover)] transition-colors disabled:opacity-40"
          title="Refresh status"
        >
          <RefreshCw size={10} className={isLoading ? 'animate-spin' : ''} />
        </button>
      </div>

      {isLoading && !syncStatus && (
        <div className="flex justify-center py-2"><Spinner /></div>
      )}

      {syncStatus && (
        <div className="space-y-2.5">
          <div className="flex items-center gap-2">
            {isSynced ? (
              <Badge variant="green">
                <span className="flex items-center gap-1"><Check size={8} /> Synced</span>
              </Badge>
            ) : (
              <Badge variant="yellow">
                <span className="flex items-center gap-1"><AlertTriangle size={8} /> Out of sync</span>
              </Badge>
            )}
          </div>

          <div className="grid grid-cols-[80px_1fr] gap-y-1.5 gap-x-3 text-[10px]">
            <span className="text-[var(--text-muted)]">Local</span>
            <span className="text-[var(--text-dim)] font-mono">{syncStatus.local_sha || '\u2014'}</span>
            <span className="text-[var(--text-muted)]">Remote</span>
            <span className="text-[var(--text-dim)] font-mono">{syncStatus.remote_sha || '\u2014'}</span>
            {behind > 0 && (
              <>
                <span className="text-[var(--text-muted)]">Behind</span>
                <span className="text-[var(--yellow)] font-mono">{behind} commit{behind !== 1 ? 's' : ''}</span>
              </>
            )}
            {ahead > 0 && (
              <>
                <span className="text-[var(--text-muted)]">Ahead</span>
                <span className="text-[var(--text-dim)] font-mono">{ahead} commit{ahead !== 1 ? 's' : ''}</span>
              </>
            )}
          </div>

          {pull.error && (
            <div className="text-[10px] text-[var(--red)] flex items-center gap-1.5">
              <AlertTriangle size={10} />
              {pull.error.message}
            </div>
          )}

          <button
            onClick={() => pull.mutate()}
            disabled={pull.isPending}
            className="flex items-center gap-1.5 px-3 py-1.5 text-[10px] font-medium bg-[var(--accent)] text-white rounded-md hover:brightness-110 transition-all disabled:opacity-50 w-full justify-center"
          >
            {pull.isPending ? (
              <><RefreshCw size={10} className="animate-spin" /> Pulling...</>
            ) : (
              <><ArrowDown size={10} /> Pull Latest</>
            )}
          </button>
        </div>
      )}
    </div>
  )
}

function StructureTab({ workspace }) {
  const [structure, setStructure] = useState(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!workspace?.id) return
    setLoading(true)
    getWorkspaceStructure(workspace.id)
      .then(data => setStructure(data.structure || {}))
      .catch(() => setStructure(null))
      .finally(() => setLoading(false))
  }, [workspace?.id])

  if (loading) {
    return <div className="flex justify-center py-8"><Spinner /></div>
  }

  const statusColors = {
    active: 'green',
    cloning: 'yellow',
    error: 'red',
  }

  return (
    <div className="space-y-4">
      {/* Git sync & pull */}
      {workspace.status === 'active' && <GitPullSection workspace={workspace} />}

      {/* Workspace info */}
      <div className="bg-[var(--bg)] border border-[var(--border-subtle)] rounded-lg p-3.5 space-y-2.5">
        <div className="flex items-center gap-2">
          <FolderTree size={12} className="text-[var(--text-muted)]" />
          <span className="text-[9px] uppercase tracking-widest text-[var(--text-muted)] font-semibold">Workspace</span>
        </div>
        <div className="grid grid-cols-[80px_1fr] gap-y-1.5 gap-x-3 text-[10px]">
          <span className="text-[var(--text-muted)]">Path</span>
          <span className="text-[var(--text-dim)] font-mono truncate">{workspace.local_path || '\u2014'}</span>
          <span className="text-[var(--text-muted)]">Status</span>
          <span><Badge variant={statusColors[workspace.status] || 'dim'}>{workspace.status || 'unknown'}</Badge></span>
          <span className="text-[var(--text-muted)]">Branch</span>
          <span className="text-[var(--text-dim)] font-mono flex items-center gap-1.5">
            <GitBranch size={9} className="text-[var(--text-muted)]" />
            {workspace.base_branch || 'main'}
          </span>
        </div>
      </div>

      {/* Repo structure */}
      {structure && (
        <div className="bg-[var(--bg)] border border-[var(--border-subtle)] rounded-lg p-3.5 space-y-2.5">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Package size={12} className="text-[var(--text-muted)]" />
              <span className="text-[9px] uppercase tracking-widest text-[var(--text-muted)] font-semibold">Repo Structure</span>
            </div>
            <Badge variant={structure.is_monorepo ? 'purple' : 'green'}>
              {structure.is_monorepo ? 'Monorepo' : 'Standard'}
            </Badge>
          </div>

          {/* Packages list */}
          {structure.packages?.length > 0 && (
            <div className="space-y-1">
              <span className="text-[9px] text-[var(--text-muted)] uppercase tracking-wider">
                Packages ({structure.packages.length})
              </span>
              <div className="bg-[var(--surface)] border border-[var(--border-subtle)] rounded-md overflow-hidden">
                {structure.packages.map((pkg, i) => (
                  <div
                    key={pkg.path || i}
                    className={`flex items-center gap-2 px-3 py-1.5 text-[10px] ${
                      i > 0 ? 'border-t border-[var(--border-subtle)]' : ''
                    }`}
                  >
                    <FolderTree size={9} className="text-[var(--accent)] flex-shrink-0" />
                    <span className="text-[var(--text-dim)] font-mono truncate">{pkg.path}</span>
                    {pkg.name && (
                      <span className="text-[var(--text-muted)] ml-auto flex-shrink-0">{pkg.name}</span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Env files found */}
          {structure.env_files?.length > 0 && (
            <div className="space-y-1">
              <span className="text-[9px] text-[var(--text-muted)] uppercase tracking-wider">
                Env Files Found
              </span>
              <div className="flex flex-wrap gap-1.5">
                {structure.env_files.map((f, i) => {
                  const path = typeof f === 'string' ? f : f.path
                  return (
                    <span key={i} className="flex items-center gap-1 px-2 py-0.5 bg-[var(--yellow-dim)] text-[var(--yellow)] rounded text-[9px] font-mono">
                      <FileCode size={8} />
                      {path}
                    </span>
                  )
                })}
              </div>
            </div>
          )}
        </div>
      )}

      {!structure && (
        <div className="text-[10px] text-[var(--text-muted)] text-center py-4">
          Could not load repo structure.
        </div>
      )}
    </div>
  )
}

export function WorkspaceSettingsModal({ open, onClose }) {
  const [activeTab, setActiveTab] = useState('General')
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [updateError, setUpdateError] = useState(null)
  const { selectedWorkspaceId, setSelectedWorkspaceId } = useWorkspaceContext()
  const { data } = useWorkspaces()
  const { mutate: update, isPending: isUpdating } = useUpdateWorkspace()
  const { mutate: del, isPending: isDeleting } = useDeleteWorkspace()

  const workspace = data?.workspaces?.find((w) => w.id === selectedWorkspaceId)
  const [form, setForm] = useState({ name: '', repo_url: '', base_branch: '' })

  useEffect(() => {
    if (workspace) {
      setForm({
        name: workspace.name || '',
        repo_url: workspace.repo_url || '',
        base_branch: workspace.base_branch || '',
      })
      setUpdateError(null)
    } else {
      setForm({ name: '', repo_url: '', base_branch: '' })
    }
    setConfirmDelete(false)
  }, [workspace?.id, workspace?.name, workspace?.repo_url, workspace?.base_branch])

  useEffect(() => {
    if (!open) {
      setConfirmDelete(false)
    } else {
      setUpdateError(null)
    }
  }, [open])

  const inputClass = 'w-full px-3 py-2 text-[11px] bg-[var(--bg)] border border-[var(--border)] rounded-md text-[var(--text)] font-mono focus:border-[var(--accent)] outline-none transition-colors'

  const handleUpdate = (e) => {
    e.preventDefault()
    if (!selectedWorkspaceId) return
    setUpdateError(null)
    update(
      { id: selectedWorkspaceId, data: form },
      {
        onSuccess: onClose,
        onError: (err) => setUpdateError(err?.message || 'Failed to update workspace.'),
      }
    )
  }

  const handleDelete = () => {
    if (!selectedWorkspaceId) return
    del(selectedWorkspaceId, {
      onSuccess: () => {
        setSelectedWorkspaceId(null)
        onClose()
      },
      onError: (err) => setUpdateError(err?.message || 'Failed to delete workspace.'),
    })
  }

  if (!workspace) {
    return (
      <Modal open={open} onClose={onClose} title="Workspace Settings">
        <p className="text-[11px] text-[var(--text-muted)]">No workspace selected. Select a workspace first.</p>
        <div className="flex justify-end mt-4">
          <Button variant="ghost" onClick={onClose}>Close</Button>
        </div>
      </Modal>
    )
  }

  return (
    <Modal open={open} onClose={onClose} title={`Settings \u2014 ${workspace.name || workspace.repo_url}`} maxWidth="560px">
      <div className="flex gap-0 border-b border-[var(--border)] mb-5">
        {TABS.map((tab) => (
          <button
            key={tab}
            onClick={() => { setActiveTab(tab); setConfirmDelete(false); setUpdateError(null) }}
            className={`relative px-4 py-2 text-[11px] font-medium transition-colors ${
              activeTab === tab
                ? 'text-[var(--text)]'
                : 'text-[var(--text-muted)] hover:text-[var(--text-dim)]'
            }`}
          >
            {tab}
            {activeTab === tab && (
              <span className="absolute bottom-0 left-2 right-2 h-[2px] bg-[var(--accent)] rounded-t-full" />
            )}
          </button>
        ))}
      </div>

      {activeTab === 'General' && (
        <form onSubmit={handleUpdate} className="flex flex-col gap-4">
          <div>
            <label className="block text-[9px] uppercase tracking-widest text-[var(--text-muted)] mb-1.5 font-medium">Display Name</label>
            <input value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} className={inputClass} />
          </div>
          <div>
            <label className="block text-[9px] uppercase tracking-widest text-[var(--text-muted)] mb-1.5 font-medium">Repository URL</label>
            <input value={form.repo_url} onChange={(e) => setForm((f) => ({ ...f, repo_url: e.target.value }))} className={inputClass} />
          </div>
          <div>
            <label className="block text-[9px] uppercase tracking-widest text-[var(--text-muted)] mb-1.5 font-medium">Base Branch</label>
            <input value={form.base_branch} onChange={(e) => setForm((f) => ({ ...f, base_branch: e.target.value }))} className={inputClass} />
          </div>
          {updateError && (
            <p className="text-[10px] text-[var(--red)]">{updateError}</p>
          )}
          <div className="flex justify-between items-center mt-1">
            <div>
              {confirmDelete ? (
                <div className="flex items-center gap-2">
                  <span className="text-[10px] text-[var(--red)]">Are you sure?</span>
                  <Button size="sm" variant="danger" loading={isDeleting} onClick={handleDelete}>
                    Yes, Delete
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setConfirmDelete(false)}>
                    Cancel
                  </Button>
                </div>
              ) : (
                <Button size="sm" variant="danger" onClick={() => setConfirmDelete(true)}>
                  Delete Workspace
                </Button>
              )}
            </div>
            <div className="flex gap-2">
              <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
              <Button type="submit" variant="primary" loading={isUpdating}>Save</Button>
            </div>
          </div>
        </form>
      )}

      {activeTab === 'Env Files' && (
        <EnvEditor workspaceId={selectedWorkspaceId} />
      )}

      {activeTab === 'Structure' && (
        <StructureTab workspace={workspace} />
      )}
    </Modal>
  )
}
