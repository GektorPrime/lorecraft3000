import { useCallback, useEffect, useRef } from 'react'
import { useBlocker } from 'react-router-dom'

const DISCARD_MESSAGE = 'Discard your unsaved changes?'

export function useUnsavedChanges(isDirty: boolean) {
  const bypassRef = useRef(false)
  const blocker = useBlocker(
    useCallback(
      ({ currentLocation, nextLocation }) =>
        isDirty && !bypassRef.current && currentLocation.key !== nextLocation.key,
      [isDirty],
    ),
  )

  useEffect(() => {
    if (blocker.state !== 'blocked') return
    if (window.confirm(DISCARD_MESSAGE)) blocker.proceed()
    else blocker.reset()
  }, [blocker])

  useEffect(() => {
    if (!isDirty) return

    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      if (bypassRef.current) return
      event.preventDefault()
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', handleBeforeUnload)
    return () => window.removeEventListener('beforeunload', handleBeforeUnload)
  }, [isDirty])

  return useCallback(() => {
    bypassRef.current = true
  }, [])
}
