import { useEffect, useRef, useState } from 'react'

interface CopyButtonProps {
  value: string
  label: string
  copiedLabel?: string
}

/** Copies `value` to the clipboard and briefly shows feedback. Falls back to
 * legacy textarea selection when navigator.clipboard is unavailable. */
export function CopyButton({ value, label, copiedLabel = 'Copied!' }: CopyButtonProps) {
  const [copied, setCopied] = useState(false)
  const timer = useRef<number | undefined>(undefined)

  useEffect(() => {
    return () => {
      if (timer.current !== undefined) window.clearTimeout(timer.current)
    }
  }, [])

  const handleCopy = async () => {
    if (!value) return
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(value)
      } else {
        const textarea = document.createElement('textarea')
        textarea.value = value
        textarea.style.position = 'fixed'
        textarea.style.opacity = '0'
        document.body.appendChild(textarea)
        textarea.select()
        document.execCommand('copy')
        document.body.removeChild(textarea)
      }
      setCopied(true)
      if (timer.current !== undefined) window.clearTimeout(timer.current)
      timer.current = window.setTimeout(() => setCopied(false), 1500)
    } catch {
      // Ignore clipboard failures; the prompt remains selectable in its block.
    }
  }

  return (
    <button type="button" className="btn" disabled={!value} onClick={() => void handleCopy()}>
      {copied ? copiedLabel : label}
    </button>
  )
}
