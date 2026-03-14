const BASE = ''

async function apiFetch(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: res.statusText }))
    throw new Error(err.error || `HTTP ${res.status}`)
  }
  return res.json()
}

// Metrics
export const getMetrics = (wsId) =>
  apiFetch(`/api/metrics${wsId ? `?workspace_id=${wsId}` : ''}`)

// Agents
export const getAgents = (wsId, limit = 20, offset = 0) =>
  apiFetch(`/api/agents?limit=${limit}&offset=${offset}${wsId ? `&workspace_id=${wsId}` : ''}`)

export const getAgentLogs = (agentId, since = 0) =>
  apiFetch(`/api/agents/${agentId}/logs?since=${since}`)

// Issues
export const getIssues = (wsId) =>
  apiFetch(`/api/issues${wsId ? `?workspace_id=${wsId}` : ''}`)

export const updateIssueStatus = (issueNumber, status, wsId) =>
  apiFetch(`/api/issues/${issueNumber}/status${wsId ? `?workspace_id=${wsId}` : ''}`, {
    method: 'PUT',
    body: JSON.stringify({ status }),
  })

// PRs
export const getPRs = (wsId) =>
  apiFetch(`/api/prs${wsId ? `?workspace_id=${wsId}` : ''}`)

// Workspaces
export const getWorkspaces = () => apiFetch('/api/workspaces')

export const createWorkspace = (data) =>
  apiFetch('/api/workspaces', { method: 'POST', body: JSON.stringify(data) })

export const updateWorkspace = (id, data) =>
  apiFetch(`/api/workspaces/${id}`, { method: 'PUT', body: JSON.stringify(data) })

export const deleteWorkspace = (id) =>
  apiFetch(`/api/workspaces/${id}`, { method: 'DELETE' })

export const getWorkspaceStructure = (wsId) =>
  apiFetch(`/api/workspaces/${wsId}/structure`)

// Env files
export const getEnvFiles = (wsId) =>
  apiFetch(`/api/workspaces/${wsId}/env-files`)

export const getEnv = (wsId, file = '.env') =>
  apiFetch(`/api/workspaces/${wsId}/env?env_file=${encodeURIComponent(file)}`)

export const saveEnv = (wsId, file, vars) =>
  apiFetch(`/api/workspaces/${wsId}/env`, {
    method: 'PUT',
    body: JSON.stringify({ vars, env_file: file }),
  })

export const deleteEnvFile = (wsId, file) =>
  apiFetch(`/api/workspaces/${wsId}/env?env_file=${encodeURIComponent(file)}`, {
    method: 'DELETE',
  })

export const loadEnvFromDisk = (wsId, file = '.env') =>
  apiFetch(`/api/workspaces/${wsId}/env-load?env_file=${encodeURIComponent(file)}`, {
    method: 'POST',
  })

// Planning
export const getPlanningSession = (sessionId) =>
  apiFetch(`/api/planning/${sessionId}`)

export const getPlanningEvents = (sessionId, since = 0) =>
  apiFetch(`/api/planning/${sessionId}/events?since=${since}`)

export const startPlanning = (wsId, message) =>
  apiFetch('/api/planning', { method: 'POST', body: JSON.stringify({ workspace_id: wsId, message }) })

export const refinePlan = (sessionId, message) =>
  apiFetch(`/api/planning/${sessionId}/messages`, {
    method: 'POST',
    body: JSON.stringify({ message }),
  })

export const createIssueFromPlan = (sessionId, title = '', messageIndex = null) =>
  apiFetch(`/api/planning/${sessionId}/create-issue`, {
    method: 'POST',
    body: JSON.stringify({ title, message_index: messageIndex }),
  })

export const cancelPlanning = (sessionId) =>
  apiFetch(`/api/planning/${sessionId}/cancel`, { method: 'POST' })

export const deletePlanningSession = (sessionId) =>
  apiFetch(`/api/planning/${sessionId}`, { method: 'DELETE' })

export const listPlanningSessions = (wsId) =>
  apiFetch(`/api/workspaces/${wsId}/planning-sessions`)
