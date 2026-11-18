/**
 * Source-text extraction for the completeness test: finds every translatable literal in the app code with the TypeScript AST.
 *   t("text") · tx("text <tag>…</tag>") · msg("text")          → message keys
 *   tn(count, { one: "…", other: "…" })                        → plural keys (the English `other` form is the key)
 *   tEnum("group", id) · tOpen("group", id)                    → enum groups in use
 * Calls whose first argument is not a literal are reported as "dynamic" (allowed only in a short allowlist: they are fed by msg() constants).
 * Test-only module: it needs the `typescript` package and node's fs.
 */
import fs from "node:fs";
import path from "node:path";
import ts from "typescript";

export interface Site {
  file: string;
  line: number;
}
export interface Extraction {
  messages: Map<string, Site[]>;
  plurals: Map<string, { one: string; sites: Site[] }[]>;
  enumGroups: Map<string, Site[]>;
  dynamic: (Site & { text: string })[];
}

const EXCLUDED = [/\.test\.tsx?$/, /[\\/]i18n[\\/]en\.ts$/, /[\\/]i18n[\\/]pl\.ts$/, /[\\/]i18n[\\/]pl[\\/]/, /[\\/]i18n[\\/]extract\.ts$/];

function walk(dir: string, out: string[] = []): string[] {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) walk(p, out);
    else if (/\.tsx?$/.test(e.name) && !EXCLUDED.some((r) => r.test(p))) out.push(p);
  }
  return out;
}

const literal = (n: ts.Node | undefined): string | null => (n && (ts.isStringLiteral(n) || ts.isNoSubstitutionTemplateLiteral(n)) ? n.text : null);

function calleeName(e: ts.Expression): string | null {
  if (ts.isIdentifier(e)) return e.text;
  if (ts.isPropertyAccessExpression(e)) return e.name.text;
  return null;
}

function push<K, V>(m: Map<K, V[]>, k: K, v: V) {
  const a = m.get(k);
  if (a) a.push(v);
  else m.set(k, [v]);
}

export function extractFromSource(srcDir: string): Extraction {
  const ex: Extraction = { messages: new Map(), plurals: new Map(), enumGroups: new Map(), dynamic: [] };
  for (const file of walk(srcDir)) {
    const text = fs.readFileSync(file, "utf8");
    const sf = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true, file.endsWith("x") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
    const rel = path.relative(srcDir, file);
    const site = (n: ts.Node): Site => ({ file: rel, line: sf.getLineAndCharacterOfPosition(n.getStart()).line + 1 });
    const visit = (n: ts.Node) => {
      if (ts.isCallExpression(n)) {
        const name = calleeName(n.expression);
        const a0 = n.arguments[0];
        if (name === "t" || name === "tx" || name === "msg") {
          const k = literal(a0);
          if (k !== null) push(ex.messages, k, site(n));
          else if (a0) ex.dynamic.push({ ...site(n), text: a0.getText(sf) });
        } else if (name === "tn") {
          const obj = n.arguments[1];
          if (obj && ts.isObjectLiteralExpression(obj)) {
            const get = (p: string) => {
              const prop = obj.properties.find((x) => ts.isPropertyAssignment(x) && x.name.getText(sf) === p) as ts.PropertyAssignment | undefined;
              return literal(prop?.initializer);
            };
            const one = get("one");
            const other = get("other");
            if (one !== null && other !== null) {
              const list = ex.plurals.get(other) ?? [];
              let entry = list.find((e) => e.one === one);
              if (!entry) list.push((entry = { one, sites: [] }));
              entry.sites.push(site(n));
              ex.plurals.set(other, list);
            } else ex.dynamic.push({ ...site(n), text: obj.getText(sf) });
          } else ex.dynamic.push({ ...site(n), text: obj ? obj.getText(sf) : "(no forms)" });
        } else if (name === "tEnum" || name === "tOpen" || name === "hasEnum" || name === "findEnum") {
          const g = literal(a0);
          if (g !== null) push(ex.enumGroups, g, site(n));
          else if (a0) ex.dynamic.push({ ...site(n), text: a0.getText(sf) });
        }
      }
      ts.forEachChild(n, visit);
    };
    visit(sf);
  }
  return ex;
}
