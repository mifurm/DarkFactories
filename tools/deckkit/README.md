# deckkit — executive-deck toolkit (python-pptx wrapper)

16:9, Arial, flat modern look, **native editable charts/tables/shapes**, measured text-fitting (text never overflows its box), speaker notes on every slide,
per-concept colour themes. Built and verified with headless LibreOffice rendering (no GUI automation of Office/Keynote).

```python
import sys
sys.path.insert(0, "/Users/michalfu/Dev/SwarmAI/tools/deckkit")
from deckkit import Deck, Theme          # run with /Users/michalfu/Dev/SwarmAI/.venv/bin/python

d = Deck(Theme.dark_factory(), footer="SwarmAI · Dark Factory · Confidential draft", title="Dark Factory — Executive deck")
d.title_slide("The factory that runs itself", "An Azure-native swarm of AI agents ...", meta="Executive briefing · November 2026", notes="...")
d.bullets("Takeaway-sentence title", ["**Bold lead** — text", ("Parent", ["sub 1", "sub 2"])], takeaway="So what.", notes="speaker notes", source="Source: ...")
d.save("deck/DarkFactory-Executive-Deck.pptx")
print(d.warnings)                         # MUST be empty before you finish (overflow / table-too-tall warnings)
```
Themes: `Theme.dark_factory()`, `Theme.commercial_studio()`, `Theme.contact_center()` (or `Theme(accent="…", dark="…")`).
Working example of every slide type: `example_deck.py` (`python example_deck.py /tmp/x.pptx`).

## Visual QA (mandatory)
```bash
/Users/michalfu/Dev/SwarmAI/.venv/bin/python /Users/michalfu/Dev/SwarmAI/tools/deckkit/render.py deck/X.pptx --out /tmp/qa-<concept> --dpi 80 --sheet --pdf-next-to-pptx
```
Writes the PDF (and copies it next to the .pptx with `--pdf-next-to-pptx`), one PNG per slide (`*-pNN.png`) and contact sheets (`*-sheet-N.png`).
LOOK at the sheets and then at every page you changed (use the image-capable `view` tool). Fix overlaps, overflow, tiny text, empty space, wrong chart values.
Render takes ~5 s. Use `--dpi 110` for a closer look.

## Slide types (all accept `notes=`, `hidden=`, and most `subtitle=`, `takeaway=`, `source=`)
| Method | Use for | Key args |
|---|---|---|
| `title_slide(title, subtitle, tagline, meta)` | opener (dark, swarm graphic) | |
| `section(title, subtitle, number)` | divider (e.g. the ACR section) | |
| `bullets(title, items, side_title, side_items, size)` | 3–6 bullets; optional right-hand card | items: `str` / `(str,[subs])`; **bold** markup |
| `two_column(title, left_title, left_items, right_title, right_items)` | contrast / do vs don't | |
| `kpi_cards(title, cards)` | headline numbers (≤ 8) | `{'value','label','sub','color'?}` |
| `chart(title, categories, series, kind, number_format, commentary, commentary_title, labels, label_format, colors)` | native charts | kind: `column stacked stacked100 bar stacked_bar line area doughnut pie`; `label_format="pct"` for pie/doughnut shares; Excel number formats e.g. `'$#,##0.0,,"M"'` (millions from raw dollars) or `'$#,##0.0"M"'` (already in millions) |
| `waterfall(title, steps, number_format, commentary)` | benefit→cost bridge | steps `[(label, +/-value)]`, total bar auto-added |
| `tornado(title, drivers, base_value, metric_label)` | sensitivity of NPV | drivers `[(name, low_metric, high_metric)]` (absolute metric values) |
| `table(title, headers, rows, col_weights, align, highlight_rows, font_pt)` | numbers (≤ ~9 rows/slide; split otherwise) | auto font-fit; warns if too tall |
| `architecture(title, layers, side)` | layer-cake Azure architecture | layers `[{'name','items':[str\|{'title','sub'}],'color'?}]`, `side={'name','items'}` for cross-cutting band |
| `hub_spoke(title, hub, spokes, ring_note)` | swarm / orchestrator topology (≤ 10 spokes) | |
| `diagram(title, nodes, edges)` | flows (voice path, pipelines, data flow) | node `{'id','x','y','w','h','title','sub','kind': box\|dark\|accent\|ghost}`, coords in inches inside the content area (≈ 12.1 × 4.4); edge `{'from','to','label','dashed','bidir'}` — leave ≥ 1.3" between nodes that carry edge labels |
| `process(title, steps)` | 3–6 step chevron flow | `{'title','body'}` |
| `timeline(title, phases)` | adoption roadmap (≤ 5) | `{'name','when','items'}` |
| `comparison(title, left_title, left_items, right_title, right_items)` | before/after | |
| `capability_map(title, groups)` | epics → features grid | `{'name','items'}` |
| `big_statement(title, statement, sub, bullets)` | "the ask" | |
| `screenshot(title, image, caption, callouts)` | one UI screenshot + numbered callouts | |
| `product_tour(dir, captions={...})` | one slide per PNG in `deck/assets/screens/` (sorted); returns count (0 if none) | `captions['01-x.png']={'title','caption','callouts':[...],'takeaway','notes'}` |
| `sources(title, items)` | paginated reference list | |
| `set_section("AZURE OPPORTUNITY · ACR")` | small caps label above every following title (call `set_section(None)` to clear) | |

## House style (follow it)
* Titles are **takeaway sentences** (≤ 2 lines, ~12 words), not topics. One message per slide. ≤ 6 bullets, ≤ ~18 words each; numbers in **bold**.
* Every number comes from `business-case/outputs.json` or a cited source (`source=` line). Say "illustrative / simulation" where true.
* Charts: label only what matters. For stacked columns with tiny segments pass `labels=False` and put totals in the title/commentary. Prefer `kind="line"` / `waterfall` for cumulative net benefit.
  Use the theme palette (default) — don't hand-pick colours unless encoding good/bad.
* Notes on EVERY slide: 60–120 words of speaker talk-track (what to say, the proof point, the likely question). `notes=` is required by the house standard.
* Architecture diagrams: 4–6 layers max; cross-cutting concerns in the `side` band; keep box text ≤ 4 words + optional 3-word `sub`.
* Divider before the Azure-opportunity part (`section(..., number="02")`) then `set_section("Azure opportunity · ACR")` so each slide is tagged.
* Hidden slides: `hidden=True` (e.g. appendix backups).
* Check `deck.warnings` — `text overflow`, `table too tall`, `title too long` must be fixed (shorten text or split the slide), not ignored.

## Notes on rendering
`deckkit` sets `invertIfNegative=0` on bar series (otherwise PowerPoint shows white negative bars and LibreOffice mirrors them) and removes shape style
references (theme shadows). Decks open natively in PowerPoint/Keynote; the PDF is produced with LibreOffice. Fonts: Arial everywhere.
