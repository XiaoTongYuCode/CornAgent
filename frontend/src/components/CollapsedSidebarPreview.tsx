import {
  useEffect,
  useRef,
  useState,
  type FocusEventHandler,
  type PointerEventHandler,
  type ReactNode,
  type RefObject,
} from 'react'
import { NavigationMenuIcon } from './sidebar/NavigationMenuIcon'

interface CollapsedSidebarPreviewRenderState {
  open: boolean
  pinOpen: () => void
  sidebarRef: RefObject<HTMLElement | null>
  sidebarInteractionProps: {
    onPointerLeave: PointerEventHandler<HTMLElement>
    onFocusCapture: FocusEventHandler<HTMLElement>
    onBlurCapture: FocusEventHandler<HTMLElement>
  }
}

interface CollapsedSidebarPreviewProps {
  collapsed: boolean
  label: string
  onExpand: () => void
  children: (state: CollapsedSidebarPreviewRenderState) => ReactNode
}

export function CollapsedSidebarPreview({ collapsed, label, onExpand, children }: CollapsedSidebarPreviewProps) {
  const [previewOpen, setPreviewOpen] = useState(false)
  const triggerRef = useRef<HTMLDivElement>(null)
  const sidebarRef = useRef<HTMLElement>(null)
  const boundaryRef = useRef<HTMLDivElement>(null)
  const open = collapsed && previewOpen
  const pinOpen = () => {
    setPreviewOpen(false)
    onExpand()
  }

  useEffect(() => {
    if (!open) return

    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      event.preventDefault()
      setPreviewOpen(false)
      triggerRef.current?.querySelector<HTMLButtonElement>('button')?.focus()
    }

    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [open])

  const closeUnlessResizing = () => {
    if (sidebarRef.current?.closest('.app-shell')?.classList.contains('sidebar-resizing')) return
    setPreviewOpen(false)
  }

  const handleBoundaryPointerLeave: PointerEventHandler<HTMLDivElement> = (event) => {
    const nextTarget = event.relatedTarget
    if (nextTarget instanceof Node && sidebarRef.current?.contains(nextTarget)) return
    closeUnlessResizing()
  }

  const handleSidebarPointerLeave: PointerEventHandler<HTMLElement> = (event) => {
    const boundaryRect = boundaryRef.current?.getBoundingClientRect()
    if (
      boundaryRect
      && event.clientX >= boundaryRect.left
      && event.clientX <= boundaryRect.right
      && event.clientY >= boundaryRect.top
      && event.clientY <= boundaryRect.bottom
    ) return
    closeUnlessResizing()
  }

  const handleSidebarFocusCapture: FocusEventHandler<HTMLElement> = () => {
    if (collapsed) setPreviewOpen(true)
  }
  const handleSidebarBlurCapture: FocusEventHandler<HTMLElement> = () => {
    window.requestAnimationFrame(() => {
      const activeElement = document.activeElement
      if (activeElement && (sidebarRef.current?.contains(activeElement) || triggerRef.current?.contains(activeElement))) return
      closeUnlessResizing()
    })
  }

  return <>
    {collapsed ? <div className="desktop-sidebar-grid-slot" aria-hidden="true" /> : null}

    {collapsed ? <div
      ref={triggerRef}
      className="desktop-sidebar-preview-trigger"
      data-open={open}
      data-testid="desktop-sidebar-preview-trigger"
      onPointerEnter={(event) => {
        if (event.pointerType !== 'touch') setPreviewOpen(true)
      }}
    >
      <button
        className="desktop-navigation-toggle"
        type="button"
        aria-label={label}
        aria-controls="primary-sidebar"
        aria-expanded={open}
        onFocus={() => setPreviewOpen(true)}
        onClick={pinOpen}
      >
        <NavigationMenuIcon variant="expand" />
      </button>
    </div> : null}

    {open ? <div
      ref={boundaryRef}
      className="desktop-sidebar-preview-boundary"
      data-testid="desktop-sidebar-preview-boundary"
      onPointerLeave={handleBoundaryPointerLeave}
    /> : null}

    {children({
      open,
      pinOpen,
      sidebarRef,
      sidebarInteractionProps: {
        onPointerLeave: handleSidebarPointerLeave,
        onFocusCapture: handleSidebarFocusCapture,
        onBlurCapture: handleSidebarBlurCapture,
      },
    })}
  </>
}
