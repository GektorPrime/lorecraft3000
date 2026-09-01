const SQLITE_UTC_TIMESTAMP =
  /^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?$/

const readableOptions: Intl.DateTimeFormatOptions = {
  dateStyle: 'medium',
  timeStyle: 'short',
}

const fullOptions: Intl.DateTimeFormatOptions = {
  dateStyle: 'full',
  timeStyle: 'long',
}

export function parseDate(value: string | Date): Date | null {
  if (value instanceof Date) {
    return Number.isNaN(value.getTime()) ? null : new Date(value)
  }

  const trimmedValue = value.trim()
  const sqliteMatch = SQLITE_UTC_TIMESTAMP.exec(trimmedValue)
  const normalizedValue = sqliteMatch
    ? `${sqliteMatch[1]}-${sqliteMatch[2]}-${sqliteMatch[3]}T${sqliteMatch[4]}:${sqliteMatch[5]}:${sqliteMatch[6]}${sqliteMatch[7] ? `.${sqliteMatch[7]}` : ''}Z`
    : trimmedValue
  const date = new Date(normalizedValue)

  return Number.isNaN(date.getTime()) ? null : date
}

export function toIsoDateTime(value: string | Date): string | null {
  return parseDate(value)?.toISOString() ?? null
}

export function formatDateTime(
  value: string | Date,
  options: Intl.DateTimeFormatOptions = readableOptions,
  locales?: Intl.LocalesArgument,
): string | null {
  const date = parseDate(value)
  return date ? new Intl.DateTimeFormat(locales, options).format(date) : null
}

export function formatFullDateTime(
  value: string | Date,
  locales?: Intl.LocalesArgument,
): string | null {
  return formatDateTime(value, fullOptions, locales)
}
