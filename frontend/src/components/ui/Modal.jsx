import { useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'
import { X } from 'lucide-react'

export function Modal({ open, onClose, title, children, maxWidth = '480px' }) {
  const overlayRef = useRef(null)

  useEffect(() => {
    if (!open) return
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = prev
    }
  }, [open])

  useEffect(() => {
    if (!open) return
    const handler = (e) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [open, onClose])

  if (!open) return null

  return createPortal(
    <div
      ref={overlayRef}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm animate-fade-in"
      onClick={(e) => {
        if (e.target === overlayRef.current) onClose()
      }}
    >
      <div
        className="relative rounded-xl border border-[var(--border)] bg-[var(--surface)] p-6 shadow-[0_24px_80px_rgba(0,0,0,0.6),0_0_40px_var(--accent-glow)] overflow-y-auto animate-fade-in"
        style={{ width: '100%', maxWidth, maxHeight: '85vh' }}
      >
        <div className="flex items-center justify-between mb-5">
          <h3 className="text-sm font-semibold tracking-tight">{title}</h3>
          <button
            onClick={onClose}
            className="p-1 rounded-md text-[var(--text-muted)] hover:text-[var(--text-dim)] hover:bg-[var(--surface-hover)] transition-colors"
          >
            <X size={14} />
          </button>
        </div>
        {children}
      </div>
    </div>,
    document.body
  )
}
