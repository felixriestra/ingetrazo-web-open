# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Painting of sheet items in paper millimetres.

Everything that draws a sheet (the desktop composer's canvas and printing, and the
web service's page preview and PDF) lives here, with no widgets: it needs only a
``QPainter``. ``views/composer.py`` re-exports these names, so existing imports keep
working.
"""
from __future__ import annotations

import datetime
import math
from typing import Optional

from PySide6.QtCore import QPoint, QPointF, QRectF, QSize, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QImage, QPainter, QPen,
                           QTransform, QVector3D)

from core.composition import (COMMON_SCALES, NEW_FRAME_STYLE, PAPER_SIZES_MM, RENDER_DPI,
                              BarraEscala, Cajetin, Composicion, CotaAngularItem, CotaItem,
                              CotaRadialItem, EtiquetaItem, expand_fields, FlechaNorte, FormaItem,
                              LlamadaItem, NivelItem, ImagenItem, Leyenda, MarcoVista,
                              PerfilTerreno, TextoItem, apply_frame_camera, cota_line_deg,
                              format_scale, parse_scale, readable_deg, snap_mm, pen_px)
from core.i18n import tr
from core.saved_views import apply_shadow_state, georef_objects

def _nice_ticks(lo: float, hi: float, target: int = 5) -> list[float]:
    """A short list of round tick values spanning ``[lo, hi]``."""
    if hi <= lo:
        return [lo]
    raw = (hi - lo) / target
    mag = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 2.5, 5, 10):
        step = m * mag
        if raw <= step:
            break
    start = math.ceil(lo / step) * step
    ticks, v = [], start
    while v <= hi + 1e-6:
        ticks.append(round(v, 6))
        v += step
    return ticks or [lo, hi]


PT_TO_MM = 25.4 / 72.0
_HANDLE_MM = 3.0          # corner resize handle, in paper mm
_SNAP_MM = 2.0

#: Standard views offered as frame sources (label key → camera.set_view key).
_STD_VIEWS = (
    ("Top (plan)", "top"),
    ("Front", "front"),
    ("Back", "back"),
    ("Left", "left"),
    ("Right", "right"),
    ("Isometric", "iso"),
)


# ── mm-space painters (shared by canvas and PDF) ────────────────────────────

def _draw_text_mm(painter: QPainter, rect: QRectF, text: str, size_mm: float,
                  bold: bool = False, align=Qt.AlignLeft | Qt.AlignTop,
                  color: QColor = QColor(30, 36, 44),
                  italic: bool = False, family: str = "Sans Serif",
                  underline: bool = False) -> None:
    """Draw *text* inside *rect* (mm units) at ``size_mm`` tall. Fonts don't
    take fractional-mm sizes, so set a large pixel size and scale the
    painter down — crisp at any output DPI."""
    if not text:
        return
    painter.save()
    font = QFont(family or "Sans Serif")
    font.setPixelSize(100)
    font.setBold(bold)
    font.setItalic(italic)
    font.setUnderline(underline)
    painter.setFont(font)
    painter.setPen(color)
    s = size_mm / 100.0 * 0.75   # pixelSize≈cap height/0.75 — visual match
    painter.scale(s, s)
    painter.drawText(QRectF(rect.x() / s, rect.y() / s,
                            rect.width() / s, rect.height() / s),
                     int(align | Qt.TextWordWrap), text)
    painter.restore()


def text_baseline_rect_mm(size_mm: float, baseline_y: float,
                          width: float = 80.0, bold: bool = False,
                          family: str = "Sans Serif") -> QRectF:
    """A rect for :func:`_draw_text_mm` (top-aligned) whose BASELINE lands
    exactly on ``baseline_y`` (mm), centred on x = 0. The gap between a
    dimension line and its number is measured to the baseline — that is
    what «distancia texto–línea» means on Rafael's sheet — so the offset a
    drafter sets is the gap he sees, not the gap plus a font's ascent."""
    from PySide6.QtGui import QFontMetricsF
    font = QFont(family or "Sans Serif")
    font.setPixelSize(100)
    font.setBold(bold)
    fm = QFontMetricsF(font)
    s = size_mm / 100.0 * 0.75              # the scale _draw_text_mm applies
    asc, desc = fm.ascent() * s, fm.descent() * s
    return QRectF(-width / 2, baseline_y - asc, width, asc + desc)


def _fit_text_size_mm(text: str, rect: QRectF, base_size_mm: float,
                      bold: bool = False,
                      family: str = "Sans Serif") -> float:
    """Largest size ≤ base at which *text*, word-wrapped, fits *rect*
    (mm units) — the title-block habit: a long project name drops to two
    or three lines and only then starts shrinking."""
    from PySide6.QtGui import QFontMetricsF
    font = QFont(family or "Sans Serif")
    font.setPixelSize(100)
    font.setBold(bold)
    fm = QFontMetricsF(font)
    size = base_size_mm
    while size > 1.0:
        s = size / 100.0 * 0.75
        box = QRectF(0, 0, rect.width() / s, rect.height() / s)
        need = fm.boundingRect(box, int(Qt.AlignLeft | Qt.TextWordWrap),
                               text)
        if need.height() <= box.height() and need.width() <= box.width():
            return size
        size *= 0.88
    return 1.0


def _text_height_mm(text: str, width_mm: float, size_mm: float,
                    bold: bool = False, family: str = "Sans Serif") -> float:
    """Height that *text*, word-wrapped at ``size_mm``, needs in a column
    ``width_mm`` wide (mm). The twin of :func:`_fit_text_size_mm`: that one
    answers «how big may it be here», this one «how much room does it want»."""
    from PySide6.QtGui import QFontMetricsF
    if not text:
        return 0.0
    font = QFont(family or "Sans Serif")
    font.setPixelSize(100)
    font.setBold(bold)
    fm = QFontMetricsF(font)
    s = size_mm / 100.0 * 0.75
    box = QRectF(0, 0, max(width_mm, 0.5) / s, 1e6)
    need = fm.boundingRect(box, int(Qt.AlignLeft | Qt.TextWordWrap), text)
    return float(need.height()) * s


#: How far a title-block row may stray from an equal share to fit what it
#: holds — three times as tall for a long project name, and never under 60 %
#: for the rows that only carry a date. Past that the text shrinks, as it
#: always did.
CAJETIN_ROW_GROW = 3.0
CAJETIN_ROW_SHRINK = 0.6


def cajetin_row_heights(rows, cols: int, per: int, body_h: float,
                        col_w: float, label_w: float,
                        layout: str = "grid") -> list:
    """Height of every row of the title block's grid, in mm.

    Equal shares while everything fits — which is every ordinary title
    block. A row whose value needs more room takes it instead of shrinking
    its type: a project name of six lines used to drop to a size that made
    every other row look oversized beside it (Marco, 2026-09-07: «no se ve
    bien porque la fuente disminuye y lo demás se hace más grande»). The
    room is paid for by the rows that never used theirs, so the block keeps
    the height the user gave it, and the values come out at about one size.
    Rows are measured index by index ACROSS the columns, so the horizontal
    lines of a multi-column block still line up."""
    base = body_h / max(per, 1)
    if per <= 1 or base <= 0:
        return [body_h] * max(per, 1)
    minimal = layout == "minimal"
    inner = max((col_w - 3.0) if minimal else (col_w - label_w - 3.0), 1.0)
    frac = 0.62 if minimal else 1.0          # of the row the value may use
    nominal = base * (0.42 if minimal else 0.52)     # the size it wants
    lab_w = max(label_w - 2.0, 1.0)
    lab_nominal = base * (0.24 if minimal else 0.38)
    weights = []
    for j in range(per):
        want = 0.0
        for k in range(cols):
            idx = k * per + j
            if idx >= len(rows):
                continue
            label, value = rows[idx][0], rows[idx][1]
            # An empty field still asks for one line: a title block waiting
            # to be filled in must read as a regular grid, and the row has
            # to hold what the user types next.
            want = max(want,
                       _text_height_mm(str(value or "") or "M", inner,
                                       nominal) / frac + 1.0)
            if not minimal:
                want = max(want, _text_height_mm(
                    str(label or ""), lab_w, lab_nominal, bold=True) + 1.0)
        # A row asks for what it holds — no more, so the rows carrying a
        # date or a sheet number hand their slack to the one that needs it,
        # and no less than the floor, so nothing collapses to a hairline.
        weights.append(min(max(want / base, CAJETIN_ROW_SHRINK),
                           CAJETIN_ROW_GROW))
    total = sum(weights)
    return [body_h * w / total for w in weights]


def frame_view_name(frame: MarcoVista) -> str:
    """The view's own name: the scene's, the standard view's, or «View»."""
    key = frame.view_key
    if key.startswith("scene:"):
        return key[6:]
    if key.startswith("std:"):
        return {k: tr(lbl) for lbl, k in _STD_VIEWS}.get(key[4:], key[4:])
    return tr("View")


def apply_frame_shadows(frame, scene) -> None:
    """The frame's own sun, over whatever the scene left: a field 3D wants
    shadows while the plan beside it does not, and neither should have to
    move the model's sun to get them (Marco, 2026-09-17). Runs inside
    ``_with_frame_camera``, which puts the model's settings back after."""
    want = getattr(frame, "shadows", None)
    hour = getattr(frame, "sun_hour", None)
    if (want is None and hour is None) or getattr(scene, "shadows",
                                                  None) is None:
        return
    state = scene.shadows.to_dict()
    if want is not None:
        state["enabled"] = bool(want)
    if hour is not None:
        h = max(0.0, min(23.999, float(hour)))
        state["hour"] = int(h)
        state["minute"] = int(round((h - int(h)) * 60.0))
    apply_shadow_state(scene, state)


def frame_title_text(frame: MarcoVista) -> str:
    """The automatic title: view name — scale («Planta — 1:100»). A
    perspective frame has no scale to give, so it says what it is."""
    if getattr(frame, "perspective", False):
        return f"{frame_view_name(frame)} — {tr('perspective')}"
    return f"{frame_view_name(frame)} — {format_scale(frame.scale_n)}"


def view_title_texts(frame: MarcoVista) -> dict:
    """The strings of the frame's title, fields expanded: ``title``
    (the typed text or the view's name), ``subtitle``, ``scale``
    («ESC. 1:N» or ""), ``number`` and ``sheet`` (the bubble). ``{escala}``
    always reads THIS frame's scale, bound uid or not."""
    from core.composition import expand_fields
    uid = getattr(frame, "uid", "") or ""
    # A perspective frame is not drawn to any scale: «ESC. 1:N» under it
    # would be a lie on a printed sheet, so it reads «SIN ESCALA» — what
    # the usual convention under a perspective viewport (Marco, 2026-09-17).
    persp = bool(getattr(frame, "perspective", False))
    n = f"{frame.scale_n:g}"
    scale_field = tr("no scale") if persp else format_scale(frame.scale_n)

    def ex(text) -> str:
        text = (text or "").replace("{escala}", scale_field)
        return expand_fields(text, uid) if text else ""
    return {
        "title": ex(getattr(frame, "title_text", "")) or frame_view_name(frame),
        "subtitle": ex(getattr(frame, "title_subtitle", "")),
        "scale": ("" if not getattr(frame, "title_scale", True)
                  else tr("NO SCALE") if persp
                  else "ESC. " + format_scale(frame.scale_n)),
        "number": ex(getattr(frame, "title_number", "")),
        "sheet": ex(getattr(frame, "title_sheet", "")),
    }


def _text_width_mm(text: str, size_mm: float, bold: bool = False) -> float:
    """Advance width of *text* as :func:`_draw_text_mm` would draw it."""
    if not text:
        return 0.0
    from PySide6.QtGui import QFontMetricsF
    font = QFont("Sans Serif")
    font.setPixelSize(100)
    font.setBold(bold)
    return QFontMetricsF(font).horizontalAdvance(text) * (size_mm / 100.0 * 0.75)


def view_title_extent(frame: MarcoVista) -> tuple:
    """Paper the title adds around the frame, as (left, top, bottom) mm —
    the canvas item's bounding box and the print both grow by it."""
    if not getattr(frame, "show_title", False):
        return (0.0, 0.0, 0.0)
    size = max(1.5, float(getattr(frame, "title_mm", 4.0) or 4.0))
    style = getattr(frame, "title_style", "layout") or "layout"
    t = view_title_texts(frame)
    if style == "bar":
        w = 2.0 + size * 1.5
        if t["subtitle"]:
            w += size * 1.1
        if t["scale"]:
            w += size * 1.1
        return (w + 1.0, 0.0, 0.0)
    if style == "simple":
        h = 1.2 + size * 1.6 + (size * 1.0 if t["subtitle"] else 0.0)
    else:
        bubble = size * 2.4 if t["number"] else 0.0
        h = (1.2 + max(bubble, size * 1.5) + 0.6
             + (size * 1.0 + 0.6 if t["subtitle"] else 0.0))
    if (getattr(frame, "title_pos", "below") or "below") == "above":
        return (0.0, h, 0.0)
    return (0.0, 0.0, h)


def _paint_title_bubble(painter: QPainter, cx: float, cy: float, d: float,
                        number: str, sheet: str, ink: QColor) -> None:
    """The view bubble: a circle with the number, split by a rule
    with the sheet reference underneath when there is one."""
    pen = QPen(ink)
    pen.setWidthF(0.35)
    painter.setPen(pen)
    painter.setBrush(QBrush(QColor(255, 255, 255)))
    painter.drawEllipse(QPointF(cx, cy), d / 2.0, d / 2.0)
    painter.setBrush(Qt.NoBrush)
    if sheet:
        painter.drawLine(QPointF(cx - d / 2.0, cy), QPointF(cx + d / 2.0, cy))
        _draw_text_mm(painter, QRectF(cx - d / 2.0, cy - d / 2.0, d, d / 2.0),
                      number, d * 0.34, bold=True,
                      align=Qt.AlignHCenter | Qt.AlignVCenter, color=ink)
        _draw_text_mm(painter, QRectF(cx - d / 2.0, cy, d, d / 2.0),
                      sheet, d * 0.26, align=Qt.AlignHCenter | Qt.AlignVCenter,
                      color=ink)
    else:
        _draw_text_mm(painter, QRectF(cx - d / 2.0, cy - d / 2.0, d, d),
                      number, d * 0.42, bold=True,
                      align=Qt.AlignHCenter | Qt.AlignVCenter, color=ink)


def _paint_view_title_mm(painter: QPainter, frame: MarcoVista) -> None:
    """The frame's title in its style (see MarcoVista.title_style)."""
    ink = QColor(30, 36, 44)
    size = max(1.5, float(getattr(frame, "title_mm", 4.0) or 4.0))
    style = getattr(frame, "title_style", "layout") or "layout"
    align = getattr(frame, "title_align", "left") or "left"
    t = view_title_texts(frame)
    w, h = frame.w_mm, frame.h_mm
    left, top, bottom = view_title_extent(frame)
    if style == "bar":
        strip_w = left - 1.0
        strip = QRectF(-left, 0.0, strip_w, h)
        pen = QPen(ink)
        pen.setWidthF(0.25)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(strip)
        painter.save()
        # Turn the strip: local x runs UP the page, local y toward the frame.
        painter.translate(strip.left(), strip.bottom())
        painter.rotate(-90.0)
        y0 = 0.0
        x0 = 0.0
        if t["number"]:
            d = min(strip_w, size * 2.4) * 0.9
            painter.save()
            painter.rotate(90.0)          # the bubble reads upright
            _paint_title_bubble(painter, strip_w / 2.0, -(d / 2.0 + 1.0), d,
                                t["number"], t["sheet"], ink)
            painter.restore()
            x0 = d + 2.0
        pad = 1.0
        cols = [(t["title"], size, True, size * 1.5)]
        if t["subtitle"]:
            cols.append((t["subtitle"], size * 0.75, False, size * 1.1))
        if t["scale"]:
            cols.append((t["scale"], size * 0.75, False, size * 1.1))
        y = y0 + pad
        for text, sz, bold, col_h in cols:
            _draw_text_mm(painter, QRectF(x0 + 1.0, y, h - x0 - 2.0, col_h),
                          text, sz, bold=bold,
                          align=Qt.AlignLeft | Qt.AlignVCenter, color=ink)
            y += col_h
        painter.restore()
        return
    above = (getattr(frame, "title_pos", "below") or "below") == "above"
    block_h = top if above else bottom
    by = -block_h if above else h + 1.2
    if style == "simple":
        text = t["title"] + (f" — {t['scale'][5:]}" if t["scale"] else "")
        qa = {"left": Qt.AlignLeft, "right": Qt.AlignRight}.get(
            align, Qt.AlignHCenter)
        _draw_text_mm(painter, QRectF(0, by, w, size * 1.6), text, size,
                      bold=True, align=qa | Qt.AlignTop, color=ink)
        if t["subtitle"]:
            _draw_text_mm(painter, QRectF(0, by + size * 1.6, w, size * 1.0),
                          t["subtitle"], size * 0.7, align=qa | Qt.AlignTop,
                          color=ink)
        return
    # "layout": bubble + title + scale over a rule, subtitle under it
    d = size * 2.4 if t["number"] else 0.0
    gap = size * 0.5
    title_w = _text_width_mm(t["title"], size, bold=True)
    scale_w = _text_width_mm(t["scale"], size * 0.8)
    text_w = title_w + (gap + scale_w if t["scale"] else 0.0)
    total = (d + gap if d else 0.0) + text_w
    if align == "right":
        x_b = max(0.0, w - total)
    elif align == "center":
        x_b = max(0.0, (w - total) / 2.0)
    else:
        x_b = 0.0
    x_text = x_b + (d + gap if d else 0.0)
    line_h = max(d, size * 1.5)
    rule_y = by + line_h
    if d:
        _paint_title_bubble(painter, x_b + d / 2.0, rule_y - d / 2.0, d,
                            t["number"], t["sheet"], ink)
    _draw_text_mm(painter, QRectF(x_text, rule_y - size * 1.5, w, size * 1.5),
                  t["title"], size, bold=True,
                  align=Qt.AlignLeft | Qt.AlignBottom, color=ink)
    if t["scale"]:
        _draw_text_mm(painter,
                      QRectF(x_text + title_w + gap, rule_y - size * 1.5,
                             w, size * 1.5 - size * 0.08),
                      t["scale"], size * 0.8,
                      align=Qt.AlignLeft | Qt.AlignBottom, color=ink)
    pen = QPen(ink)
    pen.setWidthF(0.35)
    painter.setPen(pen)
    x_rule = x_b + d if (align == "left" and d) else 0.0
    painter.drawLine(QPointF(x_rule, rule_y + 0.2), QPointF(w, rule_y + 0.2))
    if t["subtitle"]:
        _draw_text_mm(painter, QRectF(x_text, rule_y + 0.6, w, size * 1.0),
                      t["subtitle"], size * 0.7,
                      align=Qt.AlignLeft | Qt.AlignTop, color=ink)


def _paint_scale_label_mm(painter: QPainter, frame: MarcoVista) -> None:
    """The frame's scale label, under a corner or inside it (with a white
    halo box inside, over the render)."""
    size = max(1.5, float(getattr(frame, "scale_mm", 3.0) or 3.0))
    text = frame.scale_label()
    pos = getattr(frame, "scale_pos", "under-right") or "under-right"
    h = size * 1.4
    if pos.startswith("under"):
        rect = QRectF(0, frame.h_mm + 1.0, frame.w_mm, h)
        align = (Qt.AlignLeft if pos == "under-left" else Qt.AlignRight)
        _draw_text_mm(painter, rect, text, size, bold=True,
                      align=align | Qt.AlignTop, color=QColor(40, 46, 54))
        return
    pad = 1.0
    w = len(text) * size * 0.62 + 2 * pad
    x = pad if pos == "inside-bl" else frame.w_mm - w - pad
    rect = QRectF(x, frame.h_mm - h - pad, w, h)
    painter.save()
    painter.setClipRect(QRectF(0, 0, frame.w_mm, frame.h_mm))
    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(QColor(255, 255, 255, 220)))
    painter.drawRect(rect)
    _draw_text_mm(painter, rect, text, size, bold=True,
                  align=Qt.AlignHCenter | Qt.AlignVCenter,
                  color=QColor(40, 46, 54))
    painter.restore()


def _paint_stale_badge(painter: QPainter, frame: MarcoVista) -> None:
    """Small "Outdated" tag in the frame's top-right corner: the model
    changed since this view was rendered (auto-render off, or a vector
    frame waiting for Update)."""
    text = tr("Outdated")
    font = QFont()
    font.setPointSizeF(2.6)
    painter.setFont(font)
    fm = painter.fontMetrics()
    w = fm.horizontalAdvance(text) + 3.0
    h = fm.height() + 1.5
    r = QRectF(frame.w_mm - w - 1.5, 1.5, w, h)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(255, 196, 60, 215))
    painter.drawRoundedRect(r, 1.0, 1.0)
    painter.setPen(QColor(60, 40, 0))
    painter.drawText(r, Qt.AlignCenter, text)


def _paint_view_edit_border(painter: QPainter, frame: MarcoVista) -> None:
    """The frame whose view is being edited in place: a blue dashed inset
    border and a small tag (sheet layout programs grey the page instead)."""
    pen = QPen(QColor(58, 110, 165), 0.6, Qt.DashLine)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    painter.drawRect(QRectF(0.8, 0.8, frame.w_mm - 1.6, frame.h_mm - 1.6))
    text = tr("Editing view")
    font = QFont()
    font.setPointSizeF(2.6)
    painter.setFont(font)
    fm = painter.fontMetrics()
    w = fm.horizontalAdvance(text) + 3.0
    h = fm.height() + 1.5
    r = QRectF(1.5, frame.h_mm - h - 1.5, w, h)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(58, 110, 165, 215))
    painter.drawRoundedRect(r, 1.0, 1.0)
    painter.setPen(QColor(255, 255, 255))
    painter.drawText(r, Qt.AlignCenter, text)


#: Traced georef paths on paper: the viewport's cyan, so the sheet reads
#: like the model (Marco, 2026-09-05: "no se ve la línea del path").
_GEO_PATH_INK = QColor(0, 150, 170)


def _paint_annots_mm(painter: QPainter, frame: MarcoVista, annots) -> None:
    """Model dimensions, leader texts and traced paths projected into the
    frame (mm): ``("line", x0, y0, x1, y1)``,
    ``("text", x, y, deg, text, size)`` and ``("poly", [(x, y), …])``."""
    r = QRectF(0, 0, frame.w_mm, frame.h_mm)
    painter.save()
    painter.setClipRect(r)
    ink = QColor(45, 55, 75)
    halo = QColor(255, 255, 255, 230)
    # Lines first with a white halo under the ink, so a leader over dark
    # water or stone still reads.
    for a in annots:
        if a[0] == "line":
            painter.setPen(QPen(halo, 0.7))
            painter.drawLine(QPointF(a[1], a[2]), QPointF(a[3], a[4]))
        elif a[0] == "secmark":
            painter.setPen(QPen(halo, 1.0))
            painter.drawLine(QPointF(a[1], a[2]), QPointF(a[3], a[4]))
        elif a[0] == "poly":
            pts = [QPointF(x, y) for x, y in a[1]]
            painter.setPen(QPen(halo, 0.9, Qt.SolidLine, Qt.RoundCap,
                                Qt.RoundJoin))
            painter.drawPolyline(pts)
    for a in annots:
        if a[0] == "poly":
            pts = [QPointF(x, y) for x, y in a[1]]
            painter.setPen(QPen(_GEO_PATH_INK, 0.4, Qt.SolidLine,
                                Qt.RoundCap, Qt.RoundJoin))
            painter.setBrush(Qt.NoBrush)
            painter.drawPolyline(pts)
            # Node marks, as the viewport draws them — small on paper.
            painter.setBrush(_GEO_PATH_INK)
            painter.setPen(QPen(halo, 0.15))
            for q in pts:
                painter.drawEllipse(q, 0.45, 0.45)
            painter.setBrush(Qt.NoBrush)
        elif a[0] == "line":
            painter.setPen(QPen(ink, 0.25))
            painter.drawLine(QPointF(a[1], a[2]), QPointF(a[3], a[4]))
        elif a[0] == "arrow":
            # a dimension's arrowhead: tip at (x, y), wings trailing back
            # along (dx, dy) — the sheet cota's own proportions
            from PySide6.QtGui import QPolygonF
            import math as _math
            _kind, x, y, dx, dy = a
            L = 1.8
            base = _math.radians(12)
            ang = _math.atan2(dy, dx)
            painter.save()
            painter.setPen(Qt.NoPen)
            painter.setBrush(ink)
            painter.drawPolygon(QPolygonF([
                QPointF(x, y),
                QPointF(x + L * _math.cos(ang + base),
                        y + L * _math.sin(ang + base)),
                QPointF(x + L * _math.cos(ang - base),
                        y + L * _math.sin(ang - base))]))
            painter.restore()
        elif a[0] == "secmark":
            _paint_section_mark_mm(painter, a, ink, halo)
        elif a[0] == "text":
            _kind, x, y, deg, text, size = a
            box = QRectF(-60, -size * 1.3, 120, size * 1.3)
            painter.save()
            painter.translate(QPointF(x, y))
            painter.rotate(deg)
            d = max(0.12, size * 0.06)
            for dx, dy in ((-d, 0), (d, 0), (0, -d), (0, d),
                           (-d, -d), (d, d), (-d, d), (d, -d)):
                _draw_text_mm(painter, box.translated(dx, dy), text, size,
                              bold=True,
                              align=Qt.AlignHCenter | Qt.AlignBottom,
                              color=halo)
            _draw_text_mm(painter, box, text, size, bold=True,
                          align=Qt.AlignHCenter | Qt.AlignBottom, color=ink)
            painter.restore()
    painter.restore()


_VECTOR_INK = QColor(30, 36, 44)


def vector_pens(frame: MarcoVista) -> dict:
    """The three pens of the vector style, by line class (core.hlr KIND_*):
    cut / profile / edge widths from the frame, in paper mm."""
    from core.hlr import KIND_CUT, KIND_EDGE, KIND_HIDDEN, KIND_PROFILE
    widths = {
        KIND_HIDDEN: float(getattr(frame, "pen_edge_mm", 0.18) or 0.18),
        KIND_EDGE: float(getattr(frame, "pen_edge_mm", 0.18) or 0.18),
        KIND_PROFILE: float(getattr(frame, "pen_profile_mm", 0.35) or 0.35),
        KIND_CUT: float(getattr(frame, "pen_cut_mm", 0.5) or 0.5)}
    pens = {}
    for kind, w in widths.items():
        pen = QPen(_VECTOR_INK)
        pen.setWidthF(max(0.05, w))
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        if kind == KIND_HIDDEN:
            # Dashed, in paper mm whatever the pen: 1.5 mm dash, 0.8 gap.
            pen.setCapStyle(Qt.FlatCap)
            w = max(0.05, w)
            pen.setDashPattern([1.5 / w, 0.8 / w])
        pens[kind] = pen
    return pens


def _paint_hlr_lines_mm(painter: QPainter, frame: MarcoVista, hlr,
                        kinds, budget=None) -> None:
    """Ink the hidden-line segments thin → profile → cut, so the heavy
    lines always sit on top where they cross the light ones.

    With a ``budget`` it inks at most that many, keeping the SILHOUETTE:
    every cut line and every profile first, plain edges with what is left.
    That is the drag pass — see ``_DRAG_SEG_BUDGET``; a printed or exported
    sheet never passes one."""
    import numpy as np
    from PySide6.QtCore import QLineF
    from core.hlr import KIND_CUT, KIND_EDGE, KIND_HIDDEN, KIND_PROFILE
    segs = np.asarray(hlr, dtype=float).reshape(-1, 4)
    pens = vector_pens(frame)
    if kinds is None or len(kinds) != len(segs):
        groups = [(KIND_EDGE, segs
                   if budget is None else segs[:int(budget)])]
    else:
        k = np.asarray(kinds)
        rows = {kind: segs[k == kind]
                for kind in (KIND_HIDDEN, KIND_EDGE, KIND_PROFILE, KIND_CUT)}
        if budget is not None and len(segs) > budget:
            left = int(budget)
            for kind in (KIND_CUT, KIND_PROFILE, KIND_EDGE, KIND_HIDDEN):
                take = max(0, min(len(rows[kind]), left))
                rows[kind] = rows[kind][:take]
                left -= take
        groups = [(kind, rows[kind])
                  for kind in (KIND_HIDDEN, KIND_EDGE, KIND_PROFILE,
                               KIND_CUT)]
    for kind, rows in groups:
        if not len(rows):
            continue
        painter.setPen(pens[kind])
        painter.drawLines([QLineF(float(x0), float(y0), float(x1), float(y1))
                           for x0, y0, x1, y1 in rows])


def _paint_cut_fills_mm(painter: QPainter, frame: MarcoVista, fills) -> None:
    """The poché: fill the closed section-cut rings (even-odd, so a hollow
    wall stays hollow) solid or with 45° hatching, under the lines."""
    mode = getattr(frame, "cut_fill", "solid") or "solid"
    if not fills or mode == "none":
        return
    from PySide6.QtCore import QLineF
    from PySide6.QtGui import QPainterPath
    path = QPainterPath()
    path.setFillRule(Qt.OddEvenFill)
    for ring in fills:
        pts = [QPointF(float(x), float(y)) for x, y in ring]
        if len(pts) < 3:
            continue
        path.moveTo(pts[0])
        for q in pts[1:]:
            path.lineTo(q)
        path.closeSubpath()
    if path.isEmpty():
        return
    color = QColor(getattr(frame, "cut_fill_color", "") or "#595e69")
    painter.save()
    if mode == "hatch":
        painter.setClipPath(path, Qt.IntersectClip)
        step = max(0.3, float(getattr(frame, "cut_hatch_mm", 1.5) or 1.5))
        pen = QPen(color)
        pen.setWidthF(max(0.05, float(getattr(frame, "pen_edge_mm", 0.18)
                                      or 0.18)))
        painter.setPen(pen)
        br = path.boundingRect()
        # lines x + y = c, phase-locked to the frame so a moved frame keeps
        # its hatching
        c = math.floor((br.left() + br.top()) / step) * step
        c_end = br.right() + br.bottom()
        lines = []
        while c <= c_end:
            xa = max(br.left(), c - br.bottom())
            xb = min(br.right(), c - br.top())
            if xb > xa:
                lines.append(QLineF(xa, c - xa, xb, c - xb))
            c += step
        if lines:
            painter.drawLines(lines)
    else:
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(color))
        painter.drawPath(path)
    painter.restore()


def _paint_section_mark_mm(painter: QPainter, a, ink: QColor,
                           halo: QColor) -> None:
    """A section mark: the cut line dash-dotted with a heavy stub at each
    end, an arrow toward the side the section looks at, and the letter
    in a bubble past the arrow — «A … A» across the plan."""
    import math as _math
    from PySide6.QtGui import QPolygonF
    _kind, x0, y0, x1, y1, ax, ay, label, size = a
    pen = QPen(ink, 0.35)
    pen.setDashPattern([8.0, 2.0, 1.0, 2.0])         # dash-dot, in pen widths
    pen.setCapStyle(Qt.FlatCap)
    painter.setPen(pen)
    painter.drawLine(QPointF(x0, y0), QPointF(x1, y1))
    dx, dy = x1 - x0, y1 - y0
    ln = _math.hypot(dx, dy) or 1.0
    ux, uy = dx / ln, dy / ln
    stub = max(3.0, size * 1.2)
    arrow = max(2.5, size * 1.0)
    r = size * 0.95                                    # bubble radius
    heavy = QPen(ink, 0.7)
    heavy.setCapStyle(Qt.FlatCap)
    for ex, ey, sx, sy in ((x0, y0, ux, uy), (x1, y1, -ux, -uy)):
        # the stub: the last bit of the line, heavy
        painter.setPen(heavy)
        painter.drawLine(QPointF(ex, ey), QPointF(ex + sx * stub, ey + sy * stub))
        # the arrow: a filled triangle sitting on the stub, pointing (ax, ay)
        bx, by = ex + sx * stub * 0.5, ey + sy * stub * 0.5
        tip = QPointF(bx + ax * arrow, by + ay * arrow)
        wing = arrow * 0.45
        painter.save()
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(ink))
        painter.drawPolygon(QPolygonF([
            tip, QPointF(bx + ux * wing, by + uy * wing),
            QPointF(bx - ux * wing, by - uy * wing)]))
        painter.restore()
        # the letter, in a bubble past the arrow
        cx, cy = bx + ax * (arrow + 0.8 + r), by + ay * (arrow + 0.8 + r)
        painter.setPen(QPen(ink, 0.35))
        painter.setBrush(QBrush(QColor(255, 255, 255)))
        painter.drawEllipse(QPointF(cx, cy), r, r)
        painter.setBrush(Qt.NoBrush)
        _draw_text_mm(painter, QRectF(cx - r, cy - r, 2 * r, 2 * r), label,
                      size * 0.9, bold=True,
                      align=Qt.AlignHCenter | Qt.AlignVCenter, color=ink)


def paint_frame_mm(painter: QPainter, frame: MarcoVista,
                   image: Optional[QImage], hlr=None, annots=None,
                   screen: bool = False, kinds=None, fills=None,
                   budget=None) -> None:
    r = QRectF(0, 0, frame.w_mm, frame.h_mm)
    if frame.style == "vectorial":
        painter.fillRect(r, QColor(255, 255, 255))
        if hlr is not None and len(hlr):
            painter.save()
            painter.setClipRect(r)
            _paint_cut_fills_mm(painter, frame, fills)
            _paint_hlr_lines_mm(painter, frame, hlr, kinds, budget)
            painter.restore()
        else:
            _draw_text_mm(painter, r.adjusted(2, 2, -2, -2),
                          tr("Update the view to render"), 3.5,
                          color=QColor(140, 150, 160))
    elif image is not None and not image.isNull():
        # Never stretch the picture: draw it at the size it was rendered
        # for and clip it to the frame, so a frame resized mid-gesture
        # keeps an undistorted drawing (#80). What no longer fits is
        # hidden and the new area is paper; when the frame has not
        # changed since the render the two rects coincide (a 1:1 blit).
        img_r = QRectF(0, 0, image.width() * 25.4 / RENDER_DPI,
                       image.height() * 25.4 / RENDER_DPI)
        if (abs(img_r.width() - r.width()) < 0.1
                and abs(img_r.height() - r.height()) < 0.1):
            painter.drawImage(r, image)
        else:
            painter.fillRect(r, QColor(255, 255, 255))
            painter.save()
            painter.setClipRect(r)
            painter.drawImage(img_r, image)
            painter.restore()
    else:
        painter.fillRect(r, QColor(245, 246, 248))
        _draw_text_mm(painter, r.adjusted(2, 2, -2, -2),
                      tr("Update the view to render"), 3.5,
                      color=QColor(140, 150, 160))
    if annots:
        _paint_annots_mm(painter, frame, annots)
    if frame.grid_m > 0 and not getattr(frame, "perspective", False):
        # the graticule: model-metre grid at the frame's scale (a
        # perspective frame has none, so its squares would be a fiction)
        from core.composition import model_height_for_frame
        model_h = model_height_for_frame(frame.h_mm, frame.scale_n)
        step = frame.grid_m * frame.h_mm / model_h
        if step >= 2.0:                     # below 2 mm it's just moiré
            gpen = QPen(QColor(90, 140, 190, 120))
            gpen.setWidthF(0.12)
            painter.save()
            painter.setClipRect(r)
            painter.setPen(gpen)
            x = step
            while x < frame.w_mm:
                painter.drawLine(QPointF(x, 0), QPointF(x, frame.h_mm))
                x += step
            y = step
            while y < frame.h_mm:
                painter.drawLine(QPointF(0, y), QPointF(frame.w_mm, y))
                y += step
            painter.restore()
    if getattr(frame, "border", False):
        pen = QPen(QColor(getattr(frame, "border_color", "#282e36")))
        pen.setWidthF(max(0.1, float(getattr(frame, "border_mm", 0.3))))
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(r)
    elif screen:
        # Canvas-only guide so a borderless frame still reads as a frame;
        # the print gets nothing here (Marco, 2026-09-02).
        pen = QPen(QColor(150, 158, 166), 0.2, Qt.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(r)
    if frame.show_title:
        _paint_view_title_mm(painter, frame)
    if getattr(frame, "show_scale", False):
        _paint_scale_label_mm(painter, frame)


def paint_scalebar_mm(painter: QPainter, sb: BarraEscala) -> None:
    """Alternating black/white boxes + metre labels + the 1:N caption."""
    seg_mm = sb.segment_mm()
    seg_m = sb.segment_m()
    bar_h = 2.4
    pen = QPen(QColor(30, 36, 44))
    pen.setWidthF(0.25)
    painter.setPen(pen)
    for i in range(sb.segments):
        r = QRectF(i * seg_mm, 0, seg_mm, bar_h)
        painter.setBrush(QBrush(QColor(30, 36, 44)) if i % 2 == 0
                         else QBrush(QColor(255, 255, 255)))
        painter.drawRect(r)
    for i in range(sb.segments + 1):
        v = i * seg_m
        label = f"{v:g}"
        _draw_text_mm(painter,
                      QRectF(i * seg_mm - 12, bar_h + 0.8, 24, 4),
                      label, 2.6, align=Qt.AlignHCenter | Qt.AlignTop)
    _draw_text_mm(painter,
                  QRectF(0, bar_h + 4.6, sb.w_mm, 4),
                  tr("metres — scale 1:{n}", n=f"{sb.scale_n:g}"), 2.6,
                  align=Qt.AlignHCenter | Qt.AlignTop)


def chainage_step(length: float, step_m: float = 0.0) -> float:
    """The chainage step in metres: the user's, or the round one that spans
    *length* in about six marks. Shared by the profile's axis and the plan
    view's marks, so a sheet's chainages agree by construction."""
    if step_m and step_m > 0:
        return float(step_m)
    ticks = _nice_ticks(0.0, length, 6)
    return (ticks[1] - ticks[0]) if len(ticks) > 1 else (length or 1.0)


def _chainage(s: float, step: float) -> str:
    """Civil chainage, ``1+250`` style; decimals only when the step needs them."""
    km, m = int(s // 1000), s % 1000
    if step >= 1.0:
        return f"{km}+{m:03.0f}"
    return f"{km}+{m:06.2f}"


def paint_perfil_mm(painter: QPainter, m: PerfilTerreno, profile,
                    path_name: str = "", message=None) -> None:
    """The longitudinal profile in paper mm: title and scale caption, the
    grid with chainage and elevation labels, the ground line over its
    tinted fill, the axes. Horizontal scale 1:N (or fit to the width) and a
    vertical exaggeration (or fit to the height) — the pair every road and
    canal plan states next to the profile."""
    w, h = float(m.w_mm), float(m.h_mm)
    ink = QColor(30, 36, 44)
    grey = QColor(90, 98, 110)
    pen = QPen(ink)
    pen.setWidthF(0.25)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    painter.drawRect(QRectF(0, 0, w, h))
    t = max(1.0, float(m.text_mm))
    title = m.title or tr("Longitudinal profile — {name}",
                          name=path_name or tr("path"))
    _draw_text_mm(painter, QRectF(2.0, 1.0, w - 4.0, t * 1.7), title,
                  t * 1.15, bold=True)
    if profile is None or not profile.samples or profile.max_elevation() is None:
        _draw_text_mm(painter, QRectF(2.0, h / 2 - t, w - 4.0, t * 2.2),
                      message or tr("Loading terrain…"), t,
                      align=Qt.AlignCenter, color=grey)
        return
    left, right = 4.0 + t * 4.2, w - 3.0
    top, bottom = t * 1.7 + 3.0 + t * 1.4, h - (t * 2.2 + 3.0)
    pw, ph = right - left, bottom - top
    if pw < 10.0 or ph < 8.0:
        return
    length = profile.length or 1.0
    elo, ehi = profile.min_elevation(), profile.max_elevation()
    if ehi - elo < 1.0:
        elo, ehi = elo - 1.0, ehi + 1.0
    v_ticks = _nice_ticks(elo, ehi, 4)
    step_v = float(m.grid_v_m) or (v_ticks[1] - v_ticks[0] if len(v_ticks) > 1 else 1.0)
    base = math.floor(elo / step_v) * step_v            # cota de comparación
    topv = math.ceil(ehi / step_v) * step_v
    if topv <= base:
        topv = base + step_v
    fitted_h = False
    if m.scale_n > 0:
        mm_per_m_h = 1000.0 / float(m.scale_n)
        if length * mm_per_m_h > pw:                    # would not fit: fall back
            mm_per_m_h, fitted_h = pw / length, True
    else:
        mm_per_m_h = pw / length
    if m.exag > 0:
        mm_per_m_v = mm_per_m_h * float(m.exag)
        if (topv - base) * mm_per_m_v > ph:
            mm_per_m_v = ph / (topv - base)
    else:
        mm_per_m_v = ph / (topv - base)
    exag_eff = mm_per_m_v / mm_per_m_h if mm_per_m_h > 0 else 1.0

    def sx(s):
        return left + s * mm_per_m_h

    def sy(e):
        return bottom - (e - base) * mm_per_m_v

    plot_right = sx(length)
    plot_top = sy(topv)
    # grid + labels
    step_h = chainage_step(length, float(m.grid_h_m))
    light = QPen(QColor(200, 206, 214))
    light.setWidthF(0.12)
    s_val = 0.0
    while s_val <= length + 1e-6:
        x = sx(s_val)
        if m.grid:
            painter.setPen(light)
            painter.drawLine(QPointF(x, plot_top), QPointF(x, bottom))
        _draw_text_mm(painter, QRectF(x - 12.0, bottom + 0.8, 24.0, t * 1.4),
                      _chainage(s_val, step_h), t,
                      align=Qt.AlignHCenter | Qt.AlignTop, color=grey)
        s_val += step_h
    e_val = base
    while e_val <= topv + 1e-6:
        y = sy(e_val)
        if m.grid:
            painter.setPen(light)
            painter.drawLine(QPointF(left, y), QPointF(plot_right, y))
        _draw_text_mm(painter, QRectF(1.0, y - t * 0.7, left - 2.0, t * 1.4),
                      f"{e_val:g}", t, align=Qt.AlignRight | Qt.AlignVCenter,
                      color=grey)
        e_val += step_v
    # the ground: runs split where the DEM is still missing
    runs, cur = [], []
    for smp in profile.samples:
        if smp.elevation is None:
            if cur:
                runs.append(cur)
                cur = []
        else:
            cur.append(QPointF(sx(smp.station), sy(smp.elevation)))
    if cur:
        runs.append(cur)
    from PySide6.QtGui import QPolygonF
    for run in runs:
        if len(run) < 2:
            continue
        if m.fill:
            poly = QPolygonF(run + [QPointF(run[-1].x(), bottom),
                                    QPointF(run[0].x(), bottom)])
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(QColor(120, 170, 110, 60)))
            painter.drawPolygon(poly)
            painter.setBrush(Qt.NoBrush)
        line = QPen(QColor(60, 110, 50))
        line.setWidthF(0.4)
        painter.setPen(line)
        painter.drawPolyline(QPolygonF(run))
    # axes
    axis = QPen(ink)
    axis.setWidthF(0.3)
    painter.setPen(axis)
    painter.drawLine(QPointF(left, plot_top), QPointF(left, bottom))
    painter.drawLine(QPointF(left, bottom), QPointF(plot_right, bottom))
    # caption: the scales, as a plan states them
    cap = tr("Scale H 1:{h} · V 1:{v} · vert. exag. ×{k}",
             h=f"{1000.0 / mm_per_m_h:.0f}", v=f"{1000.0 / mm_per_m_v:.0f}",
             k=f"{exag_eff:.1f}")
    if fitted_h:
        cap += "  " + tr("(fitted to the width)")
    if message:
        cap += "  " + message
    _draw_text_mm(painter, QRectF(2.0, t * 1.7 + 1.6, w - 4.0, t * 1.4), cap,
                  t * 0.9, color=grey)


def paint_norte_mm(painter: QPainter, n: FlechaNorte) -> None:
    """Circle + needle + N, the whole symbol rotated to the project north.

    The N rides the needle's tip, outside the circle, and turns with it
    (Marco, 2026-09-20: «cuando giro la N de norte debería la N girar
    también») — at 0° it sits where its band used to be, above the
    compass. The compass is centred in the box and sized so the letter
    stays inside the box at every angle: the item paints nothing beyond
    its own bounds."""
    sz = n.size_mm
    c = sz / 2.0
    rad = sz * 0.30
    painter.save()
    painter.translate(c, c)
    painter.rotate(n.angle_deg)
    pen = QPen(QColor(30, 36, 44))
    pen.setWidthF(0.35)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    painter.drawEllipse(QPointF(0, 0), rad * 0.92, rad * 0.92)
    from PySide6.QtGui import QPolygonF
    r = rad * 0.78
    painter.setBrush(QBrush(QColor(30, 36, 44)))
    painter.drawPolygon(QPolygonF([QPointF(0, -r), QPointF(r * 0.28, r * 0.35),
                                   QPointF(0, r * 0.12)]))
    painter.setBrush(QBrush(QColor(255, 255, 255)))
    painter.drawPolygon(QPolygonF([QPointF(0, -r), QPointF(-r * 0.28, r * 0.35),
                                   QPointF(0, r * 0.12)]))
    # the N: centred 0.40·sz out along the needle, 0.18·sz tall — its far
    # edge at 0.49·sz, just inside the box whichever way it points
    h = sz * 0.18
    _draw_text_mm(painter, QRectF(-c, -sz * 0.40 - h / 2, sz, h), "N", h,
                  bold=True, align=Qt.AlignCenter)
    painter.restore()


def paint_leyenda_mm(painter: QPainter, le: Leyenda) -> None:
    r = QRectF(0, 0, le.w_mm, le.h_mm)
    painter.fillRect(r, QColor(255, 255, 255))
    pen = QPen(QColor(30, 36, 44))
    pen.setWidthF(0.3)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    painter.drawRect(r)
    _draw_text_mm(painter, QRectF(2, 1.4, le.w_mm - 4, 5), le.title,
                  3.2, bold=True)
    y = 7.5
    rows = le.rows or [tr("(no layers)")]
    for name in rows:
        painter.setBrush(QBrush(QColor(226, 232, 238)))
        painter.setPen(QPen(QColor(30, 36, 44), 0.2))
        painter.drawRect(QRectF(2.2, y + 0.8, 4.0, 3.2))
        _draw_text_mm(painter, QRectF(8, y + 0.7, le.w_mm - 10, 5),
                      name, 2.8)
        y += 5.5


def paint_forma_mm(painter: QPainter, f: FormaItem) -> None:
    pen = QPen(QColor(f.color))
    pen.setWidthF(f.stroke_mm)
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    painter.setBrush(QBrush(QColor(f.fill_color))
                     if f.fill and f.kind in ("rect", "elipse", "poligono")
                     else Qt.NoBrush)
    r = QRectF(0, 0, f.w_mm, f.h_mm)
    if f.kind == "rect":
        rad = min(f.radius_mm, f.w_mm / 2, f.h_mm / 2)
        if rad > 0.01:
            painter.drawRoundedRect(r, rad, rad)
        else:
            painter.drawRect(r)
    elif f.kind == "elipse":
        painter.drawEllipse(r)
    elif f.kind == "poligono":
        import math as _math
        from PySide6.QtGui import QPolygonF
        n = max(3, min(int(f.sides), 24))
        cx, cy = f.w_mm / 2, f.h_mm / 2
        # vertex at the top, inscribed in the item's box (an octagon in a
        # square box comes out regular)
        pts = [QPointF(cx + cx * _math.sin(2 * _math.pi * i / n),
                       cy - cy * _math.cos(2 * _math.pi * i / n))
               for i in range(n)]
        painter.drawPolygon(QPolygonF(pts))
    else:
        a = QPointF(0, f.h_mm if f.invert else 0)
        b = QPointF(f.w_mm, 0 if f.invert else f.h_mm)
        if f.kind == "terreno":
            _paint_ground_mm(painter, f, a, b)
        painter.drawLine(a, b)
        if f.kind == "flecha":
            import math as _math
            from PySide6.QtGui import QPolygonF
            ang = _math.atan2(b.y() - a.y(), b.x() - a.x())
            L = max(2.5, f.stroke_mm * 7)
            for da in (_math.radians(153), -_math.radians(153)):
                painter.drawLine(b, QPointF(
                    b.x() + L * _math.cos(ang + da),
                    b.y() + L * _math.sin(ang + da)))


def _paint_ground_mm(painter: QPainter, f: FormaItem, a: QPointF,
                     b: QPointF) -> None:
    """What hangs UNDER a ground line (the line itself is drawn by the
    caller, on top): 45° ticks, a hatched band or a filled band. «Under»
    is the side of positive page y, whichever way the line slopes, so a
    grade drawn right-to-left still buries the right side."""
    import math as _math
    from PySide6.QtGui import QPolygonF
    dx, dy = b.x() - a.x(), b.y() - a.y()
    length = _math.hypot(dx, dy)
    if length < 1e-6:
        return
    ux, uy = dx / length, dy / length
    nx, ny = -uy, ux                     # a normal; flip it to point DOWN
    if ny < 0:
        nx, ny = -nx, -ny
    step = max(0.5, float(f.tick_step_mm))
    tick = max(0.2, float(f.tick_mm))
    depth = max(0.5, float(f.band_mm))
    mode = f.ground or "ticks"
    if mode == "band":
        col = QColor(f.fill_color)
        col.setAlphaF(0.6)
        painter.save()
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(col))
        painter.drawPolygon(QPolygonF([
            a, b, QPointF(b.x() + nx * depth, b.y() + ny * depth),
            QPointF(a.x() + nx * depth, a.y() + ny * depth)]))
        painter.restore()
        return
    # 45° strokes: from the line, down and BACK along it (the classic
    # earth ticks lean against the direction of travel). A hatch band is
    # the same strokes, longer, clipped to the band and closed underneath.
    pen = QPen(QColor(f.color))
    pen.setWidthF(max(0.1, f.stroke_mm * 0.6))
    pen.setCapStyle(Qt.RoundCap)
    painter.save()
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    if mode == "hatch":
        band = QPolygonF([
            a, b, QPointF(b.x() + nx * depth, b.y() + ny * depth),
            QPointF(a.x() + nx * depth, a.y() + ny * depth)])
        painter.setClipRect(painter.clipBoundingRect()
                            if painter.hasClipping() else
                            QRectF(-1e6, -1e6, 2e6, 2e6))
        from PySide6.QtGui import QPainterPath
        path = QPainterPath()
        path.addPolygon(band)
        painter.setClipPath(path, Qt.IntersectClip)
        reach = depth * _math.sqrt(2.0)      # a 45° stroke spanning the band
        t = -depth
        while t < length + depth:
            x0, y0 = a.x() + ux * t, a.y() + uy * t
            painter.drawLine(QPointF(x0, y0), QPointF(
                x0 + (nx - ux) * reach / _math.sqrt(2.0),
                y0 + (ny - uy) * reach / _math.sqrt(2.0)))
            t += step
        painter.restore()
        painter.save()
        painter.setPen(pen)
        painter.drawLine(QPointF(a.x() + nx * depth, a.y() + ny * depth),
                         QPointF(b.x() + nx * depth, b.y() + ny * depth))
        painter.restore()
        return
    t = step / 2.0
    k = tick / _math.sqrt(2.0)
    while t <= length:
        x0, y0 = a.x() + ux * t, a.y() + uy * t
        painter.drawLine(QPointF(x0, y0),
                         QPointF(x0 + (nx - ux) * k, y0 + (ny - uy) * k))
        t += step
    painter.restore()


def cota_label_anchor(ct: CotaItem) -> tuple:
    """The label's reference point in item space: the dimension line's
    midpoint, moved outside its start or end when ``text_along`` says so,
    plus the free drag (``text_dx_mm``/``text_dy_mm``) — the usual convention lets the
    text box be dragged anywhere, and the line stays put."""
    import math as _math
    (a2x, a2y), (b2x, b2y) = ct.line_points()
    mx, my = (a2x + b2x) / 2, (a2y + b2y) / 2
    along = getattr(ct, "text_along", "middle") or "middle"
    if along in ("start", "end"):
        ldx, ldy = b2x - a2x, b2y - a2y
        length = _math.hypot(ldx, ldy)
        if length > 1e-9:
            ux, uy = ldx / length, ldy / length
            extent = ct.label_extent_mm()     # the box's shadow along the line
            shift = length / 2 + extent / 2 + 1.0
            if along == "start":
                shift = -shift
            mx, my = mx + ux * shift, my + uy * shift
    return (mx + float(getattr(ct, "text_dx_mm", 0.0) or 0.0),
            my + float(getattr(ct, "text_dy_mm", 0.0) or 0.0))


def cota_label_is_automatic(ct: CotaItem) -> bool:
    """Whether the label sits where the line's middle puts it — only then
    may a centered label open the line around itself."""
    return ((getattr(ct, "text_along", "middle") or "middle") == "middle"
            and abs(float(getattr(ct, "text_dx_mm", 0.0) or 0.0)) < 1e-9
            and abs(float(getattr(ct, "text_dy_mm", 0.0) or 0.0)) < 1e-9)


def cota_aside_frame(ct: CotaItem) -> tuple:
    """Where a «beside the line» label sits: ``(ox, oy, deg, tw, th)`` —
    the label box's centre relative to the dimension line's midpoint
    (page mm), the text's rotation, and the box size. The box stands
    clear of the line by ``offset_mm`` on the line's «above» side
    (``aside``) or the other one (``aside_below``); a horizontal label on
    a vertical cota therefore lands to its left or right, whole, instead
    of straddling it (Marco, 2026-09-08: «sería bueno que la posición de
    texto en acotar también haya una opción para ponerla a un costado»)."""
    import math as _math
    deg = cota_line_deg(ct)
    horizontal = (getattr(ct, "text_align", "aligned")
                  or "aligned") == "horizontal"
    label = ct.label()
    tw = len(label) * ct.text_mm * 0.62 + 2.0
    th = ct.text_mm * 1.3 + 0.8
    d = _math.radians(deg)
    ux, uy = _math.sin(d), -_math.cos(d)          # the «above» side
    if (getattr(ct, "text_pos", "") or "") == "aside_below":
        ux, uy = -ux, -uy
    half = (tw / 2 * abs(ux) + th / 2 * abs(uy)) if horizontal else th / 2
    dist = ct.offset_mm + half
    return ux * dist, uy * dist, (0.0 if horizontal else deg), tw, th


def paint_cota_mm(painter: QPainter, ct: CotaItem) -> None:
    """Architect-style dimension: the line runs ``sep_mm`` off the measured
    points along their normal, tied back with extension
    lines; oblique ticks / arrows / bare ends; centred label of the REAL
    model distance (paper length × N).

    The standard is carried by ``text_pos``, not by a switch over it:
    ``above`` is ISO, whose dimension line is NEVER interrupted (rule 5 of
    Rafael's video, 09:00), and ``centered`` IS the German/Japanese
    rendering, which opens the line around the text (rule 18, 14:00). Only
    ISO is on the menu for now (Marco, 2026-09-20); the other values still
    paint so a drawing that already carries them keeps its look."""
    import math as _math
    from PySide6.QtGui import QBrush, QPolygonF
    a = QPointF(0, 0)
    b = QPointF(ct.dx_mm, ct.dy_mm)
    (a2x, a2y), (b2x, b2y) = ct.line_points()
    a2, b2 = QPointF(a2x, a2y), QPointF(b2x, b2y)
    color = QColor(ct.color)
    pen = QPen(color)
    pen.setWidthF(ct.stroke_mm)
    painter.setPen(pen)
    # Extension lines: small gap at the measured point, small overshoot past
    # the dimension line (the usual drafting convention). Each one
    # runs from ITS point to ITS foot, so a cota forced straight over two
    # points at different heights gets extension lines of different lengths
    # — which is the whole point of forcing it.
    for p, p2 in ((a, a2), (b, b2)):
        ex, ey = p2.x() - p.x(), p2.y() - p.y()
        ln = _math.hypot(ex, ey)
        if ln <= 0.05:                  # the point is on the line already
            continue
        ux, uy = ex / ln, ey / ln
        painter.drawLine(QPointF(p.x() + ux, p.y() + uy),
                         QPointF(p2.x() + ux * 1.2, p2.y() + uy * 1.2))
    tail = ct.text_tail()                 # rule 4: the line covers the words
    if tail is not None:
        (tx0, ty0), (tx1, ty1) = tail
        painter.drawLine(QPointF(tx0, ty0), QPointF(tx1, ty1))
    ang = _math.atan2(b2.y() - a2.y(), b2.x() - a2.x())
    label = ct.label()
    mid = QPointF((a2.x() + b2.x()) / 2, (a2.y() + b2.y()) / 2)
    text_pos = getattr(ct, "text_pos", "above") or "above"
    length = _math.hypot(ct.dx_mm, ct.dy_mm)
    if text_pos == "centered" and cota_label_is_automatic(ct):
        # The label sits ON the line, which opens around it (the
        # "centered" text position). The opening is the label box's
        # shadow ALONG the line: a horizontal label on a vertical cota
        # only covers its own height there — measuring its width opened
        # the whole line (Marco, 2026-09-08: «en 0.80 no se ve la línea
        # de acotación y en la 0.50 sí»).
        ux, uy = _math.cos(ang), _math.sin(ang)
        tw = len(label) * ct.text_mm * 0.62 + 2.0
        th = ct.text_mm * 1.3 + 0.8
        horizontal = (getattr(ct, "text_align", "aligned")
                      or "aligned") == "horizontal"
        extent = abs(tw * ux) + abs(th * uy) if horizontal else tw
        half = extent / 2 + 0.5
        if 2 * half < length - 2.0:
            painter.drawLine(a2, QPointF(mid.x() - ux * half,
                                         mid.y() - uy * half))
            painter.drawLine(QPointF(mid.x() + ux * half,
                                     mid.y() + uy * half), b2)
        else:
            painter.drawLine(a2, b2)
    else:
        painter.drawLine(a2, b2)
    if ct.ends == "arrow":
        L = max(1.8, ct.stroke_mm * 6)
        painter.save()
        painter.setBrush(QBrush(color))
        painter.setPen(Qt.NoPen)
        for pt, direction in ((a2, ang), (b2, ang + _math.pi)):
            tip = pt
            base = _math.radians(12)
            painter.drawPolygon(QPolygonF([
                tip,
                QPointF(tip.x() + L * _math.cos(direction + base),
                        tip.y() + L * _math.sin(direction + base)),
                QPointF(tip.x() + L * _math.cos(direction - base),
                        tip.y() + L * _math.sin(direction - base))]))
        painter.restore()
    elif ct.ends != "none":
        tick = 1.6
        for pt in (a2, b2):
            painter.drawLine(
                QPointF(pt.x() - tick * _math.cos(ang + _math.radians(45)),
                        pt.y() - tick * _math.sin(ang + _math.radians(45))),
                QPointF(pt.x() + tick * _math.cos(ang + _math.radians(45)),
                        pt.y() + tick * _math.sin(ang + _math.radians(45))))
    painter.save()
    tcol = QColor(ct.text_color) if getattr(ct, "text_color", "") else color
    lx, ly = cota_label_anchor(ct)          # outside an end / dragged
    if text_pos in ("aside", "aside_below"):
        ox, oy, deg, _tw, th = cota_aside_frame(ct)
        painter.translate(lx + ox, ly + oy)
        painter.rotate(deg)
        rect = QRectF(-40, -th / 2, 80, th)
        align = Qt.AlignHCenter | Qt.AlignVCenter
    else:
        painter.translate(lx, ly)
        deg = cota_line_deg(ct)                     # ISO: head to the LEFT
        if (getattr(ct, "text_align", "aligned") or "aligned") == "horizontal":
            deg = 0.0
        painter.rotate(deg)
        if text_pos == "below":
            rect = QRectF(-40, ct.offset_mm, 80, ct.text_mm * 1.3)
            align = Qt.AlignHCenter | Qt.AlignTop
        elif text_pos == "centered":
            rect = QRectF(-40, -ct.text_mm * 0.65, 80, ct.text_mm * 1.3)
            align = Qt.AlignHCenter | Qt.AlignVCenter
        else:
            rect = text_baseline_rect_mm(ct.text_mm, -ct.offset_mm)
            align = Qt.AlignHCenter | Qt.AlignTop
    bg = getattr(ct, "text_bg", "") or ""
    if bg and label:
        tw = len(label) * ct.text_mm * 0.62 + 2.0
        painter.save()
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(_with_opacity(
            bg, getattr(ct, "text_bg_opacity", 1.0))))
        painter.drawRect(QRectF(-tw / 2, rect.top() - 0.4, tw,
                                rect.height() + 0.8))
        painter.restore()
    _draw_text_mm(painter, rect, label, ct.text_mm, align=align, color=tcol)
    painter.restore()


def _text_metrics(size_mm: float, bold: bool = False,
                  family: str = "Sans Serif"):
    """``(QFontMetricsF, scale)`` for the font :func:`_draw_text_mm` uses."""
    from PySide6.QtGui import QFontMetricsF
    font = QFont(family or "Sans Serif")
    font.setPixelSize(100)
    font.setBold(bold)
    return QFontMetricsF(font), size_mm / 100.0 * 0.75


def _line_count(text: str, width_mm: float, size_mm: float,
                bold: bool = False, family: str = "Sans Serif") -> int:
    """Lines *text* takes word-wrapped in ``width_mm`` (typed breaks and
    automatic ones), read off the font's bounding box."""
    if not text:
        return 0
    fm, s = _text_metrics(size_mm, bold, family)
    box = QRectF(0, 0, max(width_mm, 0.5) / s, 1e6)
    need = fm.boundingRect(box, int(Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap), text)
    return max(1, int(round(need.height() / max(fm.height(), 1e-6))))


def _laid_out_height_mm(text: str, width_mm: float, size_mm: float,
                        bold: bool = False, family: str = "Sans Serif") -> float:
    """Height :func:`_draw_text_mm` really lays *text* out in: the first
    line's ascent + descent, then the font's LINE SPACING per extra line
    (QPainter stacks lines at that pitch — measured 4.0 mm at 11 pt while
    ``QFontMetricsF.boundingRect`` summed bare line heights and came out
    short: a three-line label's last descender poked out of its
    background)."""
    n = _line_count(text, width_mm, size_mm, bold, family)
    if n == 0:
        return 0.0
    fm, s = _text_metrics(size_mm, bold, family)
    return (fm.ascent() + fm.descent() + (n - 1) * fm.lineSpacing()) * s


def text_bg_span_mm(text: str, width_mm: float, size_mm: float,
                    bold: bool = False, family: str = "Sans Serif") -> tuple:
    """``(y0, y1)`` of a background slab that hugs the LETTERS of *text*
    laid out from y = 0: a line box carries ~1 mm of air above the
    capitals at 11 pt, so a slab hugging the box read as a wide band above
    and below the words (Marco, 2026-09-14: «arriba y abajo… reducirlo
    más»). Measured against the painter: the slab starts 0.25 × the size
    above the capitals (room for accents) and ends 0.05 × the size under
    the last line's descent."""
    n = _line_count(text, width_mm, size_mm, bold, family)
    fm, s = _text_metrics(size_mm, bold, family)
    if n == 0:
        return 0.0, size_mm
    y0 = (fm.ascent() - fm.capHeight()) * s - 0.25 * size_mm
    y1 = (fm.ascent() + fm.descent() + (n - 1) * fm.lineSpacing()) * s + 0.05 * size_mm
    return y0, y1


def _label_block_h(et: EtiquetaItem) -> float:
    """The label's inked height: the wrapped lines as painted, plus a hair.
    The model's ``h_mm`` (1.4 × size per line, 6 mm floor) is a generous
    guess that left a blank band under every label's background — the
    three-line «Escultura de campesino con pedestal» sat on 4 mm of empty
    white (Marco, 2026-09-14: «ese fondo blanco… ocupa mucho espacio»)."""
    size_mm = et.size_pt * PT_TO_MM
    h = _laid_out_height_mm(expand_fields(et.text), float(et.w_mm), size_mm,
                            et.bold)
    return max(size_mm * 1.15, h)


def etiqueta_ink_w_mm(et: EtiquetaItem) -> float:
    """The width the label's text actually inks, capped at the block: the
    leader starts at the TEXT, not at the far edge of a block much wider
    than its two words (Marco, 2026-09-08: «¿por qué no me sale la línea
    hasta el texto?» — a 50 mm block around «farola ornamental»)."""
    text = expand_fields(et.text)
    size_mm = et.size_pt * PT_TO_MM
    widest = max((_text_width_mm(line, size_mm, et.bold)
                  for line in text.split("\n")), default=0.0)
    return max(2.0, min(float(et.w_mm), widest + 0.2))


def etiqueta_bg_rect_mm(et: EtiquetaItem) -> QRectF:
    """The label's background slab: the inked text plus the side pad,
    hugging the letters top and bottom — ``w_mm`` stays the WRAP width,
    not the painted one."""
    y0, y1 = text_bg_span_mm(expand_fields(et.text), float(et.w_mm),
                             et.size_pt * PT_TO_MM, et.bold)
    return QRectF(-TEXT_BG_PAD_MM, y0,
                  etiqueta_ink_w_mm(et) + 2 * TEXT_BG_PAD_MM, max(1.0, y1 - y0))


def etiqueta_leader_start(et: EtiquetaItem, spot=None) -> tuple:
    """Where a leader leaves the text: the midpoint of the text box's
    edge that faces the pointed-at spot (the first one, or ``spot`` =
    ``(ax_mm, ay_mm)`` of an extra leader)."""
    ax, ay = (et.ax_mm, et.ay_mm) if spot is None else spot
    tw, h = etiqueta_ink_w_mm(et), _label_block_h(et)
    cx, cy = tw / 2, h / 2
    if ax < 0:
        return -0.8, cy
    if ax > tw:
        return tw + 0.8, cy
    if ay < 0:
        return cx, -0.8
    return cx, h + 0.8


def paint_etiqueta_mm(painter: QPainter, et: EtiquetaItem) -> None:
    """Label with a leader: the text block at the origin, a line from the
    text's nearest edge midpoint to the pointed-at spot, arrow head there."""
    import math as _math
    from PySide6.QtGui import QBrush, QPolygonF
    text = expand_fields(et.text)
    size_mm = et.size_pt * PT_TO_MM
    h = _label_block_h(et)
    color = QColor(et.color)
    pen = QPen(color)
    pen.setWidthF(et.stroke_mm)
    pen.setCapStyle(Qt.RoundCap)
    # One leader per pointed-at spot: the first, then the extra ones (a
    # multileader — «BUZÓN» naming three manholes with one word).
    dot_r = max(0.45, et.stroke_mm * 1.8) if getattr(et, "dot", True) else 0.0
    for ax, ay in et.spots():
        sx, sy = etiqueta_leader_start(et, (ax, ay))
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawLine(QPointF(sx, sy), QPointF(ax, ay))
        if dot_r:
            painter.save()
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(color))
            painter.drawEllipse(QPointF(sx, sy), dot_r, dot_r)
            painter.restore()
        if et.arrow:
            ang = _math.atan2(sy - ay, sx - ax)        # from the tip back
            L = max(1.8, et.stroke_mm * 7)
            base = _math.radians(14)
            painter.save()
            painter.setBrush(QBrush(color))
            painter.setPen(Qt.NoPen)
            painter.drawPolygon(QPolygonF([
                QPointF(ax, ay),
                QPointF(ax + L * _math.cos(ang + base), ay + L * _math.sin(ang + base)),
                QPointF(ax + L * _math.cos(ang - base), ay + L * _math.sin(ang - base))]))
            painter.restore()
    bg = et.bg_color or ""
    if bg:
        # The background hugs the inked text (like the leader does), not
        # the 50 mm wrap box: a one-word label used to sit in a wide white
        # slab that blanked the drawing beside it (Marco, 2026-09-14,
        # «BUZÓN» on the plaza sheet).
        painter.save()
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(_with_opacity(bg, et.bg_opacity)))
        painter.drawRect(etiqueta_bg_rect_mm(et))
        painter.restore()
    _draw_text_mm(painter, QRectF(0, 0, et.w_mm, h + size_mm), text, size_mm,
                  et.bold, align=Qt.AlignLeft | Qt.AlignTop, color=color,
                  italic=getattr(et, "italic", False),
                  underline=getattr(et, "underline", False))


def nivel_text_x_mm(nv: NivelItem) -> float:
    """Where the label starts along the level line: past the symbol."""
    s = nv.symbol_mm
    return (s / 2.0 if nv.symbol == "circle" else s / 2.0) + 0.6


def nivel_line_mm(nv: NivelItem) -> float:
    """The level line's drawn length: the set length, or longer when the
    label needs it — a bigger text (or a long prefix) must never wrap onto
    a second line and lose its top half (Marco, 2026-09-08: «cuando
    aumento el tamaño de la letra de NPT se distorsiona»)."""
    need = nivel_text_x_mm(nv) + _text_width_mm(nv.label(), nv.size_mm) + 1.0
    return max(float(nv.line_mm), need)


def nivel_bounds_mm(nv: NivelItem) -> QRectF:
    """The mark's ink box in item space (the apex at the origin)."""
    s = nv.symbol_mm
    sign = -1.0 if nv.mirror else 1.0
    text_h = nv.size_mm * 1.4
    line = nivel_line_mm(nv)
    x0 = min(-s / 2.0, sign * (line + 0.5), nv.ax_mm, 0.0)
    x1 = max(s / 2.0, sign * (line + 0.5), nv.ax_mm, 0.0)
    if nv.symbol == "circle":
        y0 = min(-s / 2.0 - text_h, nv.ay_mm)
        y1 = max(s / 2.0, nv.ay_mm)
    else:
        y0 = min(-s - text_h, nv.ay_mm)
        y1 = max(0.5, nv.ay_mm)
    return QRectF(x0 - 0.5, y0 - 0.5, x1 - x0 + 1.0, y1 - y0 + 1.0)


def paint_nivel_mm(painter: QPainter, nv: NivelItem) -> None:
    """Level mark: the symbol on its point, the level line from it and the
    value above the line («N.P.T. +0.15»); a hair-thin leader from the
    model point when the mark was slid away from it."""
    import math as _math
    from PySide6.QtGui import QBrush, QPainterPath, QPolygonF
    color = QColor(nv.color)
    pen = QPen(color)
    pen.setWidthF(nv.stroke_mm)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    s = nv.symbol_mm
    sign = -1.0 if nv.mirror else 1.0
    if _math.hypot(nv.ax_mm, nv.ay_mm) > 0.3:
        thin = QPen(color)
        thin.setWidthF(max(0.1, nv.stroke_mm * 0.5))
        painter.setPen(thin)
        painter.drawLine(QPointF(nv.ax_mm, nv.ay_mm), QPointF(0.0, 0.0))
        painter.setPen(pen)
    if nv.symbol == "circle":
        # the plan symbol: a circle with two opposite quadrants filled
        r = s / 2.0
        painter.drawEllipse(QPointF(0.0, 0.0), r, r)
        path = QPainterPath()
        for start in (0.0, 180.0):
            path.moveTo(0.0, 0.0)
            path.arcTo(QRectF(-r, -r, 2 * r, 2 * r), start, 90.0)
            path.closeSubpath()
        painter.fillPath(path, QBrush(color))
        line_y = -r
        text_x = sign * (r + 0.6)
    else:
        # the section symbol: an open triangle standing on its apex
        half = s / 2.0
        hgt = s * 0.866
        painter.drawPolygon(QPolygonF([QPointF(0.0, 0.0),
                                       QPointF(-half, -hgt),
                                       QPointF(half, -hgt)]))
        line_y = -hgt
        text_x = sign * (half + 0.6)
    line = nivel_line_mm(nv)                 # grows with the label
    painter.drawLine(QPointF(0.0, line_y), QPointF(sign * line, line_y))
    text_h = nv.size_mm * 1.4
    if nv.mirror:
        rect = QRectF(-line, line_y - text_h, line - abs(text_x), text_h)
        align = Qt.AlignRight | Qt.AlignBottom
    else:
        rect = QRectF(text_x, line_y - text_h, line - text_x, text_h)
        align = Qt.AlignLeft | Qt.AlignBottom
    _draw_text_mm(painter, rect, nv.label(), nv.size_mm, bold=False,
                  align=align, color=color)


def llamada_bounds_mm(ll: LlamadaItem) -> QRectF:
    """Box ∪ bubble, in item space (the box's top-left at the origin)."""
    r = ll.bubble_mm / 2.0
    x0 = min(0.0, ll.bx_mm - r)
    y0 = min(0.0, ll.by_mm - r)
    x1 = max(ll.w_mm, ll.bx_mm + r)
    y1 = max(ll.h_mm, ll.by_mm + r)
    return QRectF(x0 - 1.0, y0 - 1.0, x1 - x0 + 2.0, y1 - y0 + 2.0)


def _llamada_leader(ll: LlamadaItem):
    """Endpoints of the leader: the box outline's point nearest the bubble
    and the bubble edge facing it (None when the bubble sits inside)."""
    import math as _math
    cx, cy = ll.bx_mm, ll.by_mm
    if ll.shape == "circle":
        ox, oy = ll.w_mm / 2.0, ll.h_mm / 2.0
        rx, ry = ll.w_mm / 2.0, ll.h_mm / 2.0
        dx, dy = cx - ox, cy - oy
        # inside the ellipse: no leader
        if rx > 1e-9 and ry > 1e-9 and (dx / rx) ** 2 + (dy / ry) ** 2 <= 1.0:
            return None
        ang = _math.atan2(dy / max(ry, 1e-9), dx / max(rx, 1e-9))
        px, py = ox + rx * _math.cos(ang), oy + ry * _math.sin(ang)
    else:
        if 0.0 <= cx <= ll.w_mm and 0.0 <= cy <= ll.h_mm:
            return None
        px = min(max(cx, 0.0), ll.w_mm)
        py = min(max(cy, 0.0), ll.h_mm)
    dx, dy = cx - px, cy - py
    ln = _math.hypot(dx, dy)
    r = ll.bubble_mm / 2.0
    if ln <= r + 0.3:
        return None
    return (px, py, cx - dx / ln * r, cy - dy / ln * r)


def paint_llamada_mm(painter: QPainter, ll: LlamadaItem) -> None:
    """Detail callout: the dashed box or circle, the leader, the bubble
    («3» over «L-05»)."""
    color = QColor(ll.color)
    pen = QPen(color)
    pen.setWidthF(ll.stroke_mm)
    pen.setDashPattern([6.0, 3.0])
    pen.setCapStyle(Qt.FlatCap)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    box = QRectF(0.0, 0.0, ll.w_mm, ll.h_mm)
    if ll.shape == "circle":
        painter.drawEllipse(box)
    else:
        painter.drawRoundedRect(box, 1.5, 1.5)
    leader = _llamada_leader(ll)
    solid = QPen(color)
    solid.setWidthF(ll.stroke_mm)
    painter.setPen(solid)
    if leader is not None:
        painter.drawLine(QPointF(leader[0], leader[1]),
                         QPointF(leader[2], leader[3]))
    from core.composition import expand_fields
    number = expand_fields(ll.number or "", ll.frame_uid or "")
    sheet = expand_fields(ll.sheet or "", ll.frame_uid or "")
    _paint_title_bubble(painter, ll.bx_mm, ll.by_mm, ll.bubble_mm,
                        number, sheet, color)


def paint_cota_angular_mm(painter: QPainter, ca: CotaAngularItem) -> None:
    """Angular dimension: two rays from the vertex to the measured points
    (extended to the arc when shorter), the arc at ``radius_mm`` with
    arrows / ticks, and the angle label outside its middle."""
    import math as _math
    from PySide6.QtGui import QBrush, QPainterPath, QPolygonF
    color = QColor(ca.color)
    pen = QPen(color)
    pen.setWidthF(ca.stroke_mm)
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    a0, sweep = ca.angles()
    R = max(ca.radius_mm, 1.0)
    for px, py in ((ca.ax_mm, ca.ay_mm), (ca.bx_mm, ca.by_mm)):
        length = _math.hypot(px, py)
        if length < 1e-9:
            continue
        reach = max(length, R + 1.2)
        painter.drawLine(QPointF(0, 0), QPointF(px / length * reach,
                                                py / length * reach))
    rect = QRectF(-R, -R, 2 * R, 2 * R)
    path = QPainterPath()
    path.arcMoveTo(rect, -_math.degrees(a0))
    path.arcTo(rect, -_math.degrees(a0), -_math.degrees(sweep))
    painter.drawPath(path)
    a1 = a0 + sweep
    sgn = 1.0 if sweep >= 0 else -1.0
    ends = [(a0, sgn), (a1, -sgn)]           # (angle, direction into the arc)
    if ca.ends == "arrow":
        L = max(1.8, ca.stroke_mm * 6)
        painter.save()
        painter.setBrush(QBrush(color))
        painter.setPen(Qt.NoPen)
        for ang, d in ends:
            tip = QPointF(R * _math.cos(ang), R * _math.sin(ang))
            heading = _math.atan2(d * _math.cos(ang), -d * _math.sin(ang))
            base = _math.radians(12)
            painter.drawPolygon(QPolygonF([
                tip,
                QPointF(tip.x() + L * _math.cos(heading + base),
                        tip.y() + L * _math.sin(heading + base)),
                QPointF(tip.x() + L * _math.cos(heading - base),
                        tip.y() + L * _math.sin(heading - base))]))
        painter.restore()
    elif ca.ends != "none":
        tick = 1.6
        for ang, _d in ends:
            cx, cy = R * _math.cos(ang), R * _math.sin(ang)
            t = ang + _math.radians(45)
            painter.drawLine(QPointF(cx - tick * _math.cos(t),
                                     cy - tick * _math.sin(t)),
                             QPointF(cx + tick * _math.cos(t),
                                     cy + tick * _math.sin(t)))
    am = a0 + sweep / 2.0
    d = R + ca.offset_mm + ca.text_mm * 0.75
    lx, ly = d * _math.cos(am), d * _math.sin(am)
    tcol = QColor(ca.text_color) if ca.text_color else color
    label = ca.label()
    bg = getattr(ca, "text_bg", "") or ""
    if bg and label:
        tw = len(label) * ca.text_mm * 0.62 + 2.0
        painter.save()
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(_with_opacity(
            bg, getattr(ca, "text_bg_opacity", 1.0))))
        painter.drawRect(QRectF(lx - tw / 2, ly - ca.text_mm * 0.75, tw,
                                ca.text_mm * 1.5))
        painter.restore()
    _draw_text_mm(painter, QRectF(lx - 20, ly - ca.text_mm * 0.65, 40,
                                  ca.text_mm * 1.3),
                  label, ca.text_mm,
                  align=Qt.AlignHCenter | Qt.AlignVCenter, color=tcol)


def paint_cota_radial_mm(painter: QPainter, cr) -> None:
    """Radius / diameter dimension, to Rafael's reference sheet.

    The line always reaches the centre (rules 8, 12, 15). It fits → the
    words ride above its middle and the arrows point outward at the arc
    (rule 9). It does not → the line is prolonged past the arc, the words
    sit on that prolongation and the arrows point back AT the centre
    (rules 10, 14). The text never reads upside down, whatever quadrant it
    is in, because it turns by :func:`readable_deg` (rule 13)."""
    import math as _math
    from PySide6.QtGui import QBrush, QPolygonF
    color = QColor(cr.color)
    pen = QPen(color)
    pen.setWidthF(cr.stroke_mm)
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    (ax, ay), (bx, by) = cr.line_points()
    tx, ty = cr.tail_end()
    out = cr.outside()
    painter.drawLine(QPointF(ax, ay), QPointF(bx, by))
    if out:                                   # «la línea se prolonga»
        painter.drawLine(QPointF(bx, by), QPointF(tx, ty))
    if cr.centre_mark:                        # the centre it measures from
        m = max(1.0, cr.text_mm * 0.45)
        painter.drawLine(QPointF(-m, 0.0), QPointF(m, 0.0))
        painter.drawLine(QPointF(0.0, -m), QPointF(0.0, m))
    ux, uy = cr.heading()
    # (tip, heading) per arrow: outward at the arc when the words are
    # inside, back toward the centre when they are out.
    tips = [((bx, by), (-ux, -uy) if out else (ux, uy))]
    if cr.kind == "diameter":
        tips.append(((ax, ay), (ux, uy) if out else (-ux, -uy)))
    if cr.ends == "arrow":
        L = max(1.8, cr.stroke_mm * 6)
        base = _math.radians(12)
        painter.save()
        painter.setBrush(QBrush(color))
        painter.setPen(Qt.NoPen)
        for (px, py), (hx, hy) in tips:
            head = _math.atan2(hy, hx) + _math.pi   # the wings trail behind
            tip = QPointF(px, py)
            painter.drawPolygon(QPolygonF([
                tip,
                QPointF(tip.x() + L * _math.cos(head + base),
                        tip.y() + L * _math.sin(head + base)),
                QPointF(tip.x() + L * _math.cos(head - base),
                        tip.y() + L * _math.sin(head - base))]))
        painter.restore()
    elif cr.ends != "none":
        t = 1.6
        ang = _math.atan2(uy, ux) + _math.radians(45)
        for (px, py), _h in tips:
            painter.drawLine(
                QPointF(px - t * _math.cos(ang), py - t * _math.sin(ang)),
                QPointF(px + t * _math.cos(ang), py + t * _math.sin(ang)))
    lx, ly = cr.text_anchor()
    label = cr.label()
    tcol = QColor(cr.text_color) if cr.text_color else color
    painter.save()
    painter.translate(lx, ly)
    painter.rotate(readable_deg(ux, uy))       # rule 13, for free
    rect = text_baseline_rect_mm(cr.text_mm, -cr.offset_mm)
    bg = getattr(cr, "text_bg", "") or ""
    if bg and label:
        tw = cr.label_width_mm()
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(_with_opacity(
            bg, getattr(cr, "text_bg_opacity", 1.0))))
        painter.drawRect(QRectF(-tw / 2, rect.top() - 0.4, tw,
                                rect.height() + 0.8))
    _draw_text_mm(painter, rect, label, cr.text_mm,
                  align=Qt.AlignHCenter | Qt.AlignTop, color=tcol)
    painter.restore()


#: Margin of a text / label background around the inked words. 1 mm read
#: as a wide slab around a one-word label at plan scale (Marco, 2026-09-14:
#: «sigue viéndose ancho»); 0.5 mm is a hair of paper, enough to lift the
#: words off the drawing.
TEXT_BG_PAD_MM = 0.5


def _with_opacity(color: str, opacity) -> QColor:
    c = QColor(color)
    try:
        c.setAlphaF(max(0.0, min(1.0, float(opacity))))
    except (TypeError, ValueError):
        pass
    return c


def paint_sheet_border_mm(painter: QPainter, comp) -> None:
    """The sheet's border on the margin rectangle: width, colour, rounded
    corners and line type (single / double / dashed)."""
    if not getattr(comp, "border", False):
        return
    pw, ph = comp.page_size_mm()
    m = comp.margin_mm
    r = QRectF(m, m, pw - 2 * m, ph - 2 * m)
    width = max(0.1, float(comp.border_mm))
    radius = max(0.0, float(comp.border_radius_mm))
    pen = QPen(QColor(comp.border_color), width)
    if comp.border_style == "dashed":
        pen.setStyle(Qt.DashLine)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.save()
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)

    def rect_path(rr):
        if radius > 0.01:
            painter.drawRoundedRect(rr, radius, radius)
        else:
            painter.drawRect(rr)
    rect_path(r)
    if comp.border_style == "double":
        inset = width * 2.0 + 1.5
        pen2 = QPen(QColor(comp.border_color), max(0.1, width * 0.5))
        pen2.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen2)
        rect_path(r.adjusted(inset, inset, -inset, -inset))
    painter.restore()


def paint_text_mm(painter: QPainter, item: TextoItem) -> None:
    size_mm = item.size_pt * PT_TO_MM
    text = expand_fields(item.text, getattr(item, "frame_uid", "") or "")
    bg = getattr(item, "bg_color", "") or ""
    if bg:
        # The fill is as tall as the wrapped words really are (auto-wrapped
        # lines included — the old line count saw only typed newlines, so
        # a wrapped block's fill fell short while a one-liner's sat on a
        # blank band; Marco, 2026-09-14).
        y0, y1 = text_bg_span_mm(text, float(item.w_mm), size_mm, item.bold,
                                 getattr(item, "family", "") or "Sans Serif")
        painter.save()
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(_with_opacity(
            bg, getattr(item, "bg_opacity", 1.0))))
        painter.drawRect(QRectF(-TEXT_BG_PAD_MM, y0,
                                item.w_mm + 2 * TEXT_BG_PAD_MM,
                                max(1.0, y1 - y0)))
        painter.restore()
    rect = QRectF(0, 0, item.w_mm, size_mm * 1.35 * (text.count("\n") + 3))
    align = {"left": Qt.AlignLeft, "center": Qt.AlignHCenter,
             "right": Qt.AlignRight}.get(item.align, Qt.AlignLeft)
    _draw_text_mm(painter, rect, text, size_mm, item.bold,
                  align=align | Qt.AlignTop, color=QColor(item.color),
                  italic=item.italic, family=item.family,
                  underline=getattr(item, "underline", False))


#: Composited images (shape, feather, opacity, fit applied), keyed by the
#: source's cacheKey and the presentation fields — a drag repaints the
#: canvas many times a second, and the mask is NumPy work per pixel.
_IMG_COMPOSITE_CACHE: dict = {}
_IMG_COMPOSITE_MAX = 24
_IMG_COMPOSITE_PX = 2048           # longest side of a composite


def _shape_alpha(W: int, H: int, shape: str, radius_px: float,
                 feather_px: float):
    """Per-pixel alpha (H, W) of the cut-out: 1 inside, 0 outside, with a
    smooth fade ``feather_px`` wide inward from the outline (or a 1 px
    anti-aliased edge when there is no feather)."""
    import numpy as np
    ys, xs = np.mgrid[0:H, 0:W].astype(np.float64)
    xs += 0.5
    ys += 0.5
    if shape == "ellipse":
        a, b = W / 2.0, H / 2.0
        dx, dy = xs - a, ys - b
        nd = np.sqrt((dx / a) ** 2 + (dy / b) ** 2)      # 1 on the outline
        ang = np.arctan2(dy, dx)
        r_dir = 1.0 / np.sqrt((np.cos(ang) / a) ** 2 + (np.sin(ang) / b) ** 2)
        dist = (1.0 - nd) * r_dir                          # px inside (+)
    else:
        r = max(0.0, min(radius_px if shape == "rounded" else 0.0,
                         W / 2.0, H / 2.0))
        qx = np.abs(xs - W / 2.0) - (W / 2.0 - r)
        qy = np.abs(ys - H / 2.0) - (H / 2.0 - r)
        outside = np.sqrt(np.maximum(qx, 0.0) ** 2 + np.maximum(qy, 0.0) ** 2)
        inside = np.minimum(np.maximum(qx, qy), 0.0)
        dist = -(outside + inside - r)
    if feather_px <= 0.5:
        return np.clip(dist + 0.5, 0.0, 1.0)
    t = np.clip(dist / feather_px, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)                          # smoothstep


def composited_image(image: QImage, item: ImagenItem) -> QImage:
    """*image* as the sheet shows it: cropped or letterboxed per ``fit`` to
    the box's aspect, cut to ``shape`` with a ``feather_mm`` fade, at
    ``opacity``. Plain rect / no feather / opaque = the image itself."""
    shape = getattr(item, "shape", "rect") or "rect"
    feather = float(getattr(item, "feather_mm", 0.0) or 0.0)
    opacity = float(getattr(item, "opacity", 1.0))
    fit = getattr(item, "fit", "stretch") or "stretch"
    plain = (shape == "rect" and feather <= 0.0 and opacity >= 1.0
             and fit == "stretch")
    if plain or image is None or image.isNull() or item.w_mm <= 0 \
            or item.h_mm <= 0:
        return image
    key = (image.cacheKey(), shape, round(float(item.radius_mm), 3),
           round(feather, 3), fit, round(opacity, 3),
           round(item.w_mm / item.h_mm, 4), round(item.w_mm, 2))
    hit = _IMG_COMPOSITE_CACHE.get(key)
    if hit is not None:
        return hit
    import numpy as np
    aspect = item.w_mm / item.h_mm
    sw, sh = float(image.width()), float(image.height())
    src = QRectF(0.0, 0.0, sw, sh)
    if fit == "cover":
        if sw / sh > aspect:
            cw = sh * aspect
            src = QRectF((sw - cw) / 2.0, 0.0, cw, sh)
        else:
            ch = sw / aspect
            src = QRectF(0.0, (sh - ch) / 2.0, sw, ch)
        W, H = src.width(), src.height()
    elif fit == "contain":
        W, H = (sw, sw / aspect) if sw / sh > aspect else (sh * aspect, sh)
    else:
        W, H = sw, sw / aspect
    m = min(1.0, _IMG_COMPOSITE_PX / max(W, H, 1.0))
    W, H = max(1, int(round(W * m))), max(1, int(round(H * m)))
    out = QImage(W, H, QImage.Format_ARGB32)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.SmoothPixmapTransform, True)
    if fit == "contain":
        k = min(W / sw, H / sh)
        dw, dh = sw * k, sh * k
        dest = QRectF((W - dw) / 2.0, (H - dh) / 2.0, dw, dh)
    else:
        dest = QRectF(0.0, 0.0, float(W), float(H))
    p.drawImage(dest, image, src)
    p.end()
    px_per_mm = W / item.w_mm
    alpha = _shape_alpha(W, H, shape,
                         float(item.radius_mm) * px_per_mm,
                         feather * px_per_mm) * max(0.0, min(1.0, opacity))
    buf = np.frombuffer(out.bits(), np.uint8).reshape(H, W, 4)
    buf[:, :, 3] = np.clip(buf[:, :, 3].astype(np.float64) * alpha, 0,
                           255).astype(np.uint8)
    if len(_IMG_COMPOSITE_CACHE) >= _IMG_COMPOSITE_MAX:
        _IMG_COMPOSITE_CACHE.pop(next(iter(_IMG_COMPOSITE_CACHE)))
    _IMG_COMPOSITE_CACHE[key] = out
    return out


def image_outline_path(item: ImagenItem):
    """The cut-out's outline in item mm — the border, the selection."""
    from PySide6.QtGui import QPainterPath
    shape = getattr(item, "shape", "rect") or "rect"
    r = QRectF(0, 0, item.w_mm, item.h_mm)
    path = QPainterPath()
    if shape == "ellipse":
        path.addEllipse(r)
    elif shape == "rounded":
        rad = max(0.0, min(float(getattr(item, "radius_mm", 0.0) or 0.0),
                           item.w_mm / 2.0, item.h_mm / 2.0))
        path.addRoundedRect(r, rad, rad)
    else:
        path.addRect(r)
    return path


def paint_image_mm(painter: QPainter, item: ImagenItem,
                   image: Optional[QImage]) -> None:
    r = QRectF(0, 0, item.w_mm, item.h_mm)
    if image is not None and not image.isNull():
        painter.save()
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.drawImage(r, composited_image(image, item))
        painter.restore()
        if getattr(item, "border", False):
            pen = QPen(QColor(getattr(item, "border_color", "#282e36")))
            pen.setWidthF(max(0.1, float(getattr(item, "border_mm", 0.3))))
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(image_outline_path(item))
    else:
        painter.fillRect(r, QColor(240, 240, 242))
        pen = QPen(QColor(170, 176, 184))
        pen.setWidthF(0.25)
        painter.setPen(pen)
        painter.drawRect(r)
        painter.drawLine(r.topLeft(), r.bottomRight())
        painter.drawLine(r.topRight(), r.bottomLeft())


def _outline_path(w: float, h: float, corner: str, r: float):
    """The title block's outline: square, rounded or chamfered corners."""
    from PySide6.QtGui import QPainterPath
    r = max(0.0, min(float(r or 0.0), w / 2.0, h / 2.0))
    path = QPainterPath()
    if corner == "rounded" and r > 0:
        path.addRoundedRect(QRectF(0, 0, w, h), r, r)
    elif corner == "chamfer" and r > 0:
        pts = [(r, 0), (w - r, 0), (w, r), (w, h - r), (w - r, h), (r, h),
               (0, h - r), (0, r)]
        path.moveTo(QPointF(*pts[0]))
        for p in pts[1:]:
            path.lineTo(QPointF(*p))
        path.closeSubpath()
    else:
        path.addRect(QRectF(0, 0, w, h))
    return path


def cajetin_outline(c: Cajetin):
    return _outline_path(c.w_mm, c.h_mm, getattr(c, "corner", "square"),
                         getattr(c, "radius_mm", 0.0))


def paint_cajetin_mm(painter: QPainter, c: Cajetin) -> None:
    """The title block in its design: the outline shape (square / rounded /
    chamfered, optionally doubled), then the rows as a labelled grid, a
    header band over a grid, or a line-free minimal layout."""
    import math as _math
    w, h = c.w_mm, c.h_mm
    outline = cajetin_outline(c)
    corner = getattr(c, "corner", "square") or "square"
    layout = getattr(c, "layout", "grid") or "grid"
    fill = getattr(c, "fill_color", "") or ""
    line_color = QColor(getattr(c, "line_color", "") or "#1e242c")
    label_color = QColor(getattr(c, "label_color", "") or "#5a626c")
    text_color = QColor(getattr(c, "text_color", "") or "#1e242c")
    heavy = QPen(line_color)
    heavy.setWidthF(c.border_mm)
    light = QPen(line_color)
    light.setWidthF(c.line_mm)
    campos = c.campos or [[label, getattr(c, attr)]
                          for label, attr in Cajetin.FIELDS]
    # Dynamic fields in the values; an empty ESCALA row reads the sheet's
    # main frame by itself (the title block that never lies about scale).
    expanded = []
    for label, value in campos:
        v = expand_fields(str(value or ""))
        if not v and str(label).strip().lower() in ("escala", "scale"):
            v = expand_fields("{escala}")
        expanded.append([label, v])
    campos = expanded

    painter.save()
    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(QColor(255, 255, 255)))
    painter.drawPath(outline)
    painter.setClipPath(outline)          # fills and lines stay in shape

    band, rest = (None, campos)
    if layout == "banded" and len(campos) > 1:
        band, rest = campos[0], campos[1:]
    band_h = 0.0
    if band is not None:
        band_h = h * 1.5 / (len(rest) + 1.5)
        if fill:
            painter.fillRect(QRectF(0, 0, w, band_h), QColor(fill))
        painter.setPen(light)
        painter.drawLine(QPointF(0, band_h), QPointF(w, band_h))
        lrect = QRectF(1.5, 0.4, w - 3.0, band_h * 0.32)
        _draw_text_mm(painter, lrect, str(band[0]), max(1.4, band_h * 0.2),
                      bold=True, align=Qt.AlignLeft | Qt.AlignTop,
                      color=label_color)
        vrect = QRectF(1.5, band_h * 0.3, w - 3.0, band_h * 0.68)
        vsize = _fit_text_size_mm(str(band[1]), vrect, band_h * 0.4,
                                  bold=True)
        _draw_text_mm(painter, vrect, str(band[1]), vsize, bold=True,
                      align=Qt.AlignHCenter | Qt.AlignVCenter,
                      color=text_color)
    y_top = band_h
    body_h = h - band_h
    cols = max(1, min(int(c.columns), max(1, len(rest))))
    per = max(1, _math.ceil(len(rest) / cols))
    col_w = w / cols
    label_mm = float(getattr(c, "label_mm", 0.0) or 0.0)
    label_w = (min(col_w * 0.6, label_mm) if label_mm > 0
               else min(28.0, col_w * 0.3))
    # Rows share the block's height, except where a value needs more of it
    # (see cajetin_row_heights): the row grows and the type stays readable.
    row_hs = cajetin_row_heights(rest, cols, per, body_h, col_w, label_w,
                                 layout)
    # The nominal type size of the block: what an EQUAL row would use. Every
    # value aims for it, so a grown row does not come out bigger than its
    # neighbours either — the whole point is one size across the block.
    base_h = body_h / per
    for k in range(cols):
        x0 = k * col_w
        chunk = rest[k * per:(k + 1) * per]
        if layout == "minimal":
            # no lines at all: a small label over its value, per cell
            y = y_top
            for j, (label, value) in enumerate(chunk):
                row_h = row_hs[j]
                lrect = QRectF(x0 + 1.5, y + 0.4, col_w - 3.0, row_h * 0.36)
                _draw_text_mm(painter, lrect, str(label),
                              max(1.4, base_h * 0.24), bold=True,
                              align=Qt.AlignLeft | Qt.AlignTop,
                              color=label_color)
                vrect = QRectF(x0 + 1.5, y + row_h * 0.36, col_w - 3.0,
                               row_h * 0.62)
                vsize = _fit_text_size_mm(str(value), vrect, base_h * 0.42)
                _draw_text_mm(painter, vrect, str(value), vsize,
                              align=Qt.AlignLeft | Qt.AlignVCenter,
                              color=text_color)
                y += row_h
            continue
        if fill:
            painter.fillRect(QRectF(x0, y_top, label_w, body_h), QColor(fill))
        painter.setPen(light)
        if k:
            painter.drawLine(QPointF(x0, y_top), QPointF(x0, h))
        painter.drawLine(QPointF(x0 + label_w, y_top),
                         QPointF(x0 + label_w, h))
        y = y_top
        for j, (label, value) in enumerate(chunk):
            row_h = row_hs[j]
            if j:
                painter.drawLine(QPointF(x0, y), QPointF(x0 + col_w, y))
            # Long content wraps to more lines inside its cell and only
            # shrinks when even wrapped — and even in the taller row it
            # earned — it does not fit.
            lrect = QRectF(x0 + 1.2, y + 0.5, label_w - 2, row_h - 1.0)
            lsize = _fit_text_size_mm(str(label), lrect, base_h * 0.38,
                                      bold=True)
            _draw_text_mm(painter, lrect, str(label), lsize, bold=True,
                          align=Qt.AlignLeft | Qt.AlignVCenter,
                          color=label_color)
            vrect = QRectF(x0 + label_w + 1.5, y + 0.5,
                           col_w - label_w - 3, row_h - 1.0)
            vsize = _fit_text_size_mm(str(value), vrect, base_h * 0.52)
            _draw_text_mm(painter, vrect, str(value), vsize,
                          align=Qt.AlignLeft | Qt.AlignVCenter,
                          color=text_color)
            y += row_h
    painter.restore()
    painter.setPen(heavy)
    painter.setBrush(Qt.NoBrush)
    painter.drawPath(outline)
    if getattr(c, "double_border", False):
        inset = 1.2
        inner = _outline_path(w - 2 * inset, h - 2 * inset, corner,
                              float(getattr(c, "radius_mm", 0.0) or 0.0) - inset)
        painter.save()
        painter.translate(inset, inset)
        painter.setPen(light)
        painter.drawPath(inner)
        painter.restore()

