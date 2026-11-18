import { KeyRound, ShieldCheck } from 'lucide-react'
import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { ApiError, api, fmt, useApi } from '../../lib/api'
import { Badge, Button, Card, DataTable, ErrorBox, Field, PageHeader, Spinner, inputCls } from '../../lib/ui'

interface Level { level: number; name: string; grants: string; how?: string; [k: string]: unknown }
interface Levels { levels: Level[]; pii_allowlist: Record<string, string[]>; otp: { ttl_s: number; max_attempts: number; delivery: string } }
interface AuditRow { seq: number; ts: number; actor: string; action: string; resource: string; outcome: string; detail: Record<string, unknown> }
interface PayInfo { amount_eur?: number; order_id?: string; status?: string; merchant?: string; [k: string]: unknown }

export default function IdentityPage() {
  const lv = useApi<Levels>('/api/identity/levels')
  const au = useApi<AuditRow[]>('/api/identity/consents?limit=30', { refreshMs: 15000 })
  return (
    <div>
      <PageHeader icon={KeyRound} title="Identity, consent & payments" subtitle="Authentication is a gate in code, not a prompt: no account tool runs before the customer is verified; sensitive changes need step-up; card data never reaches the model or the transcript." />
      {lv.loading && !lv.data ? <Spinner /> : lv.error || !lv.data ? <ErrorBox error={lv.error} /> : (
        <div className="space-y-4">
          <div className="grid gap-3 md:grid-cols-3">{lv.data.levels.map((l) => <Card key={l.level} title={<span className="flex items-center gap-2"><Badge tone={l.level === 0 ? 'slate' : l.level === 1 ? 'blue' : 'green'}>L{l.level}</Badge>{l.name}</span>}><p className="text-sm text-slate-700">{l.grants}</p>{typeof l.how === 'string' && <p className="mt-1 text-xs text-slate-500">{l.how}</p>}</Card>)}</div>
          <div className="grid gap-4 lg:grid-cols-2">
            <Card title="What the model may see (PII allow-list)" subtitle={`one-time code: ${lv.data.otp.ttl_s / 60} min, ${lv.data.otp.max_attempts} attempts, delivery ${lv.data.otp.delivery}`}>
              <dl className="space-y-2 text-sm">{Object.entries(lv.data.pii_allowlist).map(([k, v]) => <div key={k}><dt className={k === 'never_sent_to_the_model' ? 'font-semibold text-rose-700' : 'font-semibold text-slate-700'}>{k.replace(/_/g, ' ')}</dt><dd className="flex flex-wrap gap-1">{v.map((x) => <Badge key={x} tone={k === 'never_sent_to_the_model' ? 'red' : 'blue'}>{x}</Badge>)}</dd></div>)}</dl>
            </Card>
            <Card title="Secure payment (PCI)" subtitle="the assistant never takes card numbers: it hands off to a hosted page or the keypad (DTMF) on a call">
              <p className="text-sm text-slate-700">Ask the assistant to pay an open balance in the widget; it issues a one-time secure link (<code>/pay/&lt;token&gt;</code>). The page validates the card (Luhn) and returns only brand + last four.</p>
              <p className="mt-2 text-xs text-slate-500">Typing a card number into the chat is redacted before storage and before the model, and the assistant switches to the secure flow.</p>
            </Card>
          </div>
          <Card title="Identity & consent events" subtitle="from the hash-chained audit log" pad={false}>
            <DataTable dense rows={au.data ?? []} rowKey={(r) => String(r.seq)} empty="No events yet." cols={[{ key: 't', header: 'Time', render: (r) => fmt.time(r.ts) }, { key: 'a', header: 'Event', render: (r) => <span className="font-mono text-xs">{r.action}</span> }, { key: 'r', header: 'Resource', render: (r) => <span className="text-xs text-slate-500">{r.resource}</span> }, { key: 'd', header: 'Detail', render: (r) => <span className="text-xs text-slate-500">{JSON.stringify(r.detail).slice(0, 90)}</span> }]} />
          </Card>
        </div>
      )}
    </div>
  )
}

/** Bare hosted payment page: card digits go here, never to the AI. */
export function PayPage() {
  const { token } = useParams()
  const info = useApi<PayInfo>(token ? `/api/identity/payments/${token}` : null)
  const [card, setCard] = useState('')
  const [exp, setExp] = useState('')
  const [cvv, setCvv] = useState('')
  const [name, setName] = useState('')
  const [res, setRes] = useState<{ status?: string; brand?: string; last4?: string } | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const submit = async () => {
    setErr(null)
    try { setRes(await api(`/api/identity/payments/${token}/submit`, { body: { card_number: card, exp, cvv, name } })); setCard(''); setCvv('') } catch (e) { setErr(e instanceof ApiError ? String((e.body as { message?: string })?.message ?? e.message) : String(e)) }
  }
  return (
    <div className="mx-auto mt-10 max-w-md rounded-3xl border border-slate-200 bg-white p-6 shadow-xl">
      <div className="mb-3 flex items-center gap-2 text-emerald-700"><ShieldCheck size={18} aria-hidden /><b className="text-sm">Contoso Home · secure payment</b></div>
      {info.error ? <ErrorBox error={info.error} /> : !info.data ? <Spinner /> : res ? <div role="status" className="rounded-xl bg-emerald-50 p-4 text-sm text-emerald-900">Payment {res.status ?? 'received'} — {res.brand} •••• {res.last4}. You can return to the chat.</div> : (
        <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); submit() }}>
          <p className="text-sm text-slate-600">{info.data.amount_eur != null ? <>Amount due: <b>€{info.data.amount_eur}</b> · </> : null}order {info.data.order_id ?? '—'}</p>
          <Field label="Name on card"><input value={name} onChange={(e) => setName(e.target.value)} autoComplete="cc-name" className={inputCls} /></Field>
          <Field label="Card number" hint="test card: 4111 1111 1111 1111"><input value={card} onChange={(e) => setCard(e.target.value)} inputMode="numeric" autoComplete="cc-number" className={inputCls} /></Field>
          <div className="grid grid-cols-2 gap-3"><Field label="Expiry (MM/YY)"><input value={exp} onChange={(e) => setExp(e.target.value)} autoComplete="cc-exp" className={inputCls} /></Field><Field label="CVV"><input value={cvv} onChange={(e) => setCvv(e.target.value)} inputMode="numeric" autoComplete="cc-csc" className={inputCls} /></Field></div>
          {err && <p role="alert" className="text-sm text-rose-700">{err}</p>}
          <Button type="submit" variant="primary" className="w-full">Pay securely</Button>
          <p className="text-center text-[11px] text-slate-400">Card details are validated here and never shared with the AI assistant.</p>
        </form>
      )}
    </div>
  )
}
