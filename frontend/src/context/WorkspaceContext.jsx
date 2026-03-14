import { createContext, useContext, useState, useEffect } from 'react'

const WorkspaceContext = createContext(null)

export function WorkspaceProvider({ children }) {
  const [selectedWorkspaceId, setSelectedWorkspaceIdRaw] = useState(() => {
    return localStorage.getItem('swarm_workspace_id') || null
  })

  const setSelectedWorkspaceId = (id) => {
    setSelectedWorkspaceIdRaw(id)
    if (id) {
      localStorage.setItem('swarm_workspace_id', id)
    } else {
      localStorage.removeItem('swarm_workspace_id')
    }
  }

  return (
    <WorkspaceContext.Provider value={{ selectedWorkspaceId, setSelectedWorkspaceId }}>
      {children}
    </WorkspaceContext.Provider>
  )
}

export function useWorkspaceContext() {
  const ctx = useContext(WorkspaceContext)
  if (!ctx) throw new Error('useWorkspaceContext must be used within WorkspaceProvider')
  return ctx
}
