import {
  AIBriefing,
  AnalysisResult,
  AnalyzeCachedPairRequest,
  DemoFloodScenarioResponse,
  FieldVerificationStatus,
  GranuleSearchRequest,
  GranuleSearchResponse,
  HealthStatus,
  HistoryItem,
  ObservationPairSearchRequest,
  ObservationPairSearchResponse,
  PairDownloadRequest,
  PairDownloadResponse,
  RoadImpactResponse,
  RoadVerificationRecord,
  RoutePlanResponse,
  RoutingMode,
} from '../types';

const API_BASE = '/api';

export async function fetchHealth(): Promise<HealthStatus> {
  const res = await fetch(`${API_BASE}/health`);
  if (!res.ok) throw new Error(`Health check failed: ${res.statusText}`);
  return res.json();
}

export async function searchGranules(
  params: GranuleSearchRequest
): Promise<GranuleSearchResponse> {
  const res = await fetch(`${API_BASE}/search/granules`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'Granule search failed');
  }
  return res.json();
}

export async function searchObservationPairs(
  params: ObservationPairSearchRequest
): Promise<ObservationPairSearchResponse> {
  const res = await fetch(`${API_BASE}/search/observation-pairs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'Observation pair search failed');
  }
  return res.json();
}

export async function analyzeUpload(
  beforeFile: File,
  afterFile: File,
  thresholdDb: number = -3.0,
  speckleFilter: boolean = true,
  bounds?: [[number, number], [number, number]]
): Promise<AnalysisResult> {
  const formData = new FormData();
  formData.append('before_file', beforeFile);
  formData.append('after_file', afterFile);
  formData.append('threshold_db', thresholdDb.toString());
  formData.append('speckle_filter', speckleFilter.toString());
  if (bounds) {
    formData.append('bounds', JSON.stringify(bounds));
  }

  const res = await fetch(`${API_BASE}/analyze/upload`, {
    method: 'POST',
    body: formData,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'Upload analysis failed');
  }
  return res.json();
}

export async function analyzeASF(
  beforeGranuleId: string,
  afterGranuleId: string,
  thresholdDb: number = -3.0,
  speckleFilter: boolean = true,
  aoiWkt?: string
): Promise<AnalysisResult> {
  const res = await fetch(`${API_BASE}/analyze/asf`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      before_granule_id: beforeGranuleId,
      after_granule_id: afterGranuleId,
      threshold_db: thresholdDb,
      speckle_filter: speckleFilter,
      aoi_wkt: aoiWkt,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'ASF analysis failed');
  }
  return res.json();
}

export async function downloadProductPair(
  params: PairDownloadRequest
): Promise<PairDownloadResponse> {
  const res = await fetch(`${API_BASE}/products/download-pair`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'Pair download failed');
  }
  return res.json();
}

export async function analyzeCachedPair(
  params: AnalyzeCachedPairRequest
): Promise<AnalysisResult> {
  const res = await fetch(`${API_BASE}/analyze/cached-pair`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'Cached pair SAR analysis failed');
  }
  return res.json();
}

export async function generateBriefing(
  analysisId: string,
  operationalFocus?: string
): Promise<AIBriefing> {
  const res = await fetch(`${API_BASE}/briefing/${analysisId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ operational_focus: operationalFocus }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'Briefing generation failed');
  }
  return res.json();
}

export async function getHistory(): Promise<HistoryItem[]> {
  const res = await fetch(`${API_BASE}/history`);
  if (!res.ok) throw new Error('Failed to fetch history');
  return res.json();
}

export async function getHistoryDetail(analysisId: string): Promise<AnalysisResult> {
  const res = await fetch(`${API_BASE}/history/${analysisId}`);
  if (!res.ok) throw new Error('Failed to fetch history detail');
  return res.json();
}

export async function deleteHistoryItem(analysisId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/history/${analysisId}`, {
    method: 'DELETE',
  });
  if (!res.ok) throw new Error('Failed to delete history item');
}

export async function assessRoadImpact(params: {
  analysis_id?: string;
  aoi_wkt?: string;
  bounds?: [number, number][];
  proximity_meters?: number;
  mask_geojson?: any;
  is_demo?: boolean;
  verifications?: Record<string, any>;
}): Promise<RoadImpactResponse> {
  const res = await fetch(`${API_BASE}/roads/impact`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'Road impact assessment failed');
  }
  return res.json();
}

export async function submitRoadVerification(params: {
  osm_id: string;
  status: FieldVerificationStatus;
  verified_by: string;
  notes?: string;
  location_lat?: number;
  location_lon?: number;
}): Promise<RoadVerificationRecord> {
  const res = await fetch(`${API_BASE}/roads/verify`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'Submitting road verification failed');
  }
  return res.json();
}

export async function fetchRoadVerifications(): Promise<RoadVerificationRecord[]> {
  const res = await fetch(`${API_BASE}/roads/verifications`);
  if (!res.ok) throw new Error('Failed to fetch road verifications');
  return res.json();
}

export async function planRoute(params: {
  start_lat: number;
  start_lon: number;
  dest_lat: number;
  dest_lon: number;
  routing_mode?: RoutingMode;
  permit_restricted?: boolean;
  proximity_meters?: number;
  analysis_id?: string;
  mask_geojson?: any;
  aoi_wkt?: string;
  bounds?: [number, number][];
  is_demo?: boolean;
  verifications?: Record<string, any>;
}): Promise<RoutePlanResponse> {
  const res = await fetch(`${API_BASE}/roads/route`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'Route calculation failed');
  }
  return res.json();
}

export async function loadDemoFloodScenario(): Promise<DemoFloodScenarioResponse> {
  const res = await fetch(`${API_BASE}/demo/flood-scenario`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'Failed to load DEMO flood scenario');
  }
  return res.json();
}
