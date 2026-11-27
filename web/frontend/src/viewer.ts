import * as THREE from "three";
import {OrbitControls} from "three/examples/jsm/controls/OrbitControls.js";
import {Line2} from "three/examples/jsm/lines/Line2.js";
import {LineGeometry} from "three/examples/jsm/lines/LineGeometry.js";
import {LineMaterial} from "three/examples/jsm/lines/LineMaterial.js";
import {GLTFLoader} from "three/examples/jsm/loaders/GLTFLoader.js";
import type {
  CameraHome, DimensionDetail, GuideDetail, MeasurementInfo, PickInfo,
  DisplayStyleDetail, GeoPathDetail, MapDetail, PhotogrammetryDetail, SectionPlaneDetail, SunDetail,
  SurveyPointDetail, TextLabelDetail,
} from "./types";

export type ViewName = "iso" | "top" | "front" | "right" | "left" | "back" | "bottom";
export type NavigationMode = "orbit" | "pan" | "zoom";
/** A snapped point under the cursor, in IngeTrazo's Z-up metres. */
export interface SnapInfo {
  point: [number, number, number];
  inference: string;
  /** Surface normal (Z-up) when the point is on a face. */
  normal?: [number, number, number];
  /** Top-level object id (``group:N``) of what the cursor is over, if any. */
  objectId?: string;
  objectName?: string;
  /** Index of the loose (ungrouped) face under the cursor, when it is one. */
  looseFace?: number;
  /** The free loose edge under the cursor, as two Z-up endpoints. */
  looseEdge?: LooseEdge;
}
/** A loose edge as two Z-up endpoints. */
export type LooseEdge = [[number, number, number], [number, number, number]];
export type SnapConstraint =
  | {kind: "plane"; point: [number, number, number]; normal: [number, number, number]}
  | {kind: "axis"; origin: [number, number, number]; direction: [number, number, number]}
  | null;
export type WalkMode = "position_camera" | "walk" | "look_around" | "first_person";

const toZup = (v: THREE.Vector3): [number, number, number] => [v.x, -v.z, v.y];


/** An object's layer and the layers of the groups around it, outermost first. */
function layerPath(semantic: Record<string, unknown> | undefined): string[] {
  if (!semantic) return [];
  const path = Array.isArray(semantic.layer_path)
    ? semantic.layer_path.filter((name): name is string => typeof name === "string") : [];
  if (typeof semantic.layer === "string" && !path.includes(semantic.layer)) path.push(semantic.layer);
  return path;
}

export class IngeTrazoViewer {
  private readonly scene = new THREE.Scene();
  private readonly renderer: THREE.WebGLRenderer;
  private readonly ambient = new THREE.HemisphereLight(0xffffff, 0x44504c, 2.3);
  private readonly sun = new THREE.DirectionalLight(0xffffff, 2.2);
  private readonly perspective = new THREE.PerspectiveCamera(45, 1, 0.001, 1e7);
  private readonly orthographic = new THREE.OrthographicCamera(-1, 1, 1, -1, -1e7, 1e7);
  private camera: THREE.PerspectiveCamera | THREE.OrthographicCamera = this.perspective;
  private controls: OrbitControls;
  private navigation: NavigationMode = "orbit";
  /** Text labels, laid out in screen space so they stay readable and do not overlap. */
  private labelEntries: {
    sprite: THREE.Sprite; group: THREE.Group; base: THREE.Vector3; widthPx: number; heightPx: number;
    leader?: THREE.Line; anchor?: THREE.Vector3;
  }[] = [];
  private labelViewKey = "";
  /** Face-me figures: upright cut-outs the desktop turns toward the camera every frame. */
  private faceMe: {kind: "quad" | "mesh"; feet: THREE.Vector3; plane?: THREE.Mesh; pivot?: THREE.Group; heading?: number}[] = [];
  private gesture = false;
  private boxSelect = false;
  private boxStart: {x: number; y: number} | undefined;
  private boxEl: HTMLDivElement | undefined;
  /** Called when a drag in the Select tool ends: what the box took in. */
  onBoxSelect: (result: {objects: string[]; faces: number[]; edges: LooseEdge[]}, additive: boolean) => void = () => undefined;
  private editContext: string | undefined;
  onContextChange: (id: string | undefined) => void = () => undefined;
  private constraint: SnapConstraint = null;
  private readonly previewRoot = new THREE.Group();
  private snapMarker: THREE.Mesh | undefined;
  private edgeSegments = new Float32Array(0);
  /** World-space endpoints of free loose edges (pairs), which can be picked, erased and moved. */
  private looseEdgeSegments = new Float32Array(0);
  private pendingMove: PointerEvent | undefined;
  private zoomWindow = false;
  private zoomBox: HTMLDivElement | undefined;
  private walkMode: WalkMode | null = null;
  private walkDrag: {x: number; y: number} | undefined;
  private yaw = 0;
  private pitch = 0;
  private readonly heldKeys = new Set<string>();
  private lastFrame = performance.now();
  /** Called when a one-shot tool (Zoom Window, Position Camera) has finished. */
  onToolDone: () => void = () => undefined;
  /** A click in the Select tool, with whether it adds to the selection (Shift / Ctrl). */
  onSelectClick: (snap: SnapInfo | null, additive: boolean) => void = () => undefined;
  private readonly highlightRoot = new THREE.Group();
  onGestureMove: (snap: SnapInfo | null) => void = () => undefined;
  onGestureClick: (snap: SnapInfo | null) => void = () => undefined;
  onGestureDown: (snap: SnapInfo | null) => void = () => undefined;
  onGestureUp: (snap: SnapInfo | null) => void = () => undefined;
  private readonly grid = new THREE.GridHelper(100, 100, 0x73827d, 0x313a37);
  private readonly root = new THREE.Group();
  private edgeRoot = new THREE.Group();
  private readonly selectionRoot = new THREE.Group();
  private readonly sectionRoot = new THREE.Group();
  private readonly measurementRoot = new THREE.Group();
  private readonly annotationRoot = new THREE.Group();
  private readonly geospatialRoot = new THREE.Group();
  private readonly mapRoot = new THREE.Group();
  private readonly terrainRoot = new THREE.Group();
  private readonly axesRoot = new THREE.Group();
  private readonly raycaster = new THREE.Raycaster();
  private readonly pointer = new THREE.Vector2();
  private bounds = new THREE.Box3();
  private edgesVisible = true;
  private axesVisible = true;
  private readonly layerVisibility = new Map<string, boolean>();
  private hiddenObjectIds = new Set<string>();
  private sectionPlane: THREE.Plane | null = null;
  private pointerDown: {x: number; y: number} | undefined;
  private loadSequence = 0;
  private measuring = false;
  private sketching = false;
  private measureStart: THREE.Vector3 | undefined;
  onSelection: (selection: PickInfo | null) => void = () => undefined;
  onMeasurement: (measurement: MeasurementInfo | null) => void = () => undefined;
  onSketchPoint: (point: [number, number, number], inference: string) => void = () => undefined;

  constructor(private readonly canvas: HTMLCanvasElement) {
    this.renderer = new THREE.WebGLRenderer({canvas, antialias: true, alpha: true, logarithmicDepthBuffer: true});
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.localClippingEnabled = true;
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.scene.background = new THREE.Color(0x171c1b);
    this.sun.position.set(4, 6, 8);
    this.sun.castShadow = false;
    this.sun.shadow.mapSize.set(2048, 2048);
    this.scene.add(
      this.ambient, this.sun, this.sun.target, this.grid, this.root, this.edgeRoot, this.selectionRoot,
      this.sectionRoot, this.measurementRoot, this.annotationRoot, this.previewRoot, this.highlightRoot,
      this.mapRoot, this.terrainRoot, this.geospatialRoot, this.axesRoot,
    );
    // The GLB exporter has already converted IngeTrazo Z-up to glTF Y-up.
    this.perspective.up.set(0, 1, 0);
    this.orthographic.up.set(0, 1, 0);
    this.controls = this.makeControls(this.camera);
    canvas.addEventListener("pointerdown", event => {
      this.pointerDown = {x: event.clientX, y: event.clientY};
    });
    canvas.addEventListener("pointerup", event => {
      if (!this.pointerDown) return;
      const moved = Math.hypot(event.clientX - this.pointerDown.x, event.clientY - this.pointerDown.y);
      this.pointerDown = undefined;
      if (this.boxSelect && moved >= 4 && event.button === 0 && !this.gesture) {
        // The drag was a box: take in what it covers (left to right: fully inside; right to left: touching).
        const start = this.boxStart ?? {x: event.clientX, y: event.clientY};
        const crossing = event.clientX < start.x;
        this.onBoxSelect(this.selectInBox(start.x, start.y, event.clientX, event.clientY, crossing),
          event.shiftKey || event.ctrlKey || event.metaKey);
        this.disposeChildren(this.selectionRoot);
      } else if (this.gesture && !this.walkMode && !this.zoomWindow) {
        const snap = this.snapAt(event.clientX, event.clientY);
        this.onGestureUp(snap);
        if (moved < 4 && event.button === 0) this.onGestureClick(snap);
      } else if (moved < 4 && this.walkMode === "position_camera") this.placeCamera(event);
      else if (moved < 4 && !this.walkMode && !this.zoomWindow) {
        const additive = event.shiftKey || event.ctrlKey || event.metaKey;
        if (event.button === 0) this.onSelectClick(this.snapAt(event.clientX, event.clientY, false), additive);
        // A plain click also feeds the single-object inspector; an additive one only edits the set.
        if (additive) this.disposeChildren(this.selectionRoot);
        else this.pick(event);
      }
    });
    new ResizeObserver(() => this.resize()).observe(canvas.parentElement!);
    this.installModeHandlers();
    this.installGestureHandlers();
    this.installBoxHandlers();
    this.renderer.setAnimationLoop(() => {
      const now = performance.now();
      this.tickWalk(Math.min((now - this.lastFrame) / 1000, 0.1));
      this.lastFrame = now;
      this.controls.update();
      this.fitClipping();
      this.turnFaceMe();
      this.layoutLabels();
      this.renderer.render(this.scene, this.camera);
    });
    this.resize();
  }

  async load(url: string, keepCamera = false): Promise<boolean> {
    const sequence = ++this.loadSequence;
    const gltf = await new GLTFLoader().loadAsync(url);
    if (sequence !== this.loadSequence) return false;
    this.disposeChildren(this.root);
    this.disposeChildren(this.edgeRoot);
    this.disposeChildren(this.selectionRoot);
    this.clearMeasurement();
    this.disposeChildren(this.annotationRoot);
    this.disposeChildren(this.geospatialRoot);
    this.disposeChildren(this.mapRoot);
    this.disposeChildren(this.terrainRoot);
    this.onSelection(null);
    this.root.add(gltf.scene);
    this.setupFaceMe();
    this.layerVisibility.clear();
    this.hiddenObjectIds.clear();
    this.root.traverse(object => {
      const semantic = object.userData.ingetrazo_object as Record<string, unknown> | undefined;
      if (!semantic) return;
      if (typeof semantic.layer === "string" && typeof semantic.layer_visible === "boolean") {
        this.layerVisibility.set(semantic.layer, semantic.layer_visible);
      }
      // The layers of the groups around it: a group on a hidden layer hides its contents.
      const path = semantic.layer_path, pathVisible = semantic.layer_path_visible;
      if (Array.isArray(path) && Array.isArray(pathVisible)) {
        path.forEach((name, index) => {
          if (typeof name === "string" && typeof pathVisible[index] === "boolean" && !this.layerVisibility.has(name)) {
            this.layerVisibility.set(name, pathVisible[index] as boolean);
          }
        });
      }
      const visibilityId = typeof semantic.visibility_id === "string"
        ? semantic.visibility_id
        : semantic.native_id;
      if (semantic.hidden === true && typeof visibilityId === "string") {
        this.hiddenObjectIds.add(visibilityId);
      }
    });
    this.applyVisibility();
    this.applyClipping(this.root);
    this.recomputeBounds();
    if (this.bounds.isEmpty()) this.bounds.setFromCenterAndSize(new THREE.Vector3(), new THREE.Vector3(1, 1, 1));
    this.buildEdges();
    this.buildAxes();
    if (!keepCamera) this.fit();
    return true;
  }

  /** Frame the picked object, or the whole model when nothing is selected. */
  fitSelection(): void {
    const box = new THREE.Box3().setFromObject(this.selectionRoot);
    if (box.isEmpty()) { this.fit(); return; }
    this.fit(box);
  }

  fit(bounds: THREE.Box3 = this.bounds): void {
    const size = bounds.getSize(new THREE.Vector3());
    const center = bounds.getCenter(new THREE.Vector3());
    const radius = Math.max(size.length() / 2, 0.01);
    const direction = this.camera.position.clone().sub(this.controls.target).normalize();
    if (!Number.isFinite(direction.x) || direction.lengthSq() < 0.5) direction.set(1, 0.8, 1).normalize();
    if (this.camera instanceof THREE.PerspectiveCamera) {
      const distance = radius / Math.sin(THREE.MathUtils.degToRad(this.camera.fov / 2));
      this.camera.position.copy(center).addScaledVector(direction, distance * 1.15);
      this.camera.near = Math.max(distance / 10000, 0.001);
      this.camera.far = Math.max(distance * 100, 1000);
    } else {
      this.camera.position.copy(center).addScaledVector(direction, radius * 3);
      this.updateOrthographic(radius * 1.15);
    }
    this.controls.target.copy(center);
    this.camera.updateProjectionMatrix();
    this.controls.update();
  }

  setView(name: ViewName): void {
    const center = this.bounds.getCenter(new THREE.Vector3());
    const radius = Math.max(this.bounds.getSize(new THREE.Vector3()).length(), 1);
    const directions: Record<ViewName, THREE.Vector3> = {
      iso: new THREE.Vector3(1, 0.8, 1),
      top: new THREE.Vector3(0, 1, 0),
      front: new THREE.Vector3(0, 0, 1),
      right: new THREE.Vector3(1, 0, 0),
      left: new THREE.Vector3(-1, 0, 0),
      back: new THREE.Vector3(0, 0, -1),
      bottom: new THREE.Vector3(0, -1, 0),
    };
    this.camera.position.copy(center).addScaledVector(directions[name].normalize(), radius * 2);
    // Top and bottom look along the glTF Y axis, so "up" must be a horizontal axis.
    if (name === "top") this.camera.up.set(0, 0, -1);
    else if (name === "bottom") this.camera.up.set(0, 0, 1);
    else this.camera.up.set(0, 1, 0);
    this.controls.target.copy(center);
    this.fit();
  }

  toggleProjection(): "Perspective" | "Orthographic" {
    const oldPosition = this.camera.position.clone();
    const target = this.controls.target.clone();
    this.camera = this.camera instanceof THREE.PerspectiveCamera ? this.orthographic : this.perspective;
    this.camera.position.copy(oldPosition);
    this.camera.up.copy(this.camera === this.orthographic ? this.perspective.up : this.orthographic.up);
    this.controls.dispose();
    this.controls = this.makeControls(this.camera);
    this.controls.target.copy(target);
    this.resize();
    this.fit();
    return this.camera instanceof THREE.PerspectiveCamera ? "Perspective" : "Orthographic";
  }

  showEdges(show: boolean): void {
    this.edgesVisible = show;
    this.edgeRoot.visible = show;
  }

  showGrid(show: boolean): void {
    this.grid.visible = show;
  }

  showAxes(show: boolean): void {
    this.axesVisible = show;
    this.axesRoot.visible = show;
  }

  setAnnotations(
    dimensions: DimensionDetail[], labels: TextLabelDetail[], guides: GuideDetail[],
  ): void {
    this.disposeChildren(this.annotationRoot);
    this.labelEntries = [];
    this.labelViewKey = "";
    const solid = new THREE.LineBasicMaterial({color: 0x222725, depthTest: false});
    const guideMaterial = new THREE.LineDashedMaterial({
      color: 0x67bcd1, dashSize: 0.14, gapSize: 0.08, transparent: true, opacity: 0.8,
      depthTest: false,
    });
    const radius = Math.max(this.bounds.getSize(new THREE.Vector3()).length(), 1);
    for (const dimension of dimensions) {
      const group = new THREE.Group();
      group.userData.ingetrazo_layer = dimension.layer ?? "Layer 0";
      group.visible = dimension.visible;
      const [lineA, lineB] = dimension.line.map(point => this.fromZUp(point));
      this.addAnnotationLine([this.fromZUp(dimension.a), lineA, lineB], solid, false, group);
      this.addAnnotationLine([this.fromZUp(dimension.b), lineB], solid, false, group);
      const made = this.makeTextSprite(dimension.label, this.fromZUp(dimension.midpoint));
      group.add(made.sprite);
      this.labelEntries.push({sprite: made.sprite, group, base: made.sprite.position.clone(),
        widthPx: made.widthPx, heightPx: made.heightPx});
      this.annotationRoot.add(group);
    }
    for (const label of labels) {
      const group = new THREE.Group();
      group.userData.ingetrazo_layer = label.layer ?? "Layer 0";
      group.visible = label.visible;
      const anchor = this.fromZUp(label.anchor);
      const position = this.fromZUp(label.position);
      const leader = this.addAnnotationLine([anchor, position], solid, false, group);
      const made = this.makeTextSprite(label.text, position);
      group.add(made.sprite);
      this.labelEntries.push({sprite: made.sprite, group, base: position.clone(), leader, anchor,
        widthPx: made.widthPx, heightPx: made.heightPx});
      this.annotationRoot.add(group);
    }
    this.applyVisibility();
    for (const guide of guides) {
      const point = this.fromZUp(guide.point);
      if (guide.direction) {
        const direction = this.fromZUp(guide.direction).normalize();
        this.addAnnotationLine([
          point.clone().addScaledVector(direction, -radius * 5),
          point.clone().addScaledVector(direction, radius * 5),
        ], guideMaterial, true);
      } else {
        if (guide.origin) this.addAnnotationLine([this.fromZUp(guide.origin), point], guideMaterial, true);
        const marker = new THREE.Mesh(
          new THREE.SphereGeometry(radius * 0.006, 12, 8),
          new THREE.MeshBasicMaterial({color: 0x67bcd1, depthTest: false}),
        );
        marker.position.copy(point);
        marker.renderOrder = 900;
        this.annotationRoot.add(marker);
      }
    }
  }

  setGeospatial(points: SurveyPointDetail[], paths: GeoPathDetail[]): void {
    this.disposeChildren(this.geospatialRoot);
    const radius = Math.max(this.bounds.getSize(new THREE.Vector3()).length(), 1);
    const pointMaterial = new THREE.MeshBasicMaterial({color: 0xffb45f, depthTest: false});
    const pathMaterial = new THREE.LineBasicMaterial({color: 0xff8a5f, depthTest: false});
    for (const point of points) {
      const marker = new THREE.Mesh(
        new THREE.SphereGeometry(radius * 0.008, 12, 8), pointMaterial.clone(),
      );
      marker.position.copy(this.fromZUp(point.position));
      marker.renderOrder = 880;
      this.geospatialRoot.add(marker);
      if (point.name) {
        const labelPosition = marker.position.clone().add(new THREE.Vector3(0, radius * 0.025, 0));
        const made = this.makeTextSprite(point.name, labelPosition);
        const worldHeight = radius * 0.03;
        made.sprite.scale.set(worldHeight * made.widthPx / made.heightPx, worldHeight, 1);
        this.geospatialRoot.add(made.sprite);
      }
    }
    for (const path of paths) {
      const vertices = path.points.map(point => this.fromZUp(point));
      if (path.closed && vertices.length > 2) vertices.push(vertices[0].clone());
      if (vertices.length > 1) this.addAnnotationLine(
        vertices, pathMaterial, false, this.geospatialRoot,
      );
    }
  }

  setMap(map: MapDetail | null | undefined): void {
    this.disposeChildren(this.mapRoot);
    if (!map?.visible) return;
    const loader = new THREE.TextureLoader();
    loader.setCrossOrigin("anonymous");
    for (const tile of map.tiles) {
      if (tile.corners.length !== 4) continue;
      const positions = tile.corners.flatMap(corner => {
        const point = this.fromZUp(corner);
        point.y -= 0.01;
        return [point.x, point.y, point.z];
      });
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
      geometry.setAttribute("uv", new THREE.Float32BufferAttribute([
        0, 1, 1, 1, 1, 0, 0, 0,
      ], 2));
      geometry.setIndex([0, 1, 2, 0, 2, 3]);
      geometry.computeVertexNormals();
      const material = new THREE.MeshBasicMaterial({
        color: 0x87968f, opacity: Math.max(0, Math.min(1, map.opacity)),
        transparent: map.opacity < 1, side: THREE.DoubleSide,
      });
      const mesh = new THREE.Mesh(geometry, material);
      mesh.renderOrder = -100;
      this.mapRoot.add(mesh);
      loader.load(tile.url, texture => {
        texture.colorSpace = THREE.SRGBColorSpace;
        material.map = texture;
        material.color.set(0xffffff);
        material.needsUpdate = true;
      }, undefined, () => undefined);
    }
  }

  setReferenceMesh(reference: PhotogrammetryDetail | null | undefined): void {
    this.disposeChildren(this.terrainRoot);
    if (!reference?.visible || !reference.mesh) return;
    const geometry = new THREE.BufferGeometry();
    const positions = reference.mesh.vertices.flatMap(vertex => {
      const point = this.fromZUp(vertex);
      return [point.x, point.y, point.z];
    });
    geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
    geometry.setIndex(reference.mesh.triangles.flat());
    geometry.computeVertexNormals();
    const material = new THREE.MeshStandardMaterial({
      color: 0x8b9b79, roughness: 0.95, metalness: 0,
      side: THREE.DoubleSide, transparent: true, opacity: 0.88,
    });
    const mesh = new THREE.Mesh(geometry, material);
    mesh.receiveShadow = true;
    this.terrainRoot.add(mesh);
  }

  applyStyle(style: DisplayStyleDetail | undefined): void {
    if (!style) return;
    const background = style.sky ? style.sky_color : style.background;
    this.scene.background = new THREE.Color(background[0], background[1], background[2]);
    this.edgesVisible = style.edges || style.face_mode === "wireframe";
    this.edgeRoot.visible = this.edgesVisible;
    const white = new THREE.Color(style.front_color[0], style.front_color[1], style.front_color[2]);
    this.root.traverse(object => {
      if (!(object instanceof THREE.Mesh)) return;
      if (style.face_mode === "wireframe") object.visible = false;
      const materials = Array.isArray(object.material) ? object.material : [object.material];
      for (const material of materials) {
        if (!(material instanceof THREE.MeshStandardMaterial
            || material instanceof THREE.MeshBasicMaterial)) continue;
        if (style.face_mode === "hidden_line" || style.face_mode === "monochrome") {
          material.color.copy(white);
          material.map = null;
        } else if (style.face_mode === "shaded") {
          material.map = null;
        } else if (style.face_mode === "xray") {
          material.transparent = true;
          material.opacity = 0.28;
          material.depthWrite = false;
        }
        material.needsUpdate = true;
      }
    });
  }

  setSun(sun: SunDetail | null | undefined, enabled: boolean, darkness: number): void {
    const direction = sun?.direction;
    const active = enabled && Boolean(direction);
    this.sun.castShadow = active;
    this.ambient.intensity = active ? Math.max(0.25, 1.6 * (1 - darkness)) : 2.3;
    this.sun.intensity = active ? 3.0 : 2.2;
    if (direction) {
      const center = this.bounds.getCenter(new THREE.Vector3());
      const radius = Math.max(this.bounds.getSize(new THREE.Vector3()).length(), 1);
      const vector = this.fromZUp(direction).normalize();
      this.sun.position.copy(center).addScaledVector(vector, radius * 3);
      this.sun.target.position.copy(center);
      const extent = radius * 1.5;
      Object.assign(this.sun.shadow.camera, {
        left: -extent, right: extent, top: extent, bottom: -extent,
        near: 0.01, far: radius * 8,
      });
      this.sun.shadow.camera.updateProjectionMatrix();
    }
    this.root.traverse(object => {
      if (object instanceof THREE.Mesh) {
        object.castShadow = active;
        object.receiveShadow = active;
      }
    });
  }

  setMeasureMode(enabled: boolean): void {
    if (!enabled && this.measureStart) {
      this.clearMeasurement();
      return;
    }
    this.measuring = enabled;
    this.measureStart = undefined;
    if (enabled) {
      this.disposeChildren(this.measurementRoot);
    }
  }

  setSketchMode(enabled: boolean): void {
    this.sketching = enabled;
    if (enabled) this.measuring = false;
  }

  clearMeasurement(): void {
    this.measuring = false;
    this.measureStart = undefined;
    this.disposeChildren(this.measurementRoot);
    this.onMeasurement(null);
  }

  setSectionPlane(section: SectionPlaneDetail | null): void {
    this.sectionPlane = section ? this.makeSectionPlane(section) : null;
    this.applyClipping(this.root);
    this.applyClipping(this.edgeRoot);
    this.clearSelection();
  }

  showSectionPlane(section: SectionPlaneDetail | null): void {
    this.disposeChildren(this.sectionRoot);
    if (!section) return;
    const size = Math.max(this.bounds.getSize(new THREE.Vector3()).length(), 1);
    const helper = new THREE.PlaneHelper(this.makeSectionPlane(section), size, 0xd9ff66);
    helper.name = section.name;
    this.sectionRoot.add(helper);
  }

  setLayerVisible(layer: string, visible: boolean): void {
    this.layerVisibility.set(layer, visible);
    this.applyVisibility();
    this.clearSelection();
    this.recomputeBounds();
  }

  setHiddenObjects(nativeIds: Set<string>): void {
    this.hiddenObjectIds = new Set(nativeIds);
    this.applyVisibility();
    this.clearSelection();
    this.recomputeBounds();
  }

  setObjectHidden(nativeId: string, hidden: boolean): void {
    if (hidden) this.hiddenObjectIds.add(nativeId);
    else this.hiddenObjectIds.delete(nativeId);
    this.applyVisibility();
    this.clearSelection();
    this.recomputeBounds();
  }

  applyCamera(home: CameraHome | null): "Perspective" | "Orthographic" | null {
    if (!home) return null;
    const originalTarget = new THREE.Vector3(...home.target);
    const target = new THREE.Vector3(originalTarget.x, originalTarget.z, -originalTarget.y);
    const cp = Math.cos(home.pitch);
    const originalEye = new THREE.Vector3(
      originalTarget.x + home.distance * cp * Math.cos(home.yaw),
      originalTarget.y + home.distance * cp * Math.sin(home.yaw),
      originalTarget.z + home.distance * Math.sin(home.pitch),
    );
    const eye = new THREE.Vector3(originalEye.x, originalEye.z, -originalEye.y);
    this.camera = home.perspective ? this.perspective : this.orthographic;
    this.perspective.fov = home.fov_deg;
    this.perspective.position.copy(eye);
    this.orthographic.position.copy(eye);
    this.perspective.up.set(0, 1, 0);
    this.orthographic.up.set(0, 1, 0);
    this.controls.dispose();
    this.controls = this.makeControls(this.camera);
    this.controls.target.copy(target);
    if (!home.perspective) {
      const halfHeight = home.distance * Math.tan(THREE.MathUtils.degToRad(home.fov_deg / 2));
      this.updateOrthographic(Math.max(halfHeight, 0.01));
    }
    this.camera.updateProjectionMatrix();
    this.controls.update();
    return home.perspective ? "Perspective" : "Orthographic";
  }

  clearSelection(): void {
    this.disposeChildren(this.selectionRoot);
    this.onSelection(null);
  }

  /**
   * The nodes that make up an object: its own, and those of everything nested in it
   * (the preview exports one node per nested object, so a container is the union of
   * its children).
   */
  private nodesOf(objectId: string): {object: THREE.Object3D; semantic: Record<string, unknown>}[] {
    const found: {object: THREE.Object3D; semantic: Record<string, unknown>}[] = [];
    this.root.traverse(object => {
      const semantic = object.userData.ingetrazo_object as Record<string, unknown> | undefined;
      const id = typeof semantic?.id === "string" ? semantic.id : undefined;
      if (semantic && id && (id === objectId || id.startsWith(`${objectId}/`))) found.push({object, semantic});
    });
    return found;
  }

  private boundsOf(objectId: string): THREE.Box3 {
    const box = new THREE.Box3();
    for (const {object} of this.nodesOf(objectId)) {
      if (this.visibleInHierarchy(object)) box.union(new THREE.Box3().setFromObject(object));
    }
    return box;
  }

  /** Where a container's name comes from: the preview has nodes only for what holds geometry. */
  nameOf: (objectId: string) => string | undefined = () => undefined;

  selectObject(objectId: string): boolean {
    this.disposeChildren(this.selectionRoot);
    const box = this.boundsOf(objectId);
    const nodes = this.nodesOf(objectId);
    if (!nodes.length || box.isEmpty()) {
      this.onSelection(null);
      return false;
    }
    const semantic = (nodes.find(node => node.semantic.id === objectId) ?? nodes[0]).semantic;
    const outline = new THREE.Box3Helper(box, 0xd9ff66);
    (outline.material as THREE.LineBasicMaterial).depthTest = false;
    outline.renderOrder = 1500;
    this.selectionRoot.add(outline);
    const exact = nodes.some(node => node.semantic.id === objectId);
    this.onSelection({
      objectId,
      object: this.nameOf(objectId) ?? (exact && typeof semantic.name === "string" ? semantic.name : "Group"),
      kind: exact && typeof semantic.kind === "string" ? semantic.kind : "group",
      layer: typeof semantic.layer === "string" ? semantic.layer : undefined,
    });
    return true;
  }

  /** Choose what a plain left-drag does (the Orbit / Pan / Zoom tools). */
  setNavigation(mode: NavigationMode): void {
    this.navigation = mode;
    this.applyNavigation(this.controls);
  }

  private applyNavigation(controls: OrbitControls): void {
    if (this.gesture || this.boxSelect) {
      // Drawing and box-select own the left button; the middle button orbits, the right pans.
      controls.mouseButtons.LEFT = -1 as unknown as THREE.MOUSE;
      controls.mouseButtons.MIDDLE = THREE.MOUSE.ROTATE;
      controls.mouseButtons.RIGHT = THREE.MOUSE.PAN;
      controls.touches.ONE = THREE.TOUCH.PAN;
      return;
    }
    controls.mouseButtons.MIDDLE = THREE.MOUSE.DOLLY;
    controls.mouseButtons.RIGHT = THREE.MOUSE.PAN;
    controls.mouseButtons.LEFT = this.navigation === "pan" ? THREE.MOUSE.PAN
      : this.navigation === "zoom" ? THREE.MOUSE.DOLLY : THREE.MOUSE.ROTATE;
    controls.touches.ONE = this.navigation === "pan" ? THREE.TOUCH.PAN : THREE.TOUCH.ROTATE;
  }


  // --- Zoom Window and walkthrough ------------------------------------------

  /** Zoom Window: drag a rectangle; the view frames it. */
  setZoomWindow(enabled: boolean): void {
    if (enabled) this.setWalkMode(null);
    this.zoomWindow = enabled;
    this.controls.enabled = !enabled;
    this.canvas.style.cursor = enabled ? "zoom-in" : "";
    if (!enabled) { this.zoomBox?.remove(); this.zoomBox = undefined; }
  }

  /** Enter or leave a walkthrough tool; ``null`` returns to orbiting. */
  setWalkMode(mode: WalkMode | null): void {
    if (mode) this.setZoomWindow(false);
    const wasWalking = this.walkMode !== null;
    this.walkMode = mode;
    this.walkDrag = undefined;
    this.heldKeys.clear();
    this.canvas.style.cursor = mode ? (mode === "position_camera" ? "crosshair" : "grab") : "";
    if (mode) {
      if (!(this.camera instanceof THREE.PerspectiveCamera)) this.toggleProjection();
      this.controls.enabled = false;
      const forward = this.camera.getWorldDirection(new THREE.Vector3());
      this.yaw = Math.atan2(forward.x, forward.z);
      this.pitch = Math.asin(THREE.MathUtils.clamp(forward.y, -1, 1));
      this.camera.up.set(0, 1, 0);
    } else if (wasWalking) {
      const forward = this.camera.getWorldDirection(new THREE.Vector3());
      const reach = Math.max(this.bounds.getSize(new THREE.Vector3()).length() * 0.3, 2);
      this.controls.target.copy(this.camera.position).addScaledVector(forward, reach);
      this.controls.enabled = true;
      this.controls.update();
    }
  }

  private aimCamera(): void {
    const cos = Math.cos(this.pitch);
    const forward = new THREE.Vector3(Math.sin(this.yaw) * cos, Math.sin(this.pitch), Math.cos(this.yaw) * cos);
    this.camera.lookAt(this.camera.position.clone().add(forward));
  }

  /** Position Camera: click a spot; the eye stands there, 1.6 m up, facing the model. */
  private placeCamera(event: PointerEvent): void {
    const rect = this.canvas.getBoundingClientRect();
    this.pointer.set(((event.clientX - rect.left) / rect.width) * 2 - 1, -((event.clientY - rect.top) / rect.height) * 2 + 1);
    this.raycaster.setFromCamera(this.pointer, this.camera);
    const hit = this.raycaster.intersectObject(this.root, true).find(item => item.object instanceof THREE.Mesh);
    const ground = new THREE.Vector3();
    const point = hit ? hit.point.clone()
      : this.raycaster.ray.intersectPlane(new THREE.Plane(new THREE.Vector3(0, 1, 0), 0), ground) ? ground : undefined;
    if (!point) return;
    this.camera.position.set(point.x, point.y + 1.6, point.z);
    const centre = this.bounds.getCenter(new THREE.Vector3());
    this.yaw = Math.atan2(centre.x - point.x, centre.z - point.z);
    this.pitch = 0;
    this.aimCamera();
    this.walkMode = "look_around";
    this.canvas.style.cursor = "grab";
    this.onToolDone();
  }

  private installModeHandlers(): void {
    const canvas = this.canvas;
    canvas.addEventListener("pointerdown", event => {
      if (this.zoomWindow) {
        this.walkDrag = {x: event.clientX, y: event.clientY};
        const box = document.createElement("div");
        box.className = "zoom-box";
        canvas.parentElement!.append(box);
        this.zoomBox = box;
        canvas.setPointerCapture(event.pointerId);
      } else if (this.walkMode && this.walkMode !== "position_camera") {
        this.walkDrag = {x: event.clientX, y: event.clientY};
        canvas.setPointerCapture(event.pointerId);
      }
    });
    canvas.addEventListener("pointermove", event => {
      const start = this.walkDrag;
      if (!start) return;
      if (this.zoomWindow && this.zoomBox) {
        const parent = canvas.parentElement!.getBoundingClientRect();
        Object.assign(this.zoomBox.style, {
          left: `${Math.min(start.x, event.clientX) - parent.left}px`,
          top: `${Math.min(start.y, event.clientY) - parent.top}px`,
          width: `${Math.abs(event.clientX - start.x)}px`,
          height: `${Math.abs(event.clientY - start.y)}px`,
        });
        return;
      }
      const dx = event.clientX - start.x;
      const dy = event.clientY - start.y;
      this.walkDrag = {x: event.clientX, y: event.clientY};
      if (this.walkMode === "walk") {
        this.yaw -= dx * 0.004;
        const stride = Math.max(this.bounds.getSize(new THREE.Vector3()).length(), 5) / 400;
        const flat = new THREE.Vector3(Math.sin(this.yaw), 0, Math.cos(this.yaw));
        this.camera.position.addScaledVector(flat, -dy * stride);
      } else {
        this.yaw -= dx * 0.004;
        this.pitch = THREE.MathUtils.clamp(this.pitch - dy * 0.004, -1.5, 1.5);
      }
      this.aimCamera();
    });
    canvas.addEventListener("pointerup", event => {
      const start = this.walkDrag;
      this.walkDrag = undefined;
      if (!this.zoomWindow || !start) return;
      this.zoomBox?.remove();
      this.zoomBox = undefined;
      if (Math.hypot(event.clientX - start.x, event.clientY - start.y) < 8) return;
      this.zoomToWindow(start.x, start.y, event.clientX, event.clientY);
      this.setZoomWindow(false);
      this.onToolDone();
    });
    window.addEventListener("keydown", event => {
      if (this.walkMode === "first_person" && !/^(input|textarea|select)$/i.test((event.target as HTMLElement).tagName)) {
        this.heldKeys.add(event.key.toLowerCase());
      }
    });
    window.addEventListener("keyup", event => this.heldKeys.delete(event.key.toLowerCase()));
    window.addEventListener("blur", () => this.heldKeys.clear());
  }

  /** WASD movement for First Person (Shift runs); a no-op in every other mode. */
  private tickWalk(dt: number): void {
    if (this.walkMode !== "first_person" || !this.heldKeys.size) return;
    const speed = Math.max(this.bounds.getSize(new THREE.Vector3()).length() * 0.12, 1.5)
      * (this.heldKeys.has("shift") ? 3 : 1) * dt;
    const forward = new THREE.Vector3(Math.sin(this.yaw), 0, Math.cos(this.yaw));
    const right = new THREE.Vector3(forward.z, 0, -forward.x);
    if (this.heldKeys.has("w")) this.camera.position.addScaledVector(forward, speed);
    if (this.heldKeys.has("s")) this.camera.position.addScaledVector(forward, -speed);
    if (this.heldKeys.has("d")) this.camera.position.addScaledVector(right, -speed);
    if (this.heldKeys.has("a")) this.camera.position.addScaledVector(right, speed);
    this.aimCamera();
  }

  private zoomToWindow(x0: number, y0: number, x1: number, y1: number): void {
    const rect = this.canvas.getBoundingClientRect();
    const centreX = ((x0 + x1) / 2 - rect.left) / rect.width * 2 - 1;
    const centreY = -(((y0 + y1) / 2 - rect.top) / rect.height) * 2 + 1;
    const ratio = Math.max(Math.abs(x1 - x0) / rect.width, Math.abs(y1 - y0) / rect.height, 0.02);
    const direction = this.camera.getWorldDirection(new THREE.Vector3());
    this.raycaster.setFromCamera(new THREE.Vector2(centreX, centreY), this.camera);
    // Frame what is under the rectangle: use the surface it meets, else the orbit target.
    const hit = this.raycaster.intersectObject(this.root, true).find(item => item.object instanceof THREE.Mesh);
    const anchor = hit ? hit.point.clone() : this.controls.target.clone();
    const distance = anchor.clone().sub(this.camera.position).dot(direction);
    const plane = new THREE.Plane().setFromNormalAndCoplanarPoint(direction, anchor);
    const centre = new THREE.Vector3();
    if (!this.raycaster.ray.intersectPlane(plane, centre)) return;
    const shift = centre.clone().sub(this.controls.target);
    this.controls.target.copy(centre);
    this.camera.position.add(shift);
    if (this.camera instanceof THREE.PerspectiveCamera) {
      this.camera.position.addScaledVector(direction, distance * (1 - ratio));
    } else {
      this.camera.zoom = Math.max(this.camera.zoom / ratio, 1e-4);
      this.camera.updateProjectionMatrix();
    }
    this.controls.update();
  }


  // --- On-canvas gestures: snapping, preview, pointer events -----------------

  /** Route plain left-clicks and moves to the active gesture tool instead of selecting. */
  setGestureMode(enabled: boolean): void {
    this.gesture = enabled;
    if (!enabled) { this.constraint = null; this.clearPreview(); }
    this.controls.enabled = !this.walkMode && !this.zoomWindow;
    this.applyNavigation(this.controls);
    this.canvas.style.cursor = enabled ? "crosshair" : "";
  }

  setSnapConstraint(constraint: SnapConstraint): void { this.constraint = constraint; }

  /** Draw polylines (Z-up metres) as the live preview of the gesture in progress. */
  setPreview(polylines: [number, number, number][][], color = 0x2f80ff): void {
    for (const child of [...this.previewRoot.children]) {
      if (child === this.snapMarker) continue;
      this.previewRoot.remove(child);
      if (child instanceof Line2) { child.geometry.dispose(); (child.material as LineMaterial).dispose(); }
    }
    for (const points of polylines) {
      if (points.length < 2) continue;
      const geometry = new LineGeometry();
      geometry.setPositions(points.flatMap(([x, y, z]) => [x, z, -y]));
      const material = new LineMaterial({color, linewidth: 2.5, depthTest: false, transparent: true});
      material.resolution.set(this.canvas.clientWidth, this.canvas.clientHeight);
      const line = new Line2(geometry, material);
      line.computeLineDistances();
      line.renderOrder = 2000;
      this.previewRoot.add(line);
    }
  }

  /**
   * The group being edited. Inside it, picks resolve to its children (one level
   * down) and everything outside it is not pickable, as in the desktop's group
   * edit context. ``undefined`` is the top level.
   */
  setEditContext(id?: string): void {
    this.editContext = id;
    this.onContextChange(id);
  }

  getEditContext(): string | undefined { return this.editContext; }

  /** The object a pick means under the current edit context. */
  private resolveId(full?: string): string | undefined {
    if (!full?.startsWith("group:")) return undefined;
    const parts = full.split("/");
    if (!this.editContext) return parts[0];
    const context = this.editContext.split("/");
    if (parts.length <= context.length || context.some((part, index) => parts[index] !== part)) return undefined;
    return parts.slice(0, context.length + 1).join("/");
  }

  /** Full hierarchy id of the object at a pixel, whatever the context. */
  fullIdAt(clientX: number, clientY: number): string | undefined {
    const rect = this.canvas.getBoundingClientRect();
    this.pointer.set(((clientX - rect.left) / rect.width) * 2 - 1, -((clientY - rect.top) / rect.height) * 2 + 1);
    this.raycaster.setFromCamera(this.pointer, this.camera);
    const hit = this.raycaster.intersectObject(this.root, true).find(item => item.object instanceof THREE.Mesh);
    const id = hit ? this.semanticObject(hit.object)?.id : undefined;
    return typeof id === "string" ? id : undefined;
  }

  /** The camera as a scene captures it: eye and target in Z-up metres. */
  cameraState(): {eye: [number, number, number]; target: [number, number, number]; fov_deg: number; perspective: boolean} {
    const zup = (v: THREE.Vector3): [number, number, number] => [v.x, -v.z, v.y];
    const perspective = this.camera instanceof THREE.PerspectiveCamera;
    return {eye: zup(this.camera.position), target: zup(this.controls.target),
      fov_deg: perspective ? (this.camera as THREE.PerspectiveCamera).fov : 45, perspective};
  }

  /** Z-up bounds of a top-level object, from its semantic node. */
  objectBounds(objectId: string): {min: [number, number, number]; max: [number, number, number]} | undefined {
    const box = this.boundsOf(objectId);
    if (box.isEmpty()) return undefined;
    return {min: [box.min.x, -box.max.z, box.min.y], max: [box.max.x, -box.min.z, box.max.y]};
  }

  /** Outline the selected objects and tint the selected loose faces. */
  setHighlights(objectIds: string[], faces: number[], edges: LooseEdge[] = []): void {
    this.disposeChildren(this.highlightRoot);
    if (edges.length) {
      const points: number[] = [];
      for (const [a, b] of edges) points.push(a[0], a[2], -a[1], b[0], b[2], -b[1]);
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute("position", new THREE.Float32BufferAttribute(points, 3));
      const lines = new THREE.LineSegments(geometry, new THREE.LineBasicMaterial({color: 0xd9ff66, depthTest: false}));
      lines.renderOrder = 1501;
      this.highlightRoot.add(lines);
    }
    for (const id of objectIds) {
      const box = this.boundsOf(id);
      if (box.isEmpty()) continue;
      const outline = new THREE.Box3Helper(box, 0xd9ff66);
      (outline.material as THREE.LineBasicMaterial).depthTest = false;
      outline.renderOrder = 1500;
      this.highlightRoot.add(outline);
    }
    if (!faces.length) return;
    const wanted = new Set(faces);
    const positions: number[] = [];
    this.root.updateMatrixWorld(true);
    this.root.traverse(object => {
      if (!(object instanceof THREE.Mesh)) return;
      const tags = object.geometry.userData?.ingetrazo_faces as number[] | undefined;
      if (!tags) return;
      const position = object.geometry.getAttribute("position");
      const index = object.geometry.getIndex();
      const corner = new THREE.Vector3();
      for (let triangle = 0; triangle < tags.length; triangle += 1) {
        if (!wanted.has(tags[triangle])) continue;
        for (let k = 0; k < 3; k += 1) {
          corner.fromBufferAttribute(position, index ? index.getX(triangle * 3 + k) : triangle * 3 + k)
            .applyMatrix4(object.matrixWorld);
          positions.push(corner.x, corner.y, corner.z);
        }
      }
    });
    if (!positions.length) return;
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
    const overlay = new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({
      color: 0xd9ff66, transparent: true, opacity: 0.45, depthTest: false, side: THREE.DoubleSide}));
    overlay.renderOrder = 1499;
    this.highlightRoot.add(overlay);
  }

  clearPreview(): void {
    this.setPreview([]);
    this.snapMarker?.removeFromParent();
  }

  /** Marker at a snapped point, coloured by inference. */
  private showSnapMarker(point: THREE.Vector3 | undefined, inference: string): void {
    if (!point) { this.snapMarker?.removeFromParent(); this.snapMarker = undefined; return; }
    const colors: Record<string, number> = {Endpoint: 0x31c46a, Midpoint: 0x24c6d8, "On Edge": 0xe05252, "On Face": 0x6c8cff};
    const size = this.pixelSize(point) * 6;
    if (!this.snapMarker) {
      this.snapMarker = new THREE.Mesh(new THREE.SphereGeometry(1, 12, 8),
        new THREE.MeshBasicMaterial({color: 0xd9ff66, depthTest: false}));
      this.snapMarker.renderOrder = 2001;
    }
    (this.snapMarker.material as THREE.MeshBasicMaterial).color.setHex(colors[inference] ?? 0xd9ff66);
    this.snapMarker.scale.setScalar(size);
    this.snapMarker.position.copy(point);
    if (!this.snapMarker.parent) this.previewRoot.add(this.snapMarker);
  }

  /** World units covered by one screen pixel at ``point``. */
  private pixelSize(point: THREE.Vector3): number {
    const height = Math.max(this.canvas.clientHeight, 1);
    if (this.camera instanceof THREE.PerspectiveCamera) {
      const distance = this.camera.position.distanceTo(point);
      return (2 * distance * Math.tan(THREE.MathUtils.degToRad(this.camera.fov / 2))) / height;
    }
    return (this.camera.top - this.camera.bottom) / this.camera.zoom / height;
  }

  /**
   * Snapped point under a pixel. Priority: endpoint, midpoint, point on an edge,
   * then the surface or ground. A constraint (drawing plane, or an axis for
   * push/pull) keeps the result on that plane or line.
   */
  snapAt(clientX: number, clientY: number, marker = true): SnapInfo | null {
    const rect = this.canvas.getBoundingClientRect();
    this.pointer.set(((clientX - rect.left) / rect.width) * 2 - 1, -((clientY - rect.top) / rect.height) * 2 + 1);
    this.raycaster.setFromCamera(this.pointer, this.camera);
    const ray = this.raycaster.ray;
    const toThree = (p: [number, number, number]) => new THREE.Vector3(p[0], p[2], -p[1]);
    const constraint = this.constraint;

    if (constraint?.kind === "axis") {
      const origin = toThree(constraint.origin);
      const direction = toThree(constraint.direction).normalize();
      const w0 = ray.origin.clone().sub(origin);
      const b = ray.direction.dot(direction);
      const d = ray.direction.dot(w0);
      const e = direction.dot(w0);
      const denominator = 1 - b * b;
      if (Math.abs(denominator) < 1e-6) return null;
      const t = (e - b * d) / denominator;
      const point = origin.clone().addScaledVector(direction, t);
      if (marker) this.showSnapMarker(point, "On Axis");
      return {point: toZup(point), inference: "On Axis"};
    }

    const hit = this.raycaster.intersectObject(this.root, true).find(item => item.object instanceof THREE.Mesh);
    let point: THREE.Vector3 | undefined;
    let inference = "On Face";
    let normal: THREE.Vector3 | undefined;
    let objectId: string | undefined;
    let objectName: string | undefined;
    let looseFace: number | undefined;
    if (constraint?.kind === "plane") {
      const plane = new THREE.Plane().setFromNormalAndCoplanarPoint(
        toThree(constraint.normal).normalize(), toThree(constraint.point));
      const onPlane = new THREE.Vector3();
      if (!ray.intersectPlane(plane, onPlane)) return null;
      point = onPlane;
      inference = "On Plane";
    } else if (hit) {
      point = hit.point.clone();
      if (hit.face) normal = hit.face.normal.clone().transformDirection(hit.object.matrixWorld);
      const semantic = this.semanticObject(hit.object);
      const id = typeof semantic?.id === "string" ? semantic.id : undefined;
      const locked = semantic?.locked === true;       // a locked layer: visible, but not selectable
      objectId = locked ? undefined : this.resolveId(id);
      objectName = typeof semantic?.name === "string" ? semantic.name : undefined;
      const tags = (hit.object as THREE.Mesh).geometry?.userData?.ingetrazo_faces as number[] | undefined;
      // Faces are named only for what can be edited face by face: the loose geometry at the
      // top level, or the object entered for editing.
      const editable = this.editContext ? id === this.editContext : semantic?.kind === "loose";
      if (!locked && editable && tags && hit.faceIndex != null && typeof tags[hit.faceIndex] === "number") looseFace = tags[hit.faceIndex];
    } else {
      const ground = new THREE.Vector3();
      if (!ray.intersectPlane(new THREE.Plane(new THREE.Vector3(0, 1, 0), 0), ground)) return null;
      point = ground;
      inference = "On Ground";
      normal = new THREE.Vector3(0, 1, 0);
    }

    // Feature snapping against the model's edges, in screen space.
    const pixel = this.pixelSize(point);
    const reach = pixel * 12;
    const segments = this.edgeSegments;
    let best: {distance: number; rank: number; at: THREE.Vector3; label: string} | undefined;
    const a = new THREE.Vector3();
    const b = new THREE.Vector3();
    const consider = (candidate: THREE.Vector3, rank: number, label: string) => {
      const distance = candidate.distanceTo(point!) / pixel;
      if (distance > 12) return;
      if (!best || rank < best.rank || (rank === best.rank && distance < best.distance)) {
        best = {distance, rank, at: candidate.clone(), label};
      }
    };
    for (let index = 0; index + 5 < segments.length; index += 6) {
      a.set(segments[index], segments[index + 1], segments[index + 2]);
      b.set(segments[index + 3], segments[index + 4], segments[index + 5]);
      if (Math.min(a.x, b.x) - reach > point.x || Math.max(a.x, b.x) + reach < point.x) continue;
      if (Math.min(a.y, b.y) - reach > point.y || Math.max(a.y, b.y) + reach < point.y) continue;
      if (Math.min(a.z, b.z) - reach > point.z || Math.max(a.z, b.z) + reach < point.z) continue;
      consider(a, 0, "Endpoint");
      consider(b, 0, "Endpoint");
      consider(a.clone().add(b).multiplyScalar(0.5), 1, "Midpoint");
      const edge = b.clone().sub(a);
      const length2 = edge.lengthSq();
      if (length2 > 1e-12) {
        const t = THREE.MathUtils.clamp(point.clone().sub(a).dot(edge) / length2, 0, 1);
        consider(a.clone().addScaledVector(edge, t), 2, "On Edge");
      }
    }
    if (best) {
      const found = best as {at: THREE.Vector3; label: string};
      point = found.at;
      inference = found.label;
      if (constraint?.kind === "plane") {
        const plane = new THREE.Plane().setFromNormalAndCoplanarPoint(
          toThree(constraint.normal).normalize(), toThree(constraint.point));
        plane.projectPoint(point, point);
      }
    }
    if (marker) this.showSnapMarker(point, inference);
    const looseEdge = constraint || this.editContext ? undefined : this.looseEdgeAt(clientX, clientY);
    return {
      point: toZup(point), inference,
      ...(looseEdge ? {looseEdge} : {}),
      ...(normal ? {normal: toZup(normal.normalize())} : {}),
      ...(objectId ? {objectId, objectName} : {}),
      ...(looseFace !== undefined ? {looseFace} : {}),
    };
  }

  private installGestureHandlers(): void {
    const canvas = this.canvas;
    canvas.addEventListener("pointerdown", event => {
      if (this.gesture && !this.walkMode && !this.zoomWindow && event.button === 0) {
        this.onGestureDown(this.snapAt(event.clientX, event.clientY));
      }
    });
    canvas.addEventListener("pointermove", event => {
      if (!this.gesture || this.walkMode || this.zoomWindow) return;
      // One snap per frame: a pointermove burst on a big model would otherwise stall.
      const idle = !this.pendingMove;
      this.pendingMove = event;
      if (!idle) return;
      requestAnimationFrame(() => {
        const last = this.pendingMove;
        this.pendingMove = undefined;
        if (last && this.gesture) this.onGestureMove(this.snapAt(last.clientX, last.clientY));
      });
    });
    canvas.addEventListener("pointerleave", () => { if (this.gesture) this.showSnapMarker(undefined, ""); });
  }


  // --- Box (marquee) selection ------------------------------------------------

  /**
   * In the Select tool the left button drags a selection box instead of
   * orbiting (middle-drag orbits, right-drag pans); ``false`` restores orbiting.
   */
  setBoxSelect(enabled: boolean): void {
    this.boxSelect = enabled;
    this.applyNavigation(this.controls);
    this.canvas.style.cursor = enabled && !this.gesture ? "default" : this.canvas.style.cursor;
  }

  private installBoxHandlers(): void {
    const canvas = this.canvas;
    const clear = () => { this.boxEl?.remove(); this.boxEl = undefined; this.boxStart = undefined; };
    canvas.addEventListener("pointerdown", event => {
      if (!this.boxSelect || this.gesture || event.button !== 0 || this.walkMode || this.zoomWindow) return;
      this.boxStart = {x: event.clientX, y: event.clientY};
    });
    canvas.addEventListener("pointermove", event => {
      const start = this.boxStart;
      if (!start || !this.boxSelect || (event.buttons & 1) === 0) return;
      if (Math.hypot(event.clientX - start.x, event.clientY - start.y) < 4 && !this.boxEl) return;
      if (!this.boxEl) {
        this.boxEl = document.createElement("div");
        canvas.parentElement!.append(this.boxEl);
      }
      const parent = canvas.parentElement!.getBoundingClientRect();
      const crossing = event.clientX < start.x;
      this.boxEl.className = crossing ? "select-box crossing" : "select-box";
      Object.assign(this.boxEl.style, {
        left: `${Math.min(start.x, event.clientX) - parent.left}px`,
        top: `${Math.min(start.y, event.clientY) - parent.top}px`,
        width: `${Math.abs(event.clientX - start.x)}px`,
        height: `${Math.abs(event.clientY - start.y)}px`,
      });
    });
    window.addEventListener("pointerup", clear);
    window.addEventListener("blur", clear);
  }

  /**
   * What a screen rectangle takes in: top-level objects (judged by their
   * projected bounding boxes) and loose faces (by their projected extent).
   * ``crossing`` accepts anything the box touches; otherwise it must be inside.
   */
  selectInBox(x0: number, y0: number, x1: number, y1: number, crossing: boolean): {objects: string[]; faces: number[]; edges: LooseEdge[]} {
    const rect = this.canvas.getBoundingClientRect();
    const box = {l: Math.min(x0, x1) - rect.left, r: Math.max(x0, x1) - rect.left,
      t: Math.min(y0, y1) - rect.top, b: Math.max(y0, y1) - rect.top};
    const width = Math.max(rect.width, 1);
    const height = Math.max(rect.height, 1);
    this.root.updateMatrixWorld(true);
    this.camera.updateMatrixWorld();
    const point = new THREE.Vector3();
    const project = (v: THREE.Vector3) => {
      point.copy(v).project(this.camera);
      return {x: (point.x * 0.5 + 0.5) * width, y: (-point.y * 0.5 + 0.5) * height, behind: point.z > 1};
    };
    const accept = (minX: number, minY: number, maxX: number, maxY: number) => crossing
      ? maxX >= box.l && minX <= box.r && maxY >= box.t && minY <= box.b
      : minX >= box.l && maxX <= box.r && minY >= box.t && maxY <= box.b;

    const objects: string[] = [];
    const context = this.editContext ? this.editContext.split("/") : [];
    const corner = new THREE.Vector3();
    // A container may own no geometry itself: its children's nodes stand for it, so
    // every node is traced up to the level being picked.
    const candidates = new Set<string>();
    this.root.traverse(node => {
      const semantic = node.userData.ingetrazo_object as Record<string, unknown> | undefined;
      const id = typeof semantic?.id === "string" ? semantic.id : undefined;
      if (!id || !id.startsWith("group:") || !this.visibleInHierarchy(node) || semantic?.locked === true) return;
      const parts = id.split("/");
      if (parts.length < context.length + 1 || context.some((part, i) => parts[i] !== part)) return;
      candidates.add(parts.slice(0, context.length + 1).join("/"));
    });
    for (const id of candidates) {
      const bounds = this.boundsOf(id);
      if (bounds.isEmpty()) continue;
      let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
      let behind = false;
      for (let i = 0; i < 8; i += 1) {
        corner.set(i & 1 ? bounds.max.x : bounds.min.x, i & 2 ? bounds.max.y : bounds.min.y, i & 4 ? bounds.max.z : bounds.min.z);
        const p = project(corner);
        behind = behind || p.behind;
        minX = Math.min(minX, p.x); maxX = Math.max(maxX, p.x);
        minY = Math.min(minY, p.y); maxY = Math.max(maxY, p.y);
      }
      if (!behind && accept(minX, minY, maxX, maxY)) objects.push(id);
    }

    // Loose faces at the top level, or the faces of the object entered for editing.
    const faces = new Set<number>();
    {
      const extents = new Map<number, {minX: number; minY: number; maxX: number; maxY: number; behind: boolean}>();
      this.root.traverse(object => {
        if (!(object instanceof THREE.Mesh) || !this.visibleInHierarchy(object)) return;
        const tags = object.geometry.userData?.ingetrazo_faces as number[] | undefined;
        const owner = this.semanticObject(object);
        if (!tags || owner?.locked === true) return;
        if (this.editContext ? owner?.id !== this.editContext : owner?.kind !== "loose") return;
        const position = object.geometry.getAttribute("position");
        const index = object.geometry.getIndex();
        for (let triangle = 0; triangle < tags.length; triangle += 1) {
          const entry = extents.get(tags[triangle])
            ?? {minX: Infinity, minY: Infinity, maxX: -Infinity, maxY: -Infinity, behind: false};
          for (let k = 0; k < 3; k += 1) {
            corner.fromBufferAttribute(position, index ? index.getX(triangle * 3 + k) : triangle * 3 + k)
              .applyMatrix4(object.matrixWorld);
            const p = project(corner);
            entry.behind = entry.behind || p.behind;
            entry.minX = Math.min(entry.minX, p.x); entry.maxX = Math.max(entry.maxX, p.x);
            entry.minY = Math.min(entry.minY, p.y); entry.maxY = Math.max(entry.maxY, p.y);
          }
          extents.set(tags[triangle], entry);
        }
      });
      for (const [face, e] of extents) {
        if (!e.behind && accept(e.minX, e.minY, e.maxX, e.maxY)) faces.add(face);
      }
    }
    // Free loose edges, only at the top level (inside a group they are not offered).
    const edges: LooseEdge[] = [];
    if (!this.editContext) {
      const segments = this.looseEdgeSegments;
      const a = new THREE.Vector3();
      const b = new THREE.Vector3();
      for (let i = 0; i + 5 < segments.length; i += 6) {
        a.set(segments[i], segments[i + 1], segments[i + 2]);
        b.set(segments[i + 3], segments[i + 4], segments[i + 5]);
        const pa = project(a);
        const qa = {x: pa.x, y: pa.y, behind: pa.behind};
        const pb = project(b);
        if (qa.behind || pb.behind) continue;
        if (accept(Math.min(qa.x, pb.x), Math.min(qa.y, pb.y), Math.max(qa.x, pb.x), Math.max(qa.y, pb.y))) {
          edges.push([toZup(a), toZup(b)]);
        }
      }
    }
    return {objects, faces: [...faces], edges};
  }

  private navigation_prefs = {orbitSpeed: 1, zoomSpeed: 1, invertZoom: false, invertOrbitVertical: false};

  /** Mouse and touch feel: speeds, and whether wheel zoom and vertical orbit are inverted. */
  setNavigationPrefs(prefs: {orbitSpeed: number; zoomSpeed: number; invertZoom: boolean; invertOrbitVertical: boolean}): void {
    this.navigation_prefs = prefs;
    this.applyNavPrefs(this.controls);
  }

  private applyNavPrefs(controls: OrbitControls): void {
    const prefs = this.navigation_prefs;
    controls.rotateSpeed = prefs.orbitSpeed;
    controls.zoomSpeed = (prefs.invertZoom ? -1 : 1) * prefs.zoomSpeed;     // a negative speed reverses the dolly
    // OrbitControls has no switch for vertical orbit alone; its (pinned, r180) internal step is wrapped once.
    const internal = controls as unknown as {_rotateUp?: (angle: number) => void; _ingetrazoRotateUp?: (angle: number) => void};
    if (typeof internal._rotateUp === "function" && !internal._ingetrazoRotateUp) {
      const original = internal._rotateUp.bind(controls);
      internal._ingetrazoRotateUp = original;
      internal._rotateUp = (angle: number) => original(this.navigation_prefs.invertOrbitVertical ? -angle : angle);
    }
  }

  private makeControls(camera: THREE.Camera): OrbitControls {
    const controls = new OrbitControls(camera, this.canvas);
    this.applyNavigation(controls);
    this.applyNavPrefs(controls);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.screenSpacePanning = true;
    return controls;
  }

  private buildEdges(): void {
    this.disposeChildren(this.edgeRoot);
    this.root.updateMatrixWorld(true);
    const collected: Float32Array[] = [];
    const looseEdges: number[] = [];
    this.root.traverse(object => {
      if (object instanceof THREE.LineSegments && object.geometry && object.layers.isEnabled(0)) {
        const position = object.geometry.getAttribute("position");
        if (!position) return;
        const world = new Float32Array(position.count * 3);
        const corner = new THREE.Vector3();
        for (let index = 0; index < position.count; index += 1) {
          corner.fromBufferAttribute(position, index).applyMatrix4(object.matrixWorld);
          world.set([corner.x, corner.y, corner.z], index * 3);
        }
        collected.push(world);
        const semantic = this.semanticObject(object);
        if (semantic?.kind === "loose" && semantic.locked !== true) looseEdges.push(...world);
        return;
      }
      if (!(object instanceof THREE.Mesh) || !object.geometry) return;
      // A face-me figure is drawn by its own cut-out; no outline around its quad.
      if (object.userData.noEdges || !object.layers.isEnabled(0)) return;
      const geometry = new THREE.EdgesGeometry(object.geometry, 20);
      if (!geometry.getAttribute("position")?.count) {
        geometry.dispose();
        return;
      }
      const lines = new THREE.LineSegments(
        geometry,
        new THREE.LineBasicMaterial({color: 0x18201e, transparent: true, opacity: 0.72}),
      );
      lines.matrix.copy(object.matrixWorld);
      lines.matrixAutoUpdate = false;
      const local = geometry.getAttribute("position");
      const world = new Float32Array(local.count * 3);
      const corner = new THREE.Vector3();
      for (let index = 0; index < local.count; index += 1) {
        corner.fromBufferAttribute(local, index).applyMatrix4(object.matrixWorld);
        world.set([corner.x, corner.y, corner.z], index * 3);
      }
      collected.push(world);
      const semantic = this.semanticObject(object);
      if (typeof semantic?.layer === "string") {
        lines.userData.ingetrazo_layer = semantic.layer;
        lines.userData.ingetrazo_layers = layerPath(semantic);
        lines.userData.ingetrazo_native_id = semantic.visibility_id ?? semantic.native_id;
        lines.visible = this.visibleInHierarchy(object);
      }
      this.edgeRoot.add(lines);
    });
    this.edgeRoot.visible = this.edgesVisible;
    this.applyClipping(this.edgeRoot);
    const total = collected.reduce((sum, part) => sum + part.length, 0);
    this.edgeSegments = new Float32Array(total);
    let offset = 0;
    for (const part of collected) { this.edgeSegments.set(part, offset); offset += part.length; }
    this.looseEdgeSegments = new Float32Array(looseEdges);
  }

  /** The free loose edge within a few pixels of the cursor, if any (screen-space test). */
  private looseEdgeAt(clientX: number, clientY: number): LooseEdge | undefined {
    const rect = this.canvas.getBoundingClientRect();
    const px = clientX - rect.left;
    const py = clientY - rect.top;
    const segments = this.looseEdgeSegments;
    const project = (x: number, y: number, z: number) => {
      const v = new THREE.Vector3(x, y, z).project(this.camera);
      return {x: (v.x + 1) / 2 * rect.width, y: (1 - v.y) / 2 * rect.height, behind: v.z > 1 || v.z < -1};
    };
    let best: {distance: number; index: number} | undefined;
    for (let index = 0; index + 5 < segments.length; index += 6) {
      const a = project(segments[index], segments[index + 1], segments[index + 2]);
      const b = project(segments[index + 3], segments[index + 4], segments[index + 5]);
      if (a.behind && b.behind) continue;
      const dx = b.x - a.x;
      const dy = b.y - a.y;
      const length2 = dx * dx + dy * dy;
      const t = length2 > 1e-9 ? THREE.MathUtils.clamp(((px - a.x) * dx + (py - a.y) * dy) / length2, 0, 1) : 0;
      const distance = Math.hypot(px - (a.x + dx * t), py - (a.y + dy * t));
      if (distance <= 7 && (!best || distance < best.distance)) best = {distance, index};
    }
    if (!best) return undefined;
    const i = best.index;
    return [toZup(new THREE.Vector3(segments[i], segments[i + 1], segments[i + 2])),
      toZup(new THREE.Vector3(segments[i + 3], segments[i + 4], segments[i + 5]))];
  }

  private axisMaterials: LineMaterial[] = [];

  /**
   * World axes as the desktop draws them: X red, Y green, Z (up) blue. They are
   * drawn on top of the model, thick enough to read, with the negative half dashed;
   * a depth-tested hairline at the origin is hidden inside most models.
   */
  private buildAxes(): void {
    this.disposeChildren(this.axesRoot);
    this.axisMaterials = [];
    const size = Math.max(this.bounds.getSize(new THREE.Vector3()).length() * 0.18, 0.25);
    // glTF is Y-up: IngeTrazo's Y is glTF -Z and its Z is glTF Y.
    const axes: [number, THREE.Vector3][] = [
      [0xe5484d, new THREE.Vector3(1, 0, 0)],
      [0x46c46a, new THREE.Vector3(0, 0, -1)],
      [0x4a86e8, new THREE.Vector3(0, 1, 0)],
    ];
    for (const [color, direction] of axes) {
      for (const sign of [1, -1]) {
        const geometry = new LineGeometry();
        geometry.setPositions([0, 0, 0, ...direction.clone().multiplyScalar(size * sign).toArray()]);
        const material = new LineMaterial({
          color, linewidth: sign > 0 ? 3 : 1.5, depthTest: false, transparent: true, opacity: sign > 0 ? 1 : 0.55,
          dashed: sign < 0, dashSize: size * 0.04, gapSize: size * 0.03,
        });
        material.resolution.set(this.canvas.clientWidth || 1, this.canvas.clientHeight || 1);
        const line = new Line2(geometry, material);
        line.computeLineDistances();
        line.renderOrder = 950;
        this.axisMaterials.push(material);
        this.axesRoot.add(line);
      }
    }
    this.axesRoot.visible = this.axesVisible;
  }

  /** Hidden itself, or inside a hidden object (an id is a path: ``group:2/0``). */
  private isHidden(id: string | undefined): boolean {
    if (!id) return false;
    if (this.hiddenObjectIds.has(id)) return true;
    for (let cut = id.lastIndexOf("/"); cut > 0; cut = id.lastIndexOf("/", cut - 1)) {
      if (this.hiddenObjectIds.has(id.slice(0, cut))) return true;
    }
    return false;
  }

  /** Whether every layer of an object and of the groups around it is shown. */
  private layersVisible(layers: string[]): boolean {
    return layers.every(name => this.layerVisibility.get(name) ?? true);
  }

  private applyVisibility(): void {
    this.root.traverse(object => {
      const semantic = object.userData.ingetrazo_object as Record<string, unknown> | undefined;
      if (!semantic) return;
      const nativeId = typeof semantic.visibility_id === "string"
        ? semantic.visibility_id
        : typeof semantic.native_id === "string" ? semantic.native_id : undefined;
      object.visible = this.layersVisible(layerPath(semantic)) && !this.isHidden(nativeId);
    });
    this.edgeRoot.traverse(object => {
      const layers = object.userData.ingetrazo_layers as string[] | undefined;
      const layer = object.userData.ingetrazo_layer;
      const nativeId = object.userData.ingetrazo_native_id;
      object.visible = this.layersVisible(layers ?? (typeof layer === "string" ? [layer] : []))
        && !this.isHidden(typeof nativeId === "string" ? nativeId : undefined);
    });
    this.annotationRoot.traverse(object => {
      const layer = object.userData.ingetrazo_layer;
      if (typeof layer === "string") object.visible = this.layerVisibility.get(layer) ?? true;
    });
  }

  private applyClipping(parent: THREE.Object3D): void {
    parent.traverse(object => {
      if (!(object instanceof THREE.Mesh || object instanceof THREE.Line)) return;
      const materials = Array.isArray(object.material) ? object.material : [object.material];
      for (const material of materials) {
        material.clippingPlanes = this.sectionPlane ? [this.sectionPlane] : [];
        material.needsUpdate = true;
      }
    });
  }

  private makeSectionPlane(section: SectionPlaneDetail): THREE.Plane {
    const point = new THREE.Vector3(section.point[0], section.point[2], -section.point[1]);
    const normal = new THREE.Vector3(
      -section.normal[0], -section.normal[2], section.normal[1],
    ).normalize();
    return new THREE.Plane().setFromNormalAndCoplanarPoint(normal, point);
  }

  private resize(): void {
    const parent = this.canvas.parentElement!;
    const width = Math.max(parent.clientWidth, 1);
    const height = Math.max(parent.clientHeight, 1);
    this.renderer.setSize(width, height, false);
    this.perspective.aspect = width / height;
    this.perspective.updateProjectionMatrix();
    for (const material of this.axisMaterials) material.resolution.set(width, height);
    const radius = Math.max(this.bounds.getSize(new THREE.Vector3()).length() / 2, 1);
    this.updateOrthographic(radius);
  }

  private recomputeBounds(): void {
    this.bounds.makeEmpty();
    this.root.traverse(object => {
      if (!(object instanceof THREE.Mesh || object instanceof THREE.Line)
          || !this.visibleInHierarchy(object)) return;
      this.bounds.expandByObject(object);
    });
    if (this.bounds.isEmpty()) {
      this.bounds.setFromCenterAndSize(new THREE.Vector3(), new THREE.Vector3(1, 1, 1));
    }
  }

  private visibleInHierarchy(object: THREE.Object3D): boolean {
    let current: THREE.Object3D | null = object;
    while (current) {
      if (!current.visible) return false;
      current = current.parent;
    }
    return true;
  }

  private semanticObject(object: THREE.Object3D): Record<string, unknown> | undefined {
    let owner: THREE.Object3D | null = object;
    while (owner) {
      const candidate = owner.userData.ingetrazo_object;
      if (candidate && typeof candidate === "object") {
        return candidate as Record<string, unknown>;
      }
      owner = owner.parent;
    }
    return undefined;
  }

  private updateOrthographic(radius: number): void {
    const parent = this.canvas.parentElement!;
    const aspect = Math.max(parent.clientWidth, 1) / Math.max(parent.clientHeight, 1);
    this.orthographic.left = -radius * aspect;
    this.orthographic.right = radius * aspect;
    this.orthographic.top = radius;
    this.orthographic.bottom = -radius;
    this.orthographic.updateProjectionMatrix();
  }

  private pick(event: PointerEvent): void {
    const rect = this.canvas.getBoundingClientRect();
    this.pointer.set(
      ((event.clientX - rect.left) / rect.width) * 2 - 1,
      -((event.clientY - rect.top) / rect.height) * 2 + 1,
    );
    this.raycaster.setFromCamera(this.pointer, this.camera);
    this.raycaster.params.Line.threshold = Math.max(
      this.bounds.getSize(new THREE.Vector3()).length() * 0.006,
      0.003,
    );
    const hit = this.raycaster.intersectObject(this.root, true).find(item =>
      item.object instanceof THREE.Mesh || item.object instanceof THREE.Line,
    );
    this.disposeChildren(this.selectionRoot);
    if (this.sketching) {
      let point = hit?.point.clone();
      let inference = hit ? "surface" : "ground plane";
      if (hit?.object instanceof THREE.Mesh && hit.face) {
        const position = hit.object.geometry.getAttribute("position");
        const vertices = [hit.face.a, hit.face.b, hit.face.c].map(index =>
          new THREE.Vector3().fromBufferAttribute(position, index)
            .applyMatrix4(hit.object.matrixWorld),
        );
        const nearest = vertices.reduce((best, candidate) =>
          !best || candidate.distanceTo(hit.point) < best.distanceTo(hit.point)
            ? candidate : best, undefined as THREE.Vector3 | undefined);
        const tolerance = Math.max(this.bounds.getSize(new THREE.Vector3()).length() * 0.015, 0.01);
        if (nearest && nearest.distanceTo(hit.point) <= tolerance) {
          point = nearest.clone();
          inference = "vertex";
        }
      }
      if (!point) {
        point = new THREE.Vector3();
        if (!this.raycaster.ray.intersectPlane(
          new THREE.Plane(new THREE.Vector3(0, 1, 0), 0), point,
        )) return;
      }
      const marker = new THREE.Mesh(
        new THREE.SphereGeometry(Math.max(this.bounds.getSize(new THREE.Vector3()).length() * 0.006, 0.01), 12, 8),
        new THREE.MeshBasicMaterial({color: 0xd9ff66, depthTest: false}),
      );
      marker.position.copy(point);
      this.selectionRoot.add(marker);
      this.onSketchPoint([point.x, -point.z, point.y], inference);
      return;
    }
    if (!hit) {
      this.onSelection(null);
      return;
    }
    if (this.measuring) {
      this.measurePoint(hit.point);
      return;
    }
    const semantic = this.semanticObject(hit.object);
    const pointZUp: [number, number, number] = [hit.point.x, -hit.point.z, hit.point.y];
    // A click means the object at the level being edited (the whole 3D text, not the letter
    // that was hit), the same rule the selection and the tools follow.
    const hitId = typeof semantic?.id === "string" ? semantic.id : undefined;
    const pickedId = this.resolveId(hitId) ?? hitId;
    const widened = pickedId !== undefined && pickedId !== hitId;
    const pickedName = widened ? (this.nameOf(pickedId!) ?? "Group") : (typeof semantic?.name === "string" ? semantic.name : undefined);
    const pickedKind = widened ? "group" : (typeof semantic?.kind === "string" ? semantic.kind : undefined);
    if (hit.object instanceof THREE.Line) {
      const geometry = hit.object.geometry.clone();
      geometry.applyMatrix4(hit.object.matrixWorld);
      const material = new THREE.LineBasicMaterial({color: 0xd9ff66, depthTest: false});
      const highlight = hit.object instanceof THREE.LineSegments
        ? new THREE.LineSegments(geometry, material)
        : new THREE.Line(geometry, material);
      highlight.renderOrder = 1000;
      this.selectionRoot.add(highlight);
      this.onSelection({
        objectId: pickedId,
        object: pickedName ?? (hit.object.name || hit.object.parent?.name || "Model line"),
        kind: pickedKind,
        layer: typeof semantic?.layer === "string" ? semantic.layer : undefined,
        material: "Line",
        point: pointZUp,
      });
      return;
    }
    if (!(hit.object instanceof THREE.Mesh) || !hit.face) {
      this.onSelection(null);
      return;
    }
    const position = hit.object.geometry.getAttribute("position");
    const triangle = [hit.face.a, hit.face.b, hit.face.c].map(index =>
      new THREE.Vector3().fromBufferAttribute(position, index).applyMatrix4(hit.object.matrixWorld),
    );
    const geometry = new THREE.BufferGeometry().setFromPoints([...triangle, triangle[0]]);
    this.selectionRoot.add(new THREE.Line(
      geometry,
      new THREE.LineBasicMaterial({color: 0xd9ff66, depthTest: false}),
    ));
    const material = Array.isArray(hit.object.material)
      ? hit.object.material[hit.face.materialIndex]
      : hit.object.material;
    this.onSelection({
      objectId: pickedId,
      object: pickedName ?? (hit.object.name || hit.object.parent?.name || "Model geometry"),
      kind: pickedKind,
      layer: typeof semantic?.layer === "string" ? semantic.layer : undefined,
      material: material?.name || "Default",
      triangle: hit.faceIndex ?? 0,
      point: pointZUp,
    });
  }

  private measurePoint(point: THREE.Vector3): void {
    const markerMaterial = new THREE.MeshBasicMaterial({color: 0xd9ff66, depthTest: false});
    const marker = new THREE.Mesh(new THREE.SphereGeometry(
      Math.max(this.bounds.getSize(new THREE.Vector3()).length() * 0.004, 0.006), 12, 8,
    ), markerMaterial);
    marker.position.copy(point);
    marker.renderOrder = 1000;
    this.measurementRoot.add(marker);
    if (!this.measureStart) {
      this.measureStart = point.clone();
      this.onMeasurement({distance: null, start: this.toZUp(point), complete: false});
      return;
    }
    const start = this.measureStart;
    const geometry = new THREE.BufferGeometry().setFromPoints([start, point]);
    const line = new THREE.Line(geometry, new THREE.LineBasicMaterial({
      color: 0xd9ff66, depthTest: false,
    }));
    line.renderOrder = 1000;
    this.measurementRoot.add(line);
    this.measuring = false;
    this.measureStart = undefined;
    this.onMeasurement({
      distance: start.distanceTo(point),
      start: this.toZUp(start),
      end: this.toZUp(point),
      complete: true,
    });
  }

  private toZUp(point: THREE.Vector3): [number, number, number] {
    return [point.x, -point.z, point.y];
  }

  private fromZUp(point: [number, number, number]): THREE.Vector3 {
    return new THREE.Vector3(point[0], point[2], -point[1]);
  }

  private addAnnotationLine(
    points: THREE.Vector3[], material: THREE.LineBasicMaterial | THREE.LineDashedMaterial,
    dashed = false, parent: THREE.Group = this.annotationRoot,
  ): THREE.Line {
    const line = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints(points), material.clone(),
    );
    if (dashed) line.computeLineDistances();
    line.renderOrder = 900;
    parent.add(line);
    return line;
  }

  /** A text label as a sprite; its on-screen size is set per frame by ``layoutLabels``. */
  private makeTextSprite(text: string, position: THREE.Vector3): {sprite: THREE.Sprite; widthPx: number; heightPx: number} {
    const lines = text.split(/\r?\n/).map(line => line.trim()).filter(Boolean);
    const font = "600 36px system-ui, sans-serif";
    const probe = document.createElement("canvas").getContext("2d")!;
    probe.font = font;
    const lineHeight = 48;
    const widest = Math.max(...lines.map(line => probe.measureText(line).width), 40);
    const canvas = document.createElement("canvas");
    canvas.width = Math.min(Math.ceil(widest + 28), 1400);
    canvas.height = lineHeight * Math.max(lines.length, 1) + 12;
    const context = canvas.getContext("2d")!;
    context.fillStyle = "rgba(247, 247, 239, .94)";
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.strokeStyle = "rgba(32, 37, 34, .35)";
    context.strokeRect(0.5, 0.5, canvas.width - 1, canvas.height - 1);
    context.font = font;
    context.fillStyle = "#202522";
    context.textBaseline = "middle";
    lines.forEach((line, index) => context.fillText(line, 14, 6 + lineHeight * (index + 0.5), canvas.width - 28));
    const texture = new THREE.CanvasTexture(canvas);
    texture.colorSpace = THREE.SRGBColorSpace;
    const sprite = new THREE.Sprite(new THREE.SpriteMaterial({map: texture, depthTest: false}));
    sprite.position.copy(position);
    sprite.renderOrder = 901;
    // About 16 px per text line on screen, whatever the model's size or the zoom.
    const heightPx = 16 * Math.max(lines.length, 1) + 4;
    return {sprite, widthPx: heightPx * canvas.width / canvas.height, heightPx};
  }

  // --- Face-me figures --------------------------------------------------------

  /**
   * Find the figures the preview carries (nodes with ``faceme`` metadata) and
   * prepare them to be turned toward the camera. A lone textured quad is
   * rebuilt as an upright plane (the way the desktop draws it); any other figure
   * keeps its geometry and is rotated whole about the vertical through its feet.
   */
  private setupFaceMe(): void {
    this.faceMe = [];
    const nodes: THREE.Object3D[] = [];
    this.root.traverse(object => {
      const semantic = object.userData.ingetrazo_object as {faceme?: unknown} | undefined;
      if (semantic?.faceme) nodes.push(object);
    });
    for (const node of nodes) {
      const info = (node.userData.ingetrazo_object as {faceme: {
        kind: "quad" | "mesh"; feet: [number, number, number]; width: number; height: number; heading?: number}}).faceme;
      const feet = new THREE.Vector3(info.feet[0], info.feet[2], -info.feet[1]);   // Z-up to glTF Y-up
      const meshes: THREE.Mesh[] = [];
      if (node instanceof THREE.Mesh) meshes.push(node);
      node.traverse(child => { if (child !== node && child instanceof THREE.Mesh) meshes.push(child); });
      if (!meshes.length) continue;
      if (info.kind === "quad") {
        const source = (Array.isArray(meshes[0].material) ? meshes[0].material[0] : meshes[0].material) as THREE.MeshStandardMaterial;
        const material = source.clone();
        material.side = THREE.DoubleSide;
        material.alphaTest = 0.35;         // the PNG's transparent corners are not part of the figure
        material.transparent = false;
        const geometry = new THREE.PlaneGeometry(Math.max(info.width, 1e-3), Math.max(info.height, 1e-3));
        geometry.translate(0, info.height / 2, 0);
        const uv = geometry.getAttribute("uv");
        for (let i = 0; i < uv.count; i += 1) uv.setY(i, 1 - uv.getY(i));   // glTF textures have a top-left origin
        const plane = new THREE.Mesh(geometry, material);
        plane.position.copy(feet);
        plane.userData.noEdges = true;
        for (const mesh of meshes) mesh.layers.set(1);   // the stored quad is neither drawn nor picked
        node.add(plane);
        this.faceMe.push({kind: "quad", feet, plane});
      } else {
        for (const mesh of meshes) {
          mesh.userData.noEdges = true;            // the cut-out's rectangle is not part of the figure
          const materials = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
          mesh.material = materials.map(original => {
            const copy = original.clone() as THREE.MeshStandardMaterial;
            copy.alphaTest = 0.35;
            return copy;
          }) as THREE.Material[];
          if (materials.length === 1) mesh.material = (mesh.material as THREE.Material[])[0];
        }
        const pivot = new THREE.Group();
        pivot.position.copy(feet);
        node.parent!.add(pivot);
        pivot.add(node);
        node.position.sub(feet);
        this.faceMe.push({kind: "mesh", feet, pivot, heading: info.heading});
      }
    }
    this.faceMeKey = "";
  }

  private faceMeKey = "";

  /** Turn each figure about its vertical to face the camera (a cheap no-op until the camera moves). */
  private turnFaceMe(): void {
    if (!this.faceMe.length) return;
    this.camera.updateMatrixWorld();
    const position = this.camera.position;
    const key = `${position.x},${position.y},${position.z},${this.camera.quaternion.x},${this.camera.quaternion.y},${this.camera.quaternion.z}`;
    if (key === this.faceMeKey) return;
    this.faceMeKey = key;
    const forward = this.camera.getWorldDirection(new THREE.Vector3());
    const ortho = this.camera instanceof THREE.OrthographicCamera;
    for (const figure of this.faceMe) {
      // Toward the camera on the ground plane; a parallel view has one direction for all.
      const dx = ortho ? -forward.x : position.x - figure.feet.x;
      const dz = ortho ? -forward.z : position.z - figure.feet.z;
      if (Math.hypot(dx, dz) < 1e-6) continue;
      if (figure.plane) figure.plane.rotation.y = Math.atan2(dx, dz);
      else if (figure.pivot && figure.heading !== undefined) figure.pivot.rotation.y = Math.atan2(-dz, dx) - figure.heading;
    }
  }

  /**
   * Fit the camera's near and far planes to the model. A depth range of
   * millions of metres leaves a 24-bit depth buffer unable to tell surfaces
   * centimetres apart (concrete from the rebar inside it), so they ghost through
   * each other; the range is kept to the model's own depth along the view.
   */
  private fitClipping(): void {
    if (this.bounds.isEmpty()) return;
    const center = this.bounds.getCenter(new THREE.Vector3());
    const radius = Math.max(this.bounds.getSize(new THREE.Vector3()).length() / 2, 0.01) * 1.25;
    const direction = this.camera.getWorldDirection(new THREE.Vector3());
    const depth = center.clone().sub(this.camera.position).dot(direction);
    if (this.camera instanceof THREE.OrthographicCamera) {
      const near = depth - radius;
      const far = depth + radius;
      if (Math.abs(this.camera.near - near) > radius * 1e-3 || Math.abs(this.camera.far - far) > radius * 1e-3) {
        this.camera.near = near;
        this.camera.far = far;
        this.camera.updateProjectionMatrix();
      }
    } else {
      const near = Math.max(depth - radius, radius * 1e-4);
      const far = Math.max(depth + radius, near * 10);
      if (Math.abs(this.camera.near - near) > near * 1e-2 || Math.abs(this.camera.far - far) > far * 1e-2) {
        this.camera.near = near;
        this.camera.far = far;
        this.camera.updateProjectionMatrix();
      }
    }
  }

  /**
   * Keep labels a constant size on screen and push overlapping ones apart.
   * Labels keep their leader line; dimension labels stay put and are laid out first.
   */
  private layoutLabels(): void {
    if (!this.labelEntries.length) return;
    this.camera.updateMatrixWorld();
    const key = `${this.camera.matrixWorldInverse.elements.join(",")}|${this.canvas.clientWidth}x${this.canvas.clientHeight}|${
      this.camera instanceof THREE.OrthographicCamera ? this.camera.zoom : 0}`;
    if (key === this.labelViewKey) return;
    this.labelViewKey = key;
    const width = Math.max(this.canvas.clientWidth, 1);
    const height = Math.max(this.canvas.clientHeight, 1);
    const toScreen = (point: THREE.Vector3) => {
      const ndc = point.clone().project(this.camera);
      return {x: (ndc.x * 0.5 + 0.5) * width, y: (-ndc.y * 0.5 + 0.5) * height, z: ndc.z};
    };
    const placed: {x0: number; y0: number; x1: number; y1: number}[] = [];
    const overlaps = (r: {x0: number; y0: number; x1: number; y1: number}) =>
      placed.some(p => r.x0 < p.x1 && r.x1 > p.x0 && r.y0 < p.y1 && r.y1 > p.y0);
    const order = [...this.labelEntries].sort((a, b) => Number(Boolean(a.leader)) - Number(Boolean(b.leader)));
    for (const entry of order) {
      if (!entry.group.visible) continue;
      const at = toScreen(entry.base);
      const hw = entry.widthPx / 2 + 3;
      const hh = entry.heightPx / 2 + 3;
      let shift = 0;
      if (entry.leader) {
        // Try straight up and down in screen space until the label sits clear of the others.
        const step = entry.heightPx + 4;
        for (let attempt = 0; attempt < 14; attempt += 1) {
          const candidate = (attempt % 2 === 0 ? -1 : 1) * Math.ceil(attempt / 2) * step;
          const rect = {x0: at.x - hw, x1: at.x + hw, y0: at.y + candidate - hh, y1: at.y + candidate + hh};
          if (!overlaps(rect)) { shift = candidate; break; }
        }
      }
      placed.push({x0: at.x - hw, x1: at.x + hw, y0: at.y + shift - hh, y1: at.y + shift + hh});
      // Back to the world: same depth as the label's own position, shifted on screen.
      const ndc = new THREE.Vector3(((at.x) / width) * 2 - 1, -((at.y + shift) / height) * 2 + 1, at.z);
      const world = ndc.unproject(this.camera);
      entry.sprite.position.copy(world);
      const pixel = this.pixelSize(world);
      entry.sprite.scale.set(pixel * entry.widthPx, pixel * entry.heightPx, 1);
      if (entry.leader && entry.anchor) {
        entry.leader.geometry.setFromPoints([entry.anchor, world]);
      }
    }
  }

  private disposeChildren(parent: THREE.Object3D): void {
    while (parent.children.length) {
      const child = parent.children.pop()!;
      child.traverse(object => {
        if (!(object instanceof THREE.Mesh || object instanceof THREE.Line
            || object instanceof THREE.Sprite)) return;
        if (object instanceof THREE.Mesh || object instanceof THREE.Line) object.geometry?.dispose();
        const materials = Array.isArray(object.material) ? object.material : [object.material];
        for (const material of materials) {
          if (!material) continue;
          for (const value of Object.values(material)) {
            if (value instanceof THREE.Texture) value.dispose();
          }
          material.dispose();
        }
      });
    }
  }
}
