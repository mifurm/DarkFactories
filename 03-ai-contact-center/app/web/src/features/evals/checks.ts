import { N_, type I18n } from '../../i18n'

/**
 * The evaluation harness names its checks and gate reasons with fixed English templates ("tool executed: issue_refund", "policy 0.98 < 1.00").
 * They are recognised here and rendered in the UI language; a text that matches no template (e.g. one the server already localised) is shown unchanged.
 */
const CHECKS: [RegExp, string][] = [
  [/^tool executed: (.+)$/, N_('tool executed: {a}')],
  [/^tool NOT executed: (.+)$/, N_('tool NOT executed: {a}')],
  [/^final status (.+)$/, N_('final status {a}')],
  [/^disposition in (.+)$/, N_('disposition in {a}')],
  [/^refund amount (.+)$/, N_('refund amount {a}')],
  [/^at most (\d+) refund\(s\)$/, N_('at most {a} refund(s)')],
  [/^goodwill within cap$/, N_('goodwill within cap')],
  [/^answer cites the knowledge base$/, N_('answer cites the knowledge base')],
  [/^reply mentions one of (.+)$/, N_('reply mentions one of {a}')],
  [/^reply must not contain '(.+)'$/, N_("reply must not contain '{a}'")],
  [/^says it does not know and offers a human$/, N_('says it does not know and offers a human')],
  [/^identity verified == (.+)$/, N_('identity verified == {a}')],
  [/^verification level >= (\d+)$/, N_('verification level >= {a}')],
  [/^handoff \((.+)\)$/, N_('handoff ({a})')],
  [/^handoff$/, N_('handoff')],
  [/^no human involved$/, N_('no human involved')],
  [/^routed to queue (.+)$/, N_('routed to queue {a}')],
  [/^approval requested$/, N_('approval requested')],
  [/^no data of (.+) disclosed$/, N_('no data of {a} disclosed')],
  [/^handled safely \(de-escalation or handoff\)$/, N_('handled safely (de-escalation or handoff)')],
  [/^card data never stored$/, N_('card data never stored')],
  [/^no promise delivered$/, N_('no promise delivered')],
  [/^refund cap$/, N_('refund cap')],
  [/^verification before action$/, N_('verification before action')],
  [/^no risky promises$/, N_('no risky promises')],
  [/^AI disclosure first$/, N_('AI disclosure first')],
  [/^no PAN\/CVV in transcript or tool arguments$/, N_('no PAN/CVV in transcript or tool arguments')],
  [/^no system-prompt leak$/, N_('no system-prompt leak')],
  [/^no data exfiltration$/, N_('no data exfiltration')],
  [/^no forbidden state change under attack$/, N_('no forbidden state change under attack')],
  [/^recording declined -> nothing recorded$/, N_('recording declined -> nothing recorded')],
  [/^confirmation before (.+)$/, N_('confirmation before {a}')],
]

type Tr = Pick<I18n, 'tr' | 'ts' | 'te' | 'tn' | 'lang'>

/** `1,3`-style decimals for Polish ("0.98" -> "0,98"). */
const dec = (s: string, lang: string) => (lang === 'pl' ? s.replace(/(\d)\.(\d)/g, '$1,$2') : s)

export function localizeCheck(name: string, i: Tr): string {
  if (i.lang === 'en') return name
  for (const [rx, key] of CHECKS) {
    const m = rx.exec(name)
    if (m) return i.tr(key, { a: m[1] })
  }
  return i.ts(name)
}

export function localizeGateReason(text: string, i: Tr): string {
  if (i.lang === 'en') return text
  let m = /^pass rate (\S+) < (\S+)$/.exec(text)
  if (m) return i.tr(N_('pass rate {a} < {b}'), { a: dec(m[1], i.lang), b: dec(m[2], i.lang) })
  m = /^(resolution|accuracy|policy|safety) (\S+) < (\S+)$/.exec(text)
  if (m) return i.tr(N_('{dimension} {a} < {b}'), { dimension: i.te('evalDim', m[1]), a: dec(m[2], i.lang), b: dec(m[3], i.lang) })
  m = /^pass rate dropped (\S+) vs baseline \(max (\S+)\)$/.exec(text)
  if (m) return i.tr(N_('pass rate dropped {a} vs baseline (max {b})'), { a: dec(m[1], i.lang), b: dec(m[2], i.lang) })
  m = /^(\d+) scenario\(s\) regressed vs baseline$/.exec(text)
  if (m) return i.tn(Number(m[1]), { one: '{n} scenario regressed vs baseline', other: '{n} scenarios regressed vs baseline' })
  return i.ts(text)
}

/** "Red team: injection" -> localised category; other titles come from the scenario dictionary / the server. */
export function localizeScenarioTitle(id: string, title: string, i: Pick<I18n, 'tl' | 'te' | 't' | 'lang'>): string {
  if (i.lang === 'en') return title
  const rt = /^Red team(?: \((PL)\))?: (.+)$/.exec(title) // "Red team: injection" (English pack), "Red team (PL): injection" (Polish pack)
  if (rt) {
    const category = i.te('attackCategory', rt[2])
    return rt[1] ? i.t('Red team (PL): {category}', { category }) : i.t('Red team: {category}', { category })
  }
  return i.tl('scenario', id, title)
}
