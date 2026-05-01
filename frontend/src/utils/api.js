// =============================================================================
// src/utils/api.js
// All HTTP and WebSocket helpers for Assignment 3
// WebSocket binary audio channel: /ws/chat
// =============================================================================

// ---------------------------------------------------------------------------
// Base URLs — picked up from Vite proxy in dev, relative paths in prod
// ---------------------------------------------------------------------------
const API_BASE = import.meta.env.VITE_API_BASE_URL || ''
const WS_BASE  = import.meta.env.VITE_WS_BASE_URL  ||
  (window.location.protocol === 'https:' ? 'wss:' : 'ws:') +
  '//' + window.location.host

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
export function generateSessionId() {
  return crypto.randomUUID()
}

function sanitize(text) {
  const el = document.createElement('div')
  el.textContent = text
  return el.innerHTML
}

async function jsonFetch(path, options = {}) {
  const res = await fetch(API_BASE + path, {
    credentials: 'include',       // send HttpOnly JWT cookie
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw Object.assign(new Error(err.detail || 'Request failed'), { status: res.status })
  }
  return res.json()
}

// ---------------------------------------------------------------------------
// Auth endpoints
// ---------------------------------------------------------------------------
export async function login(username, password) {
  return jsonFetch('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ username: sanitize(username), password }),
  })
}

export async function logout() {
  return jsonFetch('/auth/logout', { method: 'POST' })
}

export async function register(username, email, password) {
  return jsonFetch('/auth/register', {
    method: 'POST',
    body: JSON.stringify({ username: sanitize(username), email, password }),
  })
}

export async function refreshToken() {
  return jsonFetch('/auth/refresh', { method: 'POST' })
}

// ---------------------------------------------------------------------------
// Session endpoints
// ---------------------------------------------------------------------------
export async function healthCheck() {
  return jsonFetch('/health')
}

export async function getWelcome(sessionId) {
  return jsonFetch(`/session/welcome/${sessionId}`)
}

export async function resetSession(sessionId) {
  return jsonFetch('/reset', {
    method: 'POST',
    body: JSON.stringify({ session_id: sessionId }),
  })
}

export async function getSessions() {
  return jsonFetch('/sessions')
}

export async function getSession(sessionId) {
  return jsonFetch(`/sessions/${sessionId}`)
}

export async function deleteSession(sessionId) {
  return jsonFetch(`/sessions/${sessionId}`, { method: 'DELETE' })
}

// ---------------------------------------------------------------------------
// WebSocket factory — /ws/chat?session_id=<uuid>
// The backend auto-detects binary (audio) vs text (JSON) frames.
// ---------------------------------------------------------------------------
export function createChatWebSocket(sessionId, token) {
  const params = new URLSearchParams({ session_id: sessionId })
  if (token) params.set('token', token)
  return new WebSocket(`${WS_BASE}/ws/chat?${params.toString()}`)
}

// ---------------------------------------------------------------------------
// Text-fallback: send JSON message through an open WebSocket
// ---------------------------------------------------------------------------
export function sendTextFrame(ws, sessionId, message) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ session_id: sessionId, message: sanitize(message) }))
    return true
  }
  return false
}
