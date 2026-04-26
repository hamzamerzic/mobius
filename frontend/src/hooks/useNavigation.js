import { useState, useEffect, useRef } from 'react'

const ACTIVE_CHAT_KEY = 'moebius_active_chat'

// Parse shell-reload state (shell rebuild preserves view across reload).
const shellReload = (() => {
  const raw = sessionStorage.getItem('shell-reload')
  if (!raw) return null
  sessionStorage.removeItem('shell-reload')
  try { return JSON.parse(raw) } catch { return null }
})()

// Parse deep-link URL (push notification taps land on /app/:id or /chat/:id).
const deepLink = (() => {
  const path = window.location.pathname
  const appMatch = path.match(/^\/app\/([^/]+)$/)
  const chatMatch = path.match(/^\/chat\/([^/]+)$/)
  if (appMatch) return { view: 'canvas', appId: parseInt(appMatch[1], 10) }
  if (chatMatch) return { view: 'chat', chatId: chatMatch[1] }
  return null
})()

/**
 * Manages navigation state with a custom back stack.
 *
 * We maintain our own navigation stack instead of using pushState,
 * because Chrome Android caches full page state for each history
 * entry and shows it during the back gesture — including the drawer.
 *
 * A single sentinel entry sits on top of the base entry. When back
 * fires, popstate runs, we apply state from our stack, and re-push
 * the sentinel. Chrome only ever sees one cached page (the sentinel).
 */
export default function useNavigation() {
  const [activeView, setActiveView] = useState(
    shellReload?.activeView || deepLink?.view || 'chat'
  )
  const [activeAppId, setActiveAppId] = useState(
    shellReload?.activeAppId || deepLink?.appId || null
  )
  const [activeChatId, setActiveChatId] = useState(
    () => shellReload?.activeChatId || deepLink?.chatId || localStorage.getItem(ACTIVE_CHAT_KEY) || null
  )
  const [drawerOpen, setDrawerOpen] = useState(false)

  const navStackRef = useRef([])
  const activeChatIdRef = useRef(activeChatId)
  activeChatIdRef.current = activeChatId
  const activeViewRef = useRef(activeView)
  activeViewRef.current = activeView
  const activeAppIdRef = useRef(activeAppId)
  activeAppIdRef.current = activeAppId
  const drawerOpenRef = useRef(drawerOpen)
  drawerOpenRef.current = drawerOpen
  // Android back gesture synthesizes a click on the logo ~300ms later.
  const backFiredRef = useRef(false)
  // True when openDrawer pushed an entry that hasn't been consumed yet.
  const drawerPushedRef = useRef(false)

  // Drawer-as-back-stack pattern: openDrawer pushes a history sentinel,
  // closeDrawer triggers history.back() to pop it, and handleBack is the
  // single place that flips drawerOpen state to false. This means there's
  // exactly one path that closes the drawer, no matter who initiates it
  // (X button, back gesture, swipe-to-close): everything funnels through
  // popstate -> handleBack. No coordination flags, no race windows.
  function openDrawer() {
    if (drawerOpenRef.current) return
    history.pushState(null, '')
    drawerPushedRef.current = true
    setDrawerOpen(true)
  }

  function closeDrawer() {
    if (!drawerOpenRef.current) return
    if (drawerPushedRef.current) {
      // Funnel through history.back() so handleBack handles the state
      // change. Without this every open/close cycle leaks a sentinel
      // entry and the user has to press back once per cycle before the
      // app actually navigates back.
      history.back()
    } else {
      // Defensive: if somehow drawer is open without a sentinel, just
      // close it directly.
      drawerOpenRef.current = false
      setDrawerOpen(false)
    }
  }

  function navTo(view, opts = {}) {
    drawerPushedRef.current = false
    navStackRef.current.push({
      view: activeViewRef.current,
      chatId: activeChatIdRef.current,
      appId: activeAppIdRef.current,
    })
    setDrawerOpen(false)
    setActiveView(view)
    if ('chatId' in opts) setActiveChatId(opts.chatId)
    if ('appId' in opts) setActiveAppId(opts.appId)
  }

  useEffect(() => {
    history.replaceState(null, '', '/')

    function handleBack() {
      backFiredRef.current = true
      setTimeout(() => { backFiredRef.current = false }, 400)
      // Drawer-first: if the drawer is open, closing it consumes this
      // back event. The user expects "back closes the drawer," not
      // "back closes the drawer AND navigates one step." If the drawer
      // wasn't pushed (defensive), still close it but don't return.
      if (drawerOpenRef.current && drawerPushedRef.current) {
        drawerPushedRef.current = false
        drawerOpenRef.current = false
        setDrawerOpen(false)
        return
      }
      // No drawer (or drawer closed without a sentinel): treat as a
      // real navigation back — pop the nav stack.
      drawerPushedRef.current = false
      drawerOpenRef.current = false
      setDrawerOpen(false)
      const entry = navStackRef.current.pop()
      if (entry) {
        setActiveView(entry.view)
        setActiveChatId(entry.chatId)
        setActiveAppId(entry.appId)
      }
    }

    // Navigation API intercept() suppresses Chrome's back-forward slide
    // on desktop. When available, use exclusively (no popstate) to avoid
    // double-popping the nav stack.
    if (typeof navigation !== 'undefined' && navigation.addEventListener) {
      function onNavigate(e) {
        if (e.navigationType !== 'traverse') return
        if (!e.canIntercept) return
        // Nothing to do — let the browser handle it (exits PWA).
        if (navStackRef.current.length === 0 && !drawerOpenRef.current) return
        e.intercept({ handler() { handleBack() } })
      }
      navigation.addEventListener('navigate', onNavigate)
      return () => navigation.removeEventListener('navigate', onNavigate)
    }

    // Fallback for browsers without Navigation API.
    function onPopState() {
      if (navStackRef.current.length === 0 && !drawerOpenRef.current) return
      handleBack()
    }
    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [])

  // Fade back in after shell-reload.
  useEffect(() => {
    if (!shellReload) return
    document.body.style.transition = 'opacity 0.2s ease'
    document.body.style.opacity = '1'
  }, [])

  // Persist active chat id locally.
  useEffect(() => {
    if (activeChatId) localStorage.setItem(ACTIVE_CHAT_KEY, activeChatId)
  }, [activeChatId])

  return {
    activeView,
    setActiveView,
    activeAppId,
    setActiveAppId,
    activeChatId,
    setActiveChatId,
    drawerOpen,
    openDrawer,
    closeDrawer,
    navTo,
    canGoBack: navStackRef.current.length > 0,
    backFiredRef,
    drawerPushedRef,
    navStackRef,
    activeViewRef,
    activeChatIdRef,
    activeAppIdRef,
  }
}
