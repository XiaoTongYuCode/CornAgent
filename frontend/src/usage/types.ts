export interface UsageGroup {
  name: string
  calls: number
  failures: number
  durationSeconds: number
  inputTokens: number
  outputTokens: number
  reportedCalls: number
  childCalls: number
}
export interface UsageData {
  days: number
  from: string
  to: string
  timezone: string
  totalRuns: number
  sessions: number
  inputTokens: number
  outputTokens: number
  reportedRuns: number
  successRate: number | null
  averageDurationSeconds: number | null
  averageSessionSeconds: number | null
  activeDays: number
  statuses: Record<'completed' | 'failed' | 'cancelled' | 'active', number>
  daily: { date: string; runs: number; inputTokens: number; outputTokens: number; durationSeconds: number | null }[]
  hours: number[][]
  telemetryEnabled: boolean
  telemetryLocal: boolean
  tools: UsageGroup[]
  models: UsageGroup[]
}
