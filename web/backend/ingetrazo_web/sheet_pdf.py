"""Headless, vector PDF output for native IngeTrazo sheet compositions.

The desktop composer owns a rich interactive canvas.  This module deliberately
keeps the web export path free of QWidget/OpenGL dependencies: it projects the
native hidden-line drawing into the sheet's exact millimetre coordinate space
and writes it with QtGui's PDF paint device.
"""
from __future__ import annotations

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QPageLayout, QPageSize,
                           QPainter, QPdfWriter, QPen, QPolygonF)

from core.camera import OrbitCamera
from core.composition import apply_frame_camera
from core.hlr import (KIND_CUT, KIND_EDGE, KIND_HIDDEN, KIND_PROFILE,
                      hlr_drawing)

PDF_DPI = 300
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}


def _saved_view(scene, frame):
    if not frame.view_key.startswith("scene:"):
        return None
    name = frame.view_key[6:]
    return next((view for view in scene.saved_views if view.name == name), None)


def _paper_point(frame, x: float, y: float) -> QPointF:
    model_h = frame.h_mm * frame.scale_n / 1000.0
    factor = frame.h_mm / model_h
    half_h = model_h / 2.0
    half_w = half_h * frame.w_mm / frame.h_mm
    return QPointF((x + half_w) * factor, (half_h - y) * factor)


def _drawing(scene, camera):
    """Exact HLR for ordinary sheets; bounded projected edges for huge ones."""
    import numpy as np
    from types import SimpleNamespace
    from core.hlr import _to_cam, camera_basis, collect_geometry

    triangles, hard, soft = collect_geometry(scene)
    if len(triangles) * max(1, len(hard) + len(soft)) <= 5_000_000:
        return hlr_drawing(scene, camera, profiles=True, fills=True, hidden=False)
    segments = []
    kinds = []
    for edges, kind in ((hard, KIND_EDGE),
                        ([(a, b) for a, b, _na, _nb in soft], KIND_PROFILE)):
        if not edges:
            continue
        world = np.asarray(edges, dtype=np.float64).reshape(-1, 2, 3)
        eye, right, up, forward = camera_basis(camera)
        projected = _to_cam(world.reshape(-1, 3), eye, right, up, forward)
        projected = projected.reshape(-1, 2, 3)
        segments.extend([
            [edge[0, 0], edge[0, 1], edge[1, 0], edge[1, 1]]
            for edge in projected
        ])
        kinds.extend([kind] * len(projected))
    return SimpleNamespace(
        segs=np.asarray(segments, dtype=np.float64).reshape(-1, 4),
        kinds=np.asarray(kinds, dtype=np.int8), loops=[],
    )


def _render_frame(painter: QPainter, scene, frame) -> None:
    camera = OrbitCamera()
    apply_frame_camera(camera, frame, _saved_view(scene, frame), scene)
    drawing = _drawing(scene, camera)
    bounds = QRectF(0, 0, frame.w_mm, frame.h_mm)
    painter.fillRect(bounds, Qt.white)
    painter.save()
    painter.setClipRect(bounds)
    for ring in drawing.loops:
        if len(ring) < 3:
            continue
        polygon = [_paper_point(frame, float(point[0]), float(point[1]))
                   for point in ring]
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor(frame.cut_fill_color)))
        painter.drawPolygon(QPolygonF(polygon))
    painter.setBrush(Qt.NoBrush)
    pens = {
        KIND_EDGE: QPen(QColor("#3a4148"), max(0.1, frame.pen_edge_mm)),
        KIND_PROFILE: QPen(QColor("#20262b"), max(0.1, frame.pen_profile_mm)),
        KIND_CUT: QPen(QColor("#15191d"), max(0.1, frame.pen_cut_mm)),
        KIND_HIDDEN: QPen(QColor("#606970"), max(0.1, frame.pen_edge_mm), Qt.DashLine),
    }
    for segment, kind in zip(drawing.segs, drawing.kinds):
        painter.setPen(pens.get(int(kind), pens[KIND_EDGE]))
        painter.drawLine(
            _paper_point(frame, float(segment[0]), float(segment[1])),
            _paper_point(frame, float(segment[2]), float(segment[3])),
        )
    painter.restore()
    if frame.border:
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor(frame.border_color), max(0.1, frame.border_mm)))
        painter.drawRect(bounds)


def _image_for(item):
    """The picture of an image item, read only if it is an ordinary image file."""
    from pathlib import Path

    from PySide6.QtGui import QImage
    path = Path(str(item.path or ""))
    try:
        if path.suffix.lower() not in _IMAGE_SUFFIXES or not path.is_file() or path.stat().st_size > 30_000_000:
            return None
    except OSError:
        return None
    image = QImage(str(path))
    return None if image.isNull() else image


def paint_sheet(painter: QPainter, scene, composition, *, index: int | None = None,
                total: int | None = None, frames: bool = True) -> None:
    """Draw one sheet in millimetres (the painter is already scaled), in stacking
    order, with the desktop composer's own painting routines for every item.

    ``frames=False`` draws each view frame as an outlined placeholder, for a fast
    preview while the exact vector drawing is still being prepared.
    """
    from core import composition as comp
    from core import sheet_paint as desktop

    comp.set_field_context(comp=composition, scene=scene, path=None, index=index, total=total)
    width, height = composition.page_size_mm()
    painter.fillRect(QRectF(0, 0, width, height), Qt.white)

    def paint(item) -> None:
        if isinstance(item, comp.MarcoVista):
            if frames:
                _render_frame(painter, scene, item)
            else:
                painter.fillRect(QRectF(0, 0, item.w_mm, item.h_mm), QColor("#f1f3f5"))
                painter.setPen(QPen(QColor("#9aa3ad"), 0.25, Qt.DashLine))
                painter.setBrush(Qt.NoBrush)
                painter.drawRect(QRectF(0, 0, item.w_mm, item.h_mm))
            desktop._paint_view_title_mm(painter, item)
            if item.show_scale:
                desktop._paint_scale_label_mm(painter, item)
        elif isinstance(item, comp.ImagenItem):
            desktop.paint_image_mm(painter, item, _image_for(item))
        elif isinstance(item, comp.TextoItem):
            desktop.paint_text_mm(painter, item)
        elif isinstance(item, comp.BarraEscala):
            desktop.paint_scalebar_mm(painter, item)
        elif isinstance(item, comp.FlechaNorte):
            desktop.paint_norte_mm(painter, item)
        elif isinstance(item, comp.Leyenda):
            desktop.paint_leyenda_mm(painter, item)
        elif isinstance(item, comp.FormaItem):
            desktop.paint_forma_mm(painter, item)
        elif isinstance(item, comp.CotaItem):
            desktop.paint_cota_mm(painter, item)
        elif isinstance(item, comp.CotaAngularItem):
            desktop.paint_cota_angular_mm(painter, item)
        elif isinstance(item, comp.CotaRadialItem):
            desktop.paint_cota_radial_mm(painter, item)
        elif isinstance(item, comp.EtiquetaItem):
            desktop.paint_etiqueta_mm(painter, item)
        elif isinstance(item, comp.NivelItem):
            desktop.paint_nivel_mm(painter, item)
        elif isinstance(item, comp.LlamadaItem):
            desktop.paint_llamada_mm(painter, item)
        elif isinstance(item, comp.Cajetin):
            desktop.paint_cajetin_mm(painter, item)
        # A terrain profile needs the survey sampling of the desktop window: not drawn here.

    for item in sorted(composition.all_items(), key=lambda it: getattr(it, "z", 0.0)):
        if getattr(item, "hidden", False):
            continue
        painter.save()
        painter.translate(item.x_mm, item.y_mm)
        try:
            paint(item)
        finally:
            painter.restore()
    desktop.paint_sheet_border_mm(painter, composition)


def render_sheet_pdf(scene, composition) -> bytes:
    """Return one exact-size, vector PDF page for ``composition``."""
    data = QByteArray()
    buffer = QBuffer(data)
    if not buffer.open(QIODevice.WriteOnly):
        raise OSError("could not open the PDF output buffer")
    writer = QPdfWriter(buffer)
    writer.setResolution(PDF_DPI)
    writer.setPageSize(QPageSize(getattr(QPageSize, composition.paper)))
    writer.setPageOrientation(
        QPageLayout.Landscape if composition.landscape else QPageLayout.Portrait,
    )
    writer.setTitle(composition.name)
    writer.setCreator("IngeTrazo Web")
    painter = QPainter(writer)
    if not painter.isActive():
        buffer.close()
        raise OSError("could not start the PDF painter")
    try:
        painter.scale(PDF_DPI / 25.4, PDF_DPI / 25.4)
        sheets = list(getattr(scene, "compositions", []) or [])
        paint_sheet(painter, scene, composition,
                    index=sheets.index(composition) if composition in sheets else None,
                    total=len(sheets))
    finally:
        painter.end()
        buffer.close()
    return bytes(data)


def render_sheet_png(scene, composition, dpi: int = 60, *, frames: bool = True) -> bytes:
    """The sheet as a PNG at ``dpi`` (the composer's page preview)."""
    from PySide6.QtGui import QImage

    width, height = composition.page_size_mm()
    pixels = (max(1, round(width * dpi / 25.4)), max(1, round(height * dpi / 25.4)))
    image = QImage(pixels[0], pixels[1], QImage.Format.Format_ARGB32)
    image.fill(Qt.white)
    painter = QPainter(image)
    try:
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        painter.scale(dpi / 25.4, dpi / 25.4)
        sheets = list(getattr(scene, "compositions", []) or [])
        paint_sheet(painter, scene, composition,
                    index=sheets.index(composition) if composition in sheets else None,
                    total=len(sheets), frames=frames)
    finally:
        painter.end()
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.WriteOnly)
    image.save(buffer, "PNG")
    buffer.close()
    return bytes(data)
