export interface SceneSummary {
  schema: "ingetrazo.scene-summary.v1";
  bounds: {min: number[] | null; max: number[] | null};
  loose_geometry: GeometryCounts;
  unique_geometry: GeometryCounts & {meshes: number};
  placements: number;
  groups: number;
  components: number;
  dimensions: number;
  dimension_details?: DimensionDetail[];
  text_labels: number;
  text_label_details?: TextLabelDetail[];
  guides?: number;
  guide_details?: GuideDetail[];
  reference_images?: number;
  reference_image_details?: ReferenceImageDetail[];
  layers: number;
  materials: number;
  saved_views: number;
  saved_view_details?: SavedViewDetail[];
  section_planes: number;
  section_details?: SectionPlaneDetail[];
  section_cuts_visible?: boolean;
  section_planes_visible?: boolean;
  compositions: number;
  composition_details?: CompositionDetail[];
  georeferenced: boolean;
  georef_detail?: GeorefDetail | null;
  map?: MapDetail | null;
  survey_points?: number;
  survey_point_details?: SurveyPointDetail[];
  survey_points_truncated?: boolean;
  geo_paths?: number;
  geo_path_details?: GeoPathDetail[];
  geo_paths_truncated?: boolean;
  photogrammetry?: PhotogrammetryDetail | null;
  display_style?: DisplayStyleDetail;
  shadows?: ShadowDetail;
  sun?: SunDetail | null;
  bim_objects?: BimObjectDetail[];
  units: {length: string; precision: number};
  camera?: CameraHome | null;
  layer_details?: LayerDetail[];
  outline?: {items: OutlineItem[]; truncated: boolean; limit: number};
}

export interface MapDetail {
  source: string;
  name: string;
  zoom: number;
  radius: number;
  opacity: number;
  visible: boolean;
  attribution: string;
  tiles: MapTileDetail[];
  tiles_truncated: boolean;
}

export interface MapTileDetail {
  x: number;
  y: number;
  url: string;
  corners: Array<[number, number, number]>;
}

export interface CompositionDetail {
  index: number;
  name: string;
  paper: string;
  landscape: boolean;
  page_mm: [number, number];
  frames: number;
  frame_details: Array<{view: string; scale: number; style: string; title: string}>;
}

export interface DisplayStyleDetail {
  name: string;
  face_mode: "textures" | "shaded" | "hidden_line" | "monochrome" | "wireframe" | "xray";
  edges: boolean;
  profiles: boolean;
  back_edges: boolean;
  edge_color: number[];
  front_color: number[];
  back_color: number[] | null;
  background: number[];
  sky: boolean;
  sky_color: number[];
  ground_color: number[];
  section_fill: boolean;
  section_fill_color: number[];
}

export interface ShadowDetail {
  enabled: boolean;
  month: number;
  day: number;
  hour: number;
  minute: number;
  darkness: number;
  utc_offset?: number;
}

export interface SunDetail {
  direction: [number, number, number] | null;
  elevation: number;
  azimuth: number;
  when_utc: string;
}

export interface GeorefDetail {
  lat: number;
  lon: number;
  alt: number;
  north?: number;
  zone: number;
  hemisphere: "N" | "S";
}

export interface SurveyPointDetail {
  id: string;
  position: [number, number, number];
  name: string;
  description: string;
}

export interface GeoPathDetail {
  id: string;
  name: string;
  points: Array<[number, number, number]>;
  points_truncated: boolean;
  closed: boolean;
  surface: "flat" | "draped" | null;
  length: number;
  area: number;
}

export interface PhotogrammetryDetail {
  vertices: number;
  triangles: number;
  visible: boolean;
  georeferenced: boolean;
  layer: string | null;
  vertical_reference: string;
  bounds: {min: [number, number, number] | null; max: [number, number, number] | null};
  mesh?: {
    vertices: Array<[number, number, number]>;
    triangles: Array<[number, number, number]>;
  } | null;
}

export interface BimObjectDetail {
  id: string;
  class: string;
  name: string;
  area_m2: number;
  volume_m3: number | null;
  takeoff: number | null;
  takeoff_unit: string;
  quantity_set: string;
  quantities: Array<{kind: "area" | "volume" | "length"; name: string; value: number}>;
}

export interface DimensionDetail {
  id: string;
  a: [number, number, number];
  b: [number, number, number];
  line: [[number, number, number], [number, number, number]];
  midpoint: [number, number, number];
  value: number;
  label: string;
  axis: "x" | "y" | "z" | null;
  layer: string | null;
  visible: boolean;
}

export interface TextLabelDetail {
  id: string;
  anchor: [number, number, number];
  position: [number, number, number];
  text: string;
  layer: string | null;
  visible: boolean;
}

export interface GuideDetail {
  id: string;
  point: [number, number, number];
  direction: [number, number, number] | null;
  origin: [number, number, number] | null;
}

interface GeometryCounts {
  vertices: number;
  edges: number;
  faces: number;
}

export interface CameraHome {
  target: [number, number, number];
  distance: number;
  yaw: number;
  pitch: number;
  fov_deg: number;
  perspective: boolean;
  two_point: boolean;
}

export interface SavedViewDetail extends CameraHome {
  name: string;
  hidden_layers: string[];
  section?: {active: number | null; planes_shown?: boolean; cuts_shown?: boolean} | null;
  hidden_objects?: string[] | null;
  hidden_object_visibility_ids?: string[] | null;
}

export interface SectionPlaneDetail {
  id: number;
  name: string;
  symbol: string;
  point: [number, number, number];
  normal: [number, number, number];
  active: boolean;
}

export interface ReferenceImageDetail {
  id: string;
  name: string;
  layer: string;
  opacity: number;
  locked: boolean;
  width: number;
  height: number;
}

export interface LayerDetail {
  name: string;
  visible: boolean;
  locked: boolean;
}

export interface OutlineItem {
  id: string;
  preview_id?: string;
  visibility_id?: string;
  native_id?: string;
  name: string;
  kind: "group" | "component";
  layer: string;
  visible: boolean;
  hidden: boolean;
  geometry: GeometryCounts;
  material?: {color?: number[]; opacity?: number; mat?: string};
  ifc?: {class?: string; name?: string; id?: string};
  children: OutlineItem[];
}

export interface PickInfo {
  objectId?: string;
  object: string;
  kind?: string;
  layer?: string;
  material?: string;
  triangle?: number;
  point?: [number, number, number];
}

export interface MeasurementInfo {
  distance: number | null;
  start: [number, number, number];
  end?: [number, number, number];
  complete: boolean;
}

export interface DocumentRevision {
  number: number;
  created_at: string;
  summary: SceneSummary;
}

export interface DocumentRecord {
  schema: "ingetrazo.document.v1";
  id: string;
  name: string;
  created_at: string;
  updated_at: string;
  latest_revision: number;
  revisions: DocumentRevision[];
  /** Where Undo and Redo lead (revision numbers), worked out by the server from the revisions. */
  undo?: {undo_to: number | null; redo_to: number | null; position: number; states: number};
}
