/**
 * The set of selected objects, loose faces and loose edges.
 *
 * A click selects one thing; Shift or Ctrl/Cmd-click adds to or removes from
 * the set. Tools that act on a selection (Move, Eraser, Paint, Delete,
 * Make group, Join segments) read it from here.
 */
import type {IngeTrazoViewer, LooseEdge, SnapInfo} from "./viewer";

export interface Selection {
  objects: () => string[];
  faces: () => number[];
  edges: () => LooseEdge[];
  isEmpty: () => boolean;
  clear: () => void;
  /** Replace the selection with these loose faces (for example, everything connected). */
  setFaces: (faces: number[]) => void;
  setObjects: (ids: string[]) => void;
  setEdges: (edges: LooseEdge[]) => void;
  hasEdge: (edge: LooseEdge) => boolean;
  onChange: (listener: () => void) => void;
}

/** The same edge whichever way round its endpoints are given. */
const edgeKey = ([a, b]: LooseEdge): string => {
  const point = (p: number[]) => p.map(v => v.toFixed(4)).join(",");
  const [first, second] = [point(a), point(b)].sort();
  return `${first}|${second}`;
};

export function mountSelection(viewer: IngeTrazoViewer): Selection {
  let objects: string[] = [];
  let faces: number[] = [];
  let edges: LooseEdge[] = [];
  const listeners: (() => void)[] = [];

  function changed(): void {
    viewer.setHighlights(objects, faces, edges);
    for (const listener of listeners) listener();
  }

  function toggle<T>(list: T[], value: T): T[] {
    return list.includes(value) ? list.filter(item => item !== value) : [...list, value];
  }

  function toggleEdge(list: LooseEdge[], edge: LooseEdge): LooseEdge[] {
    const key = edgeKey(edge);
    return list.some(item => edgeKey(item) === key) ? list.filter(item => edgeKey(item) !== key) : [...list, edge];
  }

  function mergeEdges(list: LooseEdge[], more: LooseEdge[]): LooseEdge[] {
    const seen = new Set(list.map(edgeKey));
    return [...list, ...more.filter(edge => !seen.has(edgeKey(edge)))];
  }

  viewer.onSelectClick = (snap: SnapInfo | null, additive: boolean) => {
    const face = snap?.looseFace;
    const object = snap?.objectId;
    // A loose edge under the cursor wins over what lies behind it.
    const edge = face === undefined ? snap?.looseEdge : undefined;
    if (!additive) {
      objects = !edge && face === undefined && object ? [object] : [];
      faces = face !== undefined ? [face] : [];
      edges = edge ? [edge] : [];
      changed();
      return;
    }
    if (edge) edges = toggleEdge(edges, edge);
    else if (face !== undefined) faces = toggle(faces, face);
    else if (object) objects = toggle(objects, object);
    changed();
  };

  viewer.onBoxSelect = ({objects: inBox, faces: facesInBox, edges: edgesInBox}, additive) => {
    if (additive) {
      objects = [...new Set([...objects, ...inBox])];
      faces = [...new Set([...faces, ...facesInBox])];
      edges = mergeEdges(edges, edgesInBox);
    } else {
      objects = inBox;
      faces = facesInBox;
      edges = edgesInBox;
    }
    changed();
  };

  return {
    objects: () => objects,
    faces: () => faces,
    edges: () => edges,
    isEmpty: () => !objects.length && !faces.length && !edges.length,
    clear() { if (objects.length || faces.length || edges.length) { objects = []; faces = []; edges = []; changed(); } },
    setFaces(list) { objects = []; edges = []; faces = [...list]; changed(); },
    setObjects(list) { faces = []; edges = []; objects = [...list]; changed(); },
    hasEdge: edge => edges.some(item => edgeKey(item) === edgeKey(edge)),
    setEdges(list) { objects = []; faces = []; edges = [...list]; changed(); },
    onChange: listener => { listeners.push(listener); },
  };
}
