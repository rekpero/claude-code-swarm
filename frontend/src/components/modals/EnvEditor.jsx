import { useState, useEffect } from 'react'
import { Plus, Trash2, Upload, Save } from 'lucide-react'
import { Button } from '../ui/Button'
import { Spinner } from '../ui/Spinner'
import { getEnvFiles, getEnv, saveEnv, deleteEnvFile, loadEnvFromDisk } from '../../api/client'

function parseEnvText(text) {
  const vars = {}
  for (const line of text.split('\n')) {
    const trimmed = line.trim()
    if (!trimmed || trimmed.startsWith('#')) continue
    const idx = trimmed.indexOf('=')
    if (idx < 0) continue
    const key = trimmed.slice(0, idx).trim()
    const raw = trimmed.slice(idx + 1).trim()
    const val = raw.replace(/^(['"])(.*)\1$/, '$2')
    if (key) vars[key] = val
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
  const [pasteText, setPasteText] = useState('')
  const [showPaste, setShowPaste] = useState(false)

  useEffect(() => {
    if (!workspaceId) return
    getEnvFiles(workspaceId).then((data) => {
      const files = [...new Set(['.env', ...(data.managed || []), ...(data.discovered || [])])]
      setEnvFiles(files)
    }).catch(() => setEnvFiles(['.env']))
  }, [workspaceId])

  useEffect(() => {
    if (!workspaceId || !activeFile) return
    let cancelled = false
    setLoading(true)
    getEnv(workspaceId, activeFile).then((data) => {
      if (!cancelled) {
        const entries = Object.entries(data.vars || {}).map(([k, v]) => ({ id: crypto.randomUUID(), key: k, value: v }))
        setRows(entries)
      }
    }).catch(() => {
      if (!cancelled) setRows([])
    }).finally(() => {
      if (!cancelled) setLoading(false)
    })
    return () => { cancelled = true }
  }, [workspaceId, activeFile, fetchCounter])

  const setRow = (i, field, val) => {
    setRows((prev) => prev.map((r, idx) => idx === i ? { ...r, [field]: val } : r))
  }

  const addRow = () => setRows((prev) => [...prev, { id: crypto.randomUUID(), key: '', value: '' }])

  const removeRow = (i) => setRows((prev) => prev.filter((_, idx) => idx !== i))

  const handleSave = async () => {
    if (!workspaceId) return
    setSaving(true)
    setSaveError(null)
    const vars = {}
    for (const { key, value } of rows) {
      if (key.trim()) vars[key.trim()] = value
    }
    try {
      await saveEnv(workspaceId, activeFile, vars)
      setFetchCounter((c) => c + 1)
    } catch (err) {
      setSaveError(err?.message || 'Failed to save')
    } finally {
      setSaving(false)
    }
  }

  const handlePaste = () => {
    const parsed = parseEnvText(pasteText)
    const newRows = Object.entries(parsed).map(([k, v]) => ({ id: crypto.randomUUID(), key: k, value: v }))
    setRows((prev) => {
      const existing = new Set(prev.map((r) => r.key))
      return [...prev, ...newRows.filter((r) => !existing.has(r.key))]
    })
    setPasteText('')
    setShowPaste(false)
  }

  const handleFileUpload = (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    const reader = new FileReader()
    reader.onload = (ev) => {
      const parsed = parseEnvText(ev.target.result)
      const newRows = Object.entries(parsed).map(([k, v]) => ({ id: crypto.randomUUID(), key: k, value: v }))
      setRows((prev) => {
        const existing = new Set(prev.map((r) => r.key))
        return [...prev, ...newRows.filter((r) => !existing.has(r.key))]
      })
    }
    reader.readAsText(file)
    e.target.value = ''
  }

  if (loading) {
    return <div className="flex justify-center py-4"><Spinner /></div>
  }

  return (
    <div className="mt-2">
      {/* File tabs */}
      <div className="flex gap-1 flex-wrap mb-3">
        {envFiles.map((f) => (
          <button
            key={f}
            onClick={() => setActiveFile(f)}
            className={`px-2.5 py-1 text-[11px] rounded border transition-colors ${
              activeFile === f
                ? 'border-[var(--accent)] text-[var(--accent)]'
                : 'border-[var(--border)] text-[var(--text-dim)] hover:border-[var(--text-dim)]'
            }`}
          >
            {f}
          </button>
        ))}
      </div>

      {/* Rows */}
      <div className="flex flex-col gap-1.5 mb-3">
        {rows.map((row, i) => (
          <div key={row.id} className="flex gap-2 items-center">
            <input
              value={row.key}
              onChange={(e) => setRow(i, 'key', e.target.value)}
              placeholder="KEY"
              className="flex-1 px-2 py-1.5 text-[11px] bg-[var(--bg)] border border-[var(--border)] rounded text-[var(--text)] font-mono focus:border-[var(--accent)] outline-none"
            />
            <input
              value={row.value}
              onChange={(e) => setRow(i, 'value', e.target.value)}
              placeholder="value"
              className="flex-[2] px-2 py-1.5 text-[11px] bg-[var(--bg)] border border-[var(--border)] rounded text-[var(--text)] font-mono focus:border-[var(--accent)] outline-none"
            />
            <button
              onClick={() => removeRow(i)}
              className="p-1 text-[var(--text-dim)] hover:text-[var(--red)] transition-colors"
            >
              <Trash2 size={13} />
            </button>
          </div>
        ))}
      </div>

      {showPaste && (
        <div className="mb-3">
          <textarea
            value={pasteText}
            onChange={(e) => setPasteText(e.target.value)}
            placeholder="Paste .env content here..."
            className="w-full h-24 px-2 py-1.5 text-[11px] bg-[var(--bg)] border border-[var(--border)] rounded text-[var(--text)] font-mono focus:border-[var(--accent)] outline-none resize-none"
          />
          <div className="flex gap-2 mt-1">
            <Button size="sm" variant="primary" onClick={handlePaste}>Import</Button>
            <Button size="sm" variant="ghost" onClick={() => setShowPaste(false)}>Cancel</Button>
          </div>
        </div>
      )}

      {saveError && (
        <p className="text-[11px] text-[var(--red)] mb-2">{saveError}</p>
      )}
      <div className="flex items-center gap-2 flex-wrap">
        <Button size="sm" variant="ghost" onClick={addRow}>
          <Plus size={11} /> Add row
        </Button>
        <Button size="sm" variant="ghost" onClick={() => setShowPaste((v) => !v)}>
          Paste .env
        </Button>
        <label className="cursor-pointer">
          <Button size="sm" variant="ghost" as="span">
            <Upload size={11} /> Upload file
          </Button>
          <input type="file" className="hidden" accept=".env,text/*" onChange={handleFileUpload} />
        </label>
        <div className="ml-auto">
          <Button size="sm" variant="primary" loading={saving} onClick={handleSave}>
            <Save size={11} /> Save
          </Button>
        </div>
      </div>
    </div>
  )
}
