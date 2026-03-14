import { useState, useRef, useCallback, useEffect } from 'react'
import {
  listPlanningSessions,
  getPlanningSession,
  getPlanningEvents,
  startPlanning,
  refinePlan,
  createIssueFromPlan,
  cancelPlanning,
  deletePlanningSession,
} from '../api/client'

export function usePlanning(workspaceId) {
  const [sessions, setSessions] = useState([])
  const [sessionId, setSessionId] = useState(null)
  const [messages, setMessages] = useState([])
  const [generating, setGenerating] = useState(false)
  const [streamEvents, setStreamEvents] = useState([])
  // Map of message index -> issue result (so each plan can have its own)
  const [issueResults, setIssueResults] = useState({})
  const [creatingIssue, setCreatingIssue] = useState(null) // message index or null
  const [sessionStatus, setSessionStatus] = useState(null)
  const [loadingSession, setLoadingSession] = useState(false)

  const lastEventIdRef = useRef(0)
  const pollTimerRef = useRef(null)
  const sessionIdRef = useRef(null)
  const pollErrorCountRef = useRef(0)

  useEffect(() => {
    sessionIdRef.current = sessionId
  }, [sessionId])

  useEffect(() => {
    return () => {
      if (pollTimerRef.current) clearTimeout(pollTimerRef.current)
    }
  }, [])

  // Reset all state and reload sessions when workspace changes
  useEffect(() => {
    if (pollTimerRef.current) {
      clearTimeout(pollTimerRef.current)
      pollTimerRef.current = null
    }
    setSessionId(null)
    setMessages([])
    setStreamEvents([])
    setGenerating(false)
    setIssueResults({})
    setCreatingIssue(null)
    setSessionStatus(null)
    lastEventIdRef.current = 0
    sessionIdRef.current = null

    if (workspaceId) {
      listPlanningSessions(workspaceId)
        .then(data => setSessions(data.sessions || []))
        .catch(() => setSessions([]))
    } else {
      setSessions([])
    }
  }, [workspaceId])

  const loadSessions = useCallback(async () => {
    if (!workspaceId) return
    try {
      const data = await listPlanningSessions(workspaceId)
      setSessions(data.sessions || [])
    } catch { /* ignore */ }
  }, [workspaceId])

  const stopPolling = useCallback(() => {
    if (pollTimerRef.current) {
      clearTimeout(pollTimerRef.current)
      pollTimerRef.current = null
    }
  }, [])

  const poll = useCallback(() => {
    const sid = sessionIdRef.current
    if (!sid) return
    stopPolling()

    pollTimerRef.current = setTimeout(async () => {
      const localSid = sessionIdRef.current
      if (localSid !== sid) return

      try {
        const [data, evData] = await Promise.all([
          getPlanningSession(localSid),
          getPlanningEvents(localSid, lastEventIdRef.current),
        ])
        if (sessionIdRef.current !== localSid) return
        if (!data) { poll(); return }

        if (evData?.events?.length) {
          setStreamEvents(prev => [...prev, ...evData.events])
          lastEventIdRef.current = evData.events[evData.events.length - 1].id
        }

        setMessages(data.messages || [])
        setSessionStatus(data.session?.status || null)

        if (data.session?.status === 'completed' && data.session.issue_url) {
          // Find the last assistant message index to mark it
          const msgs = data.messages || []
          for (let i = msgs.length - 1; i >= 0; i--) {
            if (msgs[i].role === 'assistant') {
              setIssueResults(prev => ({ ...prev, [i]: { url: data.session.issue_url } }))
              break
            }
          }
        }

        pollErrorCountRef.current = 0
        if (data.generating || data.session?.status === 'generating') {
          poll()
        } else {
          setGenerating(false)
        }
      } catch {
        pollErrorCountRef.current += 1
        const MAX_POLL_ERRORS = 5
        if (pollErrorCountRef.current <= MAX_POLL_ERRORS) {
          // Exponential backoff: 600ms, 1.2s, 2.4s, 4.8s, 9.6s
          const backoff = Math.min(300 * Math.pow(2, pollErrorCountRef.current), 30000)
          pollTimerRef.current = setTimeout(() => poll(), backoff)
        }
        // else: stop retrying after MAX_POLL_ERRORS consecutive failures
      }
    }, 300)
  }, [stopPolling])

  const startNew = useCallback(() => {
    stopPolling()
    setSessionId(null)
    setMessages([])
    setStreamEvents([])
    setGenerating(false)
    setIssueResults({})
    setCreatingIssue(null)
    setSessionStatus(null)
    lastEventIdRef.current = 0
  }, [stopPolling])

  const resumeSession = useCallback(async (sid) => {
    stopPolling()
    setStreamEvents([])
    setMessages([])
    setSessionId(sid)
    sessionIdRef.current = sid
    setIssueResults({})
    setCreatingIssue(null)
    lastEventIdRef.current = 0
    setLoadingSession(true)

    try {
      const [data, evData] = await Promise.all([
        getPlanningSession(sid),
        getPlanningEvents(sid, 0),
      ])
      if (!data || data.error) return

      setMessages(data.messages || [])
      setSessionStatus(data.session?.status || null)

      // Restore all events so the analysis steps accordion is visible
      if (evData?.events?.length) {
        setStreamEvents(evData.events)
        lastEventIdRef.current = evData.events[evData.events.length - 1].id
      }

      if (data.session?.status === 'completed' && data.session.issue_url) {
        // Mark the last assistant message as having an issue
        const msgs = data.messages || []
        for (let i = msgs.length - 1; i >= 0; i--) {
          if (msgs[i].role === 'assistant') {
            setIssueResults({ [i]: { url: data.session.issue_url } })
            break
          }
        }
      }

      if (data.generating || data.session?.status === 'generating') {
        setGenerating(true)
        poll()
      } else {
        setGenerating(false)
      }
    } catch { /* ignore */ } finally {
      setLoadingSession(false)
    }
  }, [stopPolling, poll])

  const sendMessage = useCallback(async (msg) => {
    if (!msg.trim()) return
    if (!workspaceId) return

    setStreamEvents([])
    setGenerating(true)

    try {
      let data
      if (!sessionIdRef.current) {
        data = await startPlanning(workspaceId, msg)
        if (data.error) { setGenerating(false); return }
        setSessionId(data.session.id)
        sessionIdRef.current = data.session.id
        loadSessions()
      } else {
        data = await refinePlan(sessionIdRef.current, msg)
        if (data.error) { setGenerating(false); return }
      }

      setMessages(data.messages || [])
      poll()
    } catch {
      setGenerating(false)
    }
  }, [workspaceId, poll, loadSessions])

  const cancelGeneration = useCallback(async () => {
    const sid = sessionIdRef.current
    if (!sid) return
    stopPolling()
    try {
      await cancelPlanning(sid)
      setStreamEvents([])
      setGenerating(false)
    } catch {
      setGenerating(true)
      poll()
    }
  }, [stopPolling, poll])

  const deleteSession = useCallback(async (sid) => {
    try {
      await deletePlanningSession(sid)
      if (sessionIdRef.current === sid) {
        startNew()
      }
      loadSessions()
    } catch { /* ignore */ }
  }, [startNew, loadSessions])

  const createIssue = useCallback(async (messageIndex, title = '') => {
    const sid = sessionIdRef.current
    if (!sid) return

    setCreatingIssue(messageIndex)

    // Poll for events during issue creation.
    // Guard against session switches: if the user switches to another session
    // while the issue is being created, stop fetching events for the old session.
    const eventPollInterval = setInterval(async () => {
      if (sessionIdRef.current !== sid) {
        clearInterval(eventPollInterval)
        return
      }
      try {
        const evData = await getPlanningEvents(sid, lastEventIdRef.current)
        if (sessionIdRef.current !== sid) return
        if (evData?.events?.length) {
          lastEventIdRef.current = evData.events[evData.events.length - 1].id
          setStreamEvents(prev => [...prev, ...evData.events])
        }
      } catch { /* ignore */ }
    }, 800)

    try {
      const data = await createIssueFromPlan(sid, title, messageIndex)
      if (data.error) {
        setCreatingIssue(null)
        return { error: data.error }
      }

      setIssueResults(prev => ({
        ...prev,
        [messageIndex]: {
          url: data.issue_url,
          title: data.title,
          number: data.issue_number,
        },
      }))
      setCreatingIssue(null)
      loadSessions()
      return data
    } catch (e) {
      setCreatingIssue(null)
      return { error: e.message }
    } finally {
      clearInterval(eventPollInterval)
    }
  }, [loadSessions])

  const hasPlan = messages.some(m => m.role === 'assistant')

  return {
    sessions,
    sessionId,
    messages,
    generating,
    streamEvents,
    issueResults,
    creatingIssue,
    sessionStatus,
    loadingSession,
    hasPlan,
    loadSessions,
    startNew,
    resumeSession,
    sendMessage,
    cancelGeneration,
    deleteSession,
    createIssue,
  }
}
