"""Typed request bodies for the command endpoints.

Each command is a pydantic model: field types, ranges and cross-field rules are
declared once, FastAPI validates before the handler runs, and a bad request answers
with the uniform error body (``errors.py``) naming the field and the limit. Models are
strict (``"3"`` is not a number, ``1`` is not ``true``) and refuse unknown fields, so a
misspelt setting is an error instead of being silently ignored.
"""
from __future__ import annotations

import math
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

LIMIT = 1_000_000.0

Revision = Annotated[int, Field(ge=1)]
Metre = Annotated[float, Field(ge=-LIMIT, le=LIMIT, allow_inf_nan=False)]
PositiveMetre = Annotated[float, Field(gt=0, le=LIMIT, allow_inf_nan=False)]
Fraction = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
Point3 = Annotated[list[Metre], Field(min_length=3, max_length=3)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
ObjectId = Annotated[str, Field(pattern=r"^group:\d+(/\d+)*$", max_length=255)]
TopLevelId = Annotated[str, Field(pattern=r"^group:\d+$", max_length=255)]


class Command(BaseModel):
    """Every command names the revision it was made against (optimistic concurrency)."""
    model_config = ConfigDict(extra="forbid", strict=True, populate_by_name=True)
    base_revision: Revision


class Targets(Command):
    """One object (``object_id``) or several (``object_ids``, which wins when given)."""
    object_id: ObjectId | None = None
    object_ids: Annotated[list[ObjectId], Field(min_length=1, max_length=500)] | None = None

    @model_validator(mode="after")
    def _one_or_many(self):
        if self.object_ids is None and self.object_id is None:
            raise ValueError("object_id (or object_ids) must identify an object")
        if self.object_ids is not None and len(set(self.object_ids)) != len(self.object_ids):
            raise ValueError("object_ids must list different objects")
        return self

    def ids(self) -> list[str]:
        return list(self.object_ids) if self.object_ids is not None else [self.object_id]


def _non_zero(point: list[float]) -> list[float]:
    if all(value == 0 for value in point):
        raise ValueError("must not be all zero")
    return point


# --- presentation and objects -------------------------------------------------

class Presentation(Command):
    layers: Annotated[dict[Annotated[str, Field(min_length=1, max_length=255)], bool], Field(max_length=256)] = {}
    hidden_objects: Annotated[dict[Annotated[str, Field(min_length=1, max_length=255)], bool], Field(max_length=1000)] = {}

    @model_validator(mode="after")
    def _something(self):
        if not self.layers and not self.hidden_objects:
            raise ValueError("at least one presentation change is required")
        return self


class LayerVisibility(Command):
    """The first, layer-only form of ``Presentation``."""
    changes: Annotated[dict[Annotated[str, Field(min_length=1, max_length=255)], bool], Field(min_length=1, max_length=256)]


class MoveObject(Targets):
    delta: Point3

    _delta = field_validator("delta")(_non_zero)


class TransformObject(Command):
    object_id: ObjectId
    operation: Literal["rotate", "scale"]
    axis: Literal["x", "y", "z"] | None = None
    degrees: Annotated[float, Field(ge=-360_000, le=360_000, allow_inf_nan=False)] | None = None
    factors: Annotated[list[Annotated[float, Field(allow_inf_nan=False)]], Field(min_length=3, max_length=3)] | None = None

    @model_validator(mode="after")
    def _by_operation(self):
        if self.operation == "rotate":
            if self.axis is None or self.degrees is None or self.degrees == 0:
                raise ValueError("rotate requires axis x, y or z and non-zero degrees")
        else:
            if self.factors is None or any(not 1e-9 <= abs(value) <= 10_000 for value in self.factors) \
                    or all(value == 1 for value in self.factors):
                raise ValueError("scale requires three non-zero factors (at most 10000) that are not all 1")
        return self


class CreateBox(Command):
    size: Annotated[list[PositiveMetre], Field(min_length=3, max_length=3)]
    origin: Point3 = [0.0, 0.0, 0.0]
    name: Name = "Box"


class ObjectLifecycle(Command):
    operation: Literal["duplicate", "delete", "rename"]
    object_id: ObjectId | None = None
    object_ids: Annotated[list[ObjectId], Field(min_length=1, max_length=500)] | None = None
    name: Name | None = None
    delta: Point3 = [0.0, 0.0, 0.0]

    @model_validator(mode="after")
    def _rules(self):
        if self.object_ids is not None:
            if self.operation != "delete":
                raise ValueError("object_ids is only supported for delete")
            if len(set(self.object_ids)) != len(self.object_ids):
                raise ValueError("object_ids must list different objects")
        elif self.object_id is None:
            raise ValueError("object_id must identify an object")
        if self.operation == "duplicate" and self.object_id is not None and "/" in self.object_id:
            raise ValueError("object_id must identify a top-level group to duplicate")
        if self.operation == "rename" and self.name is None:
            raise ValueError("name must contain 1-255 characters")
        return self


class ObjectMaterial(Targets):
    clear: bool = False
    color: Annotated[list[Fraction], Field(min_length=3, max_length=3)] | None = None
    opacity: Fraction = 1.0
    texture: Annotated[str, Field(max_length=255)] | None = None

    @model_validator(mode="after")
    def _paint(self):
        if not self.clear and self.texture is None and self.color is None:
            raise ValueError("color (three RGB values from 0 to 1) or texture is required unless clear is true")
        return self


class SetObjectScale(Command):
    """Take an object to an absolute scale along its own axes (1.0 is unscaled)."""
    object_id: ObjectId
    scale: Annotated[list[Annotated[float, Field(ge=1e-6, le=10_000, allow_inf_nan=False)]],
                     Field(min_length=3, max_length=3)]


class ObjectIfc(Command):
    object_id: ObjectId
    clear: bool = False
    ifc_class: str | None = Field(None, alias="class")
    name: Name | None = None

    @model_validator(mode="after")
    def _classified(self):
        from core.bim import IFC_CLASSES
        if not self.clear:
            if self.ifc_class not in IFC_CLASSES:
                raise ValueError("class must be a supported IFC class")
            if self.name is None:
                raise ValueError("name must contain 1-255 characters")
        return self


class RestoreRevision(Command):
    source_revision: Revision
    #: ``undo`` or ``redo`` when this restore is a step through the history (see revision_history.py).
    history: Literal["undo", "redo"] | None = None

    @model_validator(mode="after")
    def _different(self):
        if self.source_revision == self.base_revision and self.history is None:
            raise ValueError("source_revision: choose a different revision to restore")
        return self


# --- geo-reference, base maps, terrain, survey ------------------------------------

class SetGeoref(Command):
    latitude: Annotated[float, Field(ge=-90, le=90, allow_inf_nan=False)]
    longitude: Annotated[float, Field(ge=-180, le=180, allow_inf_nan=False)]
    altitude: Annotated[float, Field(ge=-20_000, le=20_000, allow_inf_nan=False)] = 0.0
    north: Annotated[float, Field(ge=-360_000, le=360_000, allow_inf_nan=False)] = 0.0


class SetMap(Command):
    clear: bool = False
    source: str = "esri_imagery"
    zoom: Annotated[int, Field(ge=1)] = 16
    radius: Annotated[float, Field(ge=10, le=100_000, allow_inf_nan=False)] = 1200.0
    opacity: Fraction = 0.85

    @model_validator(mode="after")
    def _source(self):
        if not self.clear:
            from georef.tiles import PRESETS
            if self.source not in PRESETS:
                raise ValueError("source must be a licensed built-in map source")
            if self.zoom > PRESETS[self.source].max_zoom:
                raise ValueError(f"zoom must be at most {PRESETS[self.source].max_zoom} for this source")
        return self


class ImportTerrain(Command):
    columns: Annotated[int, Field(ge=2, le=100)]
    text: Annotated[str, Field(min_length=1, max_length=2_000_000)]

    @field_validator("text")
    @classmethod
    def _rows(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must contain XYZ rows")
        return value


class ImportSurvey(Command):
    text: Annotated[str, Field(min_length=1, max_length=5_000_000)]
    zone: Annotated[int, Field(ge=1, le=60)] | None = None
    northern: bool | None = None

    @field_validator("text")
    @classmethod
    def _rows(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must contain survey rows")
        return value


class CreateGeoPath(Command):
    points: Annotated[list[Point3], Field(min_length=2, max_length=10_000)]
    closed: bool = False
    name: Name = "Path"
    surface: Literal["flat", "draped"] | None = None

    @model_validator(mode="after")
    def _closed(self):
        if self.closed and len(self.points) < 3:
            raise ValueError("closed needs at least three points")
        return self


# --- display, shadows, sheets ----------------------------------------------------------

class SetStyle(Command):
    name: str

    @field_validator("name")
    @classmethod
    def _known(cls, value: str) -> str:
        from core.style import style_by_name
        if style_by_name(value) is None:
            raise ValueError("must identify a built-in or saved display style")
        return value


class SetShadows(Command):
    enabled: bool
    month: Annotated[int, Field(ge=1, le=12)]
    day: Annotated[int, Field(ge=1, le=31)]
    hour: Annotated[int, Field(ge=0, le=23)]
    minute: Annotated[int, Field(ge=0, le=59)]
    darkness: Fraction
    utc_offset: Annotated[int, Field(ge=-14, le=14)] | None = None

    @model_validator(mode="after")
    def _real_date(self):
        from datetime import datetime
        try:
            datetime(2026, self.month, self.day, self.hour, self.minute)
        except ValueError as exc:
            raise ValueError("the shadow-study date is not a real date") from exc
        return self


class CreateSheet(Command):
    name: Name
    paper: Literal["A4", "A3", "A2", "A1", "A0"] = "A3"
    landscape: bool = True
    view: Annotated[str, Field(max_length=255)] = "top"
    scale: Annotated[float, Field(ge=0.1, le=100_000, allow_inf_nan=False)] = 100.0


# --- annotations ------------------------------------------------------------------------

LayerName = Annotated[str, Field(min_length=1, max_length=255)]


class DimensionIn(Command):
    operation: Literal["dimension"]
    a: Point3
    b: Point3
    offset: Point3
    axis: Literal["x", "y", "z"] | None = None
    text: Annotated[str, Field(max_length=1000)] | None = None
    layer: LayerName | None = None

    @model_validator(mode="after")
    def _apart(self):
        if math.dist(self.a, self.b) < 1e-9:
            raise ValueError("dimension endpoints must be different")
        return self


class TextIn(Command):
    operation: Literal["text"]
    anchor: Point3
    offset: Point3
    text: Annotated[str, Field(min_length=1, max_length=4000)]
    layer: LayerName | None = None

    @field_validator("text")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class GuideLineIn(Command):
    operation: Literal["guide-line"]
    point: Point3
    direction: Point3
    layer: LayerName | None = None

    @field_validator("direction")
    @classmethod
    def _non_zero_direction(cls, value: list[float]) -> list[float]:
        if math.hypot(*value) < 1e-9:
            raise ValueError("guide direction must be non-zero")
        return value


class GuidePointIn(Command):
    operation: Literal["guide-point"]
    point: Point3
    origin: Point3 | None = None
    layer: LayerName | None = None


Annotation = Annotated[Union[DimensionIn, TextIn, GuideLineIn, GuidePointIn], Field(discriminator="operation")]


# --- layers, sections, scenes -----------------------------------------------------------

class FlipObject(Command):
    object_id: TopLevelId
    axis: Literal["x", "y", "z"]
    copy_: bool = Field(False, alias="copy")        # "copy" is the wire name; it shadows BaseModel.copy


class SectionFill(Command):
    enabled: bool


class CreateLayer(Command):
    name: Name


class RenameLayer(Command):
    name: Name
    new_name: Name


class DeleteLayer(Command):
    name: Name


class SetLayerLock(Command):
    name: Name
    locked: bool


class AssignLayer(Command):
    object_id: TopLevelId
    layer: Name = "Layer 0"


class CreateSection(Command):
    point: Point3
    normal: Point3
    name: Name | None = None

    @field_validator("normal")
    @classmethod
    def _facing(cls, value: list[float]) -> list[float]:
        if math.hypot(*value) < 1e-9:
            raise ValueError("must be non-zero")
        return value


class SaveScene(Command):
    name: Name = "Scene"
    eye: Point3
    target: Point3
    fov_deg: Annotated[float, Field(ge=5, le=120, allow_inf_nan=False)] = 45.0
    perspective: bool = True

    @model_validator(mode="after")
    def _apart(self):
        if math.dist(self.eye, self.target) < 1e-6:
            raise ValueError("eye and target must differ")
        return self


class DeleteScene(Command):
    name: Name = "Scene"
    names: Annotated[list[Name], Field(min_length=1, max_length=1000)] | None = None


# --- loose geometry and groups being edited ------------------------------------------------

FaceNumber = Annotated[int, Field(ge=0, le=10_000_000)]
Edge = Annotated[list[Point3], Field(min_length=2, max_length=2)]


class LooseFaces(Command):
    """Faces of the loose geometry, or of the group named by ``object_id``."""
    face_indices: Annotated[list[FaceNumber], Field(min_length=1, max_length=50_000)]
    object_id: ObjectId | None = None


class LoosePushPull(Command):
    face_index: FaceNumber
    distance: Metre
    keep_base: bool = False
    object_id: ObjectId | None = None

    @field_validator("distance")
    @classmethod
    def _enough(cls, value: float) -> float:
        if abs(value) < 0.0002:
            raise ValueError("must be at least 0.2 mm")
        return value


class LoosePaint(LooseFaces):
    texture: Annotated[str, Field(max_length=255)] | None = None
    #: A material of the document itself (imported from .igmat or .skm), by name.
    material: Annotated[str, Field(min_length=1, max_length=255)] | None = None
    color: Annotated[list[Fraction], Field(min_length=3, max_length=3)] | None = None
    opacity: Fraction = 1.0

    @model_validator(mode="after")
    def _paint(self):
        if self.texture is None and self.color is None and self.material is None:
            raise ValueError("color (three RGB values from 0 to 1), texture or material is required")
        return self


class LooseMove(Command):
    delta: Point3
    face_indices: Annotated[list[FaceNumber], Field(min_length=1, max_length=50_000)] | None = None
    edges: Annotated[list[Edge], Field(min_length=1, max_length=10_000)] | None = None
    object_id: ObjectId | None = None

    @model_validator(mode="after")
    def _something_to_move(self):
        if max(abs(value) for value in self.delta) < 1e-6:
            raise ValueError("delta must not be zero")
        if self.face_indices is None and self.edges is None:
            raise ValueError("choose loose faces or edges to move")
        return self


class LooseEdgeErase(Command):
    edges: Annotated[list[Edge], Field(min_length=1, max_length=10_000)]
    object_id: ObjectId | None = None


class LooseBridge(Command):
    """Bridge: side faces between two profiles, each a loose face or a chain of loose edges."""
    face_indices: Annotated[list[FaceNumber], Field(max_length=2)] | None = None
    edges: Annotated[list[Edge], Field(max_length=10_000)] | None = None
    object_id: ObjectId | None = None


class LooseMakeFacesExtrude(Command):
    """Make Faces and Extrude: each loop the edges close becomes its own solid group."""
    edges: Annotated[list[Edge], Field(min_length=3, max_length=20_000)]
    height: Metre
    fill_holes: bool = False
    object_id: ObjectId | None = None


class SetCutOpening(Targets):
    """Mark or unmark windows and doors that cut their own hole in the wall they sit on."""
    on: bool = True


class TerrainCreate(Command):
    """Editable ground: a grid over a rectangle (``corner_a``/``corner_b``), a TIN through
    survey ``points``, or a ground through contour ``segments`` (each at its own height)."""
    corner_a: Point3 | None = None
    corner_b: Point3 | None = None
    cell: Annotated[float, Field(ge=0.05, le=1000, allow_inf_nan=False)] = 1.0
    relief: Annotated[float, Field(ge=0, le=1000, allow_inf_nan=False)] = 0.0
    points: Annotated[list[Point3], Field(min_length=3, max_length=200_000)] | None = None
    max_side: Annotated[float, Field(ge=0, le=1_000_000, allow_inf_nan=False)] = 0.0
    segments: Annotated[list[Edge], Field(min_length=1, max_length=200_000)] | None = None
    name: Name = "Terrain"

    @model_validator(mode="after")
    def _one_source(self):
        given = [self.points is not None, self.segments is not None,
                 self.corner_a is not None or self.corner_b is not None]
        if sum(given) != 1:
            raise ValueError("give corner_a and corner_b, points, or segments")
        if given[2] and (self.corner_a is None or self.corner_b is None):
            raise ValueError("a grid needs both corner_a and corner_b")
        return self


class TerrainDeform(Command):
    """Push the ground of a terrain object up (``height`` > 0) or down at ``center``."""
    object_id: ObjectId
    center: Point3
    radius: Annotated[float, Field(gt=0, le=100_000, allow_inf_nan=False)]
    height: Metre


class TerrainStamp(Command):
    """Cut a level platform the shape of ``footprint`` into a terrain object, with a slope out."""
    object_id: ObjectId
    footprint: Annotated[list[Point3], Field(min_length=3, max_length=10_000)]
    height: Metre
    slope: Annotated[float, Field(ge=0, le=100_000, allow_inf_nan=False)] = 2.0


class LooseResegment(Command):
    """Rebuild the circle, arc or polygon one of its edges belongs to with another segment count."""
    edge: Edge
    segments: Annotated[int, Field(ge=2, le=999)]
    object_id: ObjectId | None = None


class LooseEdgeJoin(Command):
    """Join Segments: the collinear pieces among these edges become one line."""
    edges: Annotated[list[Edge], Field(min_length=2, max_length=10_000)]
    object_id: ObjectId | None = None


class ExplodeObjects(Targets):
    """Groups to explode, top-level or nested (a nested one dissolves into its parent)."""


# --- the Parts section ----------------------------------------------------------------------

class PartsHide(Targets):
    hidden: bool


class SplitPieces(Command):
    object_id: TopLevelId


class ExplodeView(Command):
    object_id: ObjectId
    factor: Annotated[float, Field(ge=0, le=10, allow_inf_nan=False)]
    mode: Literal["outward", "x", "y", "z"] = "outward"


# --- placing library content ---------------------------------------------------------------

class InsertPerson(Command):
    person: str
    origin: Point3 = [0.0, 0.0, 0.0]


class InsertComponent(Command):
    component: str
    origin: Point3 = [0.0, 0.0, 0.0]


class InsertOnline(Command):
    model: str
    origin: Point3 = [0.0, 0.0, 0.0]


class InsertFaceMe(Command):
    image_base64: Annotated[str, Field(min_length=1, max_length=12_000_000)]
    height: Annotated[float, Field(ge=0.05, le=500, allow_inf_nan=False)] = 1.75
    origin: Point3 = [0.0, 0.0, 0.0]
    name: Annotated[str, Field(max_length=255)] | None = None


# --- sheets, extensions, exports --------------------------------------------------------------

class SheetEdit(Command):
    sheet_index: Annotated[int, Field(ge=0)]
    ops: Annotated[list["SheetOp"], Field(min_length=1, max_length=100)]


class DeleteSheet(Command):
    sheet_index: Annotated[int, Field(ge=0)]


class RunExtension(Command):
    extension: str
    params: dict[str, Any] | None = None


class ExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    format: str


class PushPullObject(Command):
    object_id: ObjectId
    direction: Literal["normal", "+x", "-x", "+y", "-y", "+z", "-z"] = "normal"
    distance: Metre
    keep_base: bool = False
    face_point: Point3 | None = None

    @field_validator("distance")
    @classmethod
    def _enough(cls, value: float) -> float:
        if abs(value) < 0.0002:
            raise ValueError("must be a non-zero metre value of at least 0.2 mm")
        return value


class OffsetFace(Command):
    object_id: TopLevelId
    distance: Metre

    @field_validator("distance")
    @classmethod
    def _non_zero(cls, value: float) -> float:
        if abs(value) < 1e-9:
            raise ValueError("must be a non-zero metre value")
        return value


# --- drawing: planar primitives and shapes --------------------------------------------------------

Plane = Literal["xy", "xz", "yz"]
Point2 = Annotated[list[Metre], Field(min_length=2, max_length=2)]
Degrees = Annotated[float, Field(ge=-360_000, le=360_000, allow_inf_nan=False)]
Tiny = 1e-6


class _Planar(Command):
    plane: Plane = "xy"
    origin: Point3 = [0.0, 0.0, 0.0]
    name: Name | None = None


class PlanarLine(_Planar):
    operation: Literal["line"]
    end: Point3

    @model_validator(mode="after")
    def _apart(self):
        if self.end == self.origin:
            raise ValueError("end must be a point different from origin")
        return self


class PlanarRectangle(_Planar):
    operation: Literal["rectangle"]
    size: Annotated[list[PositiveMetre], Field(min_length=2, max_length=2)]


class PlanarCircle(_Planar):
    operation: Literal["circle"]
    radius: PositiveMetre
    segments: Annotated[int, Field(ge=3, le=256)] = 24


class PlanarArc(_Planar):
    operation: Literal["arc"]
    radius: PositiveMetre
    start_degrees: Degrees = 0.0
    sweep_degrees: Annotated[float, Field(gt=-360, lt=360, allow_inf_nan=False)]
    segments: Annotated[int, Field(ge=2, le=256)] = 12

    @field_validator("sweep_degrees")
    @classmethod
    def _sweeps(cls, value: float) -> float:
        if value == 0:
            raise ValueError("must be non-zero")
        return value


Planar = Annotated[Union[PlanarLine, PlanarRectangle, PlanarCircle, PlanarArc], Field(discriminator="operation")]
LengthM = Annotated[float, Field(ge=Tiny, le=LIMIT, allow_inf_nan=False)]


class _Shape(Command):
    plane: Plane = "xy"
    origin: Point3 = [0.0, 0.0, 0.0]
    segments: Annotated[int, Field(ge=2, le=256)] = 12
    name: Name | None = None


class ShapePolygon(_Shape):
    operation: Literal["polygon"]
    sides: Annotated[int, Field(ge=3, le=256)]
    radius: LengthM
    start_degrees: Degrees = 0.0


class ShapeRotatedRectangle(_Shape):
    operation: Literal["rotated_rectangle"]
    width: LengthM
    depth: LengthM
    angle_degrees: Degrees = 0.0


class ShapePie(_Shape):
    operation: Literal["pie"]
    radius: LengthM
    start_degrees: Degrees = 0.0
    sweep_degrees: Annotated[float, Field(ge=-359.999, le=359.999, allow_inf_nan=False)]

    @field_validator("sweep_degrees")
    @classmethod
    def _sweeps(cls, value: float) -> float:
        if value == 0:
            raise ValueError("must not be zero")
        return value


class ShapeArc2(_Shape):
    operation: Literal["arc2"]
    start: Point2
    end: Point2
    bulge: Metre

    @field_validator("bulge")
    @classmethod
    def _bulges(cls, value: float) -> float:
        if value == 0:
            raise ValueError("must not be zero")
        return value


class ShapeArc3(_Shape):
    operation: Literal["arc3"]
    start: Point2
    through: Point2
    end: Point2


class ShapeFreehand(_Shape):
    operation: Literal["freehand"]
    points: Annotated[list[Point2], Field(min_length=2, max_length=5000)]
    closed: bool = False


Shape = Annotated[Union[ShapePolygon, ShapeRotatedRectangle, ShapePie, ShapeArc2, ShapeArc3, ShapeFreehand],
                  Field(discriminator="operation")]


# --- modifying objects ---------------------------------------------------------------------------------

class FollowMe(Command):
    object_id: TopLevelId
    path: Annotated[list[Point3], Field(min_length=2, max_length=2000)]
    closed: bool = False


class EdgeRef(BaseModel):
    """An edge named by its two end points."""
    model_config = ConfigDict(extra="forbid", strict=True)
    a: Point3
    b: Point3


class Fillet(Command):
    object_id: TopLevelId
    radius: LengthM
    segments: Annotated[int, Field(ge=1, le=64)] = 8
    edges: Literal["sharp"] | Annotated[list[EdgeRef], Field(min_length=1, max_length=500)]


class SolidOperation(Command):
    operation: Literal["outer_shell", "union", "subtract", "trim", "intersect", "split"]
    object_ids: Annotated[list[TopLevelId], Field(min_length=2, max_length=64)]

    @field_validator("object_ids")
    @classmethod
    def _different(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("must name different objects")
        return value


class CreateText3d(Command):
    text: Annotated[str, Field(min_length=1, max_length=200)]
    height: Annotated[float, Field(ge=1e-4, le=1000, allow_inf_nan=False)] = 0.25
    thickness: Annotated[float, Field(ge=1e-4, le=1000, allow_inf_nan=False)] = 0.05
    origin: Point3 = [0.0, 0.0, 0.0]
    bold: bool = True
    italic: bool = False

    @field_validator("text")
    @classmethod
    def _visible(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class LooseGroup(Command):
    object_ids: Annotated[list[TopLevelId], Field(min_length=1, max_length=500)] | None = None
    face_indices: Annotated[list[FaceNumber], Field(min_length=1, max_length=50_000)] | None = None
    connected: bool = False
    component: bool = False
    name: Name | None = None

    @model_validator(mode="after")
    def _something(self):
        if self.object_ids is None and self.face_indices is None:
            raise ValueError("choose loose faces or objects to group")
        if self.object_ids is not None and len(set(self.object_ids)) != len(self.object_ids):
            raise ValueError("object_ids must list different objects")
        return self


# --- component categories (no revision: the tree belongs to the server) ----------------------------------

class _Tree(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, populate_by_name=True)


CategoryId = Annotated[str, Field(max_length=64)]


class CategoryCreate(_Tree):
    name: Annotated[str, Field(max_length=200)]
    parent_id: CategoryId | None = None


class CategoryRename(_Tree):
    id: CategoryId
    name: Annotated[str, Field(max_length=200)]


class CategoryDelete(_Tree):
    id: CategoryId


class CategoryHide(_Tree):
    id: CategoryId
    hidden: bool


class CategoryMove(_Tree):
    id: CategoryId
    parent_id: CategoryId | None = None


class CategoryItem(_Tree):
    item: Annotated[str, Field(max_length=200)]
    node: CategoryId


class CategoryMoveItem(_Tree):
    item: Annotated[str, Field(max_length=200)]
    from_: CategoryId = Field(alias="from")
    to: CategoryId


CATEGORY_OPERATIONS = {"create": CategoryCreate, "rename": CategoryRename, "delete": CategoryDelete,
                       "hide": CategoryHide, "move": CategoryMove, "add": CategoryItem,
                       "remove": CategoryItem, "move_item": CategoryMoveItem}


# --- sheet operations ------------------------------------------------------------------------------------

class _Op(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class OpPage(_Op):
    op: Literal["page"]
    changes: Annotated[dict[str, Any], Field(min_length=1)]


class OpAdd(_Op):
    op: Literal["add"]
    list: str
    fields: dict[str, Any] | None = None
    image_base64: str | None = None


class OpSet(_Op):
    op: Literal["set"]
    id: Annotated[str, Field(pattern=r"^[a-z_]+/\d+$", max_length=40)]
    changes: Annotated[dict[str, Any], Field(min_length=1)]


class OpRemove(_Op):
    op: Literal["remove"]
    id: Annotated[str, Field(pattern=r"^[a-z_]+/\d+$", max_length=40)]


class OpOrder(_Op):
    op: Literal["order"]
    id: Annotated[str, Field(pattern=r"^[a-z_]+/\d+$", max_length=40)]
    to: Literal["front", "back"]


class OpDuplicate(_Op):
    op: Literal["duplicate"]
    id: Annotated[str, Field(pattern=r"^[a-z_]+/\d+$", max_length=40)]


SheetOp = Annotated[Union[OpPage, OpAdd, OpSet, OpRemove, OpOrder, OpDuplicate], Field(discriminator="op")]


SheetEdit.model_rebuild()


class BlankDocument(BaseModel):
    """A new empty document (no upload needed)."""
    model_config = ConfigDict(extra="forbid", strict=True)
    name: Name = "Untitled"
