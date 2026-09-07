import { useBudget } from '../api/useBudget'
import { AsyncMessage } from './AsyncMessage'
import { Icon } from './Icon'

/** Past this share of the cap the meter turns amber. */
const WARN_AT = 0.75
/** Past this share of the cap it turns red. */
const DANGER_AT = 0.9

/**
 * Daily spend, shown in the sidebar footer. The budget gates every paid
 * generation, so it is visible on every route.
 *
 * The exact figures stay in the text ("Budget: $0.07 / $3.00") rather than
 * being replaced by the bar — the bar is a glanceable proportion, the text is
 * the answer to "how much exactly". The <progress>-style element carries an
 * aria-valuetext so screen readers get the figures too, not a bare percentage.
 */
export function BudgetMeter() {
  const { budget, refreshError } = useBudget()
  const spentCents = budget.spent_today_cents
  const capCents = budget.daily_spend_cap_cents

  const spent = (spentCents / 100).toFixed(2)
  const cap = (capCents / 100).toFixed(2)

  // A zero or missing cap must not produce NaN width or a divide-by-zero.
  const ratio = capCents > 0 ? Math.min(1, Math.max(0, spentCents / capCents)) : 0
  const accessibleSpentCents = capCents > 0 ? Math.min(capCents, Math.max(0, spentCents)) : 0
  const level = ratio >= DANGER_AT ? 'danger' : ratio >= WARN_AT ? 'warn' : null

  return (
    <div className={level ? `budget-meter budget-meter--${level}` : 'budget-meter'}>
      <span className="budget-meter__label">
        <Icon name="budget" size="xs" />
        Daily budget
      </span>
      <div
        className="budget-meter__track"
        role="progressbar"
        aria-label="Daily spend against cap"
        aria-valuemin={0}
        aria-valuemax={capCents}
        aria-valuenow={accessibleSpentCents}
        aria-valuetext={`$${spent} of $${cap} spent`}
      >
        {/* Genuinely dynamic: the fill width is data, not styling. */}
        <div className="budget-meter__fill" style={{ width: `${ratio * 100}%` }} />
      </div>
      <p className="budget-meter__value" title="Daily spend budget">
        Budget: ${spent} / ${cap}
      </p>
      {refreshError && (
        <AsyncMessage kind="error" className="budget-meter__warning" title={refreshError}>
          Budget may be out of date
        </AsyncMessage>
      )}
    </div>
  )
}
