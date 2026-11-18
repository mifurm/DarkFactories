"""deckkit — a small, opinionated python-pptx wrapper for consulting-grade executive decks.

16:9, Arial, generous whitespace, native (editable) charts/tables/shapes, measured text-fitting so
nothing overflows, speaker notes on every slide.  See README.md for the API and an example.
"""
from __future__ import annotations

import colorsys
import math
import os
import random
import re
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

from lxml import etree
from PIL import Image, ImageDraw, ImageFont
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION, XL_LEGEND_POSITION, XL_TICK_LABEL_POSITION
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt

SLIDE_W = 13.333
SLIDE_H = 7.5
MARGIN = 0.6
CONTENT_W = SLIDE_W - 2 * MARGIN

_HERE = Path(__file__).resolve().parent


# --------------------------------------------------------------------------------------
# colour helpers
# --------------------------------------------------------------------------------------
def rgb(hex_: str) -> RGBColor:
    h = hex_.lstrip("#")
    return RGBColor(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def tint(hex_: str, factor: float) -> str:
    """Blend colour toward white. factor 0 = original, 1 = white."""
    h = hex_.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    r = int(r + (255 - r) * factor)
    g = int(g + (255 - g) * factor)
    b = int(b + (255 - b) * factor)
    return f"{r:02X}{g:02X}{b:02X}"


def shade(hex_: str, factor: float) -> str:
    """Blend colour toward black."""
    h = hex_.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    return f"{int(r * (1 - factor)):02X}{int(g * (1 - factor)):02X}{int(b * (1 - factor)):02X}"


@dataclass
class Theme:
    name: str = "SwarmAI"
    ink: str = "0B1F3A"
    muted: str = "5B6B7F"
    faint: str = "94A3B8"
    line: str = "D9E0EA"
    card: str = "F3F6FA"
    bg: str = "FFFFFF"
    dark: str = "0B1F3A"
    accent: str = "0078D4"
    accent2: str = "00B7C3"
    accent3: str = "FFB900"
    good: str = "107C10"
    bad: str = "C4314B"
    font: str = "Arial"
    palette: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.palette:
            self.palette = (self.accent, "0078D4", self.accent2, self.accent3, "8764B8", "107C10", "C4314B", "7A8CA3")

    # ---- concept themes -------------------------------------------------------------
    @classmethod
    def dark_factory(cls) -> "Theme":
        return cls(name="Dark Factory", dark="0A1220", ink="0F1B2D", accent="E8890C", accent2="2BA3D8", accent3="3DB88B",
                   palette=("E8890C", "2BA3D8", "3DB88B", "8764B8", "C4314B", "FFB900", "0078D4", "7A8CA3"))

    @classmethod
    def commercial_studio(cls) -> "Theme":
        return cls(name="Commercial Studio", dark="140B2E", ink="1B1238", accent="7C3AED", accent2="EC4899", accent3="06B6D4",
                   palette=("7C3AED", "EC4899", "06B6D4", "F59E0B", "22C55E", "0078D4", "C4314B", "7A8CA3"))

    @classmethod
    def contact_center(cls) -> "Theme":
        return cls(name="Contact Center", dark="062C33", ink="0B2530", accent="0E9AA7", accent2="2F6FED", accent3="F2A900",
                   palette=("0E9AA7", "2F6FED", "F2A900", "8764B8", "22A06B", "C4314B", "0078D4", "7A8CA3"))


# --------------------------------------------------------------------------------------
# text measurement (so text never overflows its box)
# --------------------------------------------------------------------------------------
_FONT_CANDIDATES = {
    False: ["/System/Library/Fonts/Supplemental/Arial.ttf", "/Library/Fonts/Arial.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"],
    True: ["/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/Library/Fonts/Arial Bold.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"],
}
_SCALE = 8


class _Meter:
    def __init__(self) -> None:
        self._fonts: dict[tuple[bool, int], ImageFont.FreeTypeFont] = {}
        self._paths: dict[bool, str] = {}
        for bold, cands in _FONT_CANDIDATES.items():
            for c in cands:
                if os.path.exists(c):
                    self._paths[bold] = c
                    break
        if not self._paths:  # fall back to matplotlib's bundled DejaVu (wider => conservative)
            import matplotlib

            base = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
            self._paths = {False: str(base / "DejaVuSans.ttf"), True: str(base / "DejaVuSans-Bold.ttf")}

    def _font(self, pt: float, bold: bool) -> ImageFont.FreeTypeFont:
        key = (bold, int(round(pt * _SCALE)))
        if key not in self._fonts:
            self._fonts[key] = ImageFont.truetype(self._paths.get(bold, self._paths[False]), key[1])
        return self._fonts[key]

    def width_in(self, text: str, pt: float, bold: bool = False) -> float:
        return self._font(pt, bold).getlength(text) / _SCALE / 72.0


_METER = _Meter()
_BOLD_RE = re.compile(r"(\*\*.+?\*\*)")


def parse_runs(text: str) -> list[tuple[str, bool]]:
    """Split '**bold** rest' into [(text, bold)] runs."""
    out: list[tuple[str, bool]] = []
    for part in _BOLD_RE.split(text):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            out.append((part[2:-2], True))
        else:
            out.append((part, False))
    return out or [("", False)]


def _wrap_lines(runs: list[tuple[str, bool]], pt: float, width_in: float, base_bold: bool) -> int:
    """Greedy word-wrap; returns number of lines."""
    tokens: list[tuple[str, bool]] = []
    for txt, b in runs:
        for w in re.findall(r"\S+\s*", txt) or [""]:
            tokens.append((w, b or base_bold))
    lines, cur = 1, 0.0
    for w, b in tokens:
        wlen = _METER.width_in(w.rstrip(), pt, b)
        full = _METER.width_in(w, pt, b)
        if cur + wlen > width_in and cur > 0:
            lines += 1
            cur = full
        else:
            cur += full
    return lines


@dataclass
class Para:
    text: str
    size: float | None = None
    bold: bool = False
    color: str | None = None
    bullet: str | None = None  # None, "•", "–", "1."
    level: int = 0
    space_after: float = 4.0
    align: str = "left"
    italic: bool = False


def _as_para(p: Any, default_bullet: str | None = None) -> Para:
    if isinstance(p, Para):
        return p
    if isinstance(p, str):
        return Para(p, bullet=default_bullet)
    if isinstance(p, dict):
        return Para(**p)
    if isinstance(p, (tuple, list)) and len(p) == 2 and isinstance(p[1], (list, tuple)):  # (text, [subs]) handled by caller
        return Para(p[0], bullet=default_bullet)
    raise TypeError(f"cannot convert {p!r} to Para")


def _flatten_bullets(items: Sequence[Any], bullet: str | None = "•") -> list[Para]:
    out: list[Para] = []
    for it in items:
        if isinstance(it, (tuple, list)) and len(it) == 2 and isinstance(it[1], (list, tuple)):
            out.append(_as_para(it[0], bullet))
            for sub in it[1]:
                sp = _as_para(sub, "–")
                sp.level = 1
                sp.bullet = "–"
                out.append(sp)
        else:
            out.append(_as_para(it, bullet))
    return out


_INDENT = {0: 0.2, 1: 0.2}  # hanging indent in inches
_LINE = 1.2  # line-height multiplier for Arial (measured, conservative)


def estimate_height(paras: Sequence[Para], width_in: float, size: float, line_mult: float = _LINE) -> float:
    total = 0.0
    for p in paras:
        sz = p.size if p.size else size
        left = (0.0 if not p.bullet else _INDENT[min(p.level, 1)]) + (0.28 * p.level)
        avail = max(0.3, width_in - left) * 0.965
        n = _wrap_lines(parse_runs(p.text), sz, avail, p.bold)
        total += n * sz * line_mult / 72.0 + p.space_after / 72.0
    return total


def fit_size(paras: Sequence[Para], width_in: float, height_in: float, max_pt: float, min_pt: float, step: float = 0.5) -> tuple[float, bool]:
    """Largest font size (pt) so that all paragraphs fit; returns (size, fits)."""
    size = max_pt
    while size >= min_pt - 1e-6:
        scaled = [Para(**{**p.__dict__, "size": (p.size * size / max_pt) if p.size else None}) for p in paras]
        if estimate_height(scaled, width_in, size) <= height_in:
            return size, True
        size -= step
    return min_pt, False


# --------------------------------------------------------------------------------------
# low-level xml helpers
# --------------------------------------------------------------------------------------
def _set_bullet(p, char: str | None, level: int, size_pt: float, color_hex: str | None) -> None:
    pPr = p._p.get_or_add_pPr()
    for tag in ("a:buNone", "a:buChar", "a:buAutoNum", "a:buFont", "a:buClr", "a:buSzPct"):
        for el in pPr.findall(qn(tag)):
            pPr.remove(el)
    if char is None:
        pPr.set("marL", "0")
        pPr.set("indent", "0")
        etree.SubElement(pPr, qn("a:buNone"))
        return
    base = _INDENT[min(level, 1)]
    marL = int(Inches(base + 0.28 * level))
    pPr.set("marL", str(marL))
    pPr.set("indent", str(-int(Inches(base))))
    if color_hex:
        buClr = etree.SubElement(pPr, qn("a:buClr"))
        srgb = etree.SubElement(buClr, qn("a:srgbClr"))
        srgb.set("val", color_hex)
    buFont = etree.SubElement(pPr, qn("a:buFont"))
    buFont.set("typeface", "Arial")
    bu = etree.SubElement(pPr, qn("a:buChar"))
    bu.set("char", char)


def _line_arrow(connector, color_hex: str, width_pt: float = 1.5, head: bool = True, dash: bool = False) -> None:
    connector.line.color.rgb = rgb(color_hex)
    connector.line.width = Pt(width_pt)
    ln = connector.line._get_or_add_ln()
    if dash:
        d = etree.SubElement(ln, qn("a:prstDash"))
        d.set("val", "dash")
    if head:
        tail = etree.SubElement(ln, qn("a:tailEnd"))
        tail.set("type", "triangle")
        tail.set("w", "med")
        tail.set("len", "med")


def _cell_border(cell, color_hex: str, width_pt: float = 0.75, sides: Iterable[str] = ("b",)) -> None:
    tcPr = cell._tc.get_or_add_tcPr()
    for side in ("l", "r", "t", "b"):
        tag = qn(f"a:ln{side.upper()}")
        for el in tcPr.findall(tag):
            tcPr.remove(el)
        ln = etree.SubElement(tcPr, tag)
        if side in sides:
            ln.set("w", str(int(Pt(width_pt))))
            fill = etree.SubElement(ln, qn("a:solidFill"))
            c = etree.SubElement(fill, qn("a:srgbClr"))
            c.set("val", color_hex)
        else:
            ln.set("w", "0")
            etree.SubElement(ln, qn("a:noFill"))
    # fills must come after borders in schema order: move any fill to the end
    for fill_tag in ("a:solidFill", "a:noFill"):
        for el in tcPr.findall(qn(fill_tag)):
            tcPr.remove(el)
            tcPr.append(el)


# --------------------------------------------------------------------------------------
# the Deck
# --------------------------------------------------------------------------------------
class Deck:
    def __init__(self, theme: Theme | None = None, footer: str = "SwarmAI · Confidential draft", title: str = "", author: str = "SwarmAI"):
        self.t = theme or Theme()
        self.footer = footer
        self.prs = Presentation()
        self.prs.slide_width = Inches(SLIDE_W)
        self.prs.slide_height = Inches(SLIDE_H)
        self.prs.core_properties.title = title
        self.prs.core_properties.author = author
        self.prs.core_properties.subject = self.t.name
        self.warnings: list[str] = []
        self._cache = _HERE / ".cache"
        self._cache.mkdir(exist_ok=True)
        self._section_label: str | None = None
        self._count = 0

    # ---- plumbing -----------------------------------------------------------------
    def _warn(self, msg: str) -> None:
        self.warnings.append(f"slide {self._count}: {msg}")
        warnings.warn(f"deckkit slide {self._count}: {msg}")

    def set_section(self, label: str | None) -> None:
        """Small caps label shown above every following slide title (e.g. 'AZURE OPPORTUNITY · ACR')."""
        self._section_label = label

    def _new(self, title: str | None, bg: str | None = None, notes: str | None = None, show_footer: bool = True, hidden: bool = False):
        layout = self.prs.slide_layouts[5] if title is not None else self.prs.slide_layouts[6]
        s = self.prs.slides.add_slide(layout)
        self._count += 1
        if hidden:
            s._element.set("show", "0")
        fill = s.background.fill
        fill.solid()
        fill.fore_color.rgb = rgb(bg or self.t.bg)
        dark_bg = bg is not None and bg != self.t.bg
        if title is not None:
            self._title(s, title, dark=dark_bg)
        if show_footer:
            self._footer(s, dark=dark_bg)
        if notes:
            s.notes_slide.notes_text_frame.text = notes
        return s

    def _title(self, s, text: str, dark: bool = False) -> None:
        ph = s.shapes.title
        ph.left, ph.top, ph.width, ph.height = Inches(MARGIN), Inches(0.52), Inches(CONTENT_W), Inches(0.95)
        tf = ph.text_frame
        tf.word_wrap = True
        tf.auto_size = MSO_AUTO_SIZE.NONE
        tf.vertical_anchor = MSO_ANCHOR.TOP
        tf.margin_left = tf.margin_right = Inches(0.02)
        tf.margin_top = tf.margin_bottom = Inches(0.02)
        para = Para(text, bold=True, space_after=0)
        size, ok = fit_size([para], CONTENT_W - 0.1, 0.92, 28, 20, 1)
        if not ok:
            self._warn(f"title too long: {text[:70]!r}")
        p = tf.paragraphs[0]
        p.alignment = PP_ALIGN.LEFT
        p.line_spacing = 0.95
        for txt, b in parse_runs(text):
            r = p.add_run()
            r.text = txt
            r.font.name = self.t.font
            r.font.size = Pt(size)
            r.font.bold = True
            r.font.color.rgb = rgb("FFFFFF" if dark else self.t.ink)
        # accent tick + optional section label above the title
        bar = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(MARGIN), Inches(0.34), Inches(0.5), Inches(0.06))
        self._flat(bar, self.t.accent)
        if self._section_label:
            self.text(s, MARGIN + 0.62, 0.22, 8.0, 0.3, [Para(self._section_label.upper(), size=9.5, bold=True, color=self.t.accent, space_after=0)], size=9.5, min_size=8, fit=False)

    def _footer(self, s, dark: bool = False) -> None:
        col = self.t.faint if dark else self.t.muted
        if not dark:
            ln = s.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(MARGIN), Inches(7.02), Inches(SLIDE_W - MARGIN), Inches(7.02))
            ln.line.color.rgb = rgb(self.t.line)
            ln.line.width = Pt(0.5)
        self.text(s, MARGIN, 7.08, 9.0, 0.28, [Para(self.footer, size=9, color=col, space_after=0)], size=9, min_size=8, fit=False)
        tb = s.shapes.add_textbox(Inches(SLIDE_W - MARGIN - 1.0), Inches(7.08), Inches(1.0), Inches(0.28))
        tf = tb.text_frame
        tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
        p = tf.paragraphs[0]
        p.alignment = PP_ALIGN.RIGHT
        fld = etree.SubElement(p._p, qn("a:fld"))
        fld.set("id", "{B6F15528-21DE-4FAA-801E-634DDDAF4B2B}")
        fld.set("type", "slidenum")
        rPr = etree.SubElement(fld, qn("a:rPr"))
        rPr.set("lang", "en-US")
        rPr.set("sz", "900")
        sf = etree.SubElement(rPr, qn("a:solidFill"))
        c = etree.SubElement(sf, qn("a:srgbClr"))
        c.set("val", col)
        lat = etree.SubElement(rPr, qn("a:latin"))
        lat.set("typeface", self.t.font)
        t = etree.SubElement(fld, qn("a:t"))
        t.text = str(self._count)

    def _flat(self, shape, fill_hex: str | None, line_hex: str | None = None, line_pt: float = 0.75) -> None:
        if fill_hex is None:
            shape.fill.background()
        else:
            shape.fill.solid()
            shape.fill.fore_color.rgb = rgb(fill_hex)
        if line_hex is None:
            shape.line.fill.background()
        else:
            shape.line.color.rgb = rgb(line_hex)
            shape.line.width = Pt(line_pt)
        shape.shadow.inherit = False
        # LibreOffice ignores the empty effectLst override and applies the theme shadow from p:style -> drop the style reference
        st = shape._element.find(qn("p:style"))
        if st is not None:
            shape._element.remove(st)

    def _rect(self, s, x, y, w, h, fill_hex, line_hex=None, radius: float | None = None, line_pt: float = 0.75, shape=None):
        kind = shape or (MSO_SHAPE.ROUNDED_RECTANGLE if radius else MSO_SHAPE.RECTANGLE)
        sh = s.shapes.add_shape(kind, Inches(x), Inches(y), Inches(w), Inches(h))
        if radius and kind == MSO_SHAPE.ROUNDED_RECTANGLE:
            sh.adjustments[0] = min(0.5, radius / max(0.1, min(w, h)))
        self._flat(sh, fill_hex, line_hex, line_pt)
        return sh

    # ---- text ---------------------------------------------------------------------
    def text(self, s, x, y, w, h, paras, size: float = 14, min_size: float = 10, color: str | None = None, bold: bool = False,
             align: str = "left", anchor: str = "top", fit: bool = True, bullet: str | None = None, inset: float = 0.04,
             line_spacing: float = 1.0, shape=None, label: str = ""):
        """Add (or fill) a text box. `paras`: str | list[str|Para|dict|(text,[subs])]. **bold** markup supported."""
        if isinstance(paras, str):
            paras = [paras]
        plist = _flatten_bullets(paras, bullet) if bullet else [_as_para(p) if not (isinstance(p, (tuple, list))) else p for p in paras]
        if any(isinstance(p, (tuple, list)) for p in plist):
            plist = _flatten_bullets(paras, bullet or "•")
        for p in plist:
            if p.bold is False and bold:
                p.bold = True
        sh = shape or s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
        tf = sh.text_frame
        tf.word_wrap = True
        tf.auto_size = MSO_AUTO_SIZE.NONE
        tf.margin_left = tf.margin_right = Inches(inset)
        tf.margin_top = tf.margin_bottom = Inches(inset)
        tf.vertical_anchor = {"top": MSO_ANCHOR.TOP, "middle": MSO_ANCHOR.MIDDLE, "bottom": MSO_ANCHOR.BOTTOM}[anchor]
        avail_w, avail_h = w - 2 * inset, h - 2 * inset
        if fit:
            use, ok = fit_size(plist, avail_w, avail_h, size, min_size)
            if not ok:
                self._warn(f"text overflow in box {label or plist[0].text[:50]!r} ({w:.1f}x{h:.1f}in) at {min_size}pt")
        else:
            use = size
        ratio = use / size
        col_default = color or self.t.ink
        for i, p in enumerate(plist):
            para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            para.alignment = {"left": PP_ALIGN.LEFT, "center": PP_ALIGN.CENTER, "right": PP_ALIGN.RIGHT}[p.align if p.align != "left" else align]
            para.line_spacing = line_spacing
            para.space_after = Pt(p.space_after * ratio)
            psz = (p.size * ratio) if p.size else use
            pcol = p.color or col_default
            _set_bullet(para, p.bullet, p.level, psz, self.t.accent if p.bullet else None)
            for txt, b in parse_runs(p.text):
                r = para.add_run()
                r.text = txt
                r.font.name = self.t.font
                r.font.size = Pt(round(psz * 2) / 2)
                r.font.bold = bool(b or p.bold)
                r.font.italic = p.italic
                r.font.color.rgb = rgb(pcol)
        return sh

    # ---- slide types ----------------------------------------------------------------
    def title_slide(self, title: str, subtitle: str | None = None, tagline: str = "SWARMAI · CONCEPT BRIEF", meta: str | None = None, notes: str | None = None):
        s = self._new(None, bg=self.t.dark, notes=notes, show_footer=False)
        img = self._swarm_png()
        pic = s.shapes.add_picture(str(img), Inches(6.35), Inches(0), height=Inches(SLIDE_H))
        pic.left = Inches(SLIDE_W) - pic.width
        self._rect(s, 0.8, 1.55, 0.9, 0.08, self.t.accent)
        self.text(s, 0.8, 1.75, 6.6, 0.4, [Para(tagline, size=12, bold=True, color=self.t.accent3, space_after=0)], size=12, fit=False)
        self.text(s, 0.8, 2.25, 6.6, 2.6, [Para(title, bold=True, color="FFFFFF", space_after=0)], size=44, min_size=28, color="FFFFFF", line_spacing=0.95, label="title")
        if subtitle:
            self.text(s, 0.8, 4.95, 6.3, 1.1, [Para(subtitle, color="C9D6EA", space_after=0)], size=20, min_size=14, color="C9D6EA", label="subtitle")
        if meta:
            self.text(s, 0.8, 6.65, 8.0, 0.4, [Para(meta, size=11, color=self.t.faint, space_after=0)], size=11, fit=False)
        return s

    def section(self, title: str, subtitle: str | None = None, number: str | None = None, notes: str | None = None, hidden: bool = False):
        bg = shade(self.t.dark, 0.0)
        s = self._new(None, bg=bg, notes=notes, show_footer=False, hidden=hidden)
        self._rect(s, 0, 0, 0.35, SLIDE_H, self.t.accent)
        if number:
            self.text(s, 1.0, 1.9, 3.0, 1.6, [Para(number, size=96, bold=True, color=self.t.accent, space_after=0)], size=96, fit=False)
        self.text(s, 1.0, 3.55, 11.0, 1.5, [Para(title, bold=True, color="FFFFFF", space_after=0)], size=40, min_size=28, color="FFFFFF", label="section title")
        if subtitle:
            self.text(s, 1.0, 5.1, 10.5, 1.2, [Para(subtitle, color="C9D6EA", space_after=0)], size=18, min_size=13, color="C9D6EA", label="section subtitle")
        self._footer(s, dark=True)
        return s

    def _content_top(self, subtitle: str | None, s=None) -> float:
        if subtitle:
            self.text(s, MARGIN, 1.42, CONTENT_W, 0.4, [Para(subtitle, size=15, color=self.t.muted, space_after=0)], size=15, min_size=11, label="subtitle")
            return 1.95
        return 1.62

    def _takeaway(self, s, text: str, y: float = 6.12, h: float = 0.55) -> None:
        self._rect(s, MARGIN, y, CONTENT_W, h, tint(self.t.accent, 0.88))
        self._rect(s, MARGIN, y, 0.08, h, self.t.accent)
        self.text(s, MARGIN + 0.25, y, CONTENT_W - 0.4, h, [Para(text, bold=True, space_after=0)], size=15, min_size=11, anchor="middle", label="takeaway")

    def _source(self, s, text: str | None) -> None:
        if text:
            self.text(s, MARGIN, 6.74, CONTENT_W, 0.24, [Para(text, size=8.5, color=self.t.muted, space_after=0)], size=8.5, min_size=7, label="source")

    def bullets(self, title: str, items: Sequence[Any], subtitle: str | None = None, takeaway: str | None = None, notes: str | None = None,
                source: str | None = None, side_title: str | None = None, side_items: Sequence[Any] | None = None, size: float = 18, hidden: bool = False):
        s = self._new(title, notes=notes, hidden=hidden)
        top = self._content_top(subtitle, s)
        bottom = 6.0 if takeaway else 6.65
        h = bottom - top
        if side_items:
            lw = CONTENT_W * 0.58
            self.text(s, MARGIN, top, lw, h, _flatten_bullets(items, "•"), size=size, min_size=11, bullet="•")
            x = MARGIN + lw + 0.35
            w = CONTENT_W - lw - 0.35
            self._rect(s, x, top, w, h, self.t.card, radius=0.1)
            paras: list[Any] = []
            if side_title:
                paras.append(Para(side_title.upper(), size=11, bold=True, color=self.t.accent, space_after=8))
            paras.extend(_flatten_bullets(side_items, "•"))
            self.text(s, x + 0.2, top + 0.15, w - 0.4, h - 0.3, paras, size=14, min_size=10)
        else:
            self.text(s, MARGIN, top, CONTENT_W, h, _flatten_bullets(items, "•"), size=size, min_size=11, bullet="•")
        if takeaway:
            self._takeaway(s, takeaway)
        self._source(s, source)
        return s

    def two_column(self, title: str, left_title: str, left_items: Sequence[Any], right_title: str, right_items: Sequence[Any], subtitle: str | None = None,
                   takeaway: str | None = None, notes: str | None = None, source: str | None = None, right_accent: bool = True, hidden: bool = False):
        s = self._new(title, notes=notes, hidden=hidden)
        top = self._content_top(subtitle, s)
        bottom = 6.0 if takeaway else 6.65
        colw = (CONTENT_W - 0.4) / 2
        for i, (ht, items) in enumerate(((left_title, left_items), (right_title, right_items))):
            x = MARGIN + i * (colw + 0.4)
            accent = self.t.accent if (i == 1 and right_accent) else self.t.muted
            self._rect(s, x, top, colw, 0.05, accent)
            self.text(s, x, top + 0.1, colw, 0.45, [Para(ht, bold=True, color=accent if i == 1 and right_accent else self.t.ink, space_after=0)], size=17, min_size=12)
            self.text(s, x, top + 0.62, colw, bottom - top - 0.62, _flatten_bullets(items, "•"), size=15, min_size=10.5, bullet="•")
        if takeaway:
            self._takeaway(s, takeaway)
        self._source(s, source)
        return s

    def kpi_cards(self, title: str, cards: Sequence[dict], subtitle: str | None = None, takeaway: str | None = None, notes: str | None = None,
                  source: str | None = None, columns: int | None = None, hidden: bool = False):
        """cards: [{'value': '−38%', 'label': 'Unplanned downtime', 'sub': 'Base case, year 3'}]"""
        s = self._new(title, notes=notes, hidden=hidden)
        top = self._content_top(subtitle, s)
        bottom = 6.0 if takeaway else 6.65
        n = len(cards)
        cols = columns or (n if n <= 4 else math.ceil(n / 2))
        rows = math.ceil(n / cols)
        gap = 0.3
        cw = (CONTENT_W - gap * (cols - 1)) / cols
        ch = min(2.6, (bottom - top - gap * (rows - 1)) / rows)
        y0 = top + max(0.0, (bottom - top - (rows * ch + gap * (rows - 1))) / 2 - 0.1)
        for i, c in enumerate(cards):
            r, k = divmod(i, cols)
            x = MARGIN + k * (cw + gap)
            y = y0 + r * (ch + gap)
            self._rect(s, x, y, cw, ch, self.t.card, radius=0.12)
            self._rect(s, x, y + 0.18, 0.07, ch - 0.36, c.get("color", self.t.accent))
            self.text(s, x + 0.28, y + 0.12, cw - 0.4, ch * 0.42, [Para(str(c["value"]), bold=True, color=c.get("color", self.t.accent), space_after=0)], size=38, min_size=20, anchor="middle", label="kpi value")
            self.text(s, x + 0.28, y + 0.12 + ch * 0.42, cw - 0.4, ch * 0.26, [Para(c["label"], bold=True, space_after=0)], size=15, min_size=10.5, anchor="top", label="kpi label")
            if c.get("sub"):
                self.text(s, x + 0.28, y + 0.12 + ch * 0.68, cw - 0.4, ch * 0.28, [Para(c["sub"], color=self.t.muted, space_after=0)], size=11.5, min_size=8.5, label="kpi sub")
        if takeaway:
            self._takeaway(s, takeaway)
        self._source(s, source)
        return s

    # ---- charts ---------------------------------------------------------------------
    def _style_chart(self, chart, number_format: str | None, legend: bool, labels: bool, label_fmt: str | None, font_pt: float = 11) -> None:
        chart.font.size = Pt(font_pt)
        chart.font.name = self.t.font
        chart.font.color.rgb = rgb(self.t.ink)
        chart.has_title = False
        chart.has_legend = legend
        if legend:
            chart.legend.position = XL_LEGEND_POSITION.BOTTOM
            chart.legend.include_in_layout = False
            chart.legend.font.size = Pt(font_pt)
        try:
            va = chart.value_axis
            va.has_major_gridlines = True
            va.major_gridlines.format.line.color.rgb = rgb(self.t.line)
            va.major_gridlines.format.line.width = Pt(0.5)
            va.format.line.fill.background()
            va.tick_labels.font.size = Pt(font_pt - 1)
            va.tick_labels.font.color.rgb = rgb(self.t.muted)
            if number_format:
                va.tick_labels.number_format = number_format
                va.tick_labels.number_format_is_linked = False
            ca = chart.category_axis
            ca.format.line.color.rgb = rgb(self.t.line)
            ca.tick_labels.font.size = Pt(font_pt)
            ca.has_major_gridlines = False
            ca.tick_label_position = XL_TICK_LABEL_POSITION.LOW  # keep labels at the bottom even when values go negative
        except Exception:  # doughnut/pie have no axes
            pass
        plot = chart.plots[0]
        if labels:
            plot.has_data_labels = True
            dl = plot.data_labels
            dl.font.size = Pt(font_pt - 1)
            dl.font.name = self.t.font
            if label_fmt or number_format:
                dl.number_format = label_fmt or number_format
                dl.number_format_is_linked = False

    def chart(self, title: str, categories: Sequence[str], series: dict[str, Sequence[float]], kind: str = "column", number_format: str | None = None,
              subtitle: str | None = None, commentary: Sequence[Any] | None = None, commentary_title: str | None = None, takeaway: str | None = None,
              notes: str | None = None, source: str | None = None, labels: bool = True, legend: bool | None = None, label_format: str | None = None,
              colors: Sequence[str] | None = None, hidden: bool = False, gap_width: int = 70):
        """kind: column | stacked | stacked100 | bar | stacked_bar | line | area | doughnut | pie"""
        s = self._new(title, notes=notes, hidden=hidden)
        top = self._content_top(subtitle, s)
        bottom = 6.0 if takeaway else 6.62
        cw = CONTENT_W if not commentary else CONTENT_W * 0.64
        self._add_chart(s, MARGIN, top, cw, bottom - top, categories, series, kind, number_format, legend, labels, label_format, colors, gap_width)
        if commentary:
            x = MARGIN + cw + 0.3
            w = CONTENT_W - cw - 0.3
            self._rect(s, x, top, w, bottom - top, self.t.card, radius=0.1)
            paras: list[Any] = []
            if commentary_title:
                paras.append(Para(commentary_title.upper(), size=11, bold=True, color=self.t.accent, space_after=8))
            paras.extend(_flatten_bullets(commentary, "•"))
            self.text(s, x + 0.2, top + 0.15, w - 0.4, bottom - top - 0.3, paras, size=14, min_size=10)
        if takeaway:
            self._takeaway(s, takeaway)
        self._source(s, source)
        return s

    def _add_chart(self, s, x, y, w, h, categories, series, kind, number_format, legend, labels, label_format, colors, gap_width=70):
        types = {
            "column": XL_CHART_TYPE.COLUMN_CLUSTERED, "stacked": XL_CHART_TYPE.COLUMN_STACKED, "stacked100": XL_CHART_TYPE.COLUMN_STACKED_100,
            "bar": XL_CHART_TYPE.BAR_CLUSTERED, "stacked_bar": XL_CHART_TYPE.BAR_STACKED, "line": XL_CHART_TYPE.LINE_MARKERS,
            "area": XL_CHART_TYPE.AREA_STACKED, "doughnut": XL_CHART_TYPE.DOUGHNUT, "pie": XL_CHART_TYPE.PIE,
        }
        cd = CategoryChartData()
        cd.categories = list(categories)
        for name, vals in series.items():
            cd.add_series(name, [float(v) for v in vals])
        gf = s.shapes.add_chart(types[kind], Inches(x), Inches(y), Inches(w), Inches(h), cd)
        chart = gf.chart
        if legend is None:
            legend = len(series) > 1 or kind in ("doughnut", "pie")
        self._style_chart(chart, number_format, legend, labels, label_format)
        pal = list(colors or self.t.palette)
        plot = chart.plots[0]
        if kind in ("doughnut", "pie"):
            ser = plot.series[0]
            for i in range(len(categories)):
                pt = ser.points[i]
                pt.format.fill.solid()
                pt.format.fill.fore_color.rgb = rgb(pal[i % len(pal)])
                pt.format.line.color.rgb = rgb("FFFFFF")
            if kind == "doughnut":
                hole = chart._chartSpace.xpath(".//c:holeSize")
                if hole:
                    hole[0].set("val", "58")
            if labels:
                dl = plot.data_labels
                dl.show_category_name = False
                dl.font.bold = True
                dl.font.size = Pt(11)
                dl.font.color.rgb = rgb("FFFFFF")
                if label_format == "pct":  # share-of-total labels
                    dl.show_value = False
                    dl.show_percentage = True
                    dl.number_format = "0%"
                    dl.number_format_is_linked = False
                else:
                    dl.show_value = True
                    dl.show_percentage = False
                    if number_format:
                        dl.number_format = label_format or number_format
                        dl.number_format_is_linked = False
        else:
            if hasattr(plot, "gap_width") and kind not in ("line", "area"):
                plot.gap_width = gap_width
            if kind in ("stacked", "stacked100", "stacked_bar"):
                plot.overlap = 100
            for i, ser in enumerate(plot.series):
                col = pal[i % len(pal)]
                if kind == "line":
                    ser.format.line.color.rgb = rgb(col)
                    ser.format.line.width = Pt(2.75)
                    ser.smooth = False
                    ser.marker.style = 8  # circle
                    ser.marker.size = 8
                    ser.marker.format.fill.solid()
                    ser.marker.format.fill.fore_color.rgb = rgb(col)
                    ser.marker.format.line.color.rgb = rgb("FFFFFF")
                else:
                    ser.format.fill.solid()
                    ser.format.fill.fore_color.rgb = rgb(col)
                    ser.format.line.fill.background()
                    ser.invert_if_negative = False  # absent flag = "invert" (white negative bars in PowerPoint, mirrored bars in LibreOffice)
            if labels and kind in ("stacked", "stacked100", "stacked_bar", "area"):
                plot.data_labels.font.color.rgb = rgb("FFFFFF")
            if kind in ("bar", "stacked_bar"):
                chart.category_axis.reverse_order = True
                chart.value_axis.tick_label_position = XL_TICK_LABEL_POSITION.HIGH if False else XL_TICK_LABEL_POSITION.NEXT_TO_AXIS
        return chart

    def waterfall(self, title: str, steps: Sequence[tuple[str, float]], number_format: str = '#,##0.0', subtitle: str | None = None,
                  takeaway: str | None = None, notes: str | None = None, source: str | None = None, total_label: str = "Net",
                  commentary: Sequence[Any] | None = None, commentary_title: str | None = None, hidden: bool = False):
        """steps: [('Downtime avoided', 12.3), ('Azure run cost', -3.1), ...] — a final total bar is appended automatically."""
        cats, base, up, down, tot = [], [], [], [], []
        running = 0.0
        for name, v in steps:
            cats.append(name)
            if v >= 0:
                base.append(running)
                up.append(v)
                down.append(0)
                running += v
            else:
                running += v
                base.append(running)
                up.append(0)
                down.append(-v)
            tot.append(0)
        cats.append(total_label)
        base.append(0)
        up.append(0)
        down.append(0)
        tot.append(running)
        s = self._new(title, notes=notes, hidden=hidden)
        top = self._content_top(subtitle, s)
        bottom = 6.0 if takeaway else 6.62
        cw = CONTENT_W if not commentary else CONTENT_W * 0.66
        ch = self._add_chart(s, MARGIN, top, cw, bottom - top, cats, {"base": base, "Benefit": up, "Cost": down, "Net": tot}, "stacked", number_format, False, False, None,
                             [self.t.bg, self.t.good, self.t.bad, self.t.accent], 55)
        plot = ch.plots[0]
        plot.series[0].format.fill.background()
        # value labels on visible series only
        for idx, ser in enumerate(plot.series):
            if idx == 0:
                continue
            vals = list((up, down, tot)[idx - 1])
            for pi, v in enumerate(vals):
                if v:
                    dl = ser.points[pi].data_label
                    dl.has_text_frame = True
                    dl.text_frame.text = f"{'−' if idx == 2 else ''}{v:,.1f}"
                    dl.position = XL_LABEL_POSITION.INSIDE_END if v > 0 else XL_LABEL_POSITION.CENTER
                    r = dl.text_frame.paragraphs[0].runs[0]
                    r.font.size = Pt(11)
                    r.font.bold = True
                    r.font.color.rgb = rgb("FFFFFF")
        ch.has_legend = False
        if commentary:
            x = MARGIN + cw + 0.3
            w = CONTENT_W - cw - 0.3
            self._rect(s, x, top, w, bottom - top, self.t.card, radius=0.1)
            paras: list[Any] = []
            if commentary_title:
                paras.append(Para(commentary_title.upper(), size=11, bold=True, color=self.t.accent, space_after=8))
            paras.extend(_flatten_bullets(commentary, "•"))
            self.text(s, x + 0.2, top + 0.15, w - 0.4, bottom - top - 0.3, paras, size=14, min_size=10)
        if takeaway:
            self._takeaway(s, takeaway)
        self._source(s, source)
        return s

    def tornado(self, title: str, drivers: Sequence[tuple[str, float, float]], base_value: float, number_format: str = '#,##0.0', metric_label: str = "NPV",
                subtitle: str | None = None, takeaway: str | None = None, notes: str | None = None, source: str | None = None, hidden: bool = False):
        """drivers: [(name, low_value, high_value)] absolute metric values at low/high assumption; bars show delta vs base."""
        rows = sorted(drivers, key=lambda d: abs(d[2] - d[1]), reverse=True)
        cats = [d[0] for d in rows]
        lows = [min(d[1], d[2]) - base_value for d in rows]
        highs = [max(d[1], d[2]) - base_value for d in rows]
        s = self._new(title, notes=notes, hidden=hidden)
        top = self._content_top(subtitle, s)
        bottom = 6.0 if takeaway else 6.62
        ch = self._add_chart(s, MARGIN, top, CONTENT_W, bottom - top, cats, {f"Downside vs base {metric_label}": lows, f"Upside vs base {metric_label}": highs}, "stacked_bar",
                             number_format, True, True, number_format, [self.t.bad, self.t.good], 45)
        ch.plots[0].data_labels.font.color.rgb = rgb("FFFFFF")
        ch.plots[0].data_labels.font.bold = True
        ch.plots[0].data_labels.position = XL_LABEL_POSITION.INSIDE_BASE
        ch.category_axis.tick_label_position = XL_TICK_LABEL_POSITION.LOW
        if takeaway:
            self._takeaway(s, takeaway)
        self._source(s, source)
        return s

    # ---- tables ---------------------------------------------------------------------
    def table(self, title: str, headers: Sequence[str], rows: Sequence[Sequence[Any]], col_weights: Sequence[float] | None = None, subtitle: str | None = None,
              takeaway: str | None = None, notes: str | None = None, source: str | None = None, align: Sequence[str] | None = None, font_pt: float | None = None,
              highlight_rows: Iterable[int] = (), first_col_bold: bool = True, hidden: bool = False, min_pt: float = 9):
        s = self._new(title, notes=notes, hidden=hidden)
        top = self._content_top(subtitle, s)
        bottom = 6.0 if takeaway else 6.65
        self._table(s, MARGIN, top, CONTENT_W, bottom - top, headers, rows, col_weights, align, font_pt, set(highlight_rows), first_col_bold, min_pt)
        if takeaway:
            self._takeaway(s, takeaway)
        self._source(s, source)
        return s

    def _table(self, s, x, y, w, h, headers, rows, col_weights, align, font_pt, highlight, first_col_bold, min_pt):
        ncols = len(headers)
        wts = list(col_weights or [1] * ncols)
        tot = sum(wts)
        widths = [w * v / tot for v in wts]
        align = list(align or ["left"] * ncols)
        pad = 0.08

        def row_h(cells: Sequence[Any], pt: float, bold_first: bool, header: bool = False) -> float:
            mx = 0.0
            for ci, c in enumerate(cells):
                paras = [Para(str(c), bold=header or (bold_first and ci == 0), space_after=0)]
                mx = max(mx, estimate_height(paras, widths[ci] - 2 * pad, pt))
            return mx + 0.14

        chosen = None
        sizes = [font_pt] if font_pt else [x_ / 2 for x_ in range(28, int(min_pt * 2) - 1, -1)]
        for pt in sizes:
            total = row_h(headers, pt, False, True) + sum(row_h(r, pt, first_col_bold) for r in rows)
            if total <= h:
                chosen = pt
                break
        if chosen is None:
            chosen = sizes[-1]
            self._warn(f"table too tall for {h:.1f}in even at {chosen}pt — split it")
        gf = s.shapes.add_table(len(rows) + 1, ncols, Inches(x), Inches(y), Inches(w), Inches(h))
        tbl = gf.table
        tblPr = tbl._tbl.tblPr
        for attr in ("firstRow", "bandRow"):
            tblPr.set(attr, "0")
        style = tblPr.find(qn("a:tableStyleId"))
        if style is not None:
            style.text = "{5940675A-B579-460E-94D1-54222C63F5DA}"  # "No Style, Table Grid" -> we override borders anyway
        for ci, cw_ in enumerate(widths):
            tbl.columns[ci].width = Inches(cw_)
        heights = [row_h(headers, chosen, False, True)] + [row_h(r, chosen, first_col_bold) for r in rows]
        scale = 1.0
        if sum(heights) < h:
            scale = min(1.5, h / sum(heights))
        for ri, hh in enumerate(heights):
            tbl.rows[ri].height = Inches(hh * scale)

        def fill_cell(cell, text, bold, color, fill_hex, al):
            cell.margin_left = cell.margin_right = Inches(pad)
            cell.margin_top = cell.margin_bottom = Inches(0.05)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            tf = cell.text_frame
            tf.word_wrap = True
            p = tf.paragraphs[0]
            p.alignment = {"left": PP_ALIGN.LEFT, "center": PP_ALIGN.CENTER, "right": PP_ALIGN.RIGHT}[al]
            for txt, b in parse_runs(str(text)):
                r = p.add_run()
                r.text = txt
                r.font.name = self.t.font
                r.font.size = Pt(chosen)
                r.font.bold = bool(bold or b)
                r.font.color.rgb = rgb(color)
            cell.fill.solid()
            cell.fill.fore_color.rgb = rgb(fill_hex)

        for ci, hd in enumerate(headers):
            c = tbl.cell(0, ci)
            fill_cell(c, hd, True, "FFFFFF", self.t.dark if self.t.dark else self.t.ink, align[ci])
            _cell_border(c, self.t.dark, 0.5, sides=())
        for ri, r in enumerate(rows, start=1):
            hl = (ri - 1) in highlight
            for ci, v in enumerate(r):
                c = tbl.cell(ri, ci)
                fill = tint(self.t.accent, 0.82) if hl else (self.t.card if ri % 2 == 0 else "FFFFFF")
                fill_cell(c, v, hl or (first_col_bold and ci == 0), self.t.ink, fill, align[ci])
                _cell_border(c, self.t.line, 0.5, sides=("b",))
        return tbl

    # ---- diagrams -------------------------------------------------------------------
    def architecture(self, title: str, layers: Sequence[dict], subtitle: str | None = None, side: dict | None = None, takeaway: str | None = None,
                     notes: str | None = None, source: str | None = None, arrows: bool = True, hidden: bool = False):
        """Layer-cake diagram. layers: [{'name': 'Edge', 'color': hex?, 'items': ['IoT Operations', {'title': 'Arc', 'sub': 'K8s'}]}]
        side: optional vertical cross-cutting band {'name': 'Security & governance', 'items': [...]}"""
        s = self._new(title, notes=notes, hidden=hidden)
        top = self._content_top(subtitle, s)
        bottom = 6.0 if takeaway else 6.62
        n = len(layers)
        gap = 0.16 if arrows else 0.12
        lh = (bottom - top - gap * (n - 1)) / n
        side_w = 2.5 if side else 0
        main_w = CONTENT_W - (side_w + 0.25 if side else 0)
        label_w = 1.75
        pal = [self.t.accent, self.t.palette[1], self.t.palette[2], self.t.palette[3], self.t.palette[4], self.t.palette[5]]
        for li, layer in enumerate(layers):
            y = top + li * (lh + gap)
            col = layer.get("color") or pal[li % len(pal)]
            self._rect(s, MARGIN, y, main_w, lh, tint(col, 0.88), radius=0.1)
            lab = self._rect(s, MARGIN, y, label_w, lh, col, radius=0.1)
            self.text(s, MARGIN, y, label_w, lh, [Para(layer["name"], bold=True, color="FFFFFF", align="center", space_after=0)], size=13, min_size=9, color="FFFFFF", anchor="middle", align="center", shape=lab)
            items = layer["items"]
            k = len(items)
            ig = 0.14
            iw = (main_w - label_w - ig * (k + 1)) / k
            for ii, it in enumerate(items):
                ix = MARGIN + label_w + ig + ii * (iw + ig)
                box = self._rect(s, ix, y + 0.12, iw, lh - 0.24, "FFFFFF", col, radius=0.08, line_pt=1.0)
                if isinstance(it, dict):
                    paras = [Para(it["title"], bold=True, align="center", space_after=2)]
                    if it.get("sub"):
                        paras.append(Para(it["sub"], size=10.5, color=self.t.muted, align="center", space_after=0))
                else:
                    paras = [Para(str(it), bold=True, align="center", space_after=0)]
                self.text(s, ix, y + 0.12, iw, lh - 0.24, paras, size=12.5, min_size=8.5, anchor="middle", align="center", shape=box, inset=0.05, label=f"arch item {layer['name']}")
            if arrows and li < n - 1:
                cx = MARGIN + (main_w + label_w) / 2
                a = s.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(cx), Inches(y + lh + 0.01), Inches(cx), Inches(y + lh + gap - 0.01))
                _line_arrow(a, self.t.muted, 1.5, head=True)
        if side:
            x = MARGIN + main_w + 0.25
            self._rect(s, x, top, side_w, bottom - top, self.t.dark, radius=0.1)
            self.text(s, x, top + 0.1, side_w, 0.5, [Para(side["name"], bold=True, color="FFFFFF", align="center", space_after=0)], size=13, min_size=10, color="FFFFFF", align="center", anchor="middle")
            sitems = side["items"]
            ih = (bottom - top - 0.8) / max(1, len(sitems))
            for si, it in enumerate(sitems):
                iy = top + 0.7 + si * ih
                box = self._rect(s, x + 0.15, iy, side_w - 0.3, ih - 0.1, shade(self.t.dark, -0.0) if False else tint(self.t.dark, 0.18), radius=0.07)
                self.text(s, x + 0.15, iy, side_w - 0.3, ih - 0.1, [Para(str(it), color="FFFFFF", align="center", space_after=0)], size=11.5, min_size=8, color="FFFFFF", anchor="middle", align="center", shape=box, inset=0.05)
        if takeaway:
            self._takeaway(s, takeaway)
        self._source(s, source)
        return s

    def hub_spoke(self, title: str, hub: dict, spokes: Sequence[dict], subtitle: str | None = None, takeaway: str | None = None, notes: str | None = None,
                  source: str | None = None, hidden: bool = False, ring_note: str | None = None):
        """Orchestrator-in-the-middle diagram. hub: {'title','sub'}; spokes: [{'title','sub'}] (up to ~10), arranged on an ellipse."""
        s = self._new(title, notes=notes, hidden=hidden)
        top = self._content_top(subtitle, s)
        bottom = 6.0 if takeaway else 6.62
        cx, cy = SLIDE_W / 2, (top + bottom) / 2
        rx, ry = 4.55, (bottom - top) / 2 - 0.62
        n = len(spokes)
        bw, bh = 2.35, 0.95
        centres = []
        for i in range(n):
            ang = -math.pi / 2 + 2 * math.pi * i / n
            centres.append((cx + rx * math.cos(ang), cy + ry * math.sin(ang)))
        # ring + spokes first (behind)
        ring = s.shapes.add_shape(MSO_SHAPE.OVAL, Inches(cx - rx), Inches(cy - ry), Inches(2 * rx), Inches(2 * ry))
        self._flat(ring, None, self.t.line, 1.0)
        for (px, py) in centres:
            c = s.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(cx), Inches(cy), Inches(px), Inches(py))
            c.line.color.rgb = rgb(self.t.faint)
            c.line.width = Pt(1.25)
        hub_w, hub_h = 2.9, 1.25
        hb = self._rect(s, cx - hub_w / 2, cy - hub_h / 2, hub_w, hub_h, self.t.dark, self.t.accent, radius=0.18, line_pt=2.5)
        paras = [Para(hub["title"], bold=True, color="FFFFFF", align="center", space_after=2)]
        if hub.get("sub"):
            paras.append(Para(hub["sub"], size=11, color="C9D6EA", align="center", space_after=0))
        self.text(s, cx - hub_w / 2, cy - hub_h / 2, hub_w, hub_h, paras, size=15, min_size=10, color="FFFFFF", anchor="middle", align="center", shape=hb, inset=0.08)
        pal = list(self.t.palette)
        for i, ((px, py), sp) in enumerate(zip(centres, spokes)):
            col = sp.get("color") or pal[i % len(pal)]
            bx = self._rect(s, px - bw / 2, py - bh / 2, bw, bh, "FFFFFF", col, radius=0.1, line_pt=2.0)
            paras = [Para(sp["title"], bold=True, align="center", space_after=1)]
            if sp.get("sub"):
                paras.append(Para(sp["sub"], size=10, color=self.t.muted, align="center", space_after=0))
            self.text(s, px - bw / 2, py - bh / 2, bw, bh, paras, size=12.5, min_size=8.5, anchor="middle", align="center", shape=bx, inset=0.06, label=f"spoke {sp['title']}")
        if ring_note:
            self.text(s, cx - 1.9, cy + hub_h / 2 + 0.08, 3.8, 0.5, [Para(ring_note, size=10.5, color=self.t.muted, align="center", space_after=0)], size=10.5, min_size=8, align="center")
        if takeaway:
            self._takeaway(s, takeaway)
        self._source(s, source)
        return s

    def diagram(self, title: str, nodes: Sequence[dict], edges: Sequence[dict] = (), subtitle: str | None = None, takeaway: str | None = None,
                notes: str | None = None, source: str | None = None, hidden: bool = False):
        """Free-form diagram on the content area. Coordinates are in inches relative to the content area's top-left
        (width ≈ 12.1, height ≈ 4.4–5.0). nodes: {'id','x','y','w','h','title','sub'?,'kind'?: box|dark|accent|ghost,'color'?}
        edges: {'from','to','label'?,'dashed'?,'bidir'?}  (straight arrows between node edges)"""
        s = self._new(title, notes=notes, hidden=hidden)
        top = self._content_top(subtitle, s)
        pos: dict[str, tuple[float, float, float, float]] = {}
        for nd in nodes:
            x, y, w, h = MARGIN + nd["x"], top + nd["y"], nd["w"], nd["h"]
            pos[nd["id"]] = (x, y, w, h)
        for ed in edges:
            fx, fy, fw, fh = pos[ed["from"]]
            tx, ty, tw, th = pos[ed["to"]]
            x1, y1 = self._edge_point((fx, fy, fw, fh), (tx + tw / 2, ty + th / 2))
            x2, y2 = self._edge_point((tx, ty, tw, th), (fx + fw / 2, fy + fh / 2))
            c = s.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x1), Inches(y1), Inches(x2), Inches(y2))
            _line_arrow(c, ed.get("color", self.t.muted), 1.75, head=True, dash=ed.get("dashed", False))
            if ed.get("bidir"):
                ln = c.line._get_or_add_ln()
                he = etree.SubElement(ln, qn("a:headEnd"))
                he.set("type", "triangle")
            if ed.get("label"):
                lx, ly = (x1 + x2) / 2, (y1 + y2) / 2
                elen = math.hypot(x2 - x1, y2 - y1)
                need = _METER.width_in(ed["label"], 9.5) + 0.18
                horizontal = abs(x2 - x1) >= abs(y2 - y1)
                if (not horizontal) or need <= elen - 0.08:
                    lw = need
                    bg = self._rect(s, lx - lw / 2, ly - 0.12, lw, 0.24, "FFFFFF")
                    self.text(s, lx - lw / 2, ly - 0.12, lw, 0.24, [Para(ed["label"], size=9.5, color=self.t.muted, align="center", space_after=0)], size=9.5, min_size=8, align="center", anchor="middle", shape=bg, inset=0.01, fit=False)
                else:  # gap too small for the label on one line: wrap it above the arrow
                    lw = max(0.7, elen - 0.08)
                    self.text(s, lx - lw / 2, ly - 0.5, lw, 0.44, [Para(ed["label"], size=9.5, color=self.t.muted, align="center", space_after=0)], size=9.5, min_size=7.5, align="center", anchor="bottom", inset=0.01, label="edge label")
        for nd in nodes:
            x, y, w, h = pos[nd["id"]]
            kind = nd.get("kind", "box")
            col = nd.get("color") or self.t.accent
            if kind == "dark":
                fill, line, txt = self.t.dark, self.t.accent, "FFFFFF"
            elif kind == "accent":
                fill, line, txt = col, col, "FFFFFF"
            elif kind == "ghost":
                fill, line, txt = tint(col, 0.9), tint(col, 0.5), self.t.ink
            else:
                fill, line, txt = "FFFFFF", col, self.t.ink
            b = self._rect(s, x, y, w, h, fill, line, radius=0.08, line_pt=1.5)
            paras = [Para(nd["title"], bold=True, color=txt, align="center", space_after=1)]
            if nd.get("sub"):
                paras.append(Para(nd["sub"], size=10, color=("C9D6EA" if kind in ("dark", "accent") else self.t.muted), align="center", space_after=0))
            self.text(s, x, y, w, h, paras, size=12.5, min_size=8, color=txt, anchor="middle", align="center", shape=b, inset=0.05, label=f"node {nd['id']}")
        if takeaway:
            self._takeaway(s, takeaway)
        self._source(s, source)
        return s

    @staticmethod
    def _edge_point(box, toward):
        x, y, w, h = box
        cx, cy = x + w / 2, y + h / 2
        dx, dy = toward[0] - cx, toward[1] - cy
        if dx == 0 and dy == 0:
            return cx, cy
        sx = (w / 2) / abs(dx) if dx else math.inf
        sy = (h / 2) / abs(dy) if dy else math.inf
        k = min(sx, sy)
        return cx + dx * k, cy + dy * k

    def process(self, title: str, steps: Sequence[dict], subtitle: str | None = None, takeaway: str | None = None, notes: str | None = None,
                source: str | None = None, hidden: bool = False):
        """Chevron flow. steps: [{'title','body'(str|list)}]"""
        s = self._new(title, notes=notes, hidden=hidden)
        top = self._content_top(subtitle, s)
        bottom = 6.0 if takeaway else 6.62
        n = len(steps)
        gap = 0.08
        w = (CONTENT_W - gap * (n - 1)) / n
        pal = list(self.t.palette)
        for i, st in enumerate(steps):
            x = MARGIN + i * (w + gap)
            shape = MSO_SHAPE.PENTAGON if i == 0 else MSO_SHAPE.CHEVRON
            ch = s.shapes.add_shape(shape, Inches(x), Inches(top), Inches(w), Inches(0.95))
            ch.adjustments[0] = 0.3
            self._flat(ch, self.t.accent if i % 2 == 0 else shade(self.t.accent, 0.22))
            # text goes in a separate box: chevron/pentagon shapes have a much narrower internal text rectangle
            tx0 = 0.4 if i else 0.14
            self.text(s, x + tx0, top, w - tx0 - 0.3, 0.95, [Para(f"{i + 1}  {st['title']}", bold=True, color="FFFFFF", space_after=0)], size=14, min_size=9.5, color="FFFFFF", anchor="middle", inset=0.02, label=f"process {i}")
            body = st.get("body", "")
            paras = _flatten_bullets(body if isinstance(body, (list, tuple)) else [body], "•" if isinstance(body, (list, tuple)) else None)
            self.text(s, x + 0.06, top + 1.1, w - 0.16, bottom - top - 1.15, paras, size=13, min_size=9, label=f"process body {i}")
        if takeaway:
            self._takeaway(s, takeaway)
        self._source(s, source)
        return s

    def timeline(self, title: str, phases: Sequence[dict], subtitle: str | None = None, takeaway: str | None = None, notes: str | None = None,
                 source: str | None = None, hidden: bool = False):
        """phases: [{'name','when','items':[...]}] — horizontal roadmap."""
        s = self._new(title, notes=notes, hidden=hidden)
        top = self._content_top(subtitle, s)
        bottom = 6.0 if takeaway else 6.62
        n = len(phases)
        colw = CONTENT_W / n
        ly = top + 1.15
        line = s.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(MARGIN), Inches(ly), Inches(SLIDE_W - MARGIN), Inches(ly))
        line.line.color.rgb = rgb(self.t.line)
        line.line.width = Pt(3)
        for i, ph in enumerate(phases):
            x = MARGIN + i * colw
            self.text(s, x + 0.05, top, colw - 0.2, 0.5, [Para(ph["name"], bold=True, space_after=0)], size=16, min_size=11, anchor="bottom", label="phase name")
            self.text(s, x + 0.05, top + 0.5, colw - 0.2, 0.35, [Para(ph.get("when", ""), color=self.t.accent, bold=True, space_after=0)], size=12.5, min_size=9, label="phase when")
            dot = s.shapes.add_shape(MSO_SHAPE.OVAL, Inches(x + 0.05), Inches(ly - 0.13), Inches(0.26), Inches(0.26))
            self._flat(dot, self.t.accent if i else self.t.accent, "FFFFFF", 2.0)
            card_h = min(bottom - ly - 0.35, 2.9)
            self._rect(s, x + 0.05, ly + 0.3, colw - 0.25, card_h, self.t.card, radius=0.08)
            self.text(s, x + 0.12, ly + 0.36, colw - 0.4, card_h - 0.12, _flatten_bullets(ph.get("items", []), "•"), size=13, min_size=9, bullet="•", label=f"phase items {i}")
        if takeaway:
            self._takeaway(s, takeaway)
        self._source(s, source)
        return s

    def comparison(self, title: str, left_title: str, left_items: Sequence[Any], right_title: str, right_items: Sequence[Any], subtitle: str | None = None,
                   takeaway: str | None = None, notes: str | None = None, source: str | None = None, hidden: bool = False):
        """Before/after panels with an arrow between."""
        s = self._new(title, notes=notes, hidden=hidden)
        top = self._content_top(subtitle, s)
        bottom = 6.0 if takeaway else 6.62
        pw = (CONTENT_W - 0.9) / 2
        bottom = min(bottom, top + 4.2)
        for i, (ht, items) in enumerate(((left_title, left_items), (right_title, right_items))):
            x = MARGIN + i * (pw + 0.9)
            col = self.t.muted if i == 0 else self.t.accent
            self._rect(s, x, top, pw, bottom - top, self.t.card if i == 0 else tint(self.t.accent, 0.9), radius=0.1)
            self._rect(s, x, top, pw, 0.55, col, radius=0.1)
            self.text(s, x + 0.15, top, pw - 0.3, 0.55, [Para(ht, bold=True, color="FFFFFF", space_after=0)], size=16, min_size=11, color="FFFFFF", anchor="middle")
            self.text(s, x + 0.2, top + 0.7, pw - 0.4, bottom - top - 0.8, _flatten_bullets(items, "•"), size=15, min_size=10, bullet="•")
        ar = s.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, Inches(MARGIN + pw + 0.15), Inches((top + bottom) / 2 - 0.3), Inches(0.6), Inches(0.6))
        self._flat(ar, self.t.accent)
        if takeaway:
            self._takeaway(s, takeaway)
        self._source(s, source)
        return s

    def capability_map(self, title: str, groups: Sequence[dict], subtitle: str | None = None, takeaway: str | None = None, notes: str | None = None,
                       source: str | None = None, hidden: bool = False, columns: int | None = None):
        """groups: [{'name': 'Epic A — ...', 'items': ['DF-01 Factory simulator', ...]}]"""
        s = self._new(title, notes=notes, hidden=hidden)
        top = self._content_top(subtitle, s)
        bottom = 6.0 if takeaway else 6.62
        n = len(groups)
        cols = columns or (n if n <= 5 else math.ceil(n / 2))
        rows = math.ceil(n / cols)
        gap = 0.18
        cw = (CONTENT_W - gap * (cols - 1)) / cols
        chh = (bottom - top - gap * (rows - 1)) / rows
        pal = list(self.t.palette)
        for i, g in enumerate(groups):
            r, k = divmod(i, cols)
            x = MARGIN + k * (cw + gap)
            y = top + r * (chh + gap)
            col = g.get("color") or pal[i % len(pal)]
            self._rect(s, x, y, cw, chh, self.t.card, radius=0.08)
            hb = self._rect(s, x, y, cw, 0.62, col, radius=0.08)
            self.text(s, x + 0.08, y, cw - 0.16, 0.62, [Para(g["name"], bold=True, color="FFFFFF", space_after=0)], size=12.5, min_size=9, color="FFFFFF", anchor="middle", shape=hb, inset=0.04, label=f"group {g['name'][:20]}")
            self.text(s, x + 0.1, y + 0.7, cw - 0.2, chh - 0.78, _flatten_bullets(g["items"], "•"), size=14, min_size=7.5, bullet="•", label=f"group items {i}")
        if takeaway:
            self._takeaway(s, takeaway)
        self._source(s, source)
        return s

    def big_statement(self, title: str, statement: str, sub: str | None = None, notes: str | None = None, hidden: bool = False, bullets: Sequence[Any] | None = None):
        """A single, big takeaway (e.g. 'the ask') with optional bullets below."""
        s = self._new(title, notes=notes, hidden=hidden)
        self._rect(s, MARGIN, 1.75, 0.1, 1.9, self.t.accent)
        self.text(s, MARGIN + 0.35, 1.75, CONTENT_W - 0.4, 1.9, [Para(statement, bold=True, space_after=0)], size=30, min_size=18, anchor="middle", label="statement")
        if sub:
            self.text(s, MARGIN + 0.35, 3.75, CONTENT_W - 0.4, 0.6, [Para(sub, color=self.t.muted, space_after=0)], size=16, min_size=11)
        if bullets:
            self.text(s, MARGIN + 0.35, 4.4, CONTENT_W - 0.4, 2.3, _flatten_bullets(bullets, "•"), size=16, min_size=11, bullet="•")
        return s

    # ---- imagery ----------------------------------------------------------------------
    def screenshot(self, title: str, image: str | Path, caption: str | None = None, callouts: Sequence[Any] | None = None, subtitle: str | None = None,
                   takeaway: str | None = None, notes: str | None = None, source: str | None = None, hidden: bool = False):
        s = self._new(title, notes=notes, hidden=hidden)
        top = self._content_top(subtitle, s)
        bottom = 6.0 if takeaway else 6.62
        img_w_max = CONTENT_W * (0.68 if callouts else 1.0)
        cap_h = 0.32 if caption else 0
        with Image.open(image) as im:
            iw, ih = im.size
        avail_h = bottom - top - cap_h - 0.1
        scale = min(img_w_max / iw, avail_h / ih)
        pw, ph = iw * scale, ih * scale
        x = MARGIN if callouts else MARGIN + (CONTENT_W - pw) / 2
        self._rect(s, x - 0.06, top - 0.06, pw + 0.12, ph + 0.12, self.t.line, radius=0.08)
        s.shapes.add_picture(str(image), Inches(x), Inches(top), Inches(pw), Inches(ph))
        if caption:
            self.text(s, x, top + ph + 0.1, pw, cap_h, [Para(caption, size=11, color=self.t.muted, italic=True, space_after=0)], size=11, min_size=8, label="caption")
        if callouts:
            cx = MARGIN + pw + 0.5
            cwid = CONTENT_W - pw - 0.5
            paras: list[Para] = []
            for i, c in enumerate(callouts, 1):
                paras.append(Para(f"**{i}**  {c}", space_after=10))
            self._rect(s, cx, top, cwid, bottom - top, self.t.card, radius=0.1)
            self.text(s, cx + 0.2, top + 0.15, cwid - 0.4, bottom - top - 0.3, paras, size=14, min_size=9.5, label="callouts")
        if takeaway:
            self._takeaway(s, takeaway)
        self._source(s, source)
        return s

    def product_tour(self, directory: str | Path, captions: dict[str, dict] | None = None, title_prefix: str = "Product tour", notes_default: str = "", hidden: bool = False) -> int:
        """One slide per PNG in `directory` (sorted by filename). captions: {'01-control-tower.png': {'title','caption','callouts':[...],'notes'}}.
        Returns number of slides added (0 if directory missing/empty)."""
        d = Path(directory)
        if not d.exists():
            return 0
        files = sorted(p for p in d.iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg"))
        for f in files:
            meta = (captions or {}).get(f.name, {})
            pretty = re.sub(r"^\d+[-_ ]*", "", f.stem).replace("-", " ").replace("_", " ").strip().title()
            self.screenshot(meta.get("title", f"{title_prefix}: {pretty}"), f, caption=meta.get("caption", pretty), callouts=meta.get("callouts"),
                            takeaway=meta.get("takeaway"), notes=meta.get("notes", notes_default), hidden=hidden)
        return len(files)

    def sources(self, title: str, items: Sequence[str], per_slide: int = 13, notes: str | None = None, hidden: bool = False):
        """Paginated reference list (small type)."""
        chunks = [items[i : i + per_slide] for i in range(0, len(items), per_slide)] or [[]]
        for ci, chunk in enumerate(chunks):
            s = self._new(title + (f" ({ci + 1}/{len(chunks)})" if len(chunks) > 1 else ""), notes=notes, hidden=hidden)
            paras = [Para(f"[{ci * per_slide + i + 1}] {t}", size=12, space_after=6) for i, t in enumerate(chunk)]
            self.text(s, MARGIN, 1.6, CONTENT_W, 5.1, paras, size=12, min_size=8, label="sources")

    # ---- decoration -------------------------------------------------------------------
    def _swarm_png(self) -> Path:
        out = self._cache / f"swarm-{self.t.name.replace(' ', '_')}-{self.t.accent}.png"
        if out.exists():
            return out
        W, H = 1500, 1500
        S = 2
        img = Image.new("RGBA", (W * S, H * S), (0, 0, 0, 0))
        d = ImageDraw.Draw(img, "RGBA")
        rnd = random.Random(7)
        pts: list[tuple[float, float, float]] = []
        for _ in range(70):
            px = rnd.random() ** 0.8
            py = rnd.random()
            pts.append((px * W * S, py * H * S, rnd.choice([6, 8, 10, 14, 20])))
        cols = [self.t.accent, self.t.accent2, self.t.accent3, "FFFFFF"]
        def hx(c: str, a: int) -> tuple[int, int, int, int]:
            c = c.lstrip("#")
            return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16), a
        for i, (x, y, r) in enumerate(pts):
            dists = sorted(((math.hypot(x - x2, y - y2), j) for j, (x2, y2, _) in enumerate(pts) if j != i))[:3]
            for dist, j in dists:
                if dist < 420 * S:
                    x2, y2, _ = pts[j]
                    d.line([(x, y), (x2, y2)], fill=hx(self.t.accent2, 70), width=2 * S)
        for i, (x, y, r) in enumerate(pts):
            c = cols[i % len(cols)]
            rr = r * S
            if r >= 14:
                d.ellipse([x - rr * 2.2, y - rr * 2.2, x + rr * 2.2, y + rr * 2.2], fill=hx(c, 26))
            d.ellipse([x - rr, y - rr, x + rr, y + rr], fill=hx(c, 210 if c != "FFFFFF" else 150))
        img = img.resize((W, H), Image.LANCZOS)
        img.save(out)
        return out

    # ---- output -----------------------------------------------------------------------
    def save(self, path: str | Path) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        self.prs.save(str(p))
        return p
