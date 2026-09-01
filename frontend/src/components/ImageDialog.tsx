import { useEffect, useRef, useState } from 'react'
import { ImageWithFallback } from './ImageWithFallback'

interface ImageDialogProps {
  src: string
  thumbnailAlt: string
  previewAlt: string
  triggerLabel: string
  dialogLabel: string
}

export function ImageDialog({
  src,
  thumbnailAlt,
  previewAlt,
  triggerLabel,
  dialogLabel,
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
        onClick={() => setOpen(true)}
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
        onCancel={(event) => {
          event.preventDefault()
          setOpen(false)
        }}
        onClose={() => {
          setOpen(false)
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
            &times;
          </button>
          <ImageWithFallback className="image-dialog__image" src={src} alt={previewAlt} />
        </div>
      </dialog>
    </>
  )
}
