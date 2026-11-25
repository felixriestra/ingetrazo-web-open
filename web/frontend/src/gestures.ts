/**
 * On-canvas tools: click, move, click, with snapping, a live preview, and a
 * typed value in the Measurements box (as in the desktop application).
 *
 * A gesture never builds geometry. It collects snapped points, previews the
 * result, and on the final click posts one modeling command, so every
 * result is a normal conflict-checked revision.
 */
import type {IngeTrazoViewer, LooseEdge, SnapInfo} from "./viewer";
import {responseApiError} from "./api";
import {faceMe} from "./online";

type V3 = [number, number, number];
type Plane = "xy" | "xz" | "yz";
interface PlaneState { plane: Plane; origin: V3; }

export interface GestureContext {
  viewer: IngeTrazoViewer;
  record: () => {id: string; latest_revision: number} | undefined;
  selectedObject: () => string | undefined;
  unitFactor: () => number;
  unitLabel: () => string;
  /** Decimal places for lengths shown in the Measurements box. */
  unitPrecision?: () => number;
  presentationDirty: () => boolean;
  applyRevision: (revised: unknown, message: string) => Promise<void>;
  setStatus: (text: string) => void;
  setHint: (text: string) => void;
  setVcb: (text: string) => void;
  /** Ask for a line of text; resolves ``null`` when cancelled. */
  ask: (label: string, initial: string) => Promise<string | null>;
  /** Everything currently selected: objects (group ids) and loose faces. */
  selectedObjects: () => string[];
  selectedFaces: () => number[];
  selectedEdges: () => LooseEdge[];
  selectFaces: (faces: number[]) => void;
  paintSettings: () => {color: [number, number, number]; opacity: number; texture?: string; material?: string};
}

interface GestureTool {
  /** Prompt shown in the status bar for the current stage. */
  prompt: () => string;
  click: (snap: SnapInfo) => void;
  move: (snap: SnapInfo) => void;
  down?: (snap: SnapInfo) => void;
  up?: (snap: SnapInfo) => void;
  /** A value typed into the Measurements box; return a message when it cannot be used. */
  value?: (text: string) => string | void;
  finish?: () => void;
  reset: () => void;
}

export interface Gestures {
  has: (key: string) => boolean;
  start: (key: string) => void;
  stop: () => void;
  /** Drop the stage in progress but stay in the tool (Esc once). */
  cancel: () => void;
  enter: (text: string) => void;
  active: () => string | undefined;
  /** Delete whatever is selected (objects and loose faces). */
  deleteSelection: () => void;
  /** Make a group or component of the selected loose faces and/or objects. */
  groupSelection: (options: {component: boolean; connected: boolean}) => void;
  /** Dissolve one level of each selected top-level group. */
  explodeSelection: () => void;
  /** Join Segments: the collinear pieces among the selected loose edges become one line. */
  joinSegments: () => void;
  /** Explode Curve: the circles and arcs among the selected loose edges become plain segments. */
  explodeCurve: () => void;
  /** Bridge: side faces between two selected loose faces, a face and a line, or two lines. */
  bridgeSelection: () => void;
  /** Change the segment count of the circle, arc or polygon the selected edge belongs to. */
  resegmentSelection: () => Promise<void>;
  /** Set the scale of the selected object along its own axes. */
  scaleSelection: () => Promise<void>;
  /** Make Faces and Extrude: each loop the selected loose edges close becomes its own solid. */
  makeFacesExtrude: () => Promise<void>;
  /** Mark (or unmark) the selected windows and doors so they cut their own hole in the wall. */
  cutOpening: (on: boolean) => void;
  /** A new terrain object over a rectangle, at the origin. */
  createTerrain: () => Promise<void>;
  /** Raise or lower the ground of a terrain object around a point. */
  deformTerrain: (objectId: string, point: [number, number, number]) => Promise<void>;
  /** Everything physically connected to the selected loose face. */
  selectConnected: () => Promise<void>;
}

const sub = (a: V3, b: V3): V3 => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const add = (a: V3, b: V3): V3 => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
const scale = (a: V3, k: number): V3 => [a[0] * k, a[1] * k, a[2] * k];
const dot = (a: V3, b: V3) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const length = (a: V3) => Math.hypot(a[0], a[1], a[2]);
const unit = (a: V3): V3 => { const l = length(a) || 1; return scale(a, 1 / l); };
const AXIS: Record<Plane, [V3, V3, V3]> = {   // u axis, v axis, normal
  xy: [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
  xz: [[1, 0, 0], [0, 0, 1], [0, -1, 0]],
  yz: [[0, 1, 0], [0, 0, 1], [1, 0, 0]],
};

function planeOf(normal: V3 | undefined): Plane {
  if (!normal) return "xy";
  const [x, y, z] = normal.map(Math.abs);
  if (z >= 0.9) return "xy";
  if (y >= 0.9) return "xz";
  if (x >= 0.9) return "yz";
  return "xy";
}

/** In-plane coordinates of ``point`` relative to ``origin``. */
function uv(plane: Plane, origin: V3, point: V3): [number, number] {
  const d = sub(point, origin);
  return [dot(d, AXIS[plane][0]), dot(d, AXIS[plane][1])];
}

function fromUV(plane: Plane, origin: V3, u: number, v: number): V3 {
  return add(origin, add(scale(AXIS[plane][0], u), scale(AXIS[plane][1], v)));
}

function constraintFor(plane: Plane, origin: V3) {
  return {kind: "plane" as const, point: origin, normal: AXIS[plane][2]};
}

export function mountGestures(ctx: GestureContext): Gestures {
  const {viewer} = ctx;
  let activeKey: string | undefined;
  let busy = false;
  const fmt = (metres: number) => `${(metres / ctx.unitFactor()).toFixed(ctx.unitPrecision?.() ?? 2)} ${ctx.unitLabel()}`;
  const parse = (text: string) => Number(text.trim().replace(/[a-z°]+$/i, "")) * 1;

  async function commit(endpoint: string, body: Record<string, unknown>, message: string): Promise<void> {
    const record = ctx.record();
    if (!record) { ctx.setStatus("Open a stored document first."); return; }
    if (ctx.presentationDirty()) { ctx.setStatus("Save or revert presentation changes before editing geometry."); return; }
    if (busy) return;
    busy = true;
    viewer.clearPreview();
    ctx.setStatus(`Saving revision ${record.latest_revision + 1}…`);
    try {
      const response = await fetch(
        `/api/v1/documents/${encodeURIComponent(record.id)}/commands/${endpoint}`,
        {method: "POST", headers: {"Content-Type": "application/json"},
          body: JSON.stringify({base_revision: record.latest_revision, ...body,
            // Faces picked inside an entered group belong to that group, not to the loose geometry.
            ...(endpoint.startsWith("loose-") && endpoint !== "loose-group" && viewer.getEditContext()
              ? {object_id: viewer.getEditContext()} : {})})});
      if (!response.ok) {
        throw await responseApiError(response);
      }
      await ctx.applyRevision(await response.json(), message);
    } catch (error) {
      ctx.setStatus(`Could not complete: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      busy = false;
    }
  }

  // --- drawing tools on a plane ------------------------------------------

  /** Click an origin, drag out a second point on the same plane. Used by Rectangle, Circle, Polygon. */
  function planarDrag(label: string, build: (state: PlaneState, end: V3, typed?: number[]) => {
    preview: V3[][]; value: string; commit: () => Promise<void>;
  }, typedHelp: string): GestureTool {
    let state: PlaneState | undefined;
    let last: V3 | undefined;
    const tool: GestureTool = {
      prompt: () => state ? `${label}: click the second point, or type ${typedHelp} and press Enter.` : `${label}: click the first point.`,
      click: snap => {
        if (!state) {
          state = {plane: planeOf(snap.normal), origin: snap.point};
          viewer.setSnapConstraint(constraintFor(state.plane, state.origin));
          ctx.setHint(tool.prompt());
          return;
        }
        void build(state, snap.point).commit().then(() => tool.reset());
      },
      move: snap => {
        if (!state) return;
        last = snap.point;
        const shown = build(state, snap.point);
        viewer.setPreview(shown.preview);
        ctx.setVcb(shown.value);
      },
      value: text => {
        if (!state) return "Click the first point before typing a value.";
        const numbers = text.split(/[,;\s]+/).filter(Boolean).map(parse);
        if (!numbers.length || numbers.some(n => !Number.isFinite(n))) return `Type ${typedHelp}.`;
        const reach = last ? sub(last, state.origin) : [1, 0, 0] as V3;
        void build(state, add(state.origin, reach), numbers.map(n => n * ctx.unitFactor())).commit().then(() => tool.reset());
      },
      reset: () => { state = undefined; last = undefined; viewer.setSnapConstraint(null); viewer.clearPreview(); ctx.setVcb(""); ctx.setHint(tool.prompt()); },
    };
    return tool;
  }

  const rectangle = (): GestureTool => planarDrag("Rectangle", (state, end, typed) => {
    let [du, dv] = uv(state.plane, state.origin, end);
    if (typed) {
      du = Math.sign(du || 1) * typed[0];
      dv = Math.sign(dv || 1) * (typed[1] ?? typed[0]);
    }
    const corners = [[0, 0], [du, 0], [du, dv], [0, dv], [0, 0]].map(([u, v]) => fromUV(state.plane, state.origin, u, v));
    return {
      preview: [corners], value: `${fmt(Math.abs(du))}, ${fmt(Math.abs(dv))}`,
      commit: () => Math.abs(du) < 1e-6 || Math.abs(dv) < 1e-6
        ? Promise.resolve(ctx.setStatus("The rectangle has no area."))
        : commit("create-planar", {
          operation: "rectangle", name: "Rectangle", plane: state.plane,
          origin: fromUV(state.plane, state.origin, Math.min(0, du), Math.min(0, dv)),
          size: [Math.abs(du), Math.abs(dv)]}, "rectangle created"),
    };
  }, "width, depth");

  const circleLike = (label: string, kind: "circle" | "polygon"): GestureTool => {
    let sides = 6;
    const tool = planarDrag(label, (state, end, typed) => {
      const [du, dv] = uv(state.plane, state.origin, end);
      const radius = typed ? typed[0] : Math.hypot(du, dv);
      const angle = Math.atan2(dv, du);
      const count = kind === "circle" ? 48 : sides;
      const ring = Array.from({length: count + 1}, (_, i) => {
        const a = (kind === "circle" ? 0 : angle) + (2 * Math.PI * i) / count;
        return fromUV(state.plane, state.origin, radius * Math.cos(a), radius * Math.sin(a));
      });
      return {
        preview: [ring, [state.origin, end]],
        value: `${fmt(radius)}${kind === "polygon" ? `  ·  ${sides} sides` : ""}`,
        commit: () => radius < 1e-6 ? Promise.resolve(ctx.setStatus("The radius must be greater than zero."))
          : kind === "circle"
            ? commit("create-planar", {operation: "circle", name: "Circle", plane: state.plane, origin: state.origin, radius, segments: 32}, "circle created")
            : commit("create-shape", {operation: "polygon", name: "Polygon", plane: state.plane, origin: state.origin, radius, sides,
              start_degrees: (angle * 180) / Math.PI}, "polygon created"),
      };
    }, kind === "polygon" ? "the radius (or 8s for the number of sides)" : "the radius");
    if (kind === "polygon") {
      const inner = tool.value!;
      tool.value = text => {
        const match = /^\s*(\d+)\s*s\s*$/i.exec(text);
        if (match) { sides = Math.min(Math.max(Number(match[1]), 3), 256); ctx.setHint(`Polygon: ${sides} sides.`); return; }
        return inner(text);
      };
    }
    return tool;
  };

  /** Several clicks on one plane, then one commit. */
  function planeClicks(label: string, need: number, prompts: string[], draw: (points: V3[], plane: Plane, cursor: V3) => V3[][], done: (points: V3[], plane: Plane) => Promise<void>): GestureTool {
    let points: V3[] = [];
    let plane: Plane = "xy";
    const tool: GestureTool = {
      prompt: () => `${label}: ${prompts[Math.min(points.length, prompts.length - 1)]}`,
      click: snap => {
        if (!points.length) { plane = planeOf(snap.normal); viewer.setSnapConstraint(constraintFor(plane, snap.point)); }
        points.push(snap.point);
        if (points.length === need) { void done(points, plane).then(() => tool.reset()); return; }
        ctx.setHint(tool.prompt());
      },
      move: snap => {
        if (!points.length) return;
        viewer.setPreview(draw(points, plane, snap.point));
        ctx.setVcb(fmt(length(sub(snap.point, points[points.length - 1]))));
      },
      reset: () => { points = []; viewer.setSnapConstraint(null); viewer.clearPreview(); ctx.setVcb(""); ctx.setHint(tool.prompt()); },
    };
    return tool;
  }

  const rotatedRectangle = () => planeClicks("Rotated Rectangle", 3,
    ["click the first corner.", "click the end of the first side.", "click to set the depth."],
    (points, plane, cursor) => points.length < 2 ? [[points[0], cursor]] : [rotatedCorners(points, plane, cursor)],
    async (points, plane) => {
      const corners = rotatedCorners(points, plane, points[2]);
      await commit("create-shape", {operation: "freehand", name: "Rotated rectangle", plane, origin: points[0],
        points: corners.slice(0, 4).map(c => uv(plane, points[0], c)), closed: true}, "rotated rectangle created");
    });

  function rotatedCorners(points: V3[], plane: Plane, third: V3): V3[] {
    const origin = points[0];
    const [bu, bv] = uv(plane, origin, points[1]);
    const side = Math.hypot(bu, bv) || 1;
    const [nu, nv] = [-bv / side, bu / side];
    const [tu, tv] = uv(plane, origin, third);
    const depth = tu * nu + tv * nv;
    const at = (u: number, v: number) => fromUV(plane, origin, u, v);
    const corners = [at(0, 0), at(bu, bv), at(bu + nu * depth, bv + nv * depth), at(nu * depth, nv * depth)];
    return [...corners, corners[0]];
  }

  const threePointArc = () => planeClicks("3 Point Arc", 3,
    ["click the start.", "click a point on the arc.", "click the end."],
    (points, _plane, cursor) => [[...points, cursor]],
    async (points, plane) => commit("create-shape", {operation: "arc3", name: "Arc", plane, origin: points[0],
      start: [0, 0], through: uv(plane, points[0], points[1]), end: uv(plane, points[0], points[2]), segments: 24}, "arc created"));

  const twoPointArc = () => planeClicks("Arc", 3,
    ["click the start of the chord.", "click the end of the chord.", "click to set how far the arc bulges."],
    (points, plane, cursor) => {
      if (points.length < 2) return [[points[0], cursor]];
      return [arcPoints(points[0], points[1], bulgeOf(points, plane, cursor), plane)];
    },
    async (points, plane) => commit("create-shape", {operation: "arc2", name: "Arc", plane, origin: points[0],
      start: [0, 0], end: uv(plane, points[0], points[1]), bulge: bulgeOf(points, plane, points[2]), segments: 24}, "arc created"));

  function bulgeOf(points: V3[], plane: Plane, cursor: V3): number {
    const [eu, ev] = uv(plane, points[0], points[1]);
    const [cu, cv] = uv(plane, points[0], cursor);
    const chord = Math.hypot(eu, ev) || 1;
    const [mu, mv] = [eu / 2, ev / 2];
    return ((cu - mu) * -ev + (cv - mv) * eu) / chord || 0.001;
  }

  function arcPoints(a: V3, b: V3, bulge: number, plane: Plane): V3[] {
    const [eu, ev] = uv(plane, a, b);
    const chord = Math.hypot(eu, ev) || 1;
    const normal: [number, number] = [-ev / chord, eu / chord];
    const through: [number, number] = [eu / 2 + normal[0] * bulge, ev / 2 + normal[1] * bulge];
    // circle through (0,0), through, (eu,ev)
    const d = 2 * (0 * (through[1] - ev) + through[0] * (ev - 0) + eu * (0 - through[1]));
    if (Math.abs(d) < 1e-9) return [a, b];
    const ux = ((through[0] ** 2 + through[1] ** 2) * (0 - ev) + (eu ** 2 + ev ** 2) * (through[1] - 0)) / d;
    const uy = ((through[0] ** 2 + through[1] ** 2) * (eu - 0) + (eu ** 2 + ev ** 2) * (0 - through[0])) / d;
    const radius = Math.hypot(ux, uy);
    const start = Math.atan2(-uy, -ux);
    const end = Math.atan2(ev - uy, eu - ux);
    const mid = Math.atan2(through[1] - uy, through[0] - ux);
    let sweep = (end - start + 2 * Math.PI) % (2 * Math.PI);
    if ((mid - start + 2 * Math.PI) % (2 * Math.PI) > sweep) sweep -= 2 * Math.PI;
    return Array.from({length: 25}, (_, i) => fromUV(plane, a, ux + radius * Math.cos(start + (sweep * i) / 24), uy + radius * Math.sin(start + (sweep * i) / 24)));
  }

  /** Centre, start point (radius and start angle), then the sweep. Center Arc and Pie. */
  function sweepTool(label: string, kind: "arc" | "pie"): GestureTool {
    let centre: V3 | undefined;
    let first: V3 | undefined;
    let plane: Plane = "xy";
    let sweep = 90;
    const tool: GestureTool = {
      prompt: () => !centre ? `${label}: click the centre.` : !first ? `${label}: click the start (sets the radius).` : `${label}: click the end, or type the sweep in degrees.`,
      click: snap => {
        if (!centre) { centre = snap.point; plane = planeOf(snap.normal); viewer.setSnapConstraint(constraintFor(plane, centre)); }
        else if (!first) first = snap.point;
        else { void finish(sweepFrom(snap.point)).then(() => tool.reset()); return; }
        ctx.setHint(tool.prompt());
      },
      move: snap => {
        if (!centre) return;
        if (!first) { viewer.setPreview([[centre, snap.point]]); ctx.setVcb(fmt(length(sub(snap.point, centre)))); return; }
        sweep = sweepFrom(snap.point);
        viewer.setPreview([shape(sweep)]);
        ctx.setVcb(`${sweep.toFixed(1)}°`);
      },
      value: text => {
        const degrees = parse(text);
        if (!first || !Number.isFinite(degrees) || degrees === 0) return "Click the start point, then type a sweep in degrees.";
        void finish(degrees).then(() => tool.reset());
      },
      reset: () => { centre = first = undefined; viewer.setSnapConstraint(null); viewer.clearPreview(); ctx.setVcb(""); ctx.setHint(tool.prompt()); },
    };
    let previous = 90;
    function angleOf(point: V3): number { const [u, v] = uv(plane, centre!, point); return Math.atan2(v, u); }
    function sweepFrom(point: V3): number {
      const raw = ((angleOf(point) - angleOf(first!)) * 180) / Math.PI;
      let degrees = ((raw % 360) + 360) % 360;
      if (previous < 0 && degrees > 180 && degrees - 360 > -359.9) degrees -= 360;
      else if (previous < 0 && degrees <= 180 && raw < 0) degrees -= 360;
      previous = degrees > 180 ? degrees - 360 : degrees;
      return Math.max(-359.9, Math.min(359.9, previous === 0 ? 0.1 : previous));
    }
    function shape(degrees: number): V3[] {
      const radius = length(sub(first!, centre!));
      const start = angleOf(first!);
      const steps = 32;
      const arc = Array.from({length: steps + 1}, (_, i) => {
        const a = start + ((degrees * Math.PI) / 180) * (i / steps);
        return fromUV(plane, centre!, radius * Math.cos(a), radius * Math.sin(a));
      });
      return kind === "pie" ? [centre!, ...arc, centre!] : arc;
    }
    async function finish(degrees: number): Promise<void> {
      const radius = length(sub(first!, centre!));
      const start = (angleOf(first!) * 180) / Math.PI;
      if (radius < 1e-6) { ctx.setStatus("The radius must be greater than zero."); return; }
      if (kind === "arc") {
        await commit("create-planar", {operation: "arc", name: "Arc", plane, origin: centre, radius, start_degrees: start, sweep_degrees: degrees, segments: 24}, "arc created");
      } else {
        await commit("create-shape", {operation: "pie", name: "Pie", plane, origin: centre, radius, start_degrees: start, sweep_degrees: degrees, segments: 24}, "pie created");
      }
    }
    return tool;
  }

  const freehand = (): GestureTool => {
    let points: V3[] = [];
    let pressed = false;
    let plane: Plane = "xy";
    const tool: GestureTool = {
      prompt: () => "Freehand: press and drag to draw a curve, release to finish.",
      click: () => undefined,
      down: snap => { pressed = true; plane = planeOf(snap.normal); viewer.setSnapConstraint(constraintFor(plane, snap.point)); points = [snap.point]; },
      move: snap => {
        if (!pressed) return;
        const last = points[points.length - 1];
        if (length(sub(snap.point, last)) < 0.03) return;
        points.push(snap.point);
        viewer.setPreview([points]);
      },
      up: () => {
        if (!pressed) return;
        pressed = false;
        const collected = points;
        if (collected.length >= 2) {
          void commit("create-shape", {operation: "freehand", name: "Freehand", plane, origin: collected[0],
            points: collected.map(p => uv(plane, collected[0], p)), closed: false}, "curve created").then(() => tool.reset());
        } else tool.reset();
      },
      reset: () => { points = []; pressed = false; viewer.setSnapConstraint(null); viewer.clearPreview(); ctx.setHint(tool.prompt()); },
    };
    return tool;
  };

  const line = (): GestureTool => {
    let start: V3 | undefined;
    let last: V3 | undefined;
    const tool: GestureTool = {
      prompt: () => start ? "Line: click the next point (Esc ends the chain), or type a length." : "Line: click the start point.",
      click: snap => {
        if (!start) { start = snap.point; ctx.setHint(tool.prompt()); return; }
        const from = start;
        void commit("create-planar", {operation: "line", name: "Line", origin: from, end: snap.point}, "line created").then(() => { start = snap.point; ctx.setHint(tool.prompt()); });
      },
      move: snap => {
        if (!start) return;
        last = snap.point;
        viewer.setPreview([[start, snap.point]]);
        ctx.setVcb(fmt(length(sub(snap.point, start))));
      },
      value: text => {
        const distance = parse(text) * ctx.unitFactor();
        if (!start || !last || !Number.isFinite(distance) || distance === 0) return "Click the start point and aim the line, then type a length.";
        const end = add(start, scale(unit(sub(last, start)), distance));
        const from = start;
        void commit("create-planar", {operation: "line", name: "Line", origin: from, end}, "line created").then(() => { start = end; });
      },
      reset: () => { start = last = undefined; viewer.clearPreview(); ctx.setVcb(""); ctx.setHint(tool.prompt()); },
    };
    return tool;
  };

  const dimension = (): GestureTool => {
    let points: V3[] = [];
    const tool: GestureTool = {
      prompt: () => ["Dimension: click the first point.", "Dimension: click the second point.", "Dimension: click where the dimension line should sit."][Math.min(points.length, 2)],
      click: snap => {
        points.push(snap.point);
        if (points.length < 3) { ctx.setHint(tool.prompt()); return; }
        const [a, b, c] = points;
        const along = unit(sub(b, a));
        const foot = add(a, scale(along, dot(sub(c, a), along)));
        let offset = sub(c, foot);
        if (length(offset) < 1e-4) offset = [0, 0.25, 0];
        void commit("create-annotation", {operation: "dimension", a, b, offset}, "dimension created").then(() => tool.reset());
      },
      move: snap => {
        if (!points.length) return;
        viewer.setPreview(points.length === 1 ? [[points[0], snap.point]] : [[points[0], points[1]], [points[0], snap.point], [points[1], snap.point]]);
        ctx.setVcb(fmt(length(sub(points.length === 1 ? snap.point : points[1], points[0]))));
      },
      reset: () => { points = []; viewer.clearPreview(); ctx.setVcb(""); ctx.setHint(tool.prompt()); },
    };
    return tool;
  };

  const text = (): GestureTool => {
    let anchor: V3 | undefined;
    const tool: GestureTool = {
      prompt: () => anchor ? "Text: click where the label should sit." : "Text: click the point to annotate.",
      click: snap => {
        if (!anchor) { anchor = snap.point; ctx.setHint(tool.prompt()); return; }
        const from = anchor;
        const offset = sub(snap.point, from);
        void ctx.ask("Label text", "").then(value => {
          if (value) return commit("create-annotation", {operation: "text", anchor: from, offset: length(offset) < 1e-4 ? [0.3, 0.3, 0.3] : offset, text: value}, "label created");
          return undefined;
        }).then(() => tool.reset());
      },
      move: snap => { if (anchor) viewer.setPreview([[anchor, snap.point]]); },
      reset: () => { anchor = undefined; viewer.clearPreview(); ctx.setHint(tool.prompt()); },
    };
    return tool;
  };

  // --- modifying tools -----------------------------------------------------

  /** Pick one top-level object (or use the current selection) and run ``next``. */
  function objectTool(label: string, ready: () => string, begin: (id: string, snap?: SnapInfo) => void, extra: Partial<GestureTool>): GestureTool {
    let chosen: string | undefined;
    const tool: GestureTool = {
      prompt: () => chosen ? ready() : `${label}: click an object.`,
      click: snap => {
        if (chosen) { extra.click?.(snap); return; }
        const id = snap.objectId ?? ctx.selectedObject();
        if (!id) { ctx.setStatus(`${label}: that part belongs to a nested component; select its top-level object in the Objects list first.`); return; }
        chosen = id;
        viewer.selectObject(id);
        begin(id, snap);
        ctx.setHint(tool.prompt());
      },
      move: snap => { if (chosen) extra.move?.(snap); },
      value: text => (chosen ? extra.value?.(text) : "Pick an object first."),
      reset: () => { chosen = undefined; extra.reset?.(); viewer.setSnapConstraint(null); viewer.clearPreview(); ctx.setVcb(""); ctx.setHint(tool.prompt()); },
    };
    objectToolSetters.set(tool, id => { chosen = id; begin(id); });
    return tool;
  }
  const objectToolSetters = new Map<GestureTool, (id: string) => void>();

  const boxLines = (min: V3, max: V3, shift: V3 = [0, 0, 0]): V3[][] => {
    const c = (x: number, y: number, z: number): V3 => add([x, y, z], shift);
    const [a, b] = [min, max];
    const bottom = [c(a[0], a[1], a[2]), c(b[0], a[1], a[2]), c(b[0], b[1], a[2]), c(a[0], b[1], a[2]), c(a[0], a[1], a[2])];
    const top = [c(a[0], a[1], b[2]), c(b[0], a[1], b[2]), c(b[0], b[1], b[2]), c(a[0], b[1], b[2]), c(a[0], a[1], b[2])];
    return [bottom, top, [bottom[0], top[0]], [bottom[1], top[1]], [bottom[2], top[2]], [bottom[3], top[3]]];
  };

  const moveObjects = (onChosen: () => void): GestureTool => {
    let base: V3 | undefined;
    let id = "";
    // Everything selected moves together when the picked object is part of the selection.
    const movingIds = () => (ctx.selectedObjects().includes(id) ? ctx.selectedObjects() : [id]);
    let last: V3 | undefined;
    const bounds = () => viewer.objectBounds(id);
    const tool: GestureTool = objectTool("Move", () => base ? "Move: click the destination, or type a distance." : "Move: click a base point.",
      chosen => { id = chosen; onChosen(); },
      {
        click: snap => {
          if (!base) { base = snap.point; ctx.setHint(tool.prompt()); return; }
          const delta = sub(snap.point, base);
          if (length(delta) < 1e-6) { ctx.setStatus("Move: the destination equals the base point."); return; }
          void commit("move-object", {object_ids: movingIds(), delta}, "moved").then(() => tool.reset());
        },
        move: snap => {
          if (!base) return;
          last = snap.point;
          const delta = sub(snap.point, base);
          const box = bounds();
          viewer.setPreview([[base, snap.point], ...(box ? boxLines(box.min, box.max, delta) : [])]);
          ctx.setVcb(fmt(length(delta)));
        },
        value: typed => {
          const distance = parse(typed) * ctx.unitFactor();
          if (!base || !last || !Number.isFinite(distance) || distance === 0) return "Click a base point, then type a distance.";
          const direction = unit(sub(last, base));
          void commit("move-object", {object_ids: movingIds(), delta: scale(direction, distance)}, "moved").then(() => tool.reset());
        },
        reset: () => { base = undefined; last = undefined; },
      });
    return tool;
  };

  /** Move: objects as before; loose faces and free edges move by base point and destination. */
  const move = (): GestureTool => {
    let objectChosen = false;
    const inner = moveObjects(() => { objectChosen = true; });
    let loose: {faces: number[]; edges: [V3, V3][]} | undefined;
    let base: V3 | undefined;
    let last: V3 | undefined;
    const send = (delta: V3) => {
      const body: Record<string, unknown> = {delta};
      if (loose!.faces.length) body.face_indices = loose!.faces;
      if (loose!.edges.length) body.edges = loose!.edges;
      void commit("loose-move", body, "moved").then(() => wrapper.reset());
    };
    const wrapper: GestureTool = {
      prompt: () => !loose ? inner.prompt() : base ? "Move: click the destination, or type a distance." : "Move: click a base point.",
      click: snap => {
        if (loose) {
          if (!base) { base = snap.point; ctx.setHint(wrapper.prompt()); return; }
          const delta = sub(snap.point, base);
          if (length(delta) < 1e-6) { ctx.setStatus("Move: the destination equals the base point."); return; }
          send(delta);
          return;
        }
        if (!objectChosen && (snap.looseEdge || snap.looseFace !== undefined)) {
          if (snap.looseEdge) loose = {faces: [], edges: [snap.looseEdge]};
          else {
            const picked = snap.looseFace!;
            loose = {faces: ctx.selectedFaces().includes(picked) ? ctx.selectedFaces() : [picked], edges: []};
            ctx.selectFaces(loose.faces);
          }
          ctx.setHint(wrapper.prompt());
          return;
        }
        inner.click(snap);
      },
      move: snap => {
        if (!loose) { inner.move(snap); return; }
        if (!base) return;
        last = snap.point;
        viewer.setPreview([[base, snap.point]]);
        ctx.setVcb(fmt(length(sub(snap.point, base))));
      },
      value: typed => {
        if (!loose) return inner.value?.(typed);
        const distance = parse(typed) * ctx.unitFactor();
        if (!base || !last || !Number.isFinite(distance) || distance === 0) return "Click a base point, then type a distance.";
        send(scale(unit(sub(last, base)), distance));
        return undefined;
      },
      reset: () => {
        loose = undefined; base = undefined; last = undefined; objectChosen = false;
        inner.reset();
      },
    };
    const setter = objectToolSetters.get(inner);
    if (setter) objectToolSetters.set(wrapper, id => { objectChosen = true; setter(id); });
    return wrapper;
  };

  const rotate = (): GestureTool => {
    let id = "";
    let centre: V3 | undefined;
    let startAngle: number | undefined;
    let degrees = 0;
    const angleAt = (p: V3) => Math.atan2(p[1] - centre![1], p[0] - centre![0]);
    const tool: GestureTool = objectTool("Rotate", () => startAngle === undefined ? "Rotate: click the start direction." : "Rotate: click the end direction, or type degrees.",
      chosen => {
        id = chosen;
        const box = viewer.objectBounds(id);
        if (box) { centre = scale(add(box.min, box.max), 0.5); viewer.setSnapConstraint(constraintFor("xy", [0, 0, centre[2]])); }
      },
      {
        click: snap => {
          if (!centre) return;
          if (startAngle === undefined) { startAngle = angleAt(snap.point); ctx.setHint(tool.prompt()); return; }
          if (Math.abs(degrees) < 0.01) { ctx.setStatus("Rotate: the angle is zero."); return; }
          void commit("transform-object", {object_id: id, operation: "rotate", axis: "z", degrees}, "object rotated").then(() => tool.reset());
        },
        move: snap => {
          if (!centre) return;
          if (startAngle === undefined) { viewer.setPreview([[centre, snap.point]]); return; }
          degrees = ((angleAt(snap.point) - startAngle) * 180) / Math.PI;
          degrees = ((degrees + 540) % 360) - 180;
          const radius = Math.max(length(sub(snap.point, centre)), 1e-3);
          const arc = Array.from({length: 25}, (_, i) => {
            const a = startAngle! + ((degrees * Math.PI) / 180) * (i / 24);
            return [centre![0] + radius * Math.cos(a), centre![1] + radius * Math.sin(a), centre![2]] as V3;
          });
          viewer.setPreview([[centre, arc[0]], arc, [centre, arc[24]]]);
          ctx.setVcb(`${degrees.toFixed(1)}°`);
        },
        value: typed => {
          const value = parse(typed);
          if (!Number.isFinite(value) || value === 0) return "Type the angle in degrees.";
          void commit("transform-object", {object_id: id, operation: "rotate", axis: "z", degrees: value}, "object rotated").then(() => tool.reset());
        },
        reset: () => { centre = undefined; startAngle = undefined; degrees = 0; },
      });
    return tool;
  };

  const scaleTool = (): GestureTool => {
    let id = "";
    let centre: V3 | undefined;
    let reference = 0;
    let factor = 1;
    const tool: GestureTool = objectTool("Scale", () => reference ? "Scale: click to apply the new size, or type a factor." : "Scale: click a reference point (its distance from the centre is 1.0).",
      chosen => {
        id = chosen;
        const box = viewer.objectBounds(id);
        if (box) { centre = scale(add(box.min, box.max), 0.5); viewer.setSnapConstraint(constraintFor("xy", [0, 0, centre[2]])); }
      },
      {
        click: snap => {
          if (!centre) return;
          if (!reference) { reference = Math.max(length(sub(snap.point, centre)), 1e-6); ctx.setHint(tool.prompt()); return; }
          if (Math.abs(factor - 1) < 1e-4 || factor <= 0) { ctx.setStatus("Scale: the factor is 1."); return; }
          void commit("transform-object", {object_id: id, operation: "scale", factors: [factor, factor, factor]}, "object scaled").then(() => tool.reset());
        },
        move: snap => {
          if (!centre) return;
          if (!reference) { viewer.setPreview([[centre, snap.point]]); return; }
          factor = length(sub(snap.point, centre)) / reference;
          const box = viewer.objectBounds(id);
          viewer.setPreview([[centre, snap.point], ...(box ? boxLines(
            add(centre, scale(sub(box.min, centre), factor)), add(centre, scale(sub(box.max, centre), factor))) : [])]);
          ctx.setVcb(factor.toFixed(3));
        },
        value: typed => {
          const value = parse(typed);
          if (!Number.isFinite(value) || value <= 0) return "Type a positive scale factor.";
          void commit("transform-object", {object_id: id, operation: "scale", factors: [value, value, value]}, "object scaled").then(() => tool.reset());
        },
        reset: () => { centre = undefined; reference = 0; factor = 1; },
      });
    return tool;
  };

  const pushPull = (): GestureTool => {
    let id: string | undefined;
    let looseFace: number | undefined;
    let origin: V3 | undefined;
    let normal: V3 | undefined;
    let distance = 0;
    const direction = (n: V3): string => {
      const [x, y, z] = n;
      const axis = Math.abs(x) >= Math.abs(y) && Math.abs(x) >= Math.abs(z) ? 0 : Math.abs(y) >= Math.abs(z) ? 1 : 2;
      const dominant = [x, y, z][axis];
      return Math.abs(dominant) < 0.95 ? "normal" : `${dominant < 0 ? "-" : "+"}${"xyz"[axis]}`;
    };
    const tool: GestureTool = {
      prompt: () => origin ? "Push/Pull: move to set the distance and click, or type it." : "Push/Pull: click a face.",
      click: snap => {
        if (!origin) {
          if (snap.looseFace !== undefined && snap.normal) {
            looseFace = snap.looseFace; origin = snap.point; normal = snap.normal;
            ctx.selectFaces([looseFace]);
            viewer.setSnapConstraint({kind: "axis", origin, direction: normal});
            ctx.setHint(tool.prompt());
            return;
          }
          if (!snap.objectId || !snap.normal) { ctx.setStatus("Push/Pull: click a face."); return; }
          id = snap.objectId; origin = snap.point; normal = snap.normal;
          viewer.selectObject(id);
          viewer.setSnapConstraint({kind: "axis", origin, direction: normal});
          ctx.setHint(tool.prompt());
          return;
        }
        if (Math.abs(distance) < 0.0002) { ctx.setStatus("Push/Pull: the distance is too small."); return; }
        void finish(distance);
      },
      move: snap => {
        if (!origin || !normal) return;
        distance = dot(sub(snap.point, origin), normal);
        viewer.setPreview([[origin, add(origin, scale(normal, distance))]]);
        ctx.setVcb(fmt(distance));
      },
      value: typed => {
        const value = parse(typed) * ctx.unitFactor();
        if (!origin || !Number.isFinite(value) || value === 0) return "Click a face, then type a distance.";
        void finish(value);
      },
      reset: () => { id = origin = normal = undefined; looseFace = undefined; distance = 0; viewer.setSnapConstraint(null); viewer.clearPreview(); ctx.setVcb(""); ctx.setHint(tool.prompt()); },
    };
    async function finish(value: number): Promise<void> {
      if (looseFace !== undefined) {
        await commit("loose-push-pull", {face_index: looseFace, distance: value}, "face pushed");
      } else {
        await commit("push-pull", {object_id: id, direction: direction(normal!), distance: value, face_point: origin}, "face pushed");
      }
      tool.reset();
    }
    return tool;
  };

  const eraser = (): GestureTool => {
    const tool: GestureTool = {
      prompt: () => "Eraser: click an object or face to delete it (recoverable from the revision history).",
      click: snap => {
        if (snap.looseEdge) {
          void commit("loose-edge-erase", {edges: [snap.looseEdge]}, "edge erased");
        } else if (snap.looseFace !== undefined) {
          const chosen = ctx.selectedFaces().includes(snap.looseFace) ? ctx.selectedFaces() : [snap.looseFace];
          void commit("loose-erase", {face_indices: chosen}, "face erased");
        } else if (snap.objectId) {
          const chosen = ctx.selectedObjects().includes(snap.objectId) ? ctx.selectedObjects() : [snap.objectId];
          void commit("object-lifecycle", {object_ids: chosen, operation: "delete"}, chosen.length > 1 ? `${chosen.length} objects deleted` : `${snap.objectName ?? "object"} deleted`);
        } else ctx.setStatus("Eraser: click an object or a face.");
      },
      move: () => undefined,
      reset: () => ctx.setHint(tool.prompt()),
    };
    return tool;
  };

  const paint = (): GestureTool => {
    const tool: GestureTool = {
      prompt: () => "Paint: click an object or face to apply the colour or texture chosen (Library tab or the Paint form).",
      click: snap => {
        const {color, opacity, texture, material} = ctx.paintSettings();
        const paintWith = texture ? {texture} : {color};
        if (material !== undefined) {
          // A document material paints faces by name: loose ones, or those of an open group.
          if (snap.looseFace === undefined) { ctx.setStatus("Document materials paint faces: click a loose face, or open the group first."); return; }
          const chosen = ctx.selectedFaces().includes(snap.looseFace) ? ctx.selectedFaces() : [snap.looseFace];
          void commit("loose-paint", {face_indices: chosen, material}, `painted with ${material}`);
        } else if (snap.looseFace !== undefined) {
          const chosen = ctx.selectedFaces().includes(snap.looseFace) ? ctx.selectedFaces() : [snap.looseFace];
          void commit("loose-paint", {face_indices: chosen, opacity, ...paintWith}, "painted");
        } else if (snap.objectId) {
          const chosen = ctx.selectedObjects().includes(snap.objectId) ? ctx.selectedObjects() : [snap.objectId];
          void commit("object-material", {object_ids: chosen, opacity, ...paintWith}, "painted");
        } else ctx.setStatus("Paint: click an object or a face.");
      },
      move: () => undefined,
      reset: () => ctx.setHint(tool.prompt()),
    };
    return tool;
  };

  /** Click in the model to drop a library component with its base centre on the point. */
  const placement = (spec: string): GestureTool => {
    // "person:<key>" is a 2D scale figure; anything else is a bundled 3D component.
    const person = spec.startsWith("person:");
    const online = spec.startsWith("online:");
    const key = person ? spec.slice(7) : online ? spec.slice(7) : spec;
    const tool: GestureTool = {
      prompt: () => `Place ${spec === "faceme" ? faceMe.name : key}: click where it should stand (Esc finishes).`,
      click: snap => {
        if (spec === "faceme") void commit("insert-faceme-image", {image_base64: faceMe.image, name: faceMe.name, height: faceMe.height, origin: snap.point}, "face-me figure placed");
        else if (online) void commit("insert-online-component", {model: key, origin: snap.point}, "component placed");
        else if (person) void commit("insert-person", {person: key, origin: snap.point}, "figure placed");
        else void commit("insert-component", {component: key, origin: snap.point}, "component placed");
      },
      move: snap => {
        viewer.setPreview([[snap.point, add(snap.point, [0, 0, 1])]]);
      },
      reset: () => { viewer.clearPreview(); ctx.setHint(tool.prompt()); },
    };
    return tool;
  };

  /** Section Plane: click a face; the plane passes through the point, facing the face. */
  const sectionPlane = (): GestureTool => {
    const tool: GestureTool = {
      prompt: () => "Section Plane: click a face to cut the model there.",
      click: snap => {
        if (!snap.normal) { ctx.setStatus("Section Plane: click on a surface."); return; }
        void commit("create-section", {point: snap.point, normal: snap.normal}, "section plane placed");
      },
      move: snap => {
        if (!snap.normal) return;
        const n = unit(snap.normal);
        const helper: V3 = Math.abs(n[2]) > 0.9 ? [1, 0, 0] : [0, 0, 1];
        const a = unit(cross(n, helper));
        const b = unit(cross(n, a));
        const half = 1.2;
        const corner = (u: number, v: number) => add(snap.point, add(scale(a, u * half), scale(b, v * half)));
        viewer.setPreview([[corner(-1, -1), corner(1, -1), corner(1, 1), corner(-1, 1), corner(-1, -1)]], 0xe0a030);
      },
      reset: () => { viewer.clearPreview(); ctx.setHint(tool.prompt()); },
    };
    return tool;
  };
  const cross = (a: V3, b: V3): V3 => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];

  const factories: Record<string, () => GestureTool> = {
    section: sectionPlane,
    line, rectangle, circle: () => circleLike("Circle", "circle"), polygon: () => circleLike("Polygon", "polygon"),
    rotated_rect: rotatedRectangle, arc: twoPointArc, arc3: threePointArc,
    center_arc: () => sweepTool("Center Arc", "arc"), pie: () => sweepTool("Pie", "pie"),
    freehand, dimension, text, move, rotate, scale: scaleTool, pushpull: pushPull, eraser, paint,
  };

  let tool: GestureTool | undefined;
  viewer.onGestureMove = snap => {
    if (!snap || !tool || busy) return;
    tool.move(snap);
    ctx.setStatus(`${snap.inference}`);
  };
  viewer.onGestureClick = snap => { if (snap && tool && !busy) tool.click(snap); };
  viewer.onGestureDown = snap => { if (snap && tool && tool.down && !busy) tool.down(snap); };
  viewer.onGestureUp = snap => { if (snap && tool && tool.up && !busy) tool.up(snap); };
  return {
    has: key => key in factories || key.startsWith("place:"),
    start(key) {
      tool?.reset();
      activeKey = key;
      tool = key.startsWith("place:") ? placement(key.slice(6)) : factories[key]();
      viewer.setGestureMode(true);
      tool.reset();
      const preselected = ctx.selectedObject();
      const setter = objectToolSetters.get(tool);
      if (setter && preselected) { setter(preselected); viewer.selectObject(preselected); ctx.setHint(tool.prompt()); }
    },
    stop() {
      tool?.reset();
      tool = undefined;
      activeKey = undefined;
      viewer.setGestureMode(false);
      ctx.setVcb("");
    },
    cancel() { tool?.reset(); ctx.setVcb(""); },
    enter(typed) {
      if (!tool?.value) return;
      const problem = tool.value(typed);
      if (problem) ctx.setStatus(problem);
    },
    active: () => activeKey,
    deleteSelection() {
      const objects = ctx.selectedObjects();
      const faces = ctx.selectedFaces();
      const edges = ctx.selectedEdges();
      if (edges.length && !faces.length && !objects.length) void commit("loose-edge-erase", {edges}, `${edges.length} edge(s) erased`);
      else if (faces.length) void commit("loose-erase", {face_indices: faces}, `${faces.length} face(s) erased`);
      else if (objects.length) void commit("object-lifecycle", {object_ids: objects, operation: "delete"}, `${objects.length} object(s) deleted`);
      else ctx.setStatus("Nothing is selected.");
    },
    groupSelection({component, connected}) {
      const faces = ctx.selectedFaces();
      const objects = ctx.selectedObjects();
      if (!faces.length && !objects.length) {
        ctx.setStatus("Select objects or loose faces first (click, Shift-click to add, or drag a box).");
        return;
      }
      if (objects.some(id => id.includes("/")) || (faces.length && viewer.getEditContext())) {
        ctx.setStatus("Make group works on top-level objects and loose faces: leave the group you are editing first.");
        return;
      }
      void commit("loose-group", {
        name: component ? "Component" : "Group", component, connected,
        ...(faces.length ? {face_indices: faces} : {}),
        ...(objects.length ? {object_ids: objects} : {}),
      }, component ? "component made" : "group made");
    },
    joinSegments() {
      const edges = ctx.selectedEdges();
      if (edges.length < 2) { ctx.setStatus("Select two or more loose edges first (Shift-click, or drag a box)."); return; }
      void commit("loose-edge-join", {edges}, "segments joined");
    },
    bridgeSelection() {
      const faces = ctx.selectedFaces();
      const edges = ctx.selectedEdges();
      if (faces.length + (edges.length ? 1 : 0) < 2 && !(edges.length >= 2)) {
        ctx.setStatus("Select two loose faces, a face and a line, or two lines to bridge.");
        return;
      }
      void commit("loose-bridge", {
        ...(faces.length ? {face_indices: faces} : {}),
        ...(edges.length ? {edges} : {}),
      }, "bridge made");
    },
    async resegmentSelection() {
      const edges = ctx.selectedEdges();
      if (!edges.length) { ctx.setStatus("Select an edge of a circle, arc or polygon first."); return; }
      const answer = await ctx.ask("Number of segments", "24");
      if (answer === null) return;
      const segments = Math.round(Number(answer.trim().replace(/s$/i, "")));
      if (!Number.isFinite(segments) || segments < 2 || segments > 999) { ctx.setStatus("Type a whole number from 2 to 999."); return; }
      void commit("loose-resegment", {edge: edges[0], segments}, `${segments} segments`);
    },
    async scaleSelection() {
      const objects = ctx.selectedObjects();
      if (objects.length !== 1) { ctx.setStatus("Select one object to scale."); return; }
      const answer = await ctx.ask("Scale along X, Y, Z (1 = unscaled; one number scales all three)", "1, 1, 1");
      if (answer === null) return;
      const numbers = answer.split(/[\s,;]+/).filter(Boolean).map(Number);
      const scale = numbers.length === 1 ? [numbers[0], numbers[0], numbers[0]] : numbers;
      if (scale.length !== 3 || scale.some(value => !Number.isFinite(value) || value <= 0)) {
        ctx.setStatus("Type one positive number, or three (X, Y, Z).");
        return;
      }
      void commit("set-object-scale", {object_id: objects[0], scale}, "scaled");
    },
    async makeFacesExtrude() {
      const edges = ctx.selectedEdges();
      if (edges.length < 3) { ctx.setStatus("Select the loose edges that close the outlines first (drag a box over the plan)."); return; }
      const answer = await ctx.ask(`Extrude height (${ctx.unitLabel()})`, "3");
      if (answer === null) return;
      const height = parse(answer) * ctx.unitFactor();
      if (!Number.isFinite(height) || height === 0) { ctx.setStatus("Type a height other than zero."); return; }
      void commit("loose-make-faces-extrude", {edges, height}, "faces made and extruded");
    },
    cutOpening(on) {
      const objects = ctx.selectedObjects();
      if (!objects.length) { ctx.setStatus("Select the windows or doors first."); return; }
      void commit("set-cut-opening", {object_ids: objects, on}, on ? "opening cut" : "opening closed");
    },
    async createTerrain() {
      const unit = ctx.unitLabel();
      const answer = await ctx.ask(`Terrain: width, depth, cell size and relief (${unit}), from the origin`, "20, 20, 1, 0");
      if (answer === null) return;
      const [width, depth, cell, relief = 0] = answer.split(/[\s,;]+/).filter(Boolean).map(value => parse(value) * ctx.unitFactor());
      if (![width, depth, cell, relief].every(Number.isFinite) || width <= 0 || depth <= 0 || cell <= 0 || relief < 0) {
        ctx.setStatus("Type width, depth and cell size above zero, and a relief of zero or more.");
        return;
      }
      void commit("terrain-create", {corner_a: [0, 0, 0], corner_b: [width, depth, 0], cell, relief}, "terrain made");
    },
    async deformTerrain(objectId, point) {
      const answer = await ctx.ask(`Raise the ground here: radius and height (${ctx.unitLabel()}; a negative height lowers it)`, "3, 1");
      if (answer === null) return;
      const [radius, height] = answer.split(/[\s,;]+/).filter(Boolean).map(value => parse(value) * ctx.unitFactor());
      if (!Number.isFinite(radius) || radius <= 0 || !Number.isFinite(height) || height === 0) {
        ctx.setStatus("Type a radius above zero and a height other than zero.");
        return;
      }
      void commit("terrain-deform", {object_id: objectId, center: point, radius, height}, "ground reshaped");
    },
    explodeCurve() {
      const edges = ctx.selectedEdges();
      if (!edges.length) { ctx.setStatus("Select the edges of a circle or an arc first."); return; }
      void commit("loose-edge-explode-curve", {edges}, "curve exploded");
    },
    explodeSelection() {
      const objects = ctx.selectedObjects();
      if (!objects.length) { ctx.setStatus("Select the groups to explode first."); return; }
      void commit("explode-object", {object_ids: objects}, "exploded");
    },
    async selectConnected() {
      const record = ctx.record();
      const faces = ctx.selectedFaces();
      if (!record || !faces.length) { ctx.setStatus("Click a loose face first."); return; }
      const response = await fetch(`/api/v1/documents/${encodeURIComponent(record.id)}/revisions/${record.latest_revision}/loose-connected?face=${faces[0]}${viewer.getEditContext() ? `&object_id=${encodeURIComponent(viewer.getEditContext()!)}` : ""}`);
      if (!response.ok) { ctx.setStatus("Could not find the connected faces."); return; }
      const {faces: connected} = await response.json() as {faces: number[]};
      ctx.selectFaces(connected);
      ctx.setStatus(`${connected.length} connected faces selected.`);
    },
  };
}
