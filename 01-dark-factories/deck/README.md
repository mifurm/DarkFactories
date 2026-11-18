# Executive deck — Dark Factory (Nightshift)

| File | What it is |
|---|---|
| `DarkFactory-Executive-Deck.pptx` / `.pdf` | Full deck: 18 storyline slides, product tour (auto-included), **Azure opportunity (ACR)** section for Microsoft and partner leadership (at-a-glance, ACR by year/family/attach/tier, the five **expansion levers** E1–E5, ACR by lever, the ACR expansion path to a 100-plant fleet, land-and-expand, sizing, audit table), appendix. Speaker notes (60–120 words) on every slide. |
| `DarkFactory-Executive-Deck-customer.pptx` | Same storyline **without** the Azure-opportunity section, for customer-only audiences (it keeps the customer-side economics of the optional expansion modules in the appendix and never says "ACR"). |
| `build_deck.py` | Builds both decks with the shared `deckkit` (python-pptx). Idempotent; reads numbers only from `../business-case/outputs.json`. |
| `assets/screens/` | UI screenshots (1600×900 PNG, `NN-<view>.png`) filled by engineering. |

## Rebuild

```bash
/Users/michalfu/Dev/SwarmAI/.venv/bin/python deck/build_deck.py          # prints warnings / notes-length problems (must be 0)
/Users/michalfu/Dev/SwarmAI/.venv/bin/python /Users/michalfu/Dev/SwarmAI/tools/deckkit/render.py \
    deck/DarkFactory-Executive-Deck.pptx --out deck/_qa --dpi 80 --sheet --pdf-next-to-pptx   # PDF + page PNGs; delete deck/_qa afterwards
```

Re-run after engineering changes anything the deck reads:

* **Screenshots** — every PNG in `assets/screens/` becomes a tour slide, sorted by filename. The first four go into the main storyline, the rest into the appendix.
  Captions and call-outs are chosen by word in the file name (`control`, `swarm`/`agent`, `twin`/`what-if`, `autonomy`/`policy`, `approval`/`inbox`, `ledger`, `ask`/`copilot`, `digest`/`shift`, `readiness`, `roi`/`calculator`, `ab`, `fleet`, `feature`, `kill`, `predictive`/`maintenance`, `planner`/`gantt`, `quality`/`spc`, `deployment`); other names get a generic caption, and files starting with `_` are ignored.
* **Feature status** — the appendix feature list and the capability-map subtitle read the status board in `../FEATURES.md`.
* **Numbers** — after any change to `business-case/assumptions.json` or `model.py`, run `python model.py` there first, then rebuild the deck.

Every number on a slide is either read from `outputs.json` (Base scenario unless stated) or carries a bracketed source `[n]` listed on the Sources slides.
