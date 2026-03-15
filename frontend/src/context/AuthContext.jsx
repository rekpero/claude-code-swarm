import { createContext, useContext, useState, useEffect, useCallback } from 'react'
import { TOKEN_KEY, login as apiLogin, logout as apiLogout, checkAuth } from '../api/client'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [token, setToken] = useState(() => localStorage.getItem(TOKEN_KEY))
  const [isChecking, setIsChecking] = useState(() => !!localStorage.getItem(TOKEN_KEY))

  // On mount: verify existing token against server
  useEffect(() => {
    if (!token) {
      setIsChecking(false)
      return
    }
    checkAuth()
      .then(() => setIsChecking(false))
      .catch(() => setIsChecking(false)) // 401 fires swarm:unauthorized below
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // Listen for 401 responses from apiFetch
  useEffect(() => {
    const handler = () => setToken(null)
    window.addEventListener('swarm:unauthorized', handler)
    return () => window.removeEventListener('swarm:unauthorized', handler)
  }, [])

  const login = useCallback(async (username, password) => {
    const data = await apiLogin(username, password)
    localStorage.setItem(TOKEN_KEY, data.token)
    setToken(data.token)
    return data
  }, [])

  const logout = useCallback(async () => {
    try { await apiLogout() } catch {}
    localStorage.removeItem(TOKEN_KEY)
    setToken(null)
  }, [])

  return (
    <AuthContext.Provider value={{ token, isAuthenticated: !!token, isChecking, login, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
