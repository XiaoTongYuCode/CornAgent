export function normalizeReasoningValue(value?: string | null): string {
  return value?.trim() ?? ''
}
