// =============================================================================
// src/hooks/useVoiceChat.js
// Primary A3 hook: binary audio WebSocket + chat state machine
//
// Voice mode  → MediaRecorder sends WebM binary → backend STT→LLM→TTS → WAV back
// Text mode   → sends JSON text frame → backend streams tokens back
// =============================================================================
import { useState, useRef, useCallback, useEffect } from 'react'
import {
  createChatWebSocket,
  sendTextFrame,
  getWelcome,
  resetSession,
  getSession,
  generateSessionId,
  deleteSession,
} from '../utils/api.js'

const MIME = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
  ? 'audio/webm;codecs=opus'
  : 'audio/webm'

export default function useVoiceChat({ token } = {}) {
  const [messages, setMessages]     = useState([])
  const [isLoading, setIsLoading]   = useState(false)
  const [micState, setMicState]     = useState('idle')   // idle|requesting|recording|processing
  const [isPlaying, setIsPlaying]   = useState(false)
  const [status, setStatus]         = useState('active') // active|ended
  const [turnsUsed, setTurnsUsed]   = useState(0)
  const [turnsMax, setTurnsMax]     = useState(15)
  const [voiceError, setVoiceError] = useState(null)

  const sessionIdRef = useRef(generateSessionId())
  const wsRef        = useRef(null)
  const recorderRef  = useRef(null)
  const streamRef    = useRef(null)
  const audioRef     = useRef(null)
  const reconnTimer  = useRef(null)
  const tokenRef     = useRef(token)   // always holds latest token without recreating connect

  // Keep tokenRef in sync whenever the token prop changes
  useEffect(() => { tokenRef.current = token }, [token])

  // ---------------------------------------------------------------------------
  // WebSocket lifecycle
  // ---------------------------------------------------------------------------
  const connect = useCallback(() => {
    if (wsRef.current && wsRef.current.readyState < 2) return // already open/connecting

    const ws = createChatWebSocket(sessionIdRef.current, tokenRef.current)
    wsRef.current = ws

    ws.onopen = () => {
      clearTimeout(reconnTimer.current)
    }

    ws.onmessage = async (event) => {
      // Binary frame = TTS audio or streamed WAV
      if (event.data instanceof Blob) {
        setIsPlaying(true)
        const url = URL.createObjectURL(event.data)
        const audio = new Audio(url)
        audioRef.current = audio
        audio.onended = () => { setIsPlaying(false); URL.revokeObjectURL(url) }
        audio.onerror = () => { setIsPlaying(false); URL.revokeObjectURL(url) }
        try { await audio.play() } catch { setIsPlaying(false) }
        return
      }

      // Text frame = JSON control message
      try {
        const msg = JSON.parse(event.data)

        if (msg.event === 'turn_complete') {
          // Add the decoded voice message text to the UI
          if (msg.user_text || msg.assistant_text) {
             setMessages(prev => {
                const newMsgs = [...prev]
                // Replace the temporary "🎤 Voice message" with the actual user_text (or remove if blank)
                const lastIdx = newMsgs.findLastIndex(m => m.isVoice && m.role === 'user')
                if (lastIdx !== -1) {
                   newMsgs[lastIdx] = { 
                     ...newMsgs[lastIdx], 
                     content: msg.user_text || '(Unintelligible audio)',
                     isVoice: false // no longer just a placeholder
                   }
                }
                
                // Add the assistant's reply text
                if (msg.assistant_text) {
                  newMsgs.push({
                     role: 'assistant',
                     content: msg.assistant_text,
                     timestamp: new Date().toISOString()
                  })
                }
                return newMsgs
             })
          }

          setTurnsUsed(msg.turns_used ?? 0)
          setTurnsMax(msg.turns_max ?? 15)
          if (msg.status === 'ended') setStatus('ended')
          setMicState('idle')
          setIsLoading(false)
          return
        }

        if (msg.event === 'error') {
          setVoiceError(msg.detail || 'An error occurred.')
          setMicState('idle')
          setIsLoading(false)
          return
        }

        // Legacy A2 text streaming: { token, done, full_response, latency_ms }
        if ('token' in msg) {
          if (!msg.done) {
            setMessages(prev => {
              const last = prev[prev.length - 1]
              if (last && last.streaming) {
                return [...prev.slice(0, -1), { ...last, content: last.content + msg.token }]
              }
              return [...prev, {
                role: 'assistant', content: msg.token,
                streaming: true, timestamp: new Date().toISOString(),
              }]
            })
          } else {
            // done frame: finalise message and attach latency
            setMessages(prev => {
              const last = prev[prev.length - 1]
              if (last && last.streaming) {
                return [...prev.slice(0, -1), {
                  ...last,
                  content: msg.full_response || last.content,
                  streaming: false,
                  latency_ms: msg.latency_ms ?? null,
                }]
              }
              return prev
            })
            // Surface session state from done frame
            if (msg.status) setStatus(msg.status)
            if (msg.turns_used !== undefined) setTurnsUsed(msg.turns_used)
            if (msg.turns_max  !== undefined) setTurnsMax(msg.turns_max)
            setIsLoading(false)
          }
          return
        }

        // Session state from text fallback
        if (msg.status) {
          setStatus(msg.status)
          if (msg.turns_used !== undefined) setTurnsUsed(msg.turns_used)
          if (msg.turns_max  !== undefined) setTurnsMax(msg.turns_max)
        }
      } catch { /* non-JSON text, ignore */ }
    }

    ws.onclose = () => {
      reconnTimer.current = setTimeout(connect, 2000)
    }
  }, [])

  // Connect & load welcome on mount
  useEffect(() => {
    connect()
    getWelcome(sessionIdRef.current)
      .then(({ response }) => {
        setMessages([{
          role: 'assistant', content: response,
          timestamp: new Date().toISOString(),
        }])
      })
      .catch(() => {
        setMessages([{
          role: 'assistant',
          content: "Hi! I'm Daraz Assistant 🛍️. What are you looking to buy today?",
          timestamp: new Date().toISOString(),
        }])
      })

    return () => {
      clearTimeout(reconnTimer.current)
      wsRef.current?.close()
    }
  }, [connect])

  // ---------------------------------------------------------------------------
  // Text send (fallback mode, also used by QuickActions)
  // ---------------------------------------------------------------------------
  const send = useCallback((text) => {
    if (!text.trim() || status === 'ended') return
    const userMsg = { role: 'user', content: text, timestamp: new Date().toISOString() }
    setMessages(prev => [...prev, userMsg])
    setIsLoading(true)
    sendTextFrame(wsRef.current, sessionIdRef.current, text)
  }, [status])

  // ---------------------------------------------------------------------------
  // Voice recording
  // ---------------------------------------------------------------------------
  const startRecording = useCallback(async () => {
    if (micState !== 'idle' || status === 'ended') return
    setMicState('requesting')
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      streamRef.current = stream
      const recorder = new MediaRecorder(stream, { mimeType: MIME })
      recorderRef.current = recorder

      // Add outgoing voice message placeholder
      const voiceMsg = {
        role: 'user', content: '🎤 Voice message', isVoice: true,
        timestamp: new Date().toISOString(),
      }
      setMessages(prev => [...prev, voiceMsg])
      setIsLoading(true)

      const chunks = []
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunks.push(e.data)
      }
      recorder.onstop = () => {
        if (wsRef.current?.readyState === WebSocket.OPEN) {
          const blob = new Blob(chunks, { type: MIME })
          wsRef.current.send(blob)           // send full audio file → backend STT+LLM+TTS
        }
      }

      recorder.start()  // collect until stopped
      setMicState('recording')
    } catch (err) {
      setVoiceError('Microphone access denied.')
      setMicState('idle')
    }
  }, [micState, status])

  const stopRecording = useCallback(() => {
    if (micState !== 'recording') return
    recorderRef.current?.stop()
    streamRef.current?.getTracks().forEach(t => t.stop())
    setMicState('processing')
  }, [micState])

  // ---------------------------------------------------------------------------
  // Stop TTS playback
  // ---------------------------------------------------------------------------
  const stopSpeaking = useCallback(() => {
    if (audioRef.current) {
      audioRef.current.pause()
      audioRef.current = null
      setIsPlaying(false)
    }
  }, [])

  // ---------------------------------------------------------------------------
  // New chat / reset
  // ---------------------------------------------------------------------------
  const reset = useCallback(async () => {
    stopSpeaking()
    recorderRef.current?.stop()
    streamRef.current?.getTracks().forEach(t => t.stop())
    setMicState('idle')
    setIsLoading(false)
    setIsPlaying(false)
    setVoiceError(null)

    await resetSession(sessionIdRef.current).catch(() => {})
    sessionIdRef.current = generateSessionId()
    wsRef.current?.close()
    setMessages([])
    setStatus('active')
    setTurnsUsed(0)

    // Small delay for WS to re-connect, then fetch new welcome
    setTimeout(() => {
      connect()
      getWelcome(sessionIdRef.current)
        .then(({ response }) => {
          setMessages([{ role: 'assistant', content: response, timestamp: new Date().toISOString() }])
        })
        .catch(() => {})
    }, 200)
  }, [connect, stopSpeaking])

  // ---------------------------------------------------------------------------
  // Load a previous session from history
  // ---------------------------------------------------------------------------
  const loadSession = useCallback(async (sid) => {
    try {
      const data = await getSession(sid)
      sessionIdRef.current = sid
      wsRef.current?.close()
      setMessages(data.history.map(m => ({
        role: m.role, content: m.content, timestamp: m.timestamp || new Date().toISOString(),
      })))
      setStatus(data.status || 'active')
      setTurnsUsed(data.turns || 0)
      setTurnsMax(data.turns_max || 15)
      setTimeout(connect, 200)
    } catch (err) {
      setVoiceError('Failed to load session.')
    }
  }, [connect])

  const clearVoiceError = useCallback(() => setVoiceError(null), [])

  return {
    messages,
    isLoading,
    micState,
    isPlaying,
    status,
    turnsUsed,
    turnsMax,
    voiceError,
    sessionId: sessionIdRef.current,
    send,
    startRecording,
    stopRecording,
    stopSpeaking,
    reset,
    loadSession,
    clearVoiceError,
  }
}
