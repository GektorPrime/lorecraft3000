import { useState } from 'react'
import type { GenerationSummary } from '../../api/types'
import { ImageDialog } from '../../components/ImageDialog'
import { AsyncMessage } from '../../components/AsyncMessage'

interface CandidateCarouselProps {
  attempts: GenerationSummary[]
  reviewingCandidateId: number | null
  onReview: (candidateId: number, verdict: 'accepted' | 'rejected') => void
}

const STATUS_LABEL: Record<string, string> = {
  pending: 'Pending review',
  accepted: 'Accepted',
  rejected: 'Rejected',
}

/** Carousel that cycles through the generated images of each attempt (an
 * attempt stores exactly one candidate image), with per-image review status
 * and accept/reject controls. Used instead of a separate per-attempt detail
 * page. */
export function CandidateCarousel({
  attempts,
  reviewingCandidateId,
  onReview,
}: CandidateCarouselProps) {
  const [index, setIndex] = useState(0)
  const reviewed = attempts.filter((attempt) => attempt.candidates.length > 0)
  const count = reviewed.length
  if (count === 0) return null

  const attempt = reviewed[index % count]
  const candidate = attempt.candidates[0]
  const isReviewing = reviewingCandidateId !== null
  const reviewingThis = isReviewing && reviewingCandidateId === candidate.id

  return (
    <div className="carousel" aria-label="Generated candidate across attempts">
      <div className="carousel__stage">
        <ImageDialog
          src={candidate.content_url}
          thumbnailAlt={`Generated image from attempt ${attempt.id}`}
          previewAlt={`Generated image from attempt ${attempt.id}, full-size preview`}
          triggerLabel={`Preview image from attempt ${attempt.id}`}
          dialogLabel={`Generated image from attempt ${attempt.id}, larger preview`}
        />
        <span className="carousel__counter">{index + 1} / {count}</span>
      </div>
      <div className="carousel__meta">
        <span className={`badge badge--attempt-${candidate.review_status}`}>
          {STATUS_LABEL[candidate.review_status] ?? candidate.review_status}
        </span>
        <span className="field__hint">Attempt #{attempt.id}</span>
      </div>
      <div className="btn-row carousel__controls">
        <button
          type="button"
          className="btn"
          disabled={count <= 1}
          onClick={() => setIndex((i) => (i - 1 + count) % count)}
          aria-label="Previous attempt"
        >
          Previous
        </button>
        <button
          type="button"
          className="btn"
          disabled={count <= 1}
          onClick={() => setIndex((i) => (i + 1) % count)}
          aria-label="Next attempt"
        >
          Next
        </button>
        <span className="carousel__spacer" />
        <button
          type="button"
          className="btn"
          disabled={isReviewing}
          onClick={() => onReview(candidate.id, 'accepted')}
        >
          Accept
        </button>
        <button
          type="button"
          className="btn btn--danger"
          disabled={isReviewing}
          onClick={() => onReview(candidate.id, 'rejected')}
        >
          Reject
        </button>
      </div>
      {reviewingThis && <AsyncMessage kind="loading">Reviewing image…</AsyncMessage>}
    </div>
  )
}