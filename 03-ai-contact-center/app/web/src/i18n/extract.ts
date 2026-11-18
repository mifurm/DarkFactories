/// <reference types="node" />
// Test/tooling helper (never imported by the app): finds every translatable literal in the source with a real parser.
import { readdirSync, readFileSync } from 'node:fs'
import { join, relative } from 'node:path'
import { parseAst } from 'rolldown/parseAst'

export interface Found {
  key: string
  file: string
  line: number
  fn: string
}
export interface Dynamic {
  file: string
  line: number
  fn: string
}
export interface Extraction {
  /** keys for t / tw / rich / N_ */
  literals: Found[]
  /** `other` forms of tn() calls (with the `one` form) */
  plurals: (Found & { one: string })[]
  /** keyed-table groups used by te() / tl() / translateKeyed() / translateLabel() (`key` = the group name) */
  groups: Found[]
  /** t() / tw() / rich() / N_() / tn() / te() calls whose literal argument cannot be read statically (must use tr() or a literal group) */
  dynamic: Dynamic[]
}

const LITERAL_FUNCS = new Set(['t', 'tw', 'rich', 'N_'])
/** functions taking the language first and the English source second: translate(lang, 'text', vars) */
const LANG_FIRST_FUNCS = new Set(['translate', 'translateRich'])
/** keyed-table accessors -> position of the group argument */
const GROUP_FUNCS: Record<string, number> = { te: 0, tl: 0, translateKeyed: 1, translateLabel: 1 }
type Node = { type: string; start: number; end: number; [k: string]: unknown }

function* walk(node: unknown): Generator<Node> {
  if (!node || typeof node !== 'object') return
  if (Array.isArray(node)) {
    for (const n of node) yield* walk(n)
    return
  }
  const n = node as Node
  if (typeof n.type === 'string') yield n
  for (const [k, v] of Object.entries(n)) if (k !== 'type' && v && typeof v === 'object') yield* walk(v)
}

/** String value of a literal, a template without expressions, or a '+' chain of those; otherwise null. */
function stringValue(n: Node | undefined): string | null {
  if (!n) return null
  if (n.type === 'Literal' && typeof n.value === 'string') return n.value
  if (n.type === 'TemplateLiteral' && (n.expressions as unknown[]).length === 0) return (n.quasis as { value: { cooked: string } }[])[0].value.cooked
  if (n.type === 'BinaryExpression' && n.operator === '+') {
    const l = stringValue(n.left as Node)
    const r = stringValue(n.right as Node)
    return l !== null && r !== null ? l + r : null
  }
  return null
}

function lineOf(src: string, offset: number): number {
  let line = 1
  for (let i = 0; i < offset; i++) if (src.charCodeAt(i) === 10) line++
  return line
}

export function extractSource(src: string, file: string): Extraction {
  const ast = parseAst(src, { lang: file.endsWith('.tsx') ? 'tsx' : 'ts' })
  const out: Extraction = { literals: [], plurals: [], groups: [], dynamic: [] }
  for (const n of walk(ast)) {
    if (n.type !== 'CallExpression') continue
    const callee = n.callee as Node & { name?: string; property?: Node & { name?: string }; computed?: boolean }
    // t('…') as well as i18n.t('…') / i.tn(…)
    const fn = callee.type === 'Identifier' ? callee.name : callee.type === 'MemberExpression' && !callee.computed ? callee.property?.name : undefined
    if (!fn) continue
    const args = n.arguments as Node[]
    if (LITERAL_FUNCS.has(fn) || LANG_FIRST_FUNCS.has(fn)) {
      const key = stringValue(args[LANG_FIRST_FUNCS.has(fn) ? 1 : 0])
      if (key === null) out.dynamic.push({ file, line: lineOf(src, n.start), fn })
      else out.literals.push({ key, file, line: lineOf(src, n.start), fn })
    } else if (fn === 'tn') {
      const forms = args[1]
      if (forms?.type !== 'ObjectExpression') {
        out.dynamic.push({ file, line: lineOf(src, n.start), fn })
        continue
      }
      const prop = (name: string) => {
        const p = (forms.properties as (Node & { key: Node & { name?: string; value?: string }; value: Node })[]).find((q) => (q.key.name ?? q.key.value) === name)
        return p ? stringValue(p.value) : null
      }
      const other = prop('other')
      const one = prop('one')
      if (other === null || one === null) out.dynamic.push({ file, line: lineOf(src, n.start), fn })
      else out.plurals.push({ key: other, one, file, line: lineOf(src, n.start), fn })
    } else if (Object.hasOwn(GROUP_FUNCS, fn)) {
      const group = stringValue(args[GROUP_FUNCS[fn]])
      if (group === null) out.dynamic.push({ file, line: lineOf(src, n.start), fn })
      else out.groups.push({ key: group, file, line: lineOf(src, n.start), fn })
    }
  }
  return out
}

/** Every .ts/.tsx under `srcDir` except the dictionaries, tests and tooling of the i18n folder itself. */
export function sourceFiles(srcDir: string): string[] {
  const files: string[] = []
  const visit = (dir: string) => {
    for (const e of readdirSync(dir, { withFileTypes: true })) {
      const p = join(dir, e.name)
      if (e.isDirectory()) visit(p)
      else if (/\.(ts|tsx)$/.test(e.name) && !/\.test\.(ts|tsx)$/.test(e.name)) files.push(p)
    }
  }
  visit(srcDir)
  return files.filter((f) => {
    const rel = relative(srcDir, f).split('\\').join('/')
    return !(rel === 'i18n/en.ts' || rel === 'i18n/pl.ts' || rel.startsWith('i18n/pl/') || rel === 'i18n/extract.ts' || rel === 'i18n/types.ts')
  })
}

export function extractAll(srcDir: string): Extraction & { files: number } {
  const all: Extraction & { files: number } = { literals: [], plurals: [], groups: [], dynamic: [], files: 0 }
  for (const f of sourceFiles(srcDir)) {
    const e = extractSource(readFileSync(f, 'utf8'), relative(srcDir, f))
    all.literals.push(...e.literals)
    all.plurals.push(...e.plurals)
    all.groups.push(...e.groups)
    all.dynamic.push(...e.dynamic)
    all.files++
  }
  return all
}

export const placeholders = (s: string): string[] => [...new Set(s.match(/\{\w+\}/g) ?? [])].sort()
export const tags = (s: string): string[] => (s.match(/<\/?(b|i|code)>/g) ?? []).sort()

// ------------------------------------------------------------------------------------------------ hard-coded UI text
export interface Hardcoded {
  file: string
  line: number
  where: 'text' | 'attribute' | 'property'
  name: string
  text: string
}

const UI_ATTRS = new Set(['title', 'subtitle', 'label', 'hint', 'placeholder', 'aria-label', 'aria-description', 'alt', 'header', 'empty', 'description'])
const UI_PROPS = new Set(['label', 'header', 'title', 'subtitle', 'hint', 'placeholder', 'description', 'empty'])
const hasWords = (s: string) => /[A-Za-z]{2,}/.test(s)

/**
 * JSX text, UI attributes and UI object properties holding a literal with words in it. Such text bypasses the dictionaries, so the
 * lint test requires it to go through t() / tn() / N_() instead (code identifiers inside <code>, <pre> and data-i18n-skip are exempt).
 */
export function findHardcoded(src: string, file: string): Hardcoded[] {
  const ast = parseAst(src, { lang: file.endsWith('.tsx') ? 'tsx' : 'ts' })
  const out: Hardcoded[] = []
  const add = (n: Node, where: Hardcoded['where'], name: string, text: string) => out.push({ file, line: lineOf(src, n.start), where, name, text: text.replace(/\s+/g, ' ').trim() })
  const visit = (node: unknown, skip: boolean): void => {
    if (!node || typeof node !== 'object') return
    if (Array.isArray(node)) {
      for (const n of node) visit(n, skip)
      return
    }
    const n = node as Node
    let inner = skip
    if (n.type === 'JSXElement') {
      const open = n.openingElement as { name: { name?: string }; attributes: (Node & { name?: { name?: string } })[] }
      if (['code', 'pre'].includes(open.name.name ?? '') || open.attributes.some((a) => a.type === 'JSXAttribute' && a.name?.name === 'data-i18n-skip')) inner = true
    }
    if (!skip) {
      if (n.type === 'JSXText') {
        const text = String(n.value)
        if (hasWords(text)) add(n, 'text', '#text', text)
      } else if (n.type === 'JSXAttribute') {
        const name = (n.name as { name?: string }).name ?? ''
        const value = n.value as Node | null
        if (UI_ATTRS.has(name) && value?.type === 'Literal' && typeof value.value === 'string' && hasWords(value.value)) add(n, 'attribute', name, value.value)
      } else if (n.type === 'Property') {
        const key = n.key as Node & { name?: string; value?: string }
        const name = key.name ?? String(key.value ?? '')
        const value = n.value as Node
        if (UI_PROPS.has(name) && value.type === 'Literal' && typeof value.value === 'string' && hasWords(value.value)) add(n, 'property', name, value.value)
      }
    }
    for (const [k, v] of Object.entries(n)) if (k !== 'type' && v && typeof v === 'object') visit(v, inner)
  }
  visit(ast, false)
  return out
}

export function hardcodedAll(srcDir: string): Hardcoded[] {
  return sourceFiles(srcDir)
    .filter((f) => f.endsWith('.tsx') || /\/(features|lib)\//.test(f))
    .flatMap((f) => findHardcoded(readFileSync(f, 'utf8'), relative(srcDir, f)))
}

// ------------------------------------------------------------------------------------------------ English-leftover heuristic
export interface LeftoverLists {
  functionWords: string[]
  uiWords: string[]
  allowPhrases: string[]
  allowWords: string[]
}

/** Whole lower-cased tokens of `text` that are English function / UI words (placeholders, tags, brand names and allow-listed phrases removed first). */
export function englishLeftovers(text: string, lists: LeftoverLists): string[] {
  let s = text.replace(/\{\w+\}/g, ' ').replace(/<\/?[a-z]+>/g, ' ')
  for (const p of lists.allowPhrases) s = s.split(p).join(' ')
  const allow = new Set(lists.allowWords.map((w) => w.toLowerCase()))
  const english = new Set([...lists.functionWords, ...lists.uiWords])
  const tokens = s.toLowerCase().match(/[\p{L}]+/gu) ?? []
  return [...new Set(tokens.filter((tk) => english.has(tk) && !allow.has(tk)))]
}

