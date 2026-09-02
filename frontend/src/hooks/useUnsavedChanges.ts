import { useCallback, useEffect, useRef } from 'react'
import { useBlocker } from 'react-router-dom'
import type { ConfirmDialogProps } from '../components/ConfirmDialog'

const DISCARD_TITLE = 'Discard unsaved changes?'
const DISCARD_DESCRIPTION = 'Your changes have not been saved. This action cannot be undone.'

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
    if (!isDirty) return

    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      if (bypassRef.current) return
      event.preventDefault()
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', handleBeforeUnload)
    return () => window.removeEventListener('beforeunload', handleBeforeUnload)
  }, [isDirty])

  const allowNavigation = useCallback(() => {
    bypassRef.current = true
  }, [])

  const confirmationProps: ConfirmDialogProps = {
    open: blocker.state === 'blocked',
    title: DISCARD_TITLE,
    description: DISCARD_DESCRIPTION,
    confirmLabel: 'Discard changes',
    cancelLabel: 'Keep editing',
    onConfirm: () => {
      if (blocker.state === 'blocked') blocker.proceed()
    },
    onCancel: () => {
      if (blocker.state === 'blocked') blocker.reset()
    },
  }

  return { allowNavigation, confirmationProps }
}
