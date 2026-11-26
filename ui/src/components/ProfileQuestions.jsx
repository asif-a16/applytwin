import { useEffect, useRef, useState } from 'react'
import { api } from '../lib/api'

/* Every question applications ask, answered once and used on every form. Used by onboarding and Settings.
   Nothing is pre-selected: an unanswered question stays blank until the person answers it. */

export function useQuestions() {
  const [qs, setQs] = useState(null)
  useEffect(() => {   // a failed load (the app restarting after an update) tries again instead of leaving blank screens
    let live = true
    const load = (n = 0) => api('/api/questions').then(d => live && setQs(d.questions))
      .catch(() => { if (live) n < 5 ? setTimeout(() => load(n + 1), 2000) : setQs([]) })
    load()
    return () => { live = false }
  }, [])
  return qs
}

// nested keys: 'eeo.gender', 'work_auth.GB'
const split = k => { const i = k.indexOf('.'); return i < 0 ? [k] : [k.slice(0, i), k.slice(i + 1)] }
export const getv = (p, k) => { const [a, b] = split(k); return b === undefined ? p[a] : (p[a] || {})[b] }
export const setv = (p, k, v) => { const [a, b] = split(k); return b === undefined ? { ...p, [a]: v } : { ...p, [a]: { ...(p[a] || {}), [b]: v } } }
// a select's options are plain strings, or {value, label} when the stored value is a code ('sponsorship')
const ov = o => typeof o === 'string' ? o : o.value
const ol = o => typeof o === 'string' ? o : o.label
const voluntary = g => g.startsWith('Voluntary') || g.startsWith('Equality')
// q.when 'GB' / 'US': needed only by users applying there (answers.WHEN). No countries picked = the US-first setup.
const PLACES = { GB: ['united kingdom', 'uk', 'gb', 'great britain', 'britain', 'england', 'scotland', 'wales', 'northern ireland', 'europe', 'emea'],
  US: ['united states', 'us', 'usa', 'u.s.', 'united states of america', 'america', 'north america', 'americas'] }
export const applies = (q, p) => {
  if (!q.when) return true
  const cs = (p.search?.countries || []).map(c => (c || '').trim().toLowerCase())
  return cs.some(c => PLACES[q.when].includes(c)) || (q.when === 'US' && cs.length === 0)
}
export const missing = (qs, p) => (qs || []).filter(q => !q.optional && applies(q, p) && [undefined, null, ''].includes(getv(p, q.key)))

// one answer that settles others: a U.S. citizen or green card holder is authorized to work and needs no sponsorship
function implied(p, key) {
  if (key !== 'citizenship') return p
  const yes = /^U\.S\. (citizen|permanent resident)/.test(p.citizenship || '')
  if (!yes) return p
  let out = p
  if ([undefined, null, ''].includes(getv(out, 'work_authorized_us'))) out = setv(out, 'work_authorized_us', true)
  if ([undefined, null, ''].includes(getv(out, 'needs_sponsorship'))) out = setv(out, 'needs_sponsorship', false)
  return out
}

export function ProfileQuestions({ qs, p, setP, groups, showMissing, filled = [], large }) {
  // "filled in for you" belongs to the value the CV gave: once you change it, it's yours and the label goes
  const first = useRef({})
  const firstSeen = (k, v) => (k in first.current ? first.current[k] : (first.current[k] = v))
  if (!qs) return <div className="skel h-64" />
  const names = groups || [...new Set(qs.map(q => q.group))]
  return (
    <div className="space-y-7">
      {names.map(g => (
        <section key={g}>
          {!large && <div className="mb-1.5 px-4 text-[13px] font-medium text-muted">{g}{voluntary(g) && ' · you can decline any of these'}{g.startsWith('US ') && ' · needed only if you apply to US jobs'}</div>}
          {voluntary(g) && qs.some(q => q.group === g && q.kind === 'select' && [undefined, null, ''].includes(getv(p, q.key))) &&
            <div className="mb-2 flex justify-end"><button onClick={() => setP(qs.filter(q => q.group === g && q.kind === 'select').reduce((acc, q) => {
              const d = (q.options || []).map(ov).find(o => /decline|do not want|prefer not/i.test(o))
              return d && [undefined, null, ''].includes(getv(acc, q.key)) ? setv(acc, q.key, d) : acc
            }, p))} className="text-[13px] font-medium text-signal-ink hover:underline">Decline all of these</button></div>}
          <div className="card divide-y divide-white/[.06] overflow-hidden">
            {qs.filter(q => q.group === g).map(q => {
              const v = getv(p, q.key)
              const blank = [undefined, null, ''].includes(v)
              const optional = q.optional || !applies(q, p)
              return (
                <div key={q.key} className={'flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between sm:gap-6 ' + (large ? 'px-5 py-3' : 'min-h-[52px] px-4 py-2.5')}>
                  <div className={'flex min-w-0 flex-1 flex-wrap items-center gap-x-2 text-white ' + (large ? 'text-[15px]' : 'text-[14.5px]')}>
                    <span>{q.label}</span>{optional && <span className="text-[12px] text-faint">optional</span>}
                    {showMissing && blank && !optional && <span className="text-[12px] text-warn">Needed</span>}
                    {filled.includes(q.key) && !blank && v === firstSeen(q.key, v) && <span className="text-[12px] text-faint">filled in for you</span>}
                  </div>
                  <div className="w-full shrink-0 sm:w-[46%]">
                    {q.kind === 'yesno' ? <YesNo value={v} onChange={x => setP(setv(p, q.key, x))} />
                      : q.kind === 'select' ? (
                        <select value={v || ''} onChange={e => setP(implied(setv(p, q.key, e.target.value), q.key))}
                          className={'h-9 w-full rounded-[10px] bg-white/[.06] px-3 text-[14px] outline-none focus:ring-2 focus:ring-signal ' + (v ? 'text-white' : 'text-faint')}>
                          <option value="" disabled>Choose…</option>
                          {(v && !q.options.map(ov).includes(v) ? [v, ...q.options] : q.options).map(o => <option key={ov(o)} value={ov(o)}>{ol(o)}</option>)}
                        </select>)
                      : <input value={v || ''} placeholder={q.hint || ''} onChange={e => setP(setv(p, q.key, e.target.value))}
                          className="h-9 w-full rounded-[10px] bg-white/[.06] px-3 text-[14px] text-white outline-none placeholder:text-faint focus:ring-2 focus:ring-signal" />}
                  </div>
                </div>)
            })}
          </div>
        </section>))}
    </div>
  )
}

function YesNo({ value, onChange }) {
  return (
    <div className="inline-flex rounded-[10px] bg-white/[.06] p-[2px]">
      {[[true, 'Yes'], [false, 'No']].map(([v, l]) => (
        <button key={l} type="button" onClick={() => onChange(v)}
          className={'h-8 rounded-[8px] px-5 text-[13.5px] transition-colors ' + (value === v ? 'bg-white/[.16] font-semibold text-white shadow-[0_1px_3px_rgb(0_0_0/.3)]' : 'text-white/70 hover:text-white')}>{l}</button>))}

    </div>
  )
}
