export type UiTextMap = Record<string, string>

export function getUiText(
  uiText: UiTextMap | null | undefined,
  key: string,
  fallback: string,
  variables?: Record<string, string | number>,
): string {
  let text = String(uiText?.[key] ?? fallback)
  if (!variables) {
    return text
  }
  return text.replace(/\{(\w+)\}/g, (_match, variableName: string) => {
    const value = variables[variableName]
    return value === undefined || value === null ? '' : String(value)
  })
}
