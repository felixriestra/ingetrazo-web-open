/**
 * Declarative tool forms: one small description per tool, one generic renderer.
 *
 * Each form posts to a modeling command, so the browser never builds geometry
 * itself. Lengths are typed in the document's units and converted to metres
 * here; the server only ever sees metres.
 */
import {responseApiError} from "./api";

export interface ToolFormContext {
  record: () => {id: string; latest_revision: number; name: string} | undefined;
  selectedObject: () => string | undefined;
  describeObject: (id: string) => string;
  unitFactor: () => number;
  unitLabel: () => string;
  presentationDirty: () => boolean;
  applyRevision: (revised: unknown, message: string) => Promise<void>;
  setStatus: (text: string) => void;
  layerNames: () => string[];
  camera: () => {eye: [number, number, number]; target: [number, number, number]; fov_deg: number; perspective: boolean};
}

type Option = [value: string, label: string];
type Field =
  | {name: string; label: string; type: "number"; value: number; length?: boolean; min?: number; max?: number; step?: number}
  | {name: string; label: string; type: "text"; value: string}
  | {name: string; label: string; type: "select"; value: string; options: Option[]; dynamic?: "layers"}
  | {name: string; label: string; type: "checkbox"; value: boolean}
  | {name: string; label: string; type: "lines"; value: string; placeholder: string}
  | {name: string; label: string; type: "vec"; value: number[]; labels: string[]; length?: boolean}
  | {name: string; label: string; type: "object"};

type Values = Record<string, unknown>;
type Built = Record<string, unknown> | string;

interface ToolForm {
  title: string;
  hint: string;
  endpoint: string;
  fields: Field[];
  submit: string;
  needsSelection?: boolean;
  /** Return the request body (without base_revision) or a message describing what is wrong. */
  build: (values: Values, helpers: Helpers) => Built;
  done: string;
}

interface Helpers {
  /** Convert a value typed in document units to metres. */
  metres: (value: number) => number;
  selected: string | undefined;
  camera: ToolFormContext["camera"];
  rows: (text: string, width: number) => number[][] | string;
}

const PLANE: Field = {
  name: "plane", label: "Plane", type: "select", value: "xy",
  options: [["xy", "XY (ground)"], ["xz", "XZ"], ["yz", "YZ"]],
};
const ORIGIN: Field = {name: "origin", label: "Origin", type: "vec", value: [0, 0, 0], labels: ["X", "Y", "Z"], length: true};
const NAME = (value: string): Field => ({name: "name", label: "Name", type: "text", value});
const AXIS: Field = {
  name: "axis", label: "Axis", type: "select", value: "x",
  options: [["x", "X (red)"], ["y", "Y (green)"], ["z", "Z (blue)"]],
};

const solid = (key: string, title: string, hint: string, firstLabel: string, secondLabel: string): ToolForm => ({
  title, hint, endpoint: "solid-operation", submit: title,
  fields: [
    {name: "first", label: firstLabel, type: "object"},
    {name: "second", label: secondLabel, type: "object"},
  ],
  build: values => {
    if (!values.first || !values.second) return "Choose both solids: select one in the model, then press its Use selected button.";
    if (values.first === values.second) return "Choose two different solids.";
    return {operation: key, object_ids: [values.first, values.second]};
  },
  done: `${title} applied`,
});

const num = (values: Values, name: string) => Number(values[name]);
const vec = (values: Values, name: string) => values[name] as number[];

export const FORMS: Record<string, ToolForm> = {
  flip: {
    title: "Flip", hint: "Mirror the selected object across its own centre.",
    endpoint: "flip-object", submit: "Flip", needsSelection: true,
    fields: [AXIS, {name: "copy", label: "Flip a copy (keep the original)", type: "checkbox", value: false}],
    build: (values, h) => ({object_id: h.selected, axis: values.axis, copy: values.copy}),
    done: "object flipped",
  },
  polygon: {
    title: "Polygon", hint: "Regular polygon: sides, radius to the corners, origin.",
    endpoint: "create-shape", submit: "Create polygon",
    fields: [NAME("Polygon"), PLANE,
      {name: "sides", label: "Sides", type: "number", value: 6, min: 3, max: 256, step: 1},
      {name: "radius", label: "Radius", type: "number", value: 1, length: true, min: 0},
      {name: "start_degrees", label: "Rotation °", type: "number", value: 0, step: 1},
      ORIGIN],
    build: (v, h) => ({operation: "polygon", name: v.name, plane: v.plane, sides: num(v, "sides"),
      radius: h.metres(num(v, "radius")), start_degrees: num(v, "start_degrees"), origin: vec(v, "origin").map(h.metres)}),
    done: "polygon created",
  },
  rotated_rect: {
    title: "Rotated Rectangle", hint: "Rectangle turned by an angle about its origin corner.",
    endpoint: "create-shape", submit: "Create rectangle",
    fields: [NAME("Rotated rectangle"), PLANE,
      {name: "width", label: "Width", type: "number", value: 2, length: true, min: 0},
      {name: "depth", label: "Depth", type: "number", value: 1, length: true, min: 0},
      {name: "angle_degrees", label: "Angle °", type: "number", value: 30, step: 1},
      ORIGIN],
    build: (v, h) => ({operation: "rotated_rectangle", name: v.name, plane: v.plane, width: h.metres(num(v, "width")),
      depth: h.metres(num(v, "depth")), angle_degrees: num(v, "angle_degrees"), origin: vec(v, "origin").map(h.metres)}),
    done: "rotated rectangle created",
  },
  arc: {
    title: "Arc (two points)", hint: "Chord start and end, plus how far the arc bulges from the chord.",
    endpoint: "create-shape", submit: "Create arc",
    fields: [NAME("Arc"), PLANE,
      {name: "start", label: "Start (u, v)", type: "vec", value: [0, 0], labels: ["U", "V"], length: true},
      {name: "end", label: "End (u, v)", type: "vec", value: [2, 0], labels: ["U", "V"], length: true},
      {name: "bulge", label: "Bulge", type: "number", value: 0.5, length: true},
      {name: "segments", label: "Segments", type: "number", value: 16, min: 2, max: 256, step: 1},
      ORIGIN],
    build: (v, h) => ({operation: "arc2", name: v.name, plane: v.plane, start: vec(v, "start").map(h.metres),
      end: vec(v, "end").map(h.metres), bulge: h.metres(num(v, "bulge")), segments: num(v, "segments"),
      origin: vec(v, "origin").map(h.metres)}),
    done: "arc created",
  },
  arc3: {
    title: "3 Point Arc", hint: "An arc through three points: start, a point on the arc, end.",
    endpoint: "create-shape", submit: "Create arc",
    fields: [NAME("Arc"), PLANE,
      {name: "start", label: "Start (u, v)", type: "vec", value: [1, 0], labels: ["U", "V"], length: true},
      {name: "through", label: "Through (u, v)", type: "vec", value: [0, 1], labels: ["U", "V"], length: true},
      {name: "end", label: "End (u, v)", type: "vec", value: [-1, 0], labels: ["U", "V"], length: true},
      {name: "segments", label: "Segments", type: "number", value: 16, min: 2, max: 256, step: 1},
      ORIGIN],
    build: (v, h) => ({operation: "arc3", name: v.name, plane: v.plane, start: vec(v, "start").map(h.metres),
      through: vec(v, "through").map(h.metres), end: vec(v, "end").map(h.metres), segments: num(v, "segments"),
      origin: vec(v, "origin").map(h.metres)}),
    done: "arc created",
  },
  pie: {
    title: "Pie", hint: "A wedge: radius, start angle and sweep about the origin.",
    endpoint: "create-shape", submit: "Create pie",
    fields: [NAME("Pie"), PLANE,
      {name: "radius", label: "Radius", type: "number", value: 1, length: true, min: 0},
      {name: "start_degrees", label: "Start °", type: "number", value: 0, step: 1},
      {name: "sweep_degrees", label: "Sweep °", type: "number", value: 90, min: -359.999, max: 359.999, step: 1},
      {name: "segments", label: "Segments", type: "number", value: 16, min: 2, max: 256, step: 1},
      ORIGIN],
    build: (v, h) => ({operation: "pie", name: v.name, plane: v.plane, radius: h.metres(num(v, "radius")),
      start_degrees: num(v, "start_degrees"), sweep_degrees: num(v, "sweep_degrees"), segments: num(v, "segments"),
      origin: vec(v, "origin").map(h.metres)}),
    done: "pie created",
  },
  freehand: {
    title: "Freehand", hint: "A polyline from points, one \"u, v\" pair per line.",
    endpoint: "create-shape", submit: "Create curve",
    fields: [NAME("Freehand"), PLANE,
      {name: "points", label: "Points (u, v per line)", type: "lines", value: "0, 0\n1, 0.4\n2, 0\n3, 0.6", placeholder: "0, 0"},
      {name: "closed", label: "Close into a face", type: "checkbox", value: false},
      ORIGIN],
    build: (v, h) => {
      const rows = h.rows(String(v.points), 2);
      if (typeof rows === "string") return rows;
      return {operation: "freehand", name: v.name, plane: v.plane, points: rows.map(r => r.map(h.metres)),
        closed: v.closed, origin: vec(v, "origin").map(h.metres)};
    },
    done: "curve created",
  },
  followme: {
    title: "Follow Me", hint: "Sweep the selected profile (a single face) along a path of points.",
    endpoint: "follow-me", submit: "Sweep", needsSelection: true,
    fields: [
      {name: "path", label: "Path (x, y, z per line)", type: "lines", value: "0, 0, 0\n0, 0, 2", placeholder: "0, 0, 0"},
      {name: "closed", label: "Closed loop", type: "checkbox", value: false}],
    build: (v, h) => {
      const rows = h.rows(String(v.path), 3);
      if (typeof rows === "string") return rows;
      return {object_id: h.selected, path: rows.map(r => r.map(h.metres)), closed: v.closed};
    },
    done: "profile swept along the path",
  },
  fillet: {
    title: "Fillet", hint: "Round every sharp edge of the selected object.",
    endpoint: "fillet", submit: "Round edges", needsSelection: true,
    fields: [
      {name: "radius", label: "Radius", type: "number", value: 0.1, length: true, min: 0},
      {name: "segments", label: "Segments", type: "number", value: 8, min: 1, max: 64, step: 1}],
    build: (v, h) => ({object_id: h.selected, edges: "sharp", radius: h.metres(num(v, "radius")), segments: num(v, "segments")}),
    done: "edges rounded",
  },
  protractor: {
    title: "Protractor", hint: "A construction guide through a point at an angle from the U axis of a plane.",
    endpoint: "create-annotation", submit: "Create guide",
    fields: [PLANE,
      {name: "point", label: "Through point", type: "vec", value: [0, 0, 0], labels: ["X", "Y", "Z"], length: true},
      {name: "angle", label: "Angle °", type: "number", value: 45, step: 1}],
    build: (v, h) => {
      const a = (num(v, "angle") * Math.PI) / 180;
      const [c, s] = [Math.cos(a), Math.sin(a)];
      const direction = v.plane === "xz" ? [c, 0, s] : v.plane === "yz" ? [0, c, s] : [c, s, 0];
      return {operation: "guide-line", point: vec(v, "point").map(h.metres), direction};
    },
    done: "angled guide created",
  },
  text3d: {
    title: "3D Text", hint: "Extruded text placed at a point (the text height is the capital height).",
    endpoint: "create-text3d", submit: "Insert 3D text",
    fields: [
      {name: "text", label: "Text", type: "text", value: "Text"},
      {name: "height", label: "Height", type: "number", value: 0.25, length: true, min: 0},
      {name: "thickness", label: "Thickness", type: "number", value: 0.05, length: true, min: 0},
      {name: "bold", label: "Bold", type: "checkbox", value: true},
      {name: "italic", label: "Italic", type: "checkbox", value: false},
      ORIGIN],
    build: (v, h) => ({text: v.text, height: h.metres(num(v, "height")), thickness: h.metres(num(v, "thickness")),
      bold: v.bold, italic: v.italic, origin: vec(v, "origin").map(h.metres)}),
    done: "3D text inserted",
  },
  layer_new: {
    title: "New layer", hint: "Layers (tags) organise what you can show, hide and recall in scenes.",
    endpoint: "create-layer", submit: "Create layer",
    fields: [{name: "name", label: "Name", type: "text", value: "Layer 1"}],
    build: v => ({name: v.name}),
    done: "layer created",
  },
  layer_assign: {
    title: "Move to layer", hint: "Put the selected object on a layer.",
    endpoint: "assign-layer", submit: "Move to layer", needsSelection: true,
    fields: [{name: "layer", label: "Layer", type: "select", value: "", options: [], dynamic: "layers"}],
    build: (v, h) => ({object_id: h.selected, layer: v.layer}),
    done: "object moved to the layer",
  },
  scene_add: {
    title: "Add scene", hint: "Save the current camera and layer visibility under a name.",
    endpoint: "save-scene", submit: "Save scene",
    fields: [{name: "name", label: "Name", type: "text", value: "Scene 1"}],
    build: (v, h) => ({name: v.name, ...h.camera()}),
    done: "scene saved",
  },
  scene_delete: {
    title: "Delete scene", hint: "Remove a saved scene by name.",
    endpoint: "delete-scene", submit: "Delete scene",
    fields: [{name: "name", label: "Scene name", type: "text", value: ""}],
    build: v => ({name: v.name}),
    done: "scene deleted",
  },
  section_fill: {
    title: "Section Fill", hint: "Fill the cut faces of a section with a solid colour (saved in the document).",
    endpoint: "section-fill", submit: "Apply",
    fields: [{name: "enabled", label: "Fill section cuts", type: "checkbox", value: true}],
    build: v => ({enabled: v.enabled}),
    done: "section fill saved",
  },
  outer_shell: solid("outer_shell", "Outer Shell", "Merge solids into one, keeping only the outer skin.", "Solid 1", "Solid 2"),
  solid_union: solid("union", "Union", "Join two solids into one.", "Solid 1", "Solid 2"),
  solid_subtract: solid("subtract", "Subtract", "Cut the first solid out of the second.", "Cutter", "Target"),
  solid_trim: solid("trim", "Trim", "Cut the second solid with the first, keeping the first.", "Cutter", "Target"),
  solid_intersect: solid("intersect", "Intersect", "Keep only the volume the two solids share.", "Solid 1", "Solid 2"),
  solid_split: solid("split", "Split", "Split two overlapping solids into the three resulting parts.", "Solid 1", "Solid 2"),
};

export interface ToolForms {
  has: (key: string) => boolean;
  show: (key: string) => string;
  refreshSelection: (reveal?: boolean) => void;
  hide: () => void;
}

export function mountToolForms(context: ToolFormContext): ToolForms {
  const panel = document.querySelector<HTMLElement>("#tool-panel")!;
  const heading = panel.querySelector<HTMLElement>("h2")!;
  const body = panel.querySelector<HTMLElement>(".tool-form")!;
  let activeKey: string | undefined;
  let objectSlots: Record<string, string | undefined> = {};
  let selectionNote: HTMLElement | undefined;
  const readers: Record<string, () => unknown> = {};

  const helpers = (): Helpers => ({
    metres: value => value * context.unitFactor(),
    selected: context.selectedObject(),
    camera: context.camera,
    rows: (text, width) => {
      const rows: number[][] = [];
      for (const line of text.split(/\r?\n/)) {
        if (!line.trim()) continue;
        const parts = line.split(/[,;\s]+/).filter(Boolean).map(Number);
        if (parts.length !== width || parts.some(item => !Number.isFinite(item))) {
          return `Each line needs ${width} numbers, for example "${Array.from({length: width}, (_, i) => i).join(", ")}".`;
        }
        rows.push(parts);
      }
      return rows;
    },
  });

  function field(spec: Field): HTMLElement {
    const label = document.createElement("label");
    label.className = "tool-field";
    const caption = document.createElement("span");
    caption.textContent = spec.type === "number" || spec.type === "vec"
      ? `${spec.label}${spec.length ? ` (${context.unitLabel()})` : ""}` : spec.label;
    if (spec.type === "checkbox") {
      const input = document.createElement("input");
      input.type = "checkbox";
      input.checked = spec.value;
      label.className = "keep-base";
      label.append(input, ` ${spec.label}`);
      readers[spec.name] = () => input.checked;
      return label;
    }
    label.append(caption);
    if (spec.type === "number") {
      const input = document.createElement("input");
      input.type = "number";
      input.value = String(spec.value);
      input.step = String(spec.step ?? "any");
      if (spec.min !== undefined) input.min = String(spec.min);
      if (spec.max !== undefined) input.max = String(spec.max);
      label.append(input);
      readers[spec.name] = () => Number(input.value);
    } else if (spec.type === "text") {
      const input = document.createElement("input");
      input.type = "text";
      input.value = spec.value;
      input.maxLength = 255;
      label.append(input);
      readers[spec.name] = () => input.value.trim();
    } else if (spec.type === "select") {
      const select = document.createElement("select");
      const options: Option[] = spec.dynamic === "layers" ? context.layerNames().map(n => [n, n] as Option) : spec.options;
      for (const [value, text] of options) select.append(new Option(text, value, false, value === spec.value));
      label.append(select);
      readers[spec.name] = () => select.value;
    } else if (spec.type === "lines") {
      const area = document.createElement("textarea");
      area.rows = 5;
      area.value = spec.value;
      area.placeholder = spec.placeholder;
      label.append(area);
      readers[spec.name] = () => area.value;
    } else if (spec.type === "vec") {
      const row = document.createElement("div");
      row.className = "move-fields";
      const inputs = spec.labels.map((text, index) => {
        const input = document.createElement("input");
        input.type = "number";
        input.step = "any";
        input.value = String(spec.value[index]);
        input.setAttribute("aria-label", `${spec.label} ${text}`);
        row.append(input);
        return input;
      });
      label.append(row);
      readers[spec.name] = () => inputs.map(input => Number(input.value));
    } else {
      const row = document.createElement("div");
      row.className = "object-slot";
      const shown = document.createElement("output");
      const pick = document.createElement("button");
      pick.type = "button";
      pick.className = "secondary-button";
      pick.textContent = "Use selected";
      const render = () => {
        const id = objectSlots[spec.name];
        shown.textContent = id ? context.describeObject(id) : "none chosen";
      };
      pick.addEventListener("click", () => {
        const id = context.selectedObject();
        if (!id) { context.setStatus("Select an object in the model first."); return; }
        objectSlots[spec.name] = id;
        render();
      });
      render();
      row.append(shown, pick);
      label.append(row);
      readers[spec.name] = () => objectSlots[spec.name];
    }
    return label;
  }

  function refreshSelection(reveal = false): void {
    if (!selectionNote || !activeKey) return;
    // Picking scrolls the sidebar to the object list; bring the tool back into view.
    if (reveal && !panel.hidden) setTimeout(() => panel.scrollIntoView({block: "start", behavior: "smooth"}), 80);
    const spec = FORMS[activeKey];
    if (!spec.needsSelection) { selectionNote.hidden = true; return; }
    const id = context.selectedObject();
    selectionNote.hidden = false;
    selectionNote.textContent = id ? `Selected: ${context.describeObject(id)}` : "Select a top-level object in the model first.";
    selectionNote.classList.toggle("warn", !id);
  }

  async function submit(spec: ToolForm): Promise<void> {
    const record = context.record();
    if (!record) { context.setStatus("Open a stored document first."); return; }
    if (context.presentationDirty()) {
      context.setStatus("Save or revert presentation changes before editing geometry.");
      return;
    }
    const values: Values = {};
    for (const [name, read] of Object.entries(readers)) values[name] = read();
    const built = spec.build(values, helpers());
    if (typeof built === "string") { context.setStatus(built); return; }
    if (spec.needsSelection && !context.selectedObject()) {
      context.setStatus("Select a top-level object in the model first.");
      return;
    }
    context.setStatus(`${spec.title}: saving revision ${record.latest_revision + 1}…`);
    try {
      const response = await fetch(
        `/api/v1/documents/${encodeURIComponent(record.id)}/commands/${spec.endpoint}`,
        {method: "POST", headers: {"Content-Type": "application/json"},
          body: JSON.stringify({base_revision: record.latest_revision, ...built})},
      );
      if (!response.ok) {
        throw await responseApiError(response);
      }
      await context.applyRevision(await response.json(), spec.done);
    } catch (error) {
      context.setStatus(`${spec.title} failed: ${error instanceof Error ? error.message : String(error)}`);
    }
  }

  return {
    has: key => key in FORMS,
    show(key) {
      const spec = FORMS[key];
      activeKey = key;
      objectSlots = {};
      for (const name of Object.keys(readers)) delete readers[name];
      body.replaceChildren();
      heading.textContent = spec.title;
      const hint = document.createElement("p");
      hint.className = "muted";
      hint.textContent = spec.hint;
      selectionNote = document.createElement("p");
      selectionNote.className = "selection-note";
      const form = document.createElement("form");
      form.className = "create-box";
      form.noValidate = true;   // the server validates; native step checks reject legal angles
      for (const item of spec.fields) form.append(field(item));
      const button = document.createElement("button");
      button.type = "submit";
      button.className = "secondary-button";
      button.textContent = spec.submit;
      form.append(button);
      form.addEventListener("submit", event => { event.preventDefault(); void submit(spec); });
      body.append(hint, selectionNote, form);
      panel.hidden = false;
      refreshSelection();
      panel.scrollIntoView({block: "nearest"});
      form.querySelector<HTMLElement>("input, select, textarea")?.focus({preventScroll: true});
      return spec.hint;
    },
    refreshSelection,
    hide() { activeKey = undefined; if (!panel.hidden) panel.hidden = true; },
  };
}
