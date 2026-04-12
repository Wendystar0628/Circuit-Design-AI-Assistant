const ZERO_EPSILON = 1e-12

export function normalizeZero(value: number): number {
  return Math.abs(value) <= ZERO_EPSILON ? 0 : value
}

export function trimTrailingZeros(value: string): string {
  return value
    .replace(/(\.\d*?[1-9])0+$/u, '$1')
    .replace(/\.0+$/u, '')
    .replace(/^-0$/u, '0')
}

function formatScaledNumber(value: number): string {
  const normalized = normalizeZero(value)
  const absolute = Math.abs(normalized)
  if (absolute >= 100) {
    return trimTrailingZeros(normalized.toFixed(0))
  }
  if (absolute >= 10) {
    return trimTrailingZeros(normalized.toFixed(1))
  }
  if (absolute >= 1) {
    return trimTrailingZeros(normalized.toFixed(2))
  }
  if (absolute >= 0.01) {
    return trimTrailingZeros(normalized.toFixed(3))
  }
  return trimTrailingZeros(normalized.toExponential(2).replace('e+', 'e'))
}

export function formatCompactNumber(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) {
    return '--'
  }

  const normalized = normalizeZero(value)
  const absolute = Math.abs(normalized)
  if (absolute === 0) {
    return '0'
  }
  if (absolute >= 1e9) {
    return `${formatScaledNumber(normalized / 1e9)}G`
  }
  if (absolute >= 1e6) {
    return `${formatScaledNumber(normalized / 1e6)}M`
  }
  if (absolute >= 1e3) {
    return `${formatScaledNumber(normalized / 1e3)}k`
  }
  if (absolute >= 0.01) {
    return formatScaledNumber(normalized)
  }
  if (absolute >= 1e-3) {
    return `${formatScaledNumber(normalized / 1e-3)}m`
  }
  if (absolute >= 1e-6) {
    return `${formatScaledNumber(normalized / 1e-6)}u`
  }
  if (absolute >= 1e-9) {
    return `${formatScaledNumber(normalized / 1e-9)}n`
  }
  return trimTrailingZeros(normalized.toExponential(2).replace('e+', 'e'))
}

export function formatMeasurementNumber(value: number | null | undefined, significantDigits = 6): string {
  if (value == null || !Number.isFinite(value)) {
    return '--'
  }

  const normalized = normalizeZero(value)
  if (normalized === 0) {
    return '0'
  }
  return trimTrailingZeros(normalized.toPrecision(significantDigits).replace('e+', 'e'))
}
