import { useState, useEffect, useRef } from 'react'
import { Plus, Trash2, Upload, Save, RefreshCw } from 'lucide-react'
import { Button } from '../ui/Button'
import { Spinner } from '../ui/Spinner'
import { getEnvFiles, getEnv, saveEnv, deleteEnvFile, loadEnvFromDisk } from '../../api/client'

function parseEnvText(text) {
  const vars = {}
  const lines = text.split('\n')
  let i = 0
  while (i < lines.length) {
    const trimmed = lines[i++].trim()
    if (!trimmed || trimmed.startsWith('#')) continue
    const idx = trimmed.indexOf('=')
    if (idx < 0) continue
    const key = trimmed.slice(0, idx).trim()
    if (!key) continue
    let raw = trimmed.slice(idx + 1).trim()
    // Accumulate continuation lines for multi-line quoted values.
    // Count unescaped occurrences of the quote char — we need at least
    // two (opening + closing) before the value is complete.
    if (raw.startsWith('"') || raw.startsWith("'")) {
      const q = raw[0]
      const countUnescaped = (s) => {
        let count = 0
        for (let j = 0; j < s.length; j++) {
          if (s[j] === '\\') { j++; continue }
          if (s[j] === q) count++
        }
        return count
      }
      while (countUnescaped(raw) < 2 && i < lines.length) {
        raw += '\n' + lines[i++]
      }
    }
    const quoteMatch = raw.match(/^(['"])([\s\S]*)\1$/)
    const val = quoteMatch
      ? quoteMatch[2].replace(new RegExp(`\\\\${quoteMatch[1]}`, 'g'), quoteMatch[1])
      : raw
    vars[key] = val
  }
  return vars
}

export function EnvEditor({ workspaceId }) {
  const [envFiles, setEnvFiles] = useState([])
  const [activeFile, setActiveFile] = useState('.env')
  const [fetchCounter, setFetchCounter] = useState(0)
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState(null)
  const [fileReadError, setFileReadError] = useState(null)
  const [pasteText, setPasteText] = useState('')
  const [showPaste, setShowPaste] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [dirty, setDirty] = useState(false)
  // Keep a ref in sync so the load effect can read the current dirty value
  // without including it in the dependency array (dirty is a guard, not a trigger).
  const dirtyRef = useRef(false)
  dirtyRef.current = dirty
  // Stores the vars from the last successful save so that a Discard action can
  // revert to the confirmed server state even if the post-save re-fetch was
  // suppressed by the dirty guard (user typed before the re-fetch fired).
  const lastSavedRef = useRef(null)

  useEffect(() => {
    setActiveFile('.env')
    setDirty(false)
  }, [workspaceId])

  useEffect(() => {
    if (!workspaceId) return
    getEnvFiles(workspaceId).then((data) => {
      const managed = data.managed || []
      // discovered can be strings or objects with {path, exists}
      const discovered = (data.discovered || []).map(d => typeof d === 'string' ? d : d.path)
      const files = [...new Set(['.env', ...managed, ...discovered])]
      setEnvFiles(files)
    }).catch(() => setEnvFiles(['.env']))
  }, [workspaceId])

  // Reset dirty flag and last-saved snapshot when switching files
  useEffect(() => {
    lastSavedRef.current = null
    setDirty(false)
  }, [activeFile])

  useEffect(() => {
    if (!workspaceId || !activeFile) return
    // Don't overwrite unsaved edits on cache-bust refetches.
    // Use dirtyRef (not dirty state) so this guard doesn't re-trigger the
    // effect on every keystroke — dirty is a guard condition, not a trigger.
    if (dirtyRef.current && fetchCounter > 0) return
    let cancelled = false
    setLoading(true)
    setFileReadError(null)

    const toRows = (vars) =>
      Object.entries(vars || {}).map(([k, v]) => ({ id: k, key: k, value: v }))

    // First try getEnv (which auto-syncs from disk if file changed).
    // If that returns empty, explicitly load from disk as a fallback.
    getEnv(workspaceId, activeFile)
      .then(async (data) => {
        if (cancelled) return
        const vars = data.vars || {}
        if (Object.keys(vars).length > 0) {
          setRows(toRows(vars))
        } else {
          // Try loading directly from disk
          try {
            const diskData = await loadEnvFromDisk(workspaceId, activeFile)
            if (!cancelled) {
              setRows(toRows(diskData.vars || {}))
            }
          } catch {
            if (!cancelled) setRows([])
          }
        }
      })
      .catch(() => {
        if (!cancelled) setRows([])
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => { cancelled = true }
  }, [workspaceId, activeFile, fetchCounter])

  const setRow = (i, field, val) => {
    setDirty(true)
    setRows((prev) => prev.map((r, idx) => {
      if (idx !== i) return r
      // Keep the row's id in sync with the key name so that after save + reload
      // (where the server rebuilds rows as { id: keyName, key: keyName, value })
      // React's key prop remains stable and avoids unmounting/remounting inputs.
      if (field === 'key') return { ...r, key: val, id: val || r.id }
      return { ...r, [field]: val }
    }))
  }

  const addRow = () => { setDirty(true); setRows((prev) => [...prev, { id: crypto.randomUUID(), key: '', value: '' }]) }
  const removeRow = (i) => { setDirty(true); setRows((prev) => prev.filter((_, idx) => idx !== i)) }

  const handleSave = async () => {
    if (!workspaceId) return

    // Check for duplicate keys before saving
    const keysSeen = new Set()
    const duplicates = new Set()
    for (const { key } of rows) {
      const trimmed = key.trim()
      if (!trimmed) continue
      if (keysSeen.has(trimmed)) {
        duplicates.add(trimmed)
      }
      keysSeen.add(trimmed)
    }
    if (duplicates.size > 0) {
      setSaveError(`Duplicate keys detected: ${[...duplicates].join(', ')}. Remove or rename duplicate rows before saving.`)
      return
    }

    setSaving(true)
    setSaveError(null)
    const vars = {}
    for (const { key, value } of rows) {
      if (key.trim()) vars[key.trim()] = value
    }
    try {
      await saveEnv(workspaceId, activeFile, vars)
      lastSavedRef.current = vars
      setDirty(false)
      setFetchCounter(c => c + 1)
    } catch (err) {
      setSaveError(err?.message || 'Failed to save')
    } finally {
      setSaving(false)
    }
  }

  const handleDiscard = () => {
    if (lastSavedRef.current !== null) {
      const saved = lastSavedRef.current
      setRows(Object.entries(saved).map(([k, v]) => ({ id: k, key: k, value: v })))
      setDirty(false)
    } else {
      setFetchCounter(c => c + 1)
      setDirty(false)
    }
  }

  const handlePaste = () => {
    const parsed = parseEnvText(pasteText)
    const newRows = Object.entries(parsed).map(([k, v]) => ({ id: k, key: k, value: v }))
    setRows((prev) => {
      const emptyKeyRows = prev.filter(r => !r.key.trim())
      const existingMap = new Map(prev.filter(r => r.key.trim()).map((r) => [r.key, r]))
      newRows.forEach((r) => {
        if (existingMap.has(r.key)) {
          existingMap.set(r.key, { ...existingMap.get(r.key), value: r.value })
        } else {
          existingMap.set(r.key, r)
        }
      })
      return [...Array.from(existingMap.values()), ...emptyKeyRows]
    })
    setDirty(true)
    setPasteText('')
    setShowPaste(false)
  }

  const handleFileUpload = (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    const reader = new FileReader()
    reader.onload = (ev) => {
      setFileReadError(null)
      const parsed = parseEnvText(ev.target.result)
      const newRows = Object.entries(parsed).map(([k, v]) => ({ id: k, key: k, value: v }))
      setRows((prev) => {
        const emptyKeyRows = prev.filter(r => !r.key.trim())
        const existingMap = new Map(prev.filter(r => r.key.trim()).map((r) => [r.key, r]))
        newRows.forEach((r) => {
          if (existingMap.has(r.key)) {
            existingMap.set(r.key, { ...existingMap.get(r.key), value: r.value })
          } else {
            existingMap.set(r.key, r)
          }
        })
        return [...Array.from(existingMap.values()), ...emptyKeyRows]
      })
      setDirty(true)
    }
    reader.onerror = () => {
      setFileReadError('Failed to read file')
    }
    reader.readAsText(file)
    e.target.value = ''
  }

  const handleSyncFromDisk = async () => {
    if (!workspaceId || !activeFile) return
    setSyncing(true)
    try {
      const data = await loadEnvFromDisk(workspaceId, activeFile)
      const entries = Object.entries(data.vars || {}).map(([k, v]) => ({ id: k, key: k, value: v }))
      setRows(entries)
      setDirty(false)
    } catch (err) {
      setFileReadError(err?.message || 'Failed to sync from disk')
    } finally {
      setSyncing(false)
    }
  }

  const inputClass = 'px-2.5 py-1.5 text-[10px] bg-[var(--bg)] border border-[var(--border)] rounded text-[var(--text)] font-mono focus:border-[var(--accent)] outline-none transition-colors'

  if (loading) {
    return <div className="flex justify-center py-6"><Spinner /></div>
  }

  return (
    <div className="mt-1">
      <div className="flex gap-1 flex-wrap mb-4">
        {envFiles.map((f) => (
          <button
            key={f}
            onClick={() => setActiveFile(f)}
            className={`relative px-2.5 py-1 text-[10px] rounded-md border font-mono transition-all ${
              activeFile === f
                ? 'border-[var(--accent-border)] text-[var(--accent)] bg-[var(--accent-dim)]'
                : 'border-[var(--border)] text-[var(--text-muted)] hover:border-[var(--text-muted)] hover:text-[var(--text-dim)]'
            }`}
          >
            {f}
          </button>
        ))}
      </div>

      <div className="flex flex-col gap-1.5 mb-4">
        {(() => {
          const keyCounts = {}
          for (const row of rows) {
            const trimmed = row.key.trim()
            if (trimmed) keyCounts[trimmed] = (keyCounts[trimmed] || 0) + 1
          }
          return rows.map((row, i) => {
            const isDuplicate = row.key.trim() && keyCounts[row.key.trim()] > 1
            return (
              <div key={row.id} className="flex gap-2 items-center">
                <input
                  value={row.key}
                  onChange={(e) => setRow(i, 'key', e.target.value)}
                  placeholder="KEY"
                  title={isDuplicate ? `Duplicate key: "${row.key.trim()}"` : undefined}
                  className={`flex-1 ${inputClass} ${isDuplicate ? 'border-[var(--red)]' : ''}`}
                />
                <input value={row.value} onChange={(e) => setRow(i, 'value', e.target.value)} placeholder="value" className={`flex-[2] ${inputClass}`} />
                <button onClick={() => removeRow(i)} className="p-1 text-[var(--text-muted)] hover:text-[var(--red)] transition-colors">
                  <Trash2 size={11} />
                </button>
              </div>
            )
          })
        })()}
      </div>

      {showPaste && (
        <div className="mb-4">
          <textarea
            value={pasteText}
            onChange={(e) => setPasteText(e.target.value)}
            placeholder="Paste .env content here..."
            className={`w-full h-24 resize-none ${inputClass}`}
          />
          <div className="flex gap-2 mt-1.5">
            <Button size="sm" variant="primary" onClick={handlePaste}>Import</Button>
            <Button size="sm" variant="ghost" onClick={() => setShowPaste(false)}>Cancel</Button>
          </div>
        </div>
      )}

      {fileReadError && <p className="text-[10px] text-[var(--red)] mb-2">{fileReadError}</p>}
      {saveError && <p className="text-[10px] text-[var(--red)] mb-2">{saveError}</p>}

      <div className="flex items-center gap-2 flex-wrap">
        <Button size="sm" variant="ghost" onClick={addRow}>
          <Plus size={10} /> Add row
        </Button>
        <Button size="sm" variant="ghost" onClick={() => setShowPaste((v) => !v)}>
          Paste .env
        </Button>
        <label className="cursor-pointer">
          <Button size="sm" variant="ghost" as="span">
            <Upload size={10} /> Upload
          </Button>
          <input type="file" className="hidden" accept=".env,text/*" onChange={handleFileUpload} />
        </label>
        <Button size="sm" variant="ghost" loading={syncing} onClick={handleSyncFromDisk} title="Re-read from disk">
          <RefreshCw size={10} /> Sync from disk
        </Button>
        <div className="ml-auto flex gap-2">
          {dirty && (
            <Button size="sm" variant="ghost" onClick={handleDiscard}>
              Discard
            </Button>
          )}
          <Button size="sm" variant="primary" loading={saving} onClick={handleSave}>
            <Save size={10} /> Save
          </Button>
        </div>
      </div>
    </div>
  )
}
