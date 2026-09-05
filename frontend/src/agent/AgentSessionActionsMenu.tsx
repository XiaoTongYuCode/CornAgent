import { DotsThree } from '@phosphor-icons/react'
import { Trash2 } from 'lucide-react'
import { useCallback, useEffect, useId, useRef, useState, type KeyboardEvent } from 'react'
import { apiErrorMessage } from '../api/transport'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { FloatingMenuPortal } from '../components/FloatingMenuPortal'
import { useI18n } from '../i18n'

interface AgentSessionActionsMenuProps {
  disabled: boolean
  disabledReason?: string
  sessionTitle: string
  triggerClassName?: string
  triggerLabel?: string
  onDelete(): Promise<void>
}

type MenuPhase = 'opening' | 'open' | 'closing'

function dropdownCloseDelay() {
  if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return 0
  return Number.parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--dropdown-close-dur')) || 150
}

export function AgentSessionActionsMenu({ disabled, disabledReason, sessionTitle, triggerClassName, triggerLabel, onDelete }: AgentSessionActionsMenuProps) {
  const { text } = useI18n()
  const menuId = useId()
  const triggerRef = useRef<HTMLButtonElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const closeTimerRef = useRef<number | null>(null)
  const [renderMenu, setRenderMenu] = useState(false)
  const [phase, setPhase] = useState<MenuPhase>('opening')
  const [confirmOpen, setConfirmOpen] = useState(false)

  const requestClose = useCallback((restoreFocus: boolean) => {
    if (!renderMenu || closeTimerRef.current !== null) return
    setPhase('closing')
    closeTimerRef.current = window.setTimeout(() => {
      closeTimerRef.current = null
      setRenderMenu(false)
      setPhase('opening')
      if (restoreFocus) triggerRef.current?.focus()
    }, dropdownCloseDelay())
  }, [renderMenu])

  useEffect(() => {
    if (!renderMenu || phase !== 'opening') return
    const frame = window.requestAnimationFrame(() => setPhase('open'))
    return () => window.cancelAnimationFrame(frame)
  }, [phase, renderMenu])

  useEffect(() => {
    if (phase !== 'open') return
    menuRef.current?.querySelector<HTMLButtonElement>('[role="menuitem"]:not(:disabled)')?.focus()
  }, [phase])

  useEffect(() => {
    if (!renderMenu) return
    function closeOnOutsidePointer(event: PointerEvent) {
      if (!(event.target instanceof Node)) return
      if (triggerRef.current?.contains(event.target) || menuRef.current?.contains(event.target)) return
      requestClose(false)
    }
    function closeOnEscape(event: globalThis.KeyboardEvent) {
      if (event.key !== 'Escape') return
      event.preventDefault()
      requestClose(true)
    }
    document.addEventListener('pointerdown', closeOnOutsidePointer, true)
    document.addEventListener('keydown', closeOnEscape)
    return () => {
      document.removeEventListener('pointerdown', closeOnOutsidePointer, true)
      document.removeEventListener('keydown', closeOnEscape)
    }
  }, [renderMenu, requestClose])

  useEffect(() => () => {
    if (closeTimerRef.current !== null) window.clearTimeout(closeTimerRef.current)
  }, [])

  function openMenu() {
    if (renderMenu) {
      requestClose(false)
      return
    }
    setRenderMenu(true)
    setPhase('opening')
  }

  function handleMenuKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return
    event.preventDefault()
    const items = [...(menuRef.current?.querySelectorAll<HTMLButtonElement>('[role="menuitem"]:not(:disabled)') ?? [])]
    if (items.length === 0) return
    const currentIndex = items.indexOf(document.activeElement as HTMLButtonElement)
    if (event.key === 'Home') items[0].focus()
    else if (event.key === 'End') items.at(-1)?.focus()
    else if (event.key === 'ArrowDown') items[(currentIndex + 1 + items.length) % items.length].focus()
    else items[(currentIndex - 1 + items.length) % items.length].focus()
  }

  return <>
    <button
      ref={triggerRef}
      className={triggerClassName ?? 'agent-chat-header-button'}
      type="button"
      aria-label={triggerLabel ?? text('更多操作', 'More actions')}
      aria-haspopup="menu"
      aria-expanded={renderMenu && phase !== 'closing'}
      aria-controls={renderMenu ? menuId : undefined}
      disabled={disabled}
      title={disabled ? disabledReason : triggerLabel ?? text('更多操作', 'More actions')}
      onClick={openMenu}
    ><DotsThree size={16} aria-hidden /></button>
    {renderMenu && <FloatingMenuPortal
      getAnchor={() => triggerRef.current}
      menuRef={menuRef}
      id={menuId}
      className={`agent-session-actions-menu t-dropdown${phase === 'open' ? ' is-open' : phase === 'closing' ? ' is-closing' : ''}`}
      placement="bottom-end"
      ariaLabel={text('会话操作', 'Conversation actions')}
    >
      <div onKeyDown={handleMenuKeyDown}>
        <button type="button" className="menu-row danger" role="menuitem" onClick={() => {
          requestClose(false)
          setConfirmOpen(true)
        }}><Trash2 size={16} aria-hidden />{text('删除会话', 'Delete conversation')}</button>
      </div>
    </FloatingMenuPortal>}
    {confirmOpen && <ConfirmDialog
      title={text(`删除“${sessionTitle}”？`, `Delete “${sessionTitle}”?`)}
      content={text('此会话及其全部消息将永久删除，且无法恢复。', 'This conversation and all of its messages will be permanently deleted. This cannot be undone.')}
      okText={text('删除会话', 'Delete conversation')}
      cancelText={text('取消', 'Cancel')}
      danger
      errorMessage={(error) => apiErrorMessage(error, text('无法删除会话。', 'Unable to delete the conversation.'), text)}
      onConfirm={onDelete}
      onClose={() => setConfirmOpen(false)}
    />}
  </>
}
