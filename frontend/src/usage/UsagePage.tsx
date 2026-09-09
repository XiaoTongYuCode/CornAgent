import { ConfigProvider, Segmented } from 'antd'
import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { Activity, ArrowUpRight, CalendarDays, Clock3, Layers3, RefreshCw, Zap } from 'lucide-react'
import { useReducedMotion } from 'motion/react'
import NumberFlow from '@number-flow/react'
import { HttpAgentTransport } from '../agent'
import { navigate } from '../app/navigation'
import { useI18n } from '../i18n'
import { AreaChart } from '../vendor/bklit/charts/area-chart'
import { Area } from '../vendor/bklit/charts/area'
import { Grid } from '../vendor/bklit/charts/grid'
import { XAxis } from '../vendor/bklit/charts/x-axis'
import { YAxis } from '../vendor/bklit/charts/y-axis'
import { TooltipBox } from '../vendor/bklit/charts/tooltip/tooltip-box'
import { ChartTooltip } from '../vendor/bklit/charts/tooltip/chart-tooltip'
import { BarChart } from '../vendor/bklit/charts/bar-chart'
import { Bar } from '../vendor/bklit/charts/bar'
import { BarXAxis } from '../vendor/bklit/charts/bar-x-axis'
import { RingChart } from '../vendor/bklit/charts/ring-chart'
import { Ring } from '../vendor/bklit/charts/ring'
import { RingCenter } from '../vendor/bklit/charts/ring-center'
import { Legend } from '../vendor/bklit/charts/legend/legend'
import { LegendItem } from '../vendor/bklit/charts/legend/legend-item'
import { LegendMarker } from '../vendor/bklit/charts/legend/legend-marker'
import { LegendLabel } from '../vendor/bklit/charts/legend/legend-label'
import { LegendValue } from '../vendor/bklit/charts/legend/legend-value'
import { HeatmapChart } from '../vendor/bklit/charts/heatmap/heatmap-chart'
import { HeatmapCells } from '../vendor/bklit/charts/heatmap/heatmap-cells'
import { HeatmapLegend } from '../vendor/bklit/charts/heatmap/heatmap-legend'
import { useHeatmap, useHeatmapInteraction } from '../vendor/bklit/charts/heatmap/heatmap-context'
import type { UsageData, UsageGroup } from './types'
import './usage.css'

const transport = new HttpAgentTransport()
const colors = ['#73968a', '#cc8474', '#bdad89', '#8c9cb7']
const heatColors: [string, string, string, string, string] = [
  'var(--surface-muted)',
  '#d5e2da',
  '#adc7b8',
  '#7ca28d',
  '#4e7c65',
]
const margin = { top: 20, right: 12, bottom: 35, left: 42 }

function Panel({
  title,
  hint,
  children,
  className = '',
  aside,
}: {
  title: string
  hint: string
  children: ReactNode
  className?: string
  aside?: ReactNode
}) {
  return (
    <section className={`usage-panel ${className}`}>
      <header>
        <div>
          <h2>{title}</h2>
          <p>{hint}</p>
        </div>
        {aside}
      </header>
      {children}
    </section>
  )
}

function ActivityTooltip() {
  const { t } = useI18n()
  const { tooltipData } = useHeatmapInteraction()
  const { containerRef, width, height } = useHeatmap()
  if (!tooltipData) return null
  return (
    <TooltipBox
      containerRef={containerRef}
      containerWidth={width}
      containerHeight={height}
      x={tooltipData.x}
      y={tooltipData.y}
      visible
      entrance={false}
    >
      <div className="usage-heat-tooltip" role="status">
        {t('usageActivityCell', {
          day: t('usageWeekdays').split(',')[tooltipData.row],
          hour: tooltipData.column,
          count: tooltipData.count,
        })}
      </div>
    </TooltipBox>
  )
}

function CallPanel({ kind, data }: { kind: 'tools' | 'models'; data: UsageData }) {
  const { t, locale } = useI18n()
  const reduce = useReducedMotion()
  const groups = data[kind]
  const chartData = groups.slice(0, 6).map((g) => ({ name: g.name, calls: g.calls }))
  return (
    <Panel
      title={t(kind === 'tools' ? 'usageTools' : 'usageModels')}
      hint={t(kind === 'tools' ? 'usageToolsHint' : 'usageModelsHint')}
    >
      {!data.telemetryLocal ? (
        <div className="usage-event-empty">
          <Layers3 size={24} />
          <strong>{t(data.telemetryEnabled ? 'usageExternalSink' : 'usageTelemetryOff')}</strong>
          <p>{!data.telemetryEnabled && t('usageTelemetryOffHint')}</p>
        </div>
      ) : !groups.length ? (
        <div className="usage-event-empty">{t('usageNoEvents')}</div>
      ) : (
        <>
          <div className="usage-call-chart" aria-hidden="true">
            <BarChart
              data={chartData}
              xDataKey="name"
              orientation="horizontal"
              animationDuration={reduce ? 0 : 400}
              animationEasing="cubic-bezier(0.22, 1, 0.36, 1)"
              margin={{ top: 8, right: 16, bottom: 8, left: 0 }}
            >
              <Bar dataKey="calls" fill={kind === 'tools' ? colors[0] : colors[3]} />
              <ChartTooltip
                showDatePill={false}
                rows={(p) => [
                  { label: String(p.name), value: Number(p.calls).toLocaleString(locale), color: colors[0] },
                ]}
              />
            </BarChart>
          </div>
          <div className="usage-table-scroll">
            <table>
              <thead>
                <tr>
                  <th>{t('usageName')}</th>
                  <th>{t('usageCalls')}</th>
                  <th>{t('usageFailures')}</th>
                  <th>{t('usageAverage')}</th>
                  {kind === 'models' && <th>Token</th>}
                </tr>
              </thead>
              <tbody>
                {groups.map((item: UsageGroup) => (
                  <tr key={item.name}>
                    <th scope="row" title={item.name}>
                      {item.name}
                    </th>
                    <td>{item.calls.toLocaleString(locale)}</td>
                    <td>{item.failures}</td>
                    <td>{t('usageSeconds', { value: item.durationSeconds.toLocaleString(locale) })}</td>
                    {kind === 'models' && (
                      <td>
                        {item.reportedCalls
                          ? (item.inputTokens + item.outputTokens).toLocaleString(locale)
                          : '—'}
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </Panel>
  )
}

export default function UsagePage() {
  const { t, locale } = useI18n()
  const reduce = useReducedMotion()
  const [days, setDays] = useState(30)
  const [revision, setRevision] = useState(0)
  const [state, setState] = useState<{ data?: UsageData; error?: boolean; loading: boolean }>({
    loading: true,
  })
  useEffect(() => {
    const controller = new AbortController()
    transport.get<UsageData>(`/agent/usage?days=${days}`, false, controller.signal).then(
      (data) => {
        if (!controller.signal.aborted) setState({ data, loading: false })
      },
      () => {
        if (!controller.signal.aborted) setState({ error: true, loading: false })
      },
    )
    return () => controller.abort()
  }, [days, revision])
  const changeDays = (next: number) => {
    if (next !== days) {
      setState({ loading: true })
      setDays(next)
    }
  }
  const refresh = () => {
    setState({ loading: true })
    setRevision((v) => v + 1)
  }
  const data = state.data
  const daily = useMemo(
    () =>
      data?.daily.map((d) => ({
        ...d,
        date: new Date(`${d.date}T00:00:00Z`),
        label: d.date.slice(5).replace('-', '/'),
      })) ?? [],
    [data],
  )
  const heatmap = useMemo(
    () =>
      Array.from({ length: 24 }, (_, hour) => ({
        bin: hour,
        bins: Array.from({ length: 7 }, (_, day) => ({
          bin: day,
          count: data?.hours[day][hour] ?? 0,
          date: new Date(Date.UTC(2026, 0, 5 + day, hour)),
        })),
      })),
    [data],
  )
  const date = (value: string) =>
    new Date(value).toLocaleDateString(locale, { month: 'short', day: 'numeric', timeZone: 'UTC' })
  const ring = data
    ? (['completed', 'failed', 'cancelled', 'active'] as const).map((key, i) => ({
        label: t(
          (
            {
              completed: 'usageCompleted',
              failed: 'usageFailed',
              cancelled: 'usageCancelled',
              active: 'usageActive',
            } as const
          )[key],
        ),
        value: data.statuses[key],
        maxValue: Math.max(1, data.totalRuns),
        color: colors[i],
      }))
    : []
  const animation = { animationDuration: reduce ? 0 : 400, animationEasing: 'cubic-bezier(0.22, 1, 0.36, 1)' }
  return (
    <div className="usage-page">
      <div className="usage-content">
        <header className="usage-header">
          <div>
            <h1>
              {t('usageTitle')}
              <span className="usage-heading-dot">.</span>
            </h1>
            <p>{t('usageSubtitle')}</p>
          </div>
          <div className="usage-controls">
            <ConfigProvider theme={{ components: { Segmented: { controlHeight: 34 } } }}>
              <Segmented<number>
                aria-label={t('usageTitle')}
                value={days}
                onChange={changeDays}
                options={[7, 30, 90].map((value) => ({
                  value,
                  label: t('usageDays', { days: value }),
                }))}
              />
            </ConfigProvider>
            <button
              type="button"
              className="usage-refresh"
              aria-label={t('usageRefresh')}
              title={t('usageRefresh')}
              disabled={state.loading}
              onClick={refresh}
            >
              <RefreshCw size={15} />
            </button>
          </div>
        </header>
        <div className="usage-context">
          <span>
            <span className="usage-status-dot" />
            {t('usageScope')}
          </span>
          <span>
            <CalendarDays size={13} />
            {data ? `${date(data.from)} – ${date(data.to)}` : t('usageDays', { days })}
          </span>
        </div>
        {state.loading ? (
          <div className="usage-skeleton" role="status" aria-label={t('loading')}>
            {Array.from({ length: 6 }, (_, i) => (
              <div key={i} />
            ))}
          </div>
        ) : state.error || !data ? (
          <div className="usage-error" role="alert">
            <p>{t('usageError')}</p>
            <button onClick={refresh}>{t('authRetry')}</button>
          </div>
        ) : (
          <>
            <div className="usage-metrics">
              {(
                [
                  [
                    t('usageRuns'),
                    data.totalRuns,
                    t('usageSessions', { count: data.sessions }),
                    <Activity size={16} />,
                  ],
                  [
                    t('usageTokens'),
                    data.reportedRuns ? data.inputTokens + data.outputTokens : null,
                    t('usageReported', { count: data.reportedRuns }),
                    <Zap size={16} />,
                  ],
                  [t('usageSuccess'), data.successRate, t('usageTerminal'), <ArrowUpRight size={16} />],
                  [
                    t('usageDuration'),
                    data.averageDurationSeconds,
                    t('usageCompletedOnly'),
                    <Clock3 size={16} />,
                  ],
                ] as const
              ).map(([label, value, hint, icon], i) => (
                <section className="usage-metric" key={label}>
                  <div className="usage-metric-label">
                    {label}
                    {icon}
                  </div>
                  <div className="usage-metric-value">
                    {value === null ? (
                      '—'
                    ) : (
                      <NumberFlow
                        value={value}
                        locales={locale}
                        animated={!reduce}
                        format={{ notation: i === 1 ? 'compact' : 'standard', maximumFractionDigits: 1 }}
                      />
                    )}
                    {value !== null && i > 1 && (
                      <small>{i === 2 ? '%' : locale === 'zh-CN' ? '秒' : 's'}</small>
                    )}
                  </div>
                  <p>{hint}</p>
                </section>
              ))}
            </div>
            {!data.totalRuns && (
              <div className="usage-empty">
                <div>
                  <strong>{t('usageEmpty')}</strong>
                  <p>{t('usageEmptyHint')}</p>
                </div>
                <button onClick={() => navigate('/chat')}>
                  {t('usageStart')}
                  <ArrowUpRight size={15} />
                </button>
              </div>
            )}
            <div className="usage-chart-grid">
              <Panel
                className="usage-trend"
                title={t('usageTrend')}
                hint={t('usageTrendHint')}
                aside={<span className="usage-chip">{t('usageActiveDays', { count: data.activeDays })}</span>}
              >
                <div className="usage-plot" aria-hidden="true">
                  <AreaChart key={locale} data={daily} {...animation} margin={margin} yDomainTween={!reduce}>
                    <Grid numTicksRows={4} strokeDasharray="3,5" />
                    <Area
                      dataKey="runs"
                      fill={colors[0]}
                      stroke={colors[0]}
                      fillOpacity={0.22}
                      animate={!reduce}
                    />
                    <XAxis numTicks={5} />
                    <YAxis
                      numTicks={4}
                      formatValue={(v) => (Number.isInteger(v) ? v.toLocaleString(locale) : '')}
                    />
                    <ChartTooltip
                      showDatePill={false}
                      rows={(p) => [
                        {
                          label: `${(p.date as Date).toLocaleDateString(locale, { timeZone: 'UTC' })} · ${t('usageRuns')}`,
                          value: Number(p.runs).toLocaleString(locale),
                          color: colors[0],
                        },
                      ]}
                    />
                  </AreaChart>
                </div>
              </Panel>
              <Panel
                className="usage-outcomes"
                title={t('usageDistribution')}
                hint={t('usageDistributionHint')}
              >
                <div className="usage-ring" aria-hidden="true">
                  <RingChart
                    data={ring}
                    size={210}
                    strokeWidth={9}
                    ringGap={6}
                    animationDuration={reduce ? 0 : 400}
                    enterStaggerScale={reduce ? 0 : 0.4}
                  >
                    <Ring index={0} animate={!reduce} showGlow={false} />
                    <Ring index={1} animate={!reduce} showGlow={false} />
                    <Ring index={2} animate={!reduce} showGlow={false} />
                    <Ring index={3} animate={!reduce} showGlow={false} />
                    <RingCenter
                      defaultLabel={t('usageRuns')}
                      valueClassName="usage-ring-number"
                      labelClassName="usage-ring-label"
                    />
                  </RingChart>
                </div>
                <Legend items={ring}>
                  <LegendItem className="usage-legend-item">
                    <LegendMarker />
                    <LegendLabel />
                    <LegendValue />
                  </LegendItem>
                </Legend>
              </Panel>
              <Panel
                className="usage-tokens"
                title={t('usageTokenTrend')}
                hint={t('usageTokenHint')}
                aside={
                  <div className="usage-inline-legend">
                    <span style={{ color: colors[0] }}>
                      ● <i>{t('usageInput')}</i>
                    </span>
                    <span style={{ color: colors[3] }}>
                      ● <i>{t('usageOutput')}</i>
                    </span>
                  </div>
                }
              >
                <div className="usage-plot" aria-hidden="true">
                  <BarChart
                    data={daily}
                    xDataKey="label"
                    stacked
                    {...animation}
                    margin={margin}
                    barGap={0.35}
                  >
                    <Grid numTicksRows={4} strokeDasharray="3,5" />
                    <Bar dataKey="inputTokens" fill={colors[0]} />
                    <Bar dataKey="outputTokens" fill={colors[3]} />
                    <BarXAxis maxLabels={5} />
                    <YAxis numTicks={4} />
                    <ChartTooltip
                      showDatePill={false}
                      rows={(p) => [
                        {
                          label: t('usageInput'),
                          value: Number(p.inputTokens).toLocaleString(locale),
                          color: colors[0],
                        },
                        {
                          label: t('usageOutput'),
                          value: Number(p.outputTokens).toLocaleString(locale),
                          color: colors[3],
                        },
                      ]}
                    />
                  </BarChart>
                </div>
              </Panel>
              <Panel className="usage-rhythm" title={t('usageHeatmap')} hint={t('usageHeatmapHint')}>
                <div className="usage-heat-layout" aria-hidden="true">
                  <div className="usage-day-labels">
                    {t('usageWeekdays')
                      .split(',')
                      .map((day) => (
                        <span key={day}>{day}</span>
                      ))}
                  </div>
                  <div className="usage-heat-grid">
                    <HeatmapChart
                      data={heatmap}
                      layout="fill"
                      margin={{ top: 0, left: 0, right: 0, bottom: 0 }}
                      gap={4}
                      levelColors={heatColors}
                      animationDuration={400}
                      enterStaggerScale={0}
                      animate={!reduce}
                    >
                      <HeatmapCells />
                      <ActivityTooltip />
                    </HeatmapChart>
                  </div>
                  <div className="usage-hour-labels">
                    {[0, 6, 12, 18, 23].map((hour) => (
                      <span key={hour}>{hour.toString().padStart(2, '0')}</span>
                    ))}
                  </div>
                </div>
                <HeatmapLegend
                  lessLabel={t('usageLess')}
                  moreLabel={t('usageMore')}
                  colorScale={(count) => heatColors[Math.max(0, Math.min(4, count ?? 0))]}
                />
                <div className="usage-span">
                  <div>
                    <span>{t('usageSessionDuration')}</span>
                    <strong>
                      {data.averageSessionSeconds === null
                        ? '—'
                        : t('usageSeconds', { value: data.averageSessionSeconds.toLocaleString(locale) })}
                    </strong>
                  </div>
                  <p>{t('usageSpanHint')}</p>
                </div>
              </Panel>
              <CallPanel kind="tools" data={data} />
              <CallPanel kind="models" data={data} />
            </div>
            <details className="usage-details">
              <summary>{t('usageDetails')}</summary>
              <div className="usage-table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>{t('usageDate')}</th>
                      <th>{t('usageRuns')}</th>
                      <th>{t('usageInput')} Token</th>
                      <th>{t('usageOutput')} Token</th>
                      <th>{t('usageDuration')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.daily.map((day) => (
                      <tr key={day.date}>
                        <th scope="row">{day.date}</th>
                        <td>{day.runs}</td>
                        <td>{day.inputTokens.toLocaleString(locale)}</td>
                        <td>{day.outputTokens.toLocaleString(locale)}</td>
                        <td>
                          {day.durationSeconds === null
                            ? '—'
                            : t('usageSeconds', { value: day.durationSeconds })}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
            <footer className="usage-footer">
              <p>{t('usageNote')}</p>
              <span>
                {t('usageUpdated', {
                  time: new Date(data.to).toLocaleTimeString(locale, {
                    hour: '2-digit',
                    minute: '2-digit',
                    timeZone: 'UTC',
                  }),
                })}{' '}
                · UTC
              </span>
            </footer>
          </>
        )}
      </div>
    </div>
  )
}
