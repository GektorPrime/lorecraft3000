import { useState } from 'react'

interface ProminenceInputProps {
  value: number
  onChange: (value: number) => void
  id?: string
  className?: string
  disabled?: boolean
  'aria-label'?: string
  'aria-describedby'?: string
}

export function ProminenceInput({ value, onChange, ...inputProps }: ProminenceInputProps) {
  const [draft, setDraft] = useState<string | null>(null)

  const commitIfValid = (next: string) => {
    const parsed = Number(next)
    if (next !== '' && Number.isInteger(parsed) && parsed >= 1) onChange(parsed)
  }

  return (
    <input
      {...inputProps}
      type="number"
      min={1}
      step={1}
      value={draft ?? String(value)}
      onChange={(event) => {
        setDraft(event.target.value)
        commitIfValid(event.target.value)
      }}
      onBlur={() => {
        commitIfValid(draft ?? String(value))
        setDraft(null)
      }}
    />
  )
}
