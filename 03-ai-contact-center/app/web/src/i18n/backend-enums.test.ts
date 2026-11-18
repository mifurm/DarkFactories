import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import enums from './backend-enums.json'
import { en } from './en'
import { extractAll } from './extract'
import { pl } from './pl'

/**
 * Backend enum values that only exist in azure mode / with real model calls (azure_prompt_shields, rules+llm, llm+guard, AI metering ids ...) never reach the UI in the
 * offline stub, so no offline test can notice a missing translation. `backend-enums.json` lists every value the backend can send; this file proves the list is translated
 * and (when the backend source is in the checkout) that the backend does not define a value the list does not know.
 */
const SRC = join(import.meta.dirname, '..')
const BACKEND = resolve(SRC, '..', '..', 'src', 'concierge') // app/src/concierge: absent in a frontend-only checkout
const hasBackend = existsSync(join(BACKEND, 'engine', 'guard.py'))
const LISTS = Object.entries(enums).filter(([g]) => !g.startsWith('_')) as [string, string[]][]
const listed = (group: string): Set<string> => new Set((enums as unknown as Record<string, string[]>)[group])

describe('backend enum values have Polish entries', () => {
  it('every listed value has a Polish entry (add it to pl/*.ts and the English identity table in en.ts)', () => {
    const missing = LISTS.flatMap(([g, values]) => values.filter((v) => pl.k[g]?.[v] === undefined).map((v) => `${g}.${v}`))
    expect(missing).toEqual([])
  })

  it('English keeps showing the raw value: groups with an English table list every value', () => {
    const bad = LISTS.flatMap(([g, values]) => (en.k[g] ? values.filter((v) => en.k[g][v] === undefined).map((v) => `${g}.${v}`) : []))
    expect(bad).toEqual([])
  })

  it('every listed group is read by the UI through te() / tl()', () => {
    const used = new Set(extractAll(SRC).groups.map((g) => g.key))
    expect(LISTS.map(([g]) => g).filter((g) => !used.has(g))).toEqual([])
  })

  it('lists no value twice and no empty group', () => {
    for (const [g, values] of LISTS) {
      expect(values.length, g).toBeGreaterThan(0)
      expect(new Set(values).size, `${g} has duplicates`).toBe(values.length)
    }
  })
})

// ================================================================================================ drift against the backend source
const read = (rel: string) => readFileSync(join(BACKEND, rel), 'utf8')
const pyFiles = (dir: string): string[] =>
  readdirSync(dir).flatMap((name) => {
    const p = join(dir, name)
    if (name === '__pycache__' || name === 'tests') return []
    return statSync(p).isDirectory() ? pyFiles(p) : name.endsWith('.py') ? [p] : []
  })
/** the source between `start` and the next line that is exactly `end` (a registry literal) */
const block = (src: string, start: string, end = '\n]\n') => {
  const i = src.indexOf(start)
  expect(i, `${start} not found in the backend source`).toBeGreaterThanOrEqual(0)
  return src.slice(i, src.indexOf(end, i))
}
const all = (re: RegExp, text: string): string[] => [...text.matchAll(re)].flatMap((m) => m.slice(1).filter((x): x is string => typeof x === 'string'))
const tupleNames = (b: string) => all(/^\s*\("([a-z0-9_]+)",\s*re\.compile/gm, b)

/** every value the backend source defines for `group` must be in backend-enums.json (and, by the tests above, translated) */
function expectListed(group: string, found: string[], atLeast: number): void {
  const values = [...new Set(found)]
  expect(values.length, `the backend source patterns for "${group}" found only ${values.length} values: the backend changed shape, update this test`).toBeGreaterThanOrEqual(atLeast)
  expect(values.filter((v) => !listed(group).has(v)), `${group}: new backend value(s): add them to backend-enums.json, pl/*.ts and en.ts`).toEqual([])
}

describe.skipIf(!hasBackend)('backend-enums.json agrees with the backend source (a new backend value must be listed, then translated)', () => {
  it('quarantine reasons: injection patterns and the azure Prompt Shields flag', () => {
    const guard = read('engine/guard.py')
    expectListed('quarantine', [...tupleNames(block(guard, 'INJECTION_PATTERNS')), ...all(/injection_reasons[^\n]*"(azure_[a-z_]+)"/g, guard)], 21)
  })

  it('risky promises', () => {
    expectListed('riskyPromise', tupleNames(block(read('engine/guard.py'), 'RISKY_PROMISES')), 9)
  })

  it('metering features: every feature= the backend records', () => {
    const found = pyFiles(BACKEND).flatMap((f) => {
      const src = readFileSync(f, 'utf8')
      return [...all(/\bfeature="([a-z_]+)"/g, src), ...all(/\bfeature: str = "([a-z_]+)"/g, src), ...all(/_post\([^\n]*?,\s*"([a-z_]+)",\s*PRICES/g, src)]
    })
    expectListed('meterFeature', found, 18)
  })

  it('QA scorer', () => {
    expectListed('qaScorer', all(/scorer = "([^"]+)"/g, read('engine/qa.py')), 2)
  })

  it('summary / composition source of hand-offs, wrap-ups and outbound messages', () => {
    const outbound = read('features/outbound/__init__.py')
    const compose = outbound.slice(outbound.indexOf('async def _compose'), outbound.indexOf('async def _send'))
    const found = [
      ...all(/"summary_source": "([a-z]+)" if llm_used else "([a-z]+)"/g, read('engine/handoff.py')),
      ...all(/source = "([a-z]+)"/g, read('engine/wrapup.py')),
      ...all(/\[:900\], "([a-z]+)"/g, read('engine/wrapup.py')),
      ...all(/return [A-Za-z_.]+, "([^"]+)"/g, compose),
    ]
    expectListed('summarySource', found, 5)
  })

  it('VoC topic labeller', () => {
    expectListed('vocLabeller', all(/\["labelled_by"\] = "([a-z\-]+)" if .* else "([a-z\-]+)"/g, read('features/voc/__init__.py')), 2)
  })

  it('language detection / translation providers', () => {
    const cognitive = read('engine/cognitive.py')
    const detectors = cognitive.slice(0, cognitive.indexOf('class OfflineSpeech')) // the speech client names are not detection providers
    const found = [...all(/"provider": "([a-z\-]+)"/g, read('engine/translate.py')), ...all(/^    name = "([a-z+\-]+)"/gm, detectors)]
    expectListed('i18nProvider', found, 4)
  })

  it('telephony providers', () => {
    const tel = read('features/voice/telephony.py')
    expectListed('telephonyProvider', [...all(/^    id = "([a-z]+)"/gm, tel), ...all(/provider: str = "([a-z\-]+)"/g, tel)], 4)
  })

  it('voice session modes', () => {
    expectListed('voiceMode', all(/self\.mode = "([a-z]+)"/g, read('features/voice/session.py')), 2)
  })

  it('/readyz dependency checks', () => {
    const main = read('main.py')
    expectListed('readyCheck', [...all(/timed\("([a-z]+)"/g, main), ...all(/results\["([a-z]+)"\] = /g, main)], 5)
  })

  it('outbound decision checks (name:value codes)', () => {
    const src = read('engine/outbound.py')
    const decide = src.slice(src.indexOf('def decide('), src.indexOf('def render('))
    expectListed('outboundCheck', [...all(/f?"([a-z_]+):(?:[a-z{])/g, decide)], 8)
    expectListed('outboundCheckValue', [...all(/"[a-z_]+:([a-z]+)"/g, decide)], 7)
  })

  it('CRM masking label', () => {
    expectListed('masking', all(/"masking": "([^"]+)" if [^\n]* else "([^"]+)"/g, read('features/crm/__init__.py')), 2)
  })

  it('return reasons of the initiate_return tool', () => {
    const literal = /^Reason = Literal\[([^\]]+)\]/m.exec(read('engine/tools.py'))?.[1] ?? ''
    expectListed('returnReason', all(/"([a-z_]+)"/g, literal), 5)
  })

  it('evaluation suites accepted by the API', () => {
    const found = all(/suite: str = Field\("core", pattern="\^\(([^)]+)\)\$"/g, read('features/evals/__init__.py')).flatMap((p) => p.split('|'))
    expectListed('suite', found, 9)
  })

  it('evaluation mode, budget and SLO statuses', () => {
    expectListed('evalMode', all(/"mode": "([a-z]+)" if svc\.llm\.deterministic else "([a-z]+)"/g, read('engine/evalrun.py')), 2)
    expectListed('budgetStatus', all(/"status": "([a-z]+)" if self\.remaining_usd <= 0 else \("([a-z]+)" if [^\n]* else "([a-z]+)"\)/g, read('core/ai/usage.py')), 3)
    expectListed('sloStatus', all(/"status": "([a-z ]+)" if not vals else \("([a-z]+)" if [^\n]* else "([a-z]+)"\)/g, read('features/observability/__init__.py')), 3)
  })

  it('conversation, agent-config and tool statuses (documented in engine/models.py)', () => {
    const models = read('engine/models.py')
    const docs = (first: string) => (new RegExp(`status: str = "${first}"\\s+#\\s*([a-z_ |]+)`).exec(models)?.[1] ?? '').split('|').map((s) => s.trim()).filter(Boolean)
    expectListed('convStatus', docs('active'), 6)
    expectListed('configStatus', docs('draft'), 5)
    expectListed('toolStatus', docs('ok'), 6)
  })
})
