export type SatellitePlatform = 'NISAR' | 'SENTINEL-1';

export type SeverityTier = 'CRITICAL' | 'ELEVATED' | 'MODERATE' | 'NOMINAL';

export interface HealthStatus {
  status: string;
  database_connected: boolean;
  earthdata_configured: boolean;
  gemini_configured: boolean;
  storage_writable: boolean;
  timestamp: string;
}

export interface SARGranule {
  id: string;
  granule_name: string;
  platform: string;
  processing_level?: string;
  data_maturity?: string;
  polarization?: string;
  acquisition_time?: string;
  footprint_geojson?: {
    type: string;
    coordinates: number[][][] | number[][][][];
  };
  download_url?: string;
  browse_url?: string;
}

export interface GranuleSearchRequest {
  wkt_polygon: string;
  dataset: SatellitePlatform;
  start_date?: string;
  end_date?: string;
  processing_level?: string;
  max_results?: number;
}

export interface GranuleSearchResponse {
  search_id: string;
  total_count: number;
  granules: SARGranule[];
  message?: string;
}

export interface CommonObservation {
  provider: string;
  original_id: string;
  collection_id: string;
  platform: string;
  instrument: string;
  frequency_band: string;
  product_type?: string;
  processing_level?: string;
  polarization?: string;
  acquisition_time?: string;
  orbit_direction?: string;
  track_or_orbit?: string;
  incidence_angle?: number;
  footprint_geojson?: {
    type: string;
    coordinates: number[][][] | number[][][][];
  };
  spatial_resolution?: number;
  is_online: boolean;
  download_url?: string;
  qualification: string;
  warnings: string[];
  raw_metadata?: Record<string, any>;
}

export interface ObservationPair {
  pair_id: string;
  before_observation: CommonObservation;
  after_observation: CommonObservation;
  is_compatible: boolean;
  status: string;
  compatibility_reasons: string[];
  rejection_reasons: string[];
  warnings: string[];
  ranking_score: number;
  ranking_explanation: string;
  aoi_coverage_percent: number;
  temporal_delta_days: number;
}

export interface ObservationPairSearchRequest {
  wkt_polygon: string;
  start_date?: string;
  end_date?: string;
  provider_preference?: string;
  dataset_preference?: string;
  max_candidates?: number;
}

export interface ObservationPairSearchResponse {
  search_id: string;
  total_observations_found: number;
  total_compatible_pairs: number;
  recommended_pair?: ObservationPair | null;
  alternative_pairs: ObservationPair[];
  status: string;
  message?: string;
  warnings: string[];
}

export interface ProductDownloadResult {
  provider: string;
  collection_id?: string;
  item_id: string;
  status: string;
  file_size_bytes?: number;
  sha256?: string;
  is_cached: boolean;
  validation_error?: string;
  sar_preflight_ok: boolean;
  sar_preflight_details?: Record<string, any>;
  warnings: string[];
}

export interface PairDownloadRequest {
  before_provider: string;
  before_item_id: string;
  before_collection?: string;
  before_download_url?: string;
  after_provider: string;
  after_item_id: string;
  after_collection?: string;
  after_download_url?: string;
  aoi_wkt?: string;
}

export interface PairDownloadResponse {
  pair_status: 'PAIR_READY_FOR_ANALYSIS' | 'PARTIAL' | 'DOWNLOAD_FAILED' | 'PAIR_UNSUPPORTED';
  before_product: ProductDownloadResult;
  after_product: ProductDownloadResult;
  message?: string;
  warnings: string[];
}

export interface AnalyzeCachedPairRequest {
  before_provider: string;
  before_item_id: string;
  before_collection?: string;
  after_provider: string;
  after_item_id: string;
  after_collection?: string;
  aoi_wkt?: string;
  threshold_db?: number;
  speckle_filter?: boolean;
  speckle_kernel_size?: number;
}


export interface HistogramBin {
  bin: string;
  count: number;
  is_change?: boolean;
}

export interface AnalysisResult {
  analysis_id: string;
  source_type: 'ASF_LIVE' | 'USER_UPLOAD' | 'CACHED_SATELLITE_PAIR' | string;
  before_granule_id?: string;
  after_granule_id?: string;
  before_date?: string;
  after_date?: string;
  before_platform?: string;
  after_platform?: string;
  threshold_db: number;
  speckle_filter: boolean;
  impacted_km2: number;
  total_scene_km2?: number;
  valid_pixels?: number;
  crs?: string;
  change_type?: string;
  scientific_qualification?: string;
  mean_db_drop: number;
  severity_tier: SeverityTier;
  mask_image_url?: string;
  mask_geojson?: {
    type: string;
    features: any[];
  };
  bounds?: [[number, number], [number, number]];
  histogram: HistogramBin[];
  created_at: string;
  briefing?: AIBriefing;
}

export interface AIBriefing {
  id: string;
  analysis_id: string;
  model_name: string;
  risk_level: SeverityTier;
  summary_text: string;
  primary_driver: string;
  recommended_actions: string[];
  created_at: string;
}

export interface HistoryItem {
  id: string;
  source_type: string;
  threshold_db: number;
  impacted_km2: number;
  mean_db_drop: number;
  severity_tier: SeverityTier;
  has_briefing: boolean;
  created_at: string;
}

export type RoadImpactClassification =
  | 'POTENTIALLY_AFFECTED'
  | 'NEARBY_CHANGE_REGION'
  | 'NO_DETECTED_INTERSECTION'
  | 'UNVERIFIED';

export type FieldVerificationStatus =
  | 'UNVERIFIED'
  | 'VERIFIED_PASSABLE'
  | 'VERIFIED_BLOCKED'
  | 'RESTRICTED';

export interface RoadImpactProperties {
  osm_id: number | string;
  name: string;
  highway: string;
  classification: RoadImpactClassification;
  sar_classification?: RoadImpactClassification;
  field_status?: FieldVerificationStatus;
  verified_by?: string;
  verified_at?: string;
  verification_notes?: string;
  distance_meters: number;
  assessment_note: string;
  scientific_qualification?: string;
}

export interface RoadImpactFeature {
  type: 'Feature';
  id?: string;
  properties: RoadImpactProperties;
  geometry: {
    type: 'LineString' | 'MultiLineString';
    coordinates: number[][] | number[][][];
  };
}

export interface RoadImpactResponse {
  assessment_id: string;
  analysis_id?: string;
  status: 'COMPLETED' | 'NO_CHANGE_DETECTED' | 'OSM_UNAVAILABLE' | 'UNASSESSED_NEUTRAL' | string;
  proximity_threshold_meters: number;
  total_roads_assessed: number;
  impacted_count: number;
  nearby_count: number;
  no_intersection_count: number;
  unverified_count: number;
  road_geojson: {
    type: 'FeatureCollection';
    features: RoadImpactFeature[];
  };
  message?: string;
  scientific_qualification: string;
  created_at: string;
}

export interface DemoFloodScenarioResponse {
  status: string;
  sar_result: AnalysisResult;
  road_assessment: RoadImpactResponse;
  demo_banner: string;
  simulated_label: string;
  scientific_qualification: string;
}

export interface RoadVerificationRecord {
  id: string;
  osm_id: string;
  status: FieldVerificationStatus;
  verified_by: string;
  notes?: string;
  location_lat?: number;
  location_lon?: number;
  created_at: string;
}

export type RoutingMode = 'CONSERVATIVE' | 'EXPLORATORY';

export interface RoutePlanResponse {
  route_id: string;
  status: 'ROUTE_FOUND' | 'NO_ROUTE_FOUND' | 'ROUTING_UNAVAILABLE';
  routing_mode: RoutingMode;
  total_distance_km: number;
  passable_segments_count: number;
  unverified_segments_count: number;
  restricted_segments_count: number;
  route_geojson?: {
    type: 'FeatureCollection';
    features: any[];
  };
  warnings: string[];
  candidate_label: string;
  scientific_qualification: string;
  message?: string;
  created_at?: string;
}
