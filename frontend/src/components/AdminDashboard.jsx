// =============================================================================
// src/components/AdminDashboard.jsx
// Admin dashboard: live sessions, compaction health, benchmark runner, user table.
// Only rendered when the JWT has admin:true.
// =============================================================================
import { useState, useEffect, useRef, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Activity, Database, Zap, Users, RefreshCw, Play,
  Unlock, ChevronRight, X, AlertTriangle, BarChart2,
} from 'lucide-react'

const API_BASE = import.meta.env.VITE_API_BASE_URL || ''

async function adminFetch(path, options = {}) {
  const token = sessionStorage.getItem('auth_token')
  const res = await fetch(API_BASE + '/admin' + path, {
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
      ...(options.headers || {}),
    },
    ...options,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || 'Admin request failed')
  }
  return res.json()
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------
function StatCard({ icon: Icon, label, value, color = '#F57224', sub }) {
  return (
    <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-5 flex items-center gap-4">
      <div className="w-11 h-11 rounded-xl flex items-center justify-center shrink-0"
        style={{ background: `${color}18` }}>
        <Icon size={20} style={{ color }} />
      </div>
      <div>
        <p className="text-2xl font-bold text-gray-800">{value ?? '—'}</p>
        <p className="text-xs text-gray-500">{label}</p>
        {sub && <p className="text-xs text-gray-400 mt-0.5">{sub}</p>}
      </div>
    </div>
  )
}

function SectionHeader({ title, onRefresh, refreshing }) {
  return (
    <div className="flex items-center justify-between mb-3">
      <h2 className="text-sm font-bold text-gray-700 uppercase tracking-wide">{title}</h2>
      {onRefresh && (
        <button onClick={onRefresh} disabled={refreshing}
          className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-[#F57224] transition disabled:opacity-50">
          <RefreshCw size={13} className={refreshing ? 'animate-spin' : ''} /> Refresh
        </button>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Sessions panel
// ---------------------------------------------------------------------------
function SessionsPanel() {
  const [data, setData]       = useState(null)
  const [loading, setLoading] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try { setData(await adminFetch('/sessions')) }
    catch (e) { console.error(e) }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load])

  return (
    <section>
      <SectionHeader title="Live Sessions" onRefresh={load} refreshing={loading} />
      {!data ? (
        <p className="text-xs text-gray-400">Loading…</p>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-gray-100">
          <table className="w-full text-xs">
            <thead className="bg-gray-50 text-gray-500 uppercase">
              <tr>
                {['Session ID', 'User', 'Turns', 'Tokens', 'Context %', 'Status'].map(h => (
                  <th key={h} className="px-3 py-2 text-left font-semibold">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {data.sessions.map((s) => (
                <tr key={s.session_id} className="hover:bg-gray-50 transition">
                  <td className="px-3 py-2 font-mono text-gray-600">{s.session_id.slice(0, 8)}…</td>
                  <td className="px-3 py-2 text-gray-500">{s.user_id?.slice(0, 8) ?? 'anon'}</td>
                  <td className="px-3 py-2">{s.turns}</td>
                  <td className="px-3 py-2">{s.token_estimate}</td>
                  <td className="px-3 py-2">
                    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full font-semibold
                      ${s.near_limit ? 'bg-yellow-50 text-yellow-700' : 'bg-green-50 text-green-700'}`}>
                      {s.near_limit && <AlertTriangle size={10} />}
                      {s.context_pct}%
                    </span>
                  </td>
                  <td className="px-3 py-2 capitalize text-gray-500">{s.status}</td>
                </tr>
              ))}
              {data.sessions.length === 0 && (
                <tr><td colSpan={6} className="px-3 py-4 text-center text-gray-400">No active sessions</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

// ---------------------------------------------------------------------------
// Compaction health panel
// ---------------------------------------------------------------------------
function CompactionPanel() {
  const [stats, setStats] = useState(null)
  const [loading, setLoading] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try { setStats(await adminFetch('/compaction/stats')) }
    catch (e) { console.error(e) }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load])

  return (
    <section>
      <SectionHeader title="Memory Health (Last 24h)" onRefresh={load} refreshing={loading} />
      {!stats ? (
        <p className="text-xs text-gray-400">Loading…</p>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          {['auto', 'micro', 'extraction'].map((type) => {
            const s = stats.stats?.[type]
            return (
              <div key={type} className="bg-white rounded-xl border border-gray-100 p-4">
                <p className="text-xs font-semibold text-gray-500 uppercase mb-2 capitalize">{type}</p>
                {s ? (
                  <>
                    <p className="text-xl font-bold text-gray-800">{s.count}</p>
                    <p className="text-xs text-gray-400">events</p>
                    {s.avg_before && (
                      <p className="text-xs text-gray-400 mt-1">
                        {Math.round(s.avg_before)} → {Math.round(s.avg_after)} tokens avg
                      </p>
                    )}
                  </>
                ) : (
                  <p className="text-sm text-gray-300">No events</p>
                )}
              </div>
            )
          })}
        </div>
      )}
    </section>
  )
}

// ---------------------------------------------------------------------------
// Benchmark runner
// ---------------------------------------------------------------------------
function BenchmarkPanel() {
  const [results, setResults]   = useState([])
  const [running, setRunning]   = useState(false)
  const [done, setDone]         = useState(false)
  const [concurrency, setConcurrency] = useState(null)
  const [testingConcurrency, setTestingConcurrency] = useState(false)

  const runBenchmark = async () => {
    setResults([])
    setRunning(true)
    setDone(false)
    try {
      const res = await fetch(API_BASE + '/admin/benchmark/run', {
        method: 'POST',
        credentials: 'include',
      })
      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buf = ''
      while (true) {
        const { done: d, value } = await reader.read()
        if (d) break
        buf += decoder.decode(value, { stream: true })
        const lines = buf.split('\n')
        buf = lines.pop()
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const json = JSON.parse(line.slice(6))
          if (json.done) { setDone(true) }
          else { setResults(prev => [...prev, json]) }
        }
      }
    } catch (e) { console.error(e) }
    finally { setRunning(false) }
  }

  const runConcurrency = async () => {
    setConcurrency({ per_user: [], status: 'simulating' })
    setTestingConcurrency(true)
    try {
      const token = sessionStorage.getItem('auth_token')
      const res = await fetch(API_BASE + '/admin/benchmark/concurrency', {
        method: 'POST',
        credentials: 'include',
        headers: {
          ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
        }
      })
      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buf = ''
      
      while (true) {
        const { done: d, value } = await reader.read()
        if (d) break
        buf += decoder.decode(value, { stream: true })
        const lines = buf.split('\n')
        buf = lines.pop()
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const json = JSON.parse(line.slice(6))
          if (json.done) {
            setConcurrency(json)
          } else if (json.individual_result) {
            setConcurrency(prev => ({
              ...prev,
              per_user: [...(prev?.per_user || []), json.individual_result]
            }))
          }
        }
      }
    } catch (e) { console.error(e) }
    finally { setTestingConcurrency(false) }
  }

  return (
    <section className="space-y-6">
      <div>
        <SectionHeader title="Functional Benchmarks" />
        <div className="flex gap-3 mb-4">
          <motion.button onClick={runBenchmark} disabled={running}
            whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.98 }}
            className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold
                       bg-[#F57224] text-white shadow-sm disabled:opacity-50 transition">
            {running ? <RefreshCw size={15} className="animate-spin" /> : <Play size={15} />}
            {running ? 'Running Tests…' : 'Run Quality Benchmark'}
          </motion.button>
          
          <motion.button onClick={runConcurrency} disabled={testingConcurrency}
            whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.98 }}
            className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold
                       bg-blue-600 text-white shadow-sm disabled:opacity-50 transition">
            {testingConcurrency ? <RefreshCw size={15} className="animate-spin" /> : <Users size={15} />}
            {testingConcurrency ? 'Simulating…' : 'Run Concurrency Test (5 Users)'}
          </motion.button>
        </div>

        {concurrency && (
          <div className="mb-6 space-y-4">
            {/* Summary cards */}
            <div className="p-4 bg-blue-50 rounded-xl border border-blue-100 grid grid-cols-2 sm:grid-cols-5 gap-4">
              <div>
                <p className="text-[10px] uppercase font-bold text-blue-500">Total Time</p>
                <p className="text-lg font-bold text-blue-900">{concurrency.total_time_ms ?? '—'}ms</p>
              </div>
              <div>
                <p className="text-[10px] uppercase font-bold text-blue-500">Avg Latency</p>
                <p className="text-lg font-bold text-blue-900">{concurrency.avg_latency_ms ?? '—'}ms</p>
              </div>
              <div>
                <p className="text-[10px] uppercase font-bold text-blue-500">P95 Latency</p>
                <p className="text-lg font-bold text-blue-900">{concurrency.p95_latency_ms ?? '—'}ms</p>
              </div>
              <div>
                <p className="text-[10px] uppercase font-bold text-blue-500">Concurrent Users</p>
                <p className="text-lg font-bold text-blue-900">{concurrency.n_users ?? '—'}</p>
              </div>
              <div>
                <p className="text-[10px] uppercase font-bold text-blue-500">Status</p>
                <p className={`text-lg font-bold capitalize ${
                  concurrency.status === 'success' ? 'text-green-700' : 
                  concurrency.status === 'simulating' ? 'text-blue-600 animate-pulse' : 'text-red-600'
                }`}>{concurrency.status}</p>
              </div>
            </div>

            {/* Per-user breakdown */}
            {concurrency.per_user?.length > 0 && (
              <div className="overflow-x-auto rounded-xl border border-blue-100">
                <table className="w-full text-xs">
                  <thead className="bg-blue-50 text-blue-500 uppercase">
                    <tr>
                      {['User', 'Session', 'Latency', 'Status', 'Preview'].map(h => (
                        <th key={h} className="px-3 py-2 text-left font-semibold">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-blue-50">
                    {concurrency.per_user.map((u) => (
                      <tr key={u.user_index} className="hover:bg-blue-50/50">
                        <td className="px-3 py-2 font-bold text-blue-800">#{u.user_index}</td>
                        <td className="px-3 py-2 font-mono text-gray-500">{u.session_id}</td>
                        <td className="px-3 py-2 text-gray-700">
                          {u.latency_ms != null ? `${u.latency_ms}ms` : '—'}
                        </td>
                        <td className="px-3 py-2">
                          <span className={`px-2 py-0.5 rounded-full font-bold text-[10px] ${
                            u.status === 'ok' ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-600'
                          }`}>{u.status.toUpperCase()}</span>
                        </td>
                        <td className="px-3 py-2 text-gray-400 italic max-w-[200px] truncate">
                          {u.response_preview}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {results.length > 0 && (
          <div className="overflow-x-auto rounded-xl border border-gray-100">
            <table className="w-full text-xs">
              <thead className="bg-gray-50 text-gray-500 uppercase">
                <tr>
                  {['Query', 'Type', 'Latency', 'Result', 'Preview'].map(h => (
                    <th key={h} className="px-3 py-2 text-left font-semibold">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {results.map((r, i) => (
                  <tr key={i} className="hover:bg-gray-50">
                    <td className="px-3 py-2 text-gray-700 font-medium">{r.query}</td>
                    <td className="px-3 py-2">
                      <span className="px-2 py-0.5 rounded-md bg-gray-100 text-gray-600 font-mono text-[10px] uppercase">
                        {r.type}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-gray-500">{r.latency_ms}ms</td>
                    <td className="px-3 py-2">
                      <span className={`px-2 py-0.5 rounded-full font-bold
                        ${r.passed ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-600'}`}>
                        {r.passed ? 'PASS' : 'FAIL'}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-gray-400 italic max-w-[200px] truncate">
                      {r.response_preview}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {done && <p className="text-xs text-green-600 px-3 py-2 font-semibold">✅ Quality Benchmark complete</p>}
          </div>
        )}
      </div>
    </section>
  )
}

// ---------------------------------------------------------------------------
// Users panel
// ---------------------------------------------------------------------------
function UsersPanel() {
  const [data, setData]         = useState(null)
  const [loading, setLoading]   = useState(false)
  const [selected, setSelected] = useState(null)
  const [crm, setCrm]           = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    try { setData(await adminFetch('/users')) }
    catch (e) { console.error(e) }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load])

  const selectUser = async (user) => {
    setSelected(user)
    setCrm(null)
    try { setCrm(await adminFetch(`/users/${user.id}/crm`)) }
    catch { setCrm({ error: 'No CRM profile.' }) }
  }

  const unlock = async (userId) => {
    try {
      await adminFetch(`/users/${userId}/unlock`, { method: 'POST' })
      load()
    } catch (e) { alert(e.message) }
  }

  return (
    <section className="relative">
      <SectionHeader title="Registered Users" onRefresh={load} refreshing={loading} />
      {!data ? (
        <p className="text-xs text-gray-400">Loading…</p>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-gray-100">
          <table className="w-full text-xs">
            <thead className="bg-gray-50 text-gray-500 uppercase">
              <tr>
                {['Username', 'Email', 'Registered', 'Last Login', 'Admin', 'Locked', 'Actions'].map(h => (
                  <th key={h} className="px-3 py-2 text-left font-semibold">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {data.users.map((u) => (
                <tr key={u.id} className="hover:bg-gray-50 cursor-pointer transition"
                  onClick={() => selectUser(u)}>
                  <td className="px-3 py-2 font-medium text-gray-800">{u.username}</td>
                  <td className="px-3 py-2 text-gray-500">{u.email}</td>
                  <td className="px-3 py-2 text-gray-400">{u.created_at?.slice(0, 10)}</td>
                  <td className="px-3 py-2 text-gray-400">{u.last_login?.slice(0, 10) ?? '—'}</td>
                  <td className="px-3 py-2">
                    {u.is_admin ? <span className="text-[#F57224] font-bold">Yes</span> : '—'}
                  </td>
                  <td className="px-3 py-2">
                    {u.locked_until ? (
                      <span className="text-red-500 font-semibold">🔒 Locked</span>
                    ) : '—'}
                  </td>
                  <td className="px-3 py-2 flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
                    {u.locked_until && (
                      <button onClick={() => unlock(u.id)}
                        className="flex items-center gap-1 px-2 py-1 rounded-lg bg-green-50 text-green-700
                                   text-xs font-semibold hover:bg-green-100 transition">
                        <Unlock size={11} /> Unlock
                      </button>
                    )}
                    <ChevronRight size={14} className="text-gray-400" />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* CRM side panel */}
      <AnimatePresence>
        {selected && (
          <motion.div
            initial={{ opacity: 0, x: 40 }} animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: 40 }}
            className="absolute top-0 right-0 w-72 bg-white rounded-2xl shadow-2xl border border-gray-100 p-5 z-10"
          >
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-bold text-gray-700">CRM — {selected.username}</h3>
              <button onClick={() => setSelected(null)}
                className="p-1 text-gray-400 hover:text-gray-600"><X size={14} /></button>
            </div>
            {!crm ? (
              <p className="text-xs text-gray-400">Loading…</p>
            ) : crm.error ? (
              <p className="text-xs text-gray-400">{crm.error}</p>
            ) : (
              <dl className="space-y-2 text-xs">
                {Object.entries(crm).filter(([k]) => k !== 'user_id').map(([k, v]) => (
                  v ? (
                    <div key={k}>
                      <dt className="font-semibold text-gray-500 capitalize">{k.replace(/_/g, ' ')}</dt>
                      <dd className="text-gray-700 ml-1">{Array.isArray(v) ? v.join(', ') : String(v)}</dd>
                    </div>
                  ) : null
                ))}
              </dl>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </section>
  )
}

// ---------------------------------------------------------------------------
// Main dashboard
// ---------------------------------------------------------------------------
const TABS = [
  { id: 'sessions',    label: 'Sessions',    icon: Activity  },
  { id: 'memory',      label: 'Memory',      icon: Database  },
  { id: 'benchmark',   label: 'Benchmark',   icon: Zap       },
  { id: 'users',       label: 'Users',       icon: Users     },
]

export default function AdminDashboard({ onClose }) {
  const [tab, setTab] = useState('sessions')

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white border-b border-gray-100 shadow-sm sticky top-0 z-20">
        <div className="max-w-6xl mx-auto px-4 h-14 flex items-center gap-4">
          <BarChart2 size={20} className="text-[#F57224]" />
          <span className="font-bold text-gray-800">Admin Dashboard</span>
          <div className="flex-1" />
          {onClose && (
            <button onClick={onClose}
              className="flex items-center gap-1.5 px-3 py-1.5 text-sm text-gray-500 hover:text-gray-800
                         rounded-lg hover:bg-gray-100 transition">
              <X size={14} /> Exit Admin
            </button>
          )}
        </div>
      </header>

      <div className="max-w-6xl mx-auto px-4 py-6">
        {/* Tab bar */}
        <div className="flex gap-1 bg-white rounded-xl p-1 shadow-sm border border-gray-100 mb-6 w-fit">
          {TABS.map(({ id, label, icon: Icon }) => (
            <button key={id} onClick={() => setTab(id)}
              className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition
                ${tab === id ? 'bg-[#F57224] text-white shadow-sm' : 'text-gray-500 hover:text-gray-700'}`}>
              <Icon size={14} /> {label}
            </button>
          ))}
        </div>

        {/* Panel */}
        <AnimatePresence mode="wait">
          <motion.div key={tab}
            initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>
            {tab === 'sessions'  && <SessionsPanel />}
            {tab === 'memory'    && <CompactionPanel />}
            {tab === 'benchmark' && <BenchmarkPanel />}
            {tab === 'users'     && <UsersPanel />}
          </motion.div>
        </AnimatePresence>
      </div>
    </div>
  )
}
