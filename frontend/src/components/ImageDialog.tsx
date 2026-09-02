import { useEffect, useRef, useState } from 'react'
import { Icon } from './Icon'
import { ImageWithFallback } from './ImageWithFallback'

interface ImageDialogProps {
  src: string
  previewSrc?: string
  thumbnailAlt: string
  previewAlt: string
  triggerLabel: string
  dialogLabel: string
  onPrevious?: () => void
  onNext?: () => void
  onOpenChange?: (open: boolean) => void
}

export function ImageDialog({
  src,
  previewSrc = src,
  thumbnailAlt,
  previewAlt,
  triggerLabel,
  dialogLabel,
  onPrevious,
  onNext,
  onOpenChange,
}: ImageDialogProps) {
  const [open, setOpen] = useState(false)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const dialogRef = useRef<HTMLDialogElement>(null)
  const closeRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    const dialog = dialogRef.current
    if (!dialog) return

    if (open && !dialog.open) {
      dialog.showModal()
      closeRef.current?.focus()
    } else if (!open && dialog.open) {
      dialog.close()
    }
  }, [open])

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        className="image-dialog__trigger"
        aria-label={triggerLabel}
        onClick={() => {
          onOpenChange?.(true)
          setOpen(true)
        }}
      >
        <ImageWithFallback
          className="image-dialog__trigger-image"
          src={src}
          alt={thumbnailAlt}
        />
      </button>
      <dialog
        ref={dialogRef}
        className="image-dialog"
        aria-label={dialogLabel}
        aria-modal="true"
        onKeyDown={(event) => {
          if (event.key === 'ArrowLeft' && onPrevious) {
            event.preventDefault()
            onPrevious()
          } else if (event.key === 'ArrowRight' && onNext) {
            event.preventDefault()
            onNext()
          }
        }}
        onCancel={(event) => {
          event.preventDefault()
          setOpen(false)
        }}
        onClose={() => {
          setOpen(false)
          onOpenChange?.(false)
          triggerRef.current?.focus()
        }}
        onClick={(event) => {
          if (event.target === event.currentTarget) setOpen(false)
        }}
      >
        <div className="image-dialog__content">
          <button
            ref={closeRef}
            type="button"
            className="image-dialog__close"
            aria-label="Close preview"
            onClick={() => setOpen(false)}
          >
            {/* Decorative: the button already carries the accessible name. */}
            <Icon name="close" size={20} />
          </button>
          <ImageWithFallback className="image-dialog__image" src={previewSrc} alt={previewAlt} />
        </div>
      </dialog>
    </>
  )
}
