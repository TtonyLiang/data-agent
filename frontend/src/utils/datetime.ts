function pad(value: number) {
  return String(value).padStart(2, '0')
}

function parseDateTime(value: unknown) {
  if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value
  if (value === null || value === undefined || value === '') return null
  if (typeof value === 'number') {
    const date = new Date(value)
    return Number.isNaN(date.getTime()) ? null : date
  }
  const raw = String(value).trim()
  if (!raw) return null
  const normalized = /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}/.test(raw)
    ? raw.replace(' ', 'T')
    : raw
  const date = new Date(normalized)
  return Number.isNaN(date.getTime()) ? null : date
}

export function formatDateTime(value: unknown, fallback = '-') {
  if (value === null || value === undefined || value === '') return fallback
  const date = parseDateTime(value)
  if (!date) return String(value)
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
}

export function isDateTimeField(key: string) {
  const normalized = String(key || '').trim().toLowerCase()
  return normalized.endsWith('_at')
    || normalized.endsWith('_time')
    || normalized.endsWith('_timestamp')
    || normalized === 'timestamp'
    || normalized === 'datetime'
}

export function isDateTimeValue(value: unknown) {
  return typeof value === 'string'
    && /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?$/.test(value.trim())
}
