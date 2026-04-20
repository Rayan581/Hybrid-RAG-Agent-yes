# Frontend Properties — Daraz Smart Assistant

A complete reference for recreating this frontend in another app.

---

## 1. Tech Stack

| Tool | Version | Role |
|---|---|---|
| **React** | ^19.2.0 | UI framework |
| **Vite** | ^7.3.1 | Build tool / dev server (port 3000) |
| **Tailwind CSS** | ^4.2.1 | Utility-first CSS (via `@tailwindcss/vite` plugin) |
| **Framer Motion** | ^12.35.0 | Animations & transitions |
| **Lucide React** | ^0.577.0 | Icon library |

**Entry point:** [index.html](file:///mnt/d/FAST%20Tasks/6th%20Semester/NLP/Assignment_2/frontend/index.html) → [src/main.jsx](file:///mnt/d/FAST%20Tasks/6th%20Semester/NLP/Assignment_2/frontend/src/main.jsx) → [src/App.jsx](file:///mnt/d/FAST%20Tasks/6th%20Semester/NLP/Assignment_2/frontend/src/App.jsx)

---

## 2. Design System

### Color Palette (CSS Custom Properties in [index.css](file:///mnt/d/FAST%20Tasks/6th%20Semester/NLP/Assignment_2/frontend/src/index.css))

```css
--daraz-orange:      #F57224   /* primary brand / CTA */
--daraz-orange-dark: #e0621a   /* hover state */
--daraz-bg:          #f5f5f5   /* page background */
--daraz-accent:      #4A90D9   /* secondary accent (reserved) */
```

Other colors used inline:
- White `#ffffff` — card backgrounds, nav
- Gray scale: `gray-50/100/200/300/400/500/700/800/900`
- Red `red-500` / `red-50` — errors, recording state
- Green `green-400/500` — online status indicator
- Orange `orange-50/100` — session ended banner, subtle highlights
- Yellow `yellow-400` — star ratings

### Typography

- **Font family:** `'Segoe UI', system-ui, -apple-system, sans-serif` (set on `html, body`)
- No external font CDN is used.
- `-webkit-font-smoothing: antialiased` applied globally.

### Spacing & Sizing Conventions

- Rounded corners: `rounded-full` (pills/avatars), `rounded-2xl` (cards/chat window), `rounded-xl` (product cards)
- Chat window: `w-[380px] h-[600px]` (widget), `max-w-3xl mx-auto` (full-page)
- FAB button: `w-14 h-14`
- Avatars: `w-8 h-8` (messages), `w-10 h-10` (header)
- Header logo icon: `w-20 h-20` (hero), `w-8 h-8` (nav bar)

---

## 3. CSS Animations ([src/index.css](file:///mnt/d/FAST%20Tasks/6th%20Semester/NLP/Assignment_2/frontend/src/index.css))

| Class | Keyframe | Purpose |
|---|---|---|
| `.typing-dot` | `bounce-dot` | 3-dot typing indicator bounce (staggered 0s / 0.16s / 0.32s) |
| `.pulse-ring` | `pulse-ring` | Online status pulsing green ring (1.5s) |
| `.mic-pulse-ring` | `mic-pulse` | Red expanding ring while mic is recording (1.1s, 2 rings staggered 0.55s) |
| `.eq-bar` | `eq-bar` | Equalizer bars during recording/speaking (5 bars, staggered 0–0.3s) |

Custom scrollbar styling on `.chat-scroll`: 6px thumb, `#ccc` → `#aaa` on hover.

---

## 4. File Structure

```
src/
├── App.jsx                    # Root — landing page + mode switch
├── main.jsx                   # ReactDOM.createRoot entry
├── index.css                  # Global styles + Tailwind import
├── components/
│   ├── ChatWidget.jsx         # Floating widget (FAB + popup window)
│   ├── ChatWindow.jsx         # Core chat UI shell
│   ├── ChatHeader.jsx         # Window header bar
│   ├── InputBar.jsx           # Text input + send + mic
│   ├── MessageBubble.jsx      # Single message row
│   ├── TypingIndicator.jsx    # Animated 3-dot "typing" bubble
│   ├── QuickActions.jsx       # Suggested query chips
│   ├── ProductCard.jsx        # Horizontal-scroll product card
│   ├── SessionSidebar.jsx     # Slide-in chat history panel
│   ├── SpeakButton.jsx        # TTS play/stop button per message
│   ├── VoiceMicButton.jsx     # ASR mic record button
│   └── FullPageChat.jsx       # Full-screen chat layout wrapper
├── hooks/
│   ├── useChat.js             # WebSocket chat + session state
│   └── useVoice.js            # Mic recording + TTS playback
└── utils/
    └── api.js                 # All fetch/WebSocket API calls
```

---

## 5. Components

### [App.jsx](file:///mnt/d/FAST%20Tasks/6th%20Semester/NLP/Assignment_2/frontend/src/App.jsx)
- **States:** `mode` (`'widget'` | `'fullpage'`), `backendStatus` (`'checking'` | `'online'` | `'offline'`)
- **Layout (widget mode):**
  - Fixed nav bar (top): logo + status dot + "Open Full Chat" button
  - Centered hero section: large icon, h1, subtitle paragraph, 3 feature pills, hint text
  - Floating `<ChatWidget>` (bottom-right)
- **Layout (fullpage mode):** full-screen `<FullPageChat>` + "Switch to Widget" button top-right
- Calls [healthCheck()](file:///mnt/d/FAST%20Tasks/6th%20Semester/NLP/Assignment_2/frontend/src/utils/api.js#38-43) on mount to set `backendStatus`

---

### [ChatWidget.jsx](file:///mnt/d/FAST%20Tasks/6th%20Semester/NLP/Assignment_2/frontend/src/components/ChatWidget.jsx)
- **States:** `isOpen` (boolean)
- **FAB:** Fixed bottom-right, `w-14 h-14`, orange `#F57224`, `MessageCircle` icon ↔ `✕` (animated swap)
- **Popup window:** Framer Motion spring animation, `w-[380px] h-[600px]`, full-screen on `max-[480px]`
- **Badge:** Tooltip "💬 Need help shopping?" appears above FAB with 1s delay when closed
- Shares a single [useChat()](file:///mnt/d/FAST%20Tasks/6th%20Semester/NLP/Assignment_2/frontend/src/hooks/useChat.js#4-202) instance passed as `chat` prop to `<ChatWindow>`

---

### [ChatWindow.jsx](file:///mnt/d/FAST%20Tasks/6th%20Semester/NLP/Assignment_2/frontend/src/components/ChatWindow.jsx)
Props: `chat`, `onMinimize`, `onClose`

- Container: `flex flex-col h-full bg-[#f5f5f5] rounded-2xl shadow-2xl`
- Instantiates [useVoice({ onTranscript: send })](file:///mnt/d/FAST%20Tasks/6th%20Semester/NLP/Assignment_2/frontend/src/hooks/useVoice.js#12-157)
- **Auto-scroll:** scrolls to bottom on every new message
- **Auto-play TTS:** when `voice.autoPlay` is on, speaks every new non-streaming assistant message
- **Voice error toast:** animated red banner (`bg-red-50 border-red-200`) that auto-dismisses after 4s
- **Session ended banner:** orange-tinted strip with "Start New Chat" link when `status === 'ended'`
- Quick actions shown only when there is exactly 1 assistant message (welcome state)
- `<TypingIndicator>` shown when `isLoading && !messages.some(m => m.streaming)`

---

### [ChatHeader.jsx](file:///mnt/d/FAST%20Tasks/6th%20Semester/NLP/Assignment_2/frontend/src/components/ChatHeader.jsx)
Props: `onReset`, `onMinimize?`, `onClose?`, `onToggleHistory?`, `autoPlay`, `onToggleAutoPlay?`

- Background: `bg-gradient-to-r from-[#F57224] to-[#ff8c42]`
- Left side: `w-10 h-10` frosted-glass avatar → `ShoppingBag` icon + title + animated green online dot
- Right side (icon buttons, `p-2 rounded-full hover:bg-white/20`):
  - **Auto-play toggle:** `Volume2` (ON) / `VolumeX` (OFF) with green indicator dot when active
  - **History:** `History` icon
  - **New Chat:** `RotateCcw` icon
  - **Minimize:** `Minus` icon (optional)
  - **Close:** `X` icon (optional)

---

### [InputBar.jsx](file:///mnt/d/FAST%20Tasks/6th%20Semester/NLP/Assignment_2/frontend/src/components/InputBar.jsx)
Props: `onSend`, `disabled`, `voice`

- Container: `flex items-center gap-2 px-3 py-3 bg-white border-t border-gray-100`
- **Mic button:** `<VoiceMicButton>` (left)
- **Text input:** `flex-1`, `bg-gray-50 border border-gray-200 rounded-full`, focus ring `#F57224`
  - Placeholder changes: "Ask about products…" / "Listening…" / "Transcribing…" / "Session ended…"
  - Disabled when session ended or voice is busy
- **Send button:** `<Send>` icon in orange circle, disabled when empty or voice busy
- Submit on Enter (not Shift+Enter)

---

### [MessageBubble.jsx](file:///mnt/d/FAST%20Tasks/6th%20Semester/NLP/Assignment_2/frontend/src/components/MessageBubble.jsx)
Props: `message { role, content, timestamp, streaming?, isError?, cancelled?, latency_ms? }`, `isLast`, `voice`

- **User bubble:** right-aligned, `bg-[#F57224] text-white rounded-2xl rounded-tr-sm`
- **Bot bubble:** left-aligned, `bg-white text-gray-800 rounded-2xl rounded-tl-sm border border-gray-100`
  - Error state adds `border-red-200 bg-red-50`
  - Active TTS adds `ring-2 ring-[#F57224]/30`
- **Bot avatar:** `w-8 h-8` gradient orange circle with letter "D"
- **User avatar:** `w-8 h-8` `bg-gray-700` circle with letter "U"
- **Streaming cursor:** blinking orange `w-1.5 h-4` block appended during streaming
- **Cancelled tag:** `"Generation stopped"` in italic orange below content
- **Timestamp + latency row:** `text-[10px] text-gray-400`, latency shown as `• 1.2s`
- **`<SpeakButton>`:** shown on all non-user, non-streaming, non-error bubbles

---

### [TypingIndicator.jsx](file:///mnt/d/FAST%20Tasks/6th%20Semester/NLP/Assignment_2/frontend/src/components/TypingIndicator.jsx)
- Bot avatar (same style as MessageBubble) + white bubble with 3 `.typing-dot` spans + "Daraz Assistant is typing..." label
- Wrapped in Framer Motion for enter/exit fade + slide

---

### [QuickActions.jsx](file:///mnt/d/FAST%20Tasks/6th%20Semester/NLP/Assignment_2/frontend/src/components/QuickActions.jsx)
- 5 pill buttons: Best Deals (🔥), Phones (📱), Electronics (🖥), Fashion (👕), Laptops (💻)
- Framer `whileHover` scale + `whileTap` scale; orange border/text on hover
- Appear with `delay: 0.3` fade-in after first welcome message

---

### [ProductCard.jsx](file:///mnt/d/FAST%20Tasks/6th%20Semester/NLP/Assignment_2/frontend/src/components/ProductCard.jsx)
Props: `product { name, price, rating, image, url }`

- `w-52 shrink-0` card in horizontal scroll row
- `h-36` image area with placeholder fallback (`placehold.co`)
- Price in `text-[#F57224] font-bold`
- Star ratings using `lucide-react` `Star` icons (filled yellow / gray)
- "View Product" CTA link → opens in new tab

---

### [SessionSidebar.jsx](file:///mnt/d/FAST%20Tasks/6th%20Semester/NLP/Assignment_2/frontend/src/components/SessionSidebar.jsx)
Props: `currentSessionId`, `onLoadSession`, `onNewChat`, `isOpen`, `onClose`, `turnsMax`

- `fixed left-0 top-0 bottom-0 w-80 bg-white z-[70]` panel
- Spring slide-in from left (`x: -320 → 0`)
- Backdrop: `bg-black/30 backdrop-blur-sm z-[60]`
- Header: same orange gradient as [ChatHeader](file:///mnt/d/FAST%20Tasks/6th%20Semester/NLP/Assignment_2/frontend/src/components/ChatHeader.jsx#4-91), with `+` (new chat) and `←` (close) buttons
- Session list items: show title, preview text, relative time, turns/max, message count, "Ended" badge
- Active session: `bg-orange-50 border-l-4 border-l-[#F57224]`; `whileHover={{ x: 4 }}`
- Delete button per item: `Trash2`, visible only on hover (`opacity-0 group-hover:opacity-100`)
- Empty state: `MessageSquare` icon + helper text

---

### [SpeakButton.jsx](file:///mnt/d/FAST%20Tasks/6th%20Semester/NLP/Assignment_2/frontend/src/components/SpeakButton.jsx)
Props: `text`, `playbackState`, `isThisPlaying`, `onSpeak`, `onStop`

- Small pill: `px-2 py-1 rounded-full text-[10px]`
- **Idle:** `Volume2` + "Speak" text, gray border
- **Loading:** `Loader2` spinning icon
- **Playing:** animated `<WaveformBars>` (eq-bar animation) + `Square` stop icon, orange border

---

### [VoiceMicButton.jsx](file:///mnt/d/FAST%20Tasks/6th%20Semester/NLP/Assignment_2/frontend/src/components/VoiceMicButton.jsx)
Props: `micState` (`'idle'|'requesting'|'recording'|'transcribing'`), `onStart`, `onStop`, `disabled`

- `w-9 h-9 rounded-full`
- **Idle:** `bg-orange-50 text-[#F57224]` + [Mic](file:///mnt/d/FAST%20Tasks/6th%20Semester/NLP/Assignment_2/frontend/src/components/VoiceMicButton.jsx#28-142) icon
- **Requesting:** `bg-orange-100` + [Mic](file:///mnt/d/FAST%20Tasks/6th%20Semester/NLP/Assignment_2/frontend/src/components/VoiceMicButton.jsx#28-142) icon (disabled)
- **Recording:** `bg-red-500 text-white` + animated `<EqualizerBars>` + 2 staggered `.mic-pulse-ring` halos
- **Transcribing:** `bg-gray-700 text-white` + `Loader2` spinning + cursor-wait
- Floating badge above button: "● Recording" (red) / "Transcribing…" (dark)

---

### [FullPageChat.jsx](file:///mnt/d/FAST%20Tasks/6th%20Semester/NLP/Assignment_2/frontend/src/components/FullPageChat.jsx)
- Instantiates its own [useChat()](file:///mnt/d/FAST%20Tasks/6th%20Semester/NLP/Assignment_2/frontend/src/hooks/useChat.js#4-202) hook
- Renders `<ChatWindow>` inside `h-screen w-full max-w-3xl mx-auto p-4 flex flex-col`

---

## 6. Hooks

### [useChat.js](file:///mnt/d/FAST%20Tasks/6th%20Semester/NLP/Assignment_2/frontend/src/hooks/useChat.js)
Returns: `{ messages, isLoading, sessionId, status, turnsUsed, turnsMax, latency, send, reset, loadSession }`

- **WebSocket:** persistent connection to `WS_BASE/chat`; auto-reconnects after 2s on close
- **Streaming:** tokens appended to a live `streaming: true` bubble; finalized on `done: true`
- **Session lifecycle:** [generateSessionId()](file:///mnt/d/FAST%20Tasks/6th%20Semester/NLP/Assignment_2/frontend/src/utils/api.js#62-65) (uses `crypto.randomUUID`), [reset()](file:///mnt/d/FAST%20Tasks/6th%20Semester/NLP/Assignment_2/frontend/src/utils/api.js#22-31) calls `POST /api/reset`, `loadSession()` calls `GET /api/sessions/:id`
- **Welcome message:** fetched from `GET /api/session/welcome/:sessionId` on mount and after reset
- **Message shape:** `{ role, content, timestamp, streaming?, isError?, cancelled?, latency_ms? }`

### [useVoice.js](file:///mnt/d/FAST%20Tasks/6th%20Semester/NLP/Assignment_2/frontend/src/hooks/useVoice.js)
Returns: `{ micState, playbackState, autoPlay, error, startRecording, stopRecording, cancelRecording, speak, stopSpeaking, toggleAutoPlay, clearError }`

- **ASR:** `navigator.mediaDevices.getUserMedia` → `MediaRecorder` (prefers `audio/webm;codecs=opus`) → `POST /api/voice/transcribe` → calls `onTranscript(text)`
- **TTS:** `POST /api/voice/synthesize` → returns audio blob → `new Audio(url).play()`
- **autoPlay:** when toggled on, [ChatWindow](file:///mnt/d/FAST%20Tasks/6th%20Semester/NLP/Assignment_2/frontend/src/components/ChatWindow.jsx#11-140) auto-calls `speak()` on each new assistant message

---

## 7. API Layer ([src/utils/api.js](file:///mnt/d/FAST%20Tasks/6th%20Semester/NLP/Assignment_2/frontend/src/utils/api.js))

| Function | Method | Endpoint |
|---|---|---|
| [healthCheck()](file:///mnt/d/FAST%20Tasks/6th%20Semester/NLP/Assignment_2/frontend/src/utils/api.js#38-43) | GET | `/api/health` |
| [getWelcome(sessionId)](file:///mnt/d/FAST%20Tasks/6th%20Semester/NLP/Assignment_2/frontend/src/utils/api.js#32-37) | GET | `/api/session/welcome/:id` |
| [sendMessage(sid, msg)](file:///mnt/d/FAST%20Tasks/6th%20Semester/NLP/Assignment_2/frontend/src/utils/api.js#12-21) | POST | `/api/chat` |
| [resetSession(sid)](file:///mnt/d/FAST%20Tasks/6th%20Semester/NLP/Assignment_2/frontend/src/utils/api.js#22-31) | POST | `/api/reset` |
| [getSessions()](file:///mnt/d/FAST%20Tasks/6th%20Semester/NLP/Assignment_2/frontend/src/utils/api.js#44-49) | GET | `/api/sessions` |
| [getSession(sid)](file:///mnt/d/FAST%20Tasks/6th%20Semester/NLP/Assignment_2/frontend/src/utils/api.js#50-55) | GET | `/api/sessions/:id` |
| [deleteSession(sid)](file:///mnt/d/FAST%20Tasks/6th%20Semester/NLP/Assignment_2/frontend/src/utils/api.js#56-61) | DELETE | `/api/sessions/:id` |
| [transcribeAudio(blob)](file:///mnt/d/FAST%20Tasks/6th%20Semester/NLP/Assignment_2/frontend/src/utils/api.js#71-85) | POST | `/api/voice/transcribe` (FormData `audio` field) |
| [synthesizeSpeech(text)](file:///mnt/d/FAST%20Tasks/6th%20Semester/NLP/Assignment_2/frontend/src/utils/api.js#86-99) | POST | `/api/voice/synthesize` (JSON `{ text }`) → audio blob |
| WebSocket chat | WS | `WS_BASE/chat` (send `{ session_id, message }`) |

**Base URL logic:**
- Dev: set `VITE_API_BASE_URL=http://localhost:8000` and `VITE_WS_BASE_URL=ws://localhost:8000` in [.env](file:///mnt/d/FAST%20Tasks/6th%20Semester/NLP/Assignment_2/frontend/.env)
- Docker/prod: env vars empty → uses relative `/api` and auto-detects `ws://` vs `wss://` from `window.location`

---

## 8. Vite Dev Server Proxy

```js
proxy: {
  '/api':       'http://localhost:8000',
  '/ws':        { target: 'ws://localhost:8000', ws: true },
  '/voice':     'http://localhost:8000',
  '/sessions':  'http://localhost:8000',
  // ... (chat, reset, health, session, benchmark)
}
```

---

## 9. Key Framer Motion Patterns

| Pattern | Usage |
|---|---|
| `initial/animate/exit` with `AnimatePresence` | Chat popup, sidebar, error toast, typing indicator |
| `type: 'spring', stiffness: 300, damping: 25` | Chat window open/close |
| `type: 'spring', stiffness: 300, damping: 30` | Sidebar slide |
| `whileHover={{ scale: 1.1 }} whileTap={{ scale: 0.9 }}` | FAB, header buttons |
| `whileHover={{ scale: 1.05 }} whileTap={{ scale: 0.95 }}` | Quick action chips |
| `AnimatePresence mode="wait"` | Icon swap in FAB and VoiceMicButton |
| `whileHover={{ x: 4 }}` | Session sidebar items |
