const POSITIVE_INTEGER = /^[1-9]\d*$/

export function parseRouteId(value: string | undefined): number | null {
  if (!value || !POSITIVE_INTEGER.test(value)) return null

  const id = Number(value)
  return Number.isSafeInteger(id) ? id : null
}
