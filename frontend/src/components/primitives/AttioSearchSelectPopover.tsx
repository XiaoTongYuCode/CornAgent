import { useI18n } from '../../i18n'
import { Check, Search, X } from 'lucide-react'
import { Popover } from 'antd'
import { useEffect, useMemo, useRef, useState } from 'react'

export interface AttioSearchSelectOption {
  value: string
  label: string
  description?: string
  keywords?: string[]
  initials?: string
  color?: string
  icon?: React.ReactNode
}

interface AttioSearchSelectPopoverProps {
  ariaLabel: string
  icon: React.ReactNode
  summary: string
  options: AttioSearchSelectOption[]
  values: string[]
  onChange: (values: string[]) => void
  searchPlaceholder: string
  emptyText: string
  multiple?: boolean
  disabled?: boolean
  triggerClassName?: string
  popupClassName?: string
  searchOptions?: (query: string, cursor?: string | null, signal?: AbortSignal) => Promise<{ data: AttioSearchSelectOption[]; nextCursor: string | null }>
  optionsNextCursor?: string | null
  loadingMoreOptions?: boolean
  onLoadMoreOptions?: () => Promise<void>
  onChoose?: (option: AttioSearchSelectOption) => void
  loadingText?: string
  loadMoreText?: string
  retryText?: string
  showSelectedChips?: boolean
}

const searchSelectPopoverStyles = {
  container: {
    width: 294,
    padding: 0,
    overflow: 'hidden',
    border: '1px solid var(--border-strong)',
    borderRadius: 9,
    color: 'var(--text)',
    background: 'var(--panel-raised)',
    boxShadow: 'var(--shadow)',
  },
} as const

export function AttioSearchSelectPopover({ ariaLabel, icon, summary, options, values, onChange, searchPlaceholder, emptyText, multiple = true, disabled = false, triggerClassName, popupClassName, searchOptions, optionsNextCursor = null, loadingMoreOptions = false, onLoadMoreOptions, onChoose, loadingText: loadingTextProp, loadMoreText: loadMoreTextProp, retryText: retryTextProp, showSelectedChips = true }: AttioSearchSelectPopoverProps) {
  const { t } = useI18n()
  const loadingText = loadingTextProp ?? t('loading')
  const loadMoreText = loadMoreTextProp ?? t('loadMore')
  const retryText = retryTextProp ?? t('retry')
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [activeIndex, setActiveIndex] = useState(0)
  const [remoteOptions, setRemoteOptions] = useState<AttioSearchSelectOption[]>([])
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [searching, setSearching] = useState(false)
  const [searchError, setSearchError] = useState<string | null>(null)
  const [retryRevision, setRetryRevision] = useState(0)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const requestControllerRef = useRef<AbortController | null>(null)
  const requestGenerationRef = useRef(0)
  const selected = useMemo(() => options.filter((option) => values.includes(option.value)), [options, values])
  const normalizedQuery = query.trim()
  const filtered = useMemo(() => {
    const needle = normalizedQuery.toLocaleLowerCase()
    if (!needle) return options
    if (searchOptions) return remoteOptions
    return options.filter((option) => [option.label, option.description, ...(option.keywords ?? [])]
      .filter(Boolean)
      .some((candidate) => candidate?.toLocaleLowerCase().includes(needle)))
  }, [normalizedQuery, options, remoteOptions, searchOptions])

  useEffect(() => () => requestControllerRef.current?.abort(), [])

  useEffect(() => {
    requestControllerRef.current?.abort()
    const generation = ++requestGenerationRef.current
    if (!open || !normalizedQuery || !searchOptions) return
    const controller = new AbortController()
    requestControllerRef.current = controller
    const timer = window.setTimeout(() => {
      void searchOptions(normalizedQuery, null, controller.signal).then((page) => {
        if (generation !== requestGenerationRef.current || controller.signal.aborted) return
        setRemoteOptions(page.data)
        setNextCursor(page.nextCursor)
      }).catch((error: unknown) => {
        if (generation !== requestGenerationRef.current || controller.signal.aborted || (error instanceof Error && error.name === 'AbortError')) return
        setRemoteOptions([])
        setNextCursor(null)
        setSearchError(error instanceof Error ? error.message : emptyText)
      }).finally(() => {
        if (generation === requestGenerationRef.current && !controller.signal.aborted) setSearching(false)
      })
    }, 180)
    return () => {
      window.clearTimeout(timer)
      controller.abort()
    }
  }, [emptyText, normalizedQuery, open, retryRevision, searchOptions])

  function updateOpen(next: boolean) {
    setOpen(next)
    if (next) {
      setActiveIndex(0)
      window.requestAnimationFrame(() => inputRef.current?.focus())
    } else {
      requestControllerRef.current?.abort()
      requestGenerationRef.current += 1
      setQuery('')
      setRemoteOptions([])
      setNextCursor(null)
      setSearching(false)
      setSearchError(null)
    }
  }

  function choose(value: string) {
    const option = filtered.find((candidate) => candidate.value === value) ?? options.find((candidate) => candidate.value === value)
    if (option) onChoose?.(option)
    if (multiple) {
      onChange(values.includes(value) ? values.filter((candidate) => candidate !== value) : [...values, value])
      window.requestAnimationFrame(() => inputRef.current?.focus())
      return
    }
    onChange([value])
    updateOpen(false)
    window.requestAnimationFrame(() => triggerRef.current?.focus())
  }

  async function loadMore() {
    if (!normalizedQuery) {
      if (!optionsNextCursor || loadingMoreOptions || !onLoadMoreOptions) return
      await onLoadMoreOptions()
      return
    }
    if (!searchOptions || !normalizedQuery || !nextCursor || searching) return
    requestControllerRef.current?.abort()
    const controller = new AbortController()
    requestControllerRef.current = controller
    const generation = ++requestGenerationRef.current
    setSearching(true)
    setSearchError(null)
    try {
      const page = await searchOptions(normalizedQuery, nextCursor, controller.signal)
      if (generation !== requestGenerationRef.current || controller.signal.aborted) return
      setRemoteOptions((current) => {
        const byValue = new Map(current.map((option) => [option.value, option]))
        page.data.forEach((option) => byValue.set(option.value, option))
        return [...byValue.values()]
      })
      setNextCursor(page.nextCursor)
    } catch (error) {
      if (generation === requestGenerationRef.current && !controller.signal.aborted && (!(error instanceof Error) || error.name !== 'AbortError')) {
        setSearchError(error instanceof Error ? error.message : emptyText)
      }
    } finally {
      if (generation === requestGenerationRef.current && !controller.signal.aborted) setSearching(false)
    }
  }

  function handleKeys(event: React.KeyboardEvent<HTMLDivElement>) {
    if (event.key === 'Escape') {
      event.preventDefault()
      event.stopPropagation()
      event.nativeEvent.stopImmediatePropagation()
      updateOpen(false)
      window.requestAnimationFrame(() => triggerRef.current?.focus())
      return
    }
    if (filtered.length === 0) return
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      const delta = event.key === 'ArrowDown' ? 1 : -1
      setActiveIndex((current) => (current + delta + filtered.length) % filtered.length)
      return
    }
    if (event.key === 'Enter') {
      event.preventDefault()
      choose(filtered[Math.min(activeIndex, filtered.length - 1)].value)
    }
  }

  function captureEscape(event: React.KeyboardEvent<HTMLDivElement>) {
    if (event.key !== 'Escape') return
    event.preventDefault()
    event.stopPropagation()
    event.nativeEvent.stopImmediatePropagation()
    updateOpen(false)
    window.requestAnimationFrame(() => triggerRef.current?.focus())
  }

  const content = <div className="attio-search-select" onKeyDownCapture={captureEscape} onKeyDown={handleKeys}>
    <label className="attio-search-select-input">
      <Search size={14} strokeWidth={1.75} aria-hidden="true" />
      <span className="sr-only">{searchPlaceholder}</span>
      <input ref={inputRef} role="combobox" aria-label={searchPlaceholder} aria-expanded={open} aria-controls={`${ariaLabel.replace(/\s+/g, '-').toLowerCase()}-options`} value={query} placeholder={searchPlaceholder} onChange={(event) => { requestControllerRef.current?.abort(); requestGenerationRef.current += 1; setQuery(event.target.value); setActiveIndex(0); setRemoteOptions([]); setNextCursor(null); setSearchError(null); setSearching(Boolean(searchOptions && event.target.value.trim())) }} />
    </label>
    {showSelectedChips && selected.length > 0 && <div className="attio-search-select-chips" aria-label={`${ariaLabel} selected`}>
      {selected.map((option) => <span key={option.value}><OptionIdentity option={option} compact /><button type="button" aria-label={`Remove ${option.label}`} onClick={() => choose(option.value)}><X size={11} strokeWidth={1.75} aria-hidden="true" /></button></span>)}
    </div>}
    <div id={`${ariaLabel.replace(/\s+/g, '-').toLowerCase()}-options`} className="attio-search-select-options" role="listbox" aria-label={`${ariaLabel} options`} aria-multiselectable={multiple}>
      {filtered.map((option, index) => {
        const isSelected = values.includes(option.value)
        return <button key={option.value} type="button" role="option" aria-label={option.label} aria-selected={isSelected} className={index === activeIndex ? 'attio-search-select-option active' : 'attio-search-select-option'} onMouseDown={(event) => event.preventDefault()} onMouseEnter={() => setActiveIndex(index)} onClick={() => choose(option.value)}><OptionIdentity option={option} />{isSelected ? <Check size={14} strokeWidth={2.5} aria-hidden="true" /> : <i />}</button>
      })}
      {searching && filtered.length === 0 && <div className="attio-search-select-empty">{loadingText}</div>}
      {!searching && filtered.length === 0 && !searchError && <div className="attio-search-select-empty">{emptyText}</div>}
      {searchError && <div className="attio-search-select-empty" role="alert"><span>{searchError}</span><button type="button" onClick={() => { setSearching(true); setSearchError(null); setRetryRevision((current) => current + 1) }}>{retryText}</button></div>}
      {(normalizedQuery ? nextCursor : optionsNextCursor) && <button type="button" className="attio-search-select-load-more" disabled={normalizedQuery ? searching : loadingMoreOptions} onMouseDown={(event) => event.preventDefault()} onClick={() => { void loadMore() }}>{(normalizedQuery ? searching : loadingMoreOptions) ? loadingText : loadMoreText}</button>}
    </div>
  </div>

  return <Popover placement="bottomLeft" trigger="click" arrow={false} open={open} onOpenChange={updateOpen} content={content} styles={searchSelectPopoverStyles} classNames={popupClassName ? { root: popupClassName } : undefined} getPopupContainer={(trigger) => trigger.closest('.list-modal-portal') ?? document.body}>
    <button ref={triggerRef} type="button" className={triggerClassName ? `attio-inline-trigger ${triggerClassName}` : 'attio-inline-trigger'} aria-label={ariaLabel} aria-expanded={open} disabled={disabled}>{icon}<span>{summary}</span></button>
  </Popover>
}

function OptionIdentity({ option, compact = false }: { option: AttioSearchSelectOption; compact?: boolean }) {
  return <span className={compact ? 'attio-option-identity compact' : 'attio-option-identity'}>
    <span className="attio-option-avatar" style={option.color ? { backgroundColor: option.color } : undefined}>{option.icon ?? option.initials ?? option.label.slice(0, 1).toUpperCase()}</span>
    <span><strong title={option.label}>{option.label}</strong>{!compact && option.description && <small title={option.description}>{option.description}</small>}</span>
  </span>
}
