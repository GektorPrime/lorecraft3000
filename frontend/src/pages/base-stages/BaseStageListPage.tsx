import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  ApiError,
  archiveBaseStage,
  listArchivedBaseStages,
  listBaseStages,
  restoreBaseStage,
} from '../../api/client'
import type { BaseStage } from '../../api/types'
import { AsyncMessage } from '../../components/AsyncMessage'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { EmptyState } from '../../components/EmptyState'
import { Icon } from '../../components/Icon'
import { ImageDialog } from '../../components/ImageDialog'
import { PageHeader } from '../../components/PageHeader'

function errorMessage(error: unknown) {
  return error instanceof ApiError ? error.message : String(error)
}

function BaseStageCard({ stage, archived, busy, onArchive, onRestore }: {
  stage: BaseStage
  archived?: boolean
  busy: boolean
  onArchive?: () => void
  onRestore?: () => void
}) {
  return (
    <article className={`resource-card base-stage-card${archived ? ' resource-card--archived' : ''}`}>
      {stage.content_url && (
        <div className="base-stage-card__preview">
          <ImageDialog
            src={stage.content_url}
            thumbnailAlt=""
            previewAlt={`Base stage #${stage.id}: ${stage.description}`}
            triggerLabel={`Preview base stage #${stage.id}`}
            dialogLabel={`Base stage #${stage.id} preview`}
          />
        </div>
      )}
      <div className="resource-card__body">
        <div className="resource-card__header">
          <h2 className="resource-card__title">
            {stage.is_editable
              ? <Link to={`/base-stages/${stage.id}/preview`}>Base stage #{stage.id}</Link>
              : `Base stage #${stage.id}`}
          </h2>
          <span className="base-stage-card__badges">
            <span className="badge badge--draft">{stage.origin === 'upload' ? 'Upload' : stage.origin}</span>
            <span className="badge badge--canonical">{stage.state === 'ready' ? 'Ready' : stage.state}</span>
          </span>
        </div>
        <p className="resource-card__summary text-clamp" title={stage.description}>{stage.description}</p>
        <p className="resource-card__meta">
          <span>{stage.dimensions ? `${stage.dimensions.width} × ${stage.dimensions.height}` : 'Dimensions unavailable'}</span>
          <span>{stage.aspect_ratio}</span>
          <span>{stage.targets.length} target{stage.targets.length === 1 ? '' : 's'}</span>
          <span>Used {stage.usage_count} time{stage.usage_count === 1 ? '' : 's'}</span>
        </p>
      </div>
      <div className="resource-card__actions">
        {archived ? (
          <button type="button" className="btn" disabled={busy} onClick={onRestore}>
            {busy ? 'Restoring…' : 'Restore'}
          </button>
        ) : (
          <button type="button" className="btn btn--danger" disabled={busy} onClick={onArchive}>
            <Icon name="trash" size={15} />
            {busy ? 'Deleting…' : 'Delete'}
          </button>
        )}
      </div>
    </article>
  )
}

export function BaseStageListPage() {
  const [stages, setStages] = useState<BaseStage[] | null>(null)
  const [archived, setArchived] = useState<BaseStage[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<number | null>(null)
  const [confirmId, setConfirmId] = useState<number | null>(null)
  const [showArchived, setShowArchived] = useState(false)
  const mounted = useRef(true)

  const reload = () => Promise.all([listBaseStages(), listArchivedBaseStages()])
    .then(([active, inactive]) => {
      if (!mounted.current) return
      setStages(active)
      setArchived(inactive)
      setError(null)
    })
    .catch((err) => {
      if (mounted.current) setError(errorMessage(err))
    })

  useEffect(() => {
    mounted.current = true
    void reload()
    return () => { mounted.current = false }
  }, [])

  const confirmArchive = async () => {
    const id = confirmId
    setConfirmId(null)
    if (id === null || busyId !== null) return
    setBusyId(id)
    setError(null)
    try {
      await archiveBaseStage(id)
      await reload()
    } catch (err) {
      if (mounted.current) setError(`Could not archive base stage: ${errorMessage(err)}`)
    } finally {
      if (mounted.current) setBusyId(null)
    }
  }

  const handleRestore = async (id: number) => {
    if (busyId !== null) return
    setBusyId(id)
    setError(null)
    try {
      await restoreBaseStage(id)
      await reload()
    } catch (err) {
      if (mounted.current) setError(`Could not restore base stage: ${errorMessage(err)}`)
    } finally {
      if (mounted.current) setBusyId(null)
    }
  }

  return (
    <section aria-busy={busyId !== null || undefined}>
      <PageHeader
        title="Base Stages"
        description="Reusable scene images that can anchor future panel compositions."
        actions={<Link to="/base-stages/upload" className="btn">Upload base stage<Icon name="plus" size={16} /></Link>}
      />
      <p>
        <Link to="/base-stages/new" className="btn btn--primary"><Icon name="sparkles" size={16} />Create generated base stage</Link>
      </p>
      {error && <AsyncMessage kind="error">{error}</AsyncMessage>}
      {!stages && !error && <AsyncMessage kind="loading">Loading base stages…</AsyncMessage>}
      {stages?.length === 0 && (
        <EmptyState
          icon="baseStages"
          title="No base stages yet"
          description="Upload a scene image or create a generated composition to start your reusable stage library."
          action={<Link to="/base-stages/new" className="btn btn--primary"><Icon name="sparkles" size={16} />Create generated base stage</Link>}
        />
      )}
      {stages && stages.length > 0 && (
        <div className="resource-list">
          {stages.map((stage) => <BaseStageCard key={stage.id} stage={stage} busy={busyId === stage.id} onArchive={() => setConfirmId(stage.id)} />)}
        </div>
      )}
      {archived.length > 0 && (
        <div className="archived-section">
          <button type="button" className="btn archived-section__toggle" aria-expanded={showArchived} onClick={() => setShowArchived((value) => !value)}>
            {showArchived ? 'Hide' : 'Show'} archived base stages ({archived.length})
          </button>
          {showArchived && <div className="resource-list">{archived.map((stage) => <BaseStageCard key={stage.id} stage={stage} archived busy={busyId === stage.id} onRestore={() => void handleRestore(stage.id)} />)}</div>}
        </div>
      )}
      <ConfirmDialog
        open={confirmId !== null}
        title="Archive this base stage?"
        description="This removes it from the base stage library while preserving its stored content and existing links. You can restore it later."
        confirmLabel="Archive base stage"
        onConfirm={() => void confirmArchive()}
        onCancel={() => setConfirmId(null)}
      />
    </section>
  )
}
