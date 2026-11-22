import React, { useState, useEffect, useRef } from 'react';
import { useLocation } from 'react-router-dom';
import {
  MapContainer,
  TileLayer,
  GeoJSON,
  ImageOverlay,
  useMap,
} from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import '@geoman-io/leaflet-geoman-free';
import '@geoman-io/leaflet-geoman-free/dist/leaflet-geoman.css';
import {
  Search,
  Layers,
  ChevronLeft,
  ChevronRight,
  Sliders,
  Calendar,
  Satellite,
  AlertTriangle,
  AlertCircle,
  Download,
  Compass,
  CheckCircle,
  FileCode,
  PenTool,
  Square,
  Eye,
  RefreshCw,
  X,
  ArrowUpDown,
  Navigation,
  Route,
  ShieldCheck,
  ShieldAlert,
  MapPin,
  CheckSquare,
} from 'lucide-react';
import {
  searchGranules,
  searchObservationPairs,
  analyzeASF,
  downloadProductPair,
  analyzeCachedPair,
  generateBriefing,
  assessRoadImpact,
  submitRoadVerification,
  planRoute,
  loadDemoFloodScenario,
} from '../api/client';
import {
  SARGranule,
  AnalysisResult,
  SatellitePlatform,
  RoadImpactResponse,
  FieldVerificationStatus,
  RoutingMode,
  RoutePlanResponse,
  ObservationPair,
  ObservationPairSearchResponse,
  CommonObservation,
  ProductDownloadResult,
  DemoFloodScenarioResponse,
} from '../types';
import { Button } from '../components/Button';
import { Card } from '../components/Card';
import { HistogramChart } from '../components/HistogramChart';
import { AIBriefingCard } from '../components/AIBriefingCard';
import { EmptyState } from '../components/EmptyState';

// Helper controller component for Geoman and Map FlyTo
const MapController: React.FC<{
  onAoiDrawn: (wkt: string) => void;
  flyToBoundsTarget: L.LatLngBoundsExpression | null;
  onMapReady: (map: L.Map) => void;
  leftOpen: boolean;
  rightOpen: boolean;
}> = ({ onAoiDrawn, flyToBoundsTarget, onMapReady, leftOpen, rightOpen }) => {
  const map = useMap();

  useEffect(() => {
    if (!map) return;
    onMapReady(map);

    // Mount Geoman Drawing Controls visibly on map (topleft)
    map.pm.addControls({
      position: 'topleft',
      drawPolygon: true,
      drawRectangle: true,
      editMode: true,
      removalMode: true,
      drawMarker: false,
      drawCircle: false,
      drawCircleMarker: false,
      drawPolyline: false,
      drawText: false,
      rotateMode: false,
      cutPolygon: false,
      dragMode: false,
    });

    map.pm.setGlobalOptions({
      pathOptions: {
        color: '#36CFC9',
        fillColor: '#36CFC9',
        fillOpacity: 0.18,
        weight: 2,
      },
    });

    const updateWktFromLayer = (layer: any) => {
      let latlngs = layer.getLatLngs ? layer.getLatLngs() : null;
      if (latlngs) {
        while (Array.isArray(latlngs) && latlngs.length > 0 && Array.isArray(latlngs[0])) {
          latlngs = latlngs[0];
        }
        if (latlngs.length > 0) {
          const coords = latlngs.map((pt: any) => `${pt.lng.toFixed(6)} ${pt.lat.toFixed(6)}`);
          coords.push(coords[0]); // Close ring
          const wkt = `POLYGON((${coords.join(', ')}))`;
          onAoiDrawn(wkt);
        }
      }
    };

    const handleCreate = (e: any) => {
      updateWktFromLayer(e.layer);
      if (e.layer && e.layer.on) {
        e.layer.on('pm:edit', (ev: any) => updateWktFromLayer(ev.layer || e.layer));
      }
    };

    const handleRemove = () => {
      onAoiDrawn('');
    };

    map.on('pm:create', handleCreate);
    map.on('pm:remove', handleRemove);

    return () => {
      map.off('pm:create', handleCreate);
      map.off('pm:remove', handleRemove);
      map.pm.removeControls();
    };
  }, [map, onAoiDrawn, onMapReady]);

  // Keep map tiles & layout synced on rail collapse/expand
  useEffect(() => {
    if (!map) return;
    const timer = setTimeout(() => {
      map.invalidateSize();
    }, 220);
    return () => clearTimeout(timer);
  }, [map, leftOpen, rightOpen]);

  useEffect(() => {
    if (map && flyToBoundsTarget) {
      try {
        const b = L.latLngBounds(flyToBoundsTarget as any);
        if (b.isValid()) {
          map.flyToBounds(b, {
            duration: 1.0,
            padding: [40, 40],
          });
        }
      } catch (err) {
        console.warn('Invalid flyToBoundsTarget:', err);
      }
    }
  }, [map, flyToBoundsTarget]);

  return null;
};

// Validation & formatting helpers for robust SAR granule handling
function isValidFootprint(fg: any): boolean {
  if (!fg || typeof fg !== 'object') return false;
  if (!fg.type || !fg.coordinates || !Array.isArray(fg.coordinates) || fg.coordinates.length === 0) return false;
  if (fg.type === 'Polygon') {
    return Array.isArray(fg.coordinates[0]) && fg.coordinates[0].length >= 3;
  }
  if (fg.type === 'MultiPolygon') {
    return (
      Array.isArray(fg.coordinates[0]) &&
      Array.isArray(fg.coordinates[0][0]) &&
      fg.coordinates[0][0].length >= 3
    );
  }
  return true;
}

function formatAcqDate(dateStr?: string | null): string {
  if (!dateStr) return 'N/A';
  try {
    const d = new Date(dateStr);
    if (isNaN(d.getTime())) return 'N/A';
    return d.toISOString().replace('T', ' ').slice(0, 16) + ' UTC';
  } catch {
    return 'N/A';
  }
}

// Convert normalized CommonObservation into standard SARGranule format
function commonObsToGranule(obs: CommonObservation): SARGranule {
  return {
    id: obs.original_id,
    granule_name: obs.original_id,
    platform: `${obs.platform} (${obs.frequency_band})`,
    processing_level: obs.product_type || obs.processing_level || 'L2',
    polarization: obs.polarization || 'HH',
    acquisition_time: obs.acquisition_time,
    footprint_geojson: obs.footprint_geojson as any,
    download_url: obs.download_url,
  };
}

function getRoadStyle(featureProps: any) {
  const fieldStatus = featureProps?.field_status;
  if (fieldStatus === 'VERIFIED_BLOCKED') {
    return {
      color: '#EF4444', // Red
      weight: 4.5,
      opacity: 0.95,
      dashArray: undefined,
    };
  }
  if (fieldStatus === 'VERIFIED_PASSABLE') {
    return {
      color: '#22C55E', // Green
      weight: 3.5,
      opacity: 0.95,
      dashArray: undefined,
    };
  }
  if (fieldStatus === 'RESTRICTED') {
    return {
      color: '#A855F7', // Purple
      weight: 3.5,
      opacity: 0.95,
      dashArray: '4, 4',
    };
  }

  // If unverified, render SAR backscatter assessment
  const cls = featureProps?.classification || featureProps?.sar_classification;
  if (cls === 'POTENTIALLY_AFFECTED') {
    return {
      color: '#E06D53', // Terracotta
      weight: 3.5,
      opacity: 0.95,
      dashArray: undefined,
    };
  }
  if (cls === 'NEARBY_CHANGE_REGION') {
    return {
      color: '#EAB308', // Yellow
      weight: 2.5,
      opacity: 0.9,
      dashArray: '5, 5',
    };
  }
  if (cls === 'NO_DETECTED_INTERSECTION') {
    return {
      color: '#64748B', // Muted neutral
      weight: 1.8,
      opacity: 0.55,
      dashArray: undefined,
    };
  }
  return {
    color: '#94A3B8', // Grey / UNVERIFIED
    weight: 1.5,
    opacity: 0.5,
    dashArray: '2, 4',
  };
}

function getRoadPopupHtml(p: any): string {
  const name = p.name || 'Unnamed Road';
  const sarCls = p.sar_classification || p.classification || 'UNVERIFIED';
  const fieldSt = p.field_status || 'UNVERIFIED';
  const hwy = p.highway || 'road';
  const dist = p.distance_meters != null && p.distance_meters >= 0 ? `${p.distance_meters} m` : 'N/A';
  const note = p.assessment_note || '';

  let badgeColor = '#94A3B8';
  let badgeBg = 'rgba(148, 163, 184, 0.15)';
  if (fieldSt === 'VERIFIED_BLOCKED') {
    badgeColor = '#EF4444';
    badgeBg = 'rgba(239, 68, 68, 0.20)';
  } else if (fieldSt === 'VERIFIED_PASSABLE') {
    badgeColor = '#22C55E';
    badgeBg = 'rgba(34, 197, 94, 0.20)';
  } else if (fieldSt === 'RESTRICTED') {
    badgeColor = '#A855F7';
    badgeBg = 'rgba(168, 85, 247, 0.20)';
  } else if (sarCls === 'POTENTIALLY_AFFECTED') {
    badgeColor = '#E06D53';
    badgeBg = 'rgba(224, 109, 83, 0.20)';
  } else if (sarCls === 'NEARBY_CHANGE_REGION') {
    badgeColor = '#EAB308';
    badgeBg = 'rgba(234, 179, 8, 0.20)';
  } else if (sarCls === 'NO_DETECTED_INTERSECTION') {
    badgeColor = '#64748B';
    badgeBg = 'rgba(100, 116, 139, 0.20)';
  }

  return `<div style="font-family: 'Space Grotesk', sans-serif; font-size: 11px; min-width: 250px; line-height: 1.45; color: #F1F5F9;">
    <div style="display: flex; gap: 4px; margin-bottom: 6px; flex-wrap: wrap;">
      <span style="font-weight: bold; font-size: 10px; padding: 2px 6px; border-radius: 3px; color: ${badgeColor}; background: ${badgeBg}; text-transform: uppercase;">
        Ground: ${fieldSt.replace(/_/g, ' ')}
      </span>
      <span style="font-weight: bold; font-size: 10px; padding: 2px 6px; border-radius: 3px; color: #AAB7C4; background: #233442; text-transform: uppercase;">
        SAR: ${sarCls.replace(/_/g, ' ')}
      </span>
    </div>
    <div style="font-size: 12px; font-weight: 700; color: #F1F5F9; margin-bottom: 2px;">${name}</div>
    <div style="color: #AAB7C4; font-family: 'JetBrains Mono', monospace; font-size: 10px; margin-bottom: 6px;">
      OSM ID: way/${p.osm_id} • Type: ${hwy}
    </div>
    <div><strong>Distance to Detected Change:</strong> <span style="font-family: 'JetBrains Mono', monospace; color: #36CFC9;">${dist}</span></div>
    ${p.verified_by ? `<div style="margin-top: 4px; font-size: 10px; color: #AAB7C4;"><strong>Verified By:</strong> ${p.verified_by} (${new Date(p.verified_at || Date.now()).toLocaleTimeString()})</div>` : ''}
    ${p.verification_notes ? `<div style="margin-top: 2px; font-size: 10px; font-style: italic; color: #CBD5E1;">"${p.verification_notes}"</div>` : ''}
    <div style="margin-top: 6px; padding: 6px; background: #233442; border-left: 3px solid ${badgeColor}; border-radius: 2px; font-size: 10px; color: #E2E8F0;">
      ${note || 'Field verification can be submitted by clicking this road.'}
    </div>
    <div style="margin-top: 6px; font-size: 9px; color: #94A3B8; border-top: 1px solid #2C3E50; padding-top: 4px;">
      Click road segment to record ground-truth field verification.
    </div>
  </div>`;
}

function getRoadTooltipHtml(p: any): string {
  const name = p.name || 'Unnamed Road';
  const sarCls = p.sar_classification || p.classification || 'UNVERIFIED';
  const fieldSt = p.field_status || 'UNVERIFIED';

  let badgeColor = '#94A3B8';
  if (fieldSt === 'VERIFIED_BLOCKED') badgeColor = '#EF4444';
  else if (fieldSt === 'VERIFIED_PASSABLE') badgeColor = '#22C55E';
  else if (fieldSt === 'RESTRICTED') badgeColor = '#A855F7';
  else if (sarCls === 'POTENTIALLY_AFFECTED') badgeColor = '#E06D53';
  else if (sarCls === 'NEARBY_CHANGE_REGION') badgeColor = '#EAB308';
  else if (sarCls === 'NO_DETECTED_INTERSECTION') badgeColor = '#64748B';

  return `<strong>${name}</strong><br/>Ground: <span style="color:${badgeColor}; font-weight:bold;">${fieldSt.replace(/_/g, ' ')}</span><br/>SAR: ${sarCls.replace(/_/g, ' ')}`;
}

export const LiveMissionPage: React.FC = () => {
  const location = useLocation();

  // Rails collapse state
  const [leftOpen, setLeftOpen] = useState<boolean>(true);
  const [rightOpen, setRightOpen] = useState<boolean>(true);

  // Search parameters
  const [dataset, setDataset] = useState<SatellitePlatform>('NISAR');
  const [wktPolygon, setWktPolygon] = useState<string>('');
  const [startDate, setStartDate] = useState<string>('2026-01-01');
  const [endDate, setEndDate] = useState<string>('2026-03-31');
  const [isSearching, setIsSearching] = useState<boolean>(false);
  const [granules, setGranules] = useState<SARGranule[]>([]);
  const [searchMessage, setSearchMessage] = useState<string | null>(null);

  // Automatic Observation Pair Selection state (Task 11)
  const [isFindingPairs, setIsFindingPairs] = useState<boolean>(false);
  const [pairSearchResponse, setPairSearchResponse] = useState<ObservationPairSearchResponse | null>(null);
  const [recommendedPair, setRecommendedPair] = useState<ObservationPair | null>(null);
  const [selectedPair, setSelectedPair] = useState<ObservationPair | null>(null);
  const [pairSearchMessage, setPairSearchMessage] = useState<string | null>(null);

  const [searchPerformed, setSearchPerformed] = useState<boolean>(false);
  const [isDemoMode, setIsDemoMode] = useState<boolean>(false);

  // Granule pair selection
  const [beforeGranule, setBeforeGranule] = useState<SARGranule | null>(null);
  const [afterGranule, setAfterGranule] = useState<SARGranule | null>(null);
  const [isPairConfirmed, setIsPairConfirmed] = useState<boolean>(false);

  // Satellite Product Download & Validation Preparation state (Task 13)
  const [isPreparingProducts, setIsPreparingProducts] = useState<boolean>(false);
  const [productPreparationStatus, setProductPreparationStatus] = useState<string | null>(null);
  const [beforeProductResult, setBeforeProductResult] = useState<ProductDownloadResult | null>(null);
  const [afterProductResult, setAfterProductResult] = useState<ProductDownloadResult | null>(null);

  // Analysis parameters & execution
  const [thresholdDb, setThresholdDb] = useState<number>(-3.0);
  const [speckleFilter, setSpeckleFilter] = useState<boolean>(true);
  const [isAnalyzing, setIsAnalyzing] = useState<boolean>(false);
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  const [analysisResult, setAnalysisResult] = useState<AnalysisResult | null>(null);
  const [isBriefingLoading, setIsBriefingLoading] = useState<boolean>(false);

  // Evidence-Based Road Network Impact Assessment state
  const [roadAssessment, setRoadAssessment] = useState<RoadImpactResponse | null>(null);
  const [isAssessingRoads, setIsAssessingRoads] = useState<boolean>(false);
  const [roadProximityMeters, setRoadProximityMeters] = useState<number>(50);
  const [roadAssessmentError, setRoadAssessmentError] = useState<string | null>(null);
  const [showRoadsLayer, setShowRoadsLayer] = useState<boolean>(true);
  const [showSarLayer, setShowSarLayer] = useState<boolean>(true);
  const [showRouteLayer, setShowRouteLayer] = useState<boolean>(true);
  const [isLoadingDemo, setIsLoadingDemo] = useState<boolean>(false);

  // Field Verification workflow state
  const [selectedRoad, setSelectedRoad] = useState<any | null>(null);
  const [verifStatusInput, setVerifStatusInput] = useState<FieldVerificationStatus>('VERIFIED_PASSABLE');
  const [verifOperatorInput, setVerifOperatorInput] = useState<string>('Field Team Alpha');
  const [verifNotesInput, setVerifNotesInput] = useState<string>('');
  const [isSubmittingVerif, setIsSubmittingVerif] = useState<boolean>(false);
  const roadLayersRef = useRef<Map<string, { layer: any; feature: any }>>(new Map());

  // Preliminary Route Planning state
  const [routingMode, setRoutingMode] = useState<RoutingMode>('CONSERVATIVE');
  const [permitRestricted, setPermitRestricted] = useState<boolean>(false);
  const [startLat, setStartLat] = useState<string>('');
  const [startLon, setStartLon] = useState<string>('');
  const [destLat, setDestLat] = useState<string>('');
  const [destLon, setDestLon] = useState<string>('');
  const [isPlanningRoute, setIsPlanningRoute] = useState<boolean>(false);
  const [routePlan, setRoutePlan] = useState<RoutePlanResponse | null>(null);
  const [routeError, setRouteError] = useState<string | null>(null);

  // Observation compatibility and validity checks
  const sensorCompatibility = React.useMemo(() => {
    if (!beforeGranule || !afterGranule) return { ok: true, reason: '' };
    const p1 = String(beforeGranule.platform || '');
    const p2 = String(afterGranule.platform || '');
    const isS1Both =
      (p1.includes('Sentinel') || p1.includes('S1')) &&
      (p2.includes('Sentinel') || p2.includes('S1'));
    const isNisarBoth = p1.includes('NISAR') && p2.includes('NISAR');
    if (isS1Both || isNisarBoth || (p1 && p1 === p2)) {
      return { ok: true, reason: '' };
    }
    return {
      ok: false,
      reason: `Incompatible sensors: Cannot compare ${p1 || 'Unknown'} with ${p2 || 'Unknown'}. Both observations must belong to the same radar sensor family.`,
    };
  }, [beforeGranule, afterGranule]);

  const productLevelCheck = React.useMemo(() => {
    if (!beforeGranule || !afterGranule) return { ok: true, reason: '' };
    const l1 = String(beforeGranule.processing_level || '').toUpperCase();
    const l2 = String(afterGranule.processing_level || '').toUpperCase();
    if (l1.includes('SLC') || l2.includes('SLC')) {
      return {
        ok: false,
        reason:
          'Level-1 SLC slant-range complex products are unsupported for direct 2D change detection. Geocoded Level-2 products (GCOV, GUNW) or terrain-corrected GRD are required.',
      };
    }
    return { ok: true, reason: '' };
  }, [beforeGranule, afterGranule]);

  const sceneIdentityCheck = React.useMemo(() => {
    if (!beforeGranule || !afterGranule) return { ok: true, reason: '' };
    if (beforeGranule.id === afterGranule.id) {
      return {
        ok: false,
        reason:
          'Same observation selected for both Before and After. Change detection requires two distinct temporal acquisitions.',
      };
    }
    return { ok: true, reason: '' };
  }, [beforeGranule, afterGranule]);

  const isChronologicalOrder = React.useMemo(() => {
    if (!beforeGranule?.acquisition_time || !afterGranule?.acquisition_time) return true;
    return new Date(beforeGranule.acquisition_time).getTime() <= new Date(afterGranule.acquisition_time).getTime();
  }, [beforeGranule, afterGranule]);

  const isPairValid =
    Boolean(beforeGranule &&
    afterGranule &&
    sensorCompatibility.ok &&
    productLevelCheck.ok &&
    sceneIdentityCheck.ok);

  const handleSwapPair = () => {
    const temp = beforeGranule;
    setBeforeGranule(afterGranule);
    setAfterGranule(temp);
    setIsPairConfirmed(false);
    setAnalysisError(null);
  };

  // Map state
  const [mapInstance, setMapInstance] = useState<L.Map | null>(null);
  const [flyTarget, setFlyTarget] = useState<L.LatLngBoundsExpression | null>(null);
  const [geocoderQuery, setGeocoderQuery] = useState<string>('');
  const [isGeocoding, setIsGeocoding] = useState<boolean>(false);

  // Listen for navigation state from UploadPage or external analysis triggers
  useEffect(() => {
    if (location.state && (location.state as any).analysisResult) {
      const res = (location.state as any).analysisResult as AnalysisResult;
      setAnalysisResult(res);
      setRightOpen(true);

      // Auto-zoom to returned polygon bounds
      if (res.bounds && Array.isArray(res.bounds) && res.bounds.length === 2) {
        try {
          const b = L.latLngBounds(res.bounds);
          if (b.isValid()) {
            setFlyTarget(res.bounds);
          }
        } catch {
          // Fallback to mask_geojson bounds below
        }
      } else if (res.mask_geojson && res.mask_geojson.features && res.mask_geojson.features.length > 0) {
        try {
          const geoLayer = L.geoJSON(res.mask_geojson as any);
          const b = geoLayer.getBounds();
          if (b.isValid()) {
            setFlyTarget(b);
          }
        } catch (e) {
          console.warn('Could not compute bounds from mask_geojson', e);
        }
      }
    }
  }, [location.state]);

  // Programmatically trigger Geoman Polygon Drawing mode
  const handleStartDrawPolygon = () => {
    if (mapInstance && (mapInstance as any).pm) {
      (mapInstance as any).pm.enableDraw('Polygon', {
        snappable: true,
        snapDistance: 20,
      });
    }
  };

  // Programmatically trigger Geoman Bounding Box (Rectangle) Drawing mode
  const handleStartDrawRectangle = () => {
    if (mapInstance && (mapInstance as any).pm) {
      (mapInstance as any).pm.enableDraw('Rectangle', {
        snappable: true,
        snapDistance: 20,
      });
    }
  };

  // Capture current viewport as geographic AOI bounds
  const handleUseCurrentView = () => {
    if (!mapInstance) return;
    const b = mapInstance.getBounds();
    const south = b.getSouth().toFixed(5);
    const north = b.getNorth().toFixed(5);
    const west = b.getWest().toFixed(5);
    const east = b.getEast().toFixed(5);
    const wkt = `POLYGON((${west} ${south}, ${east} ${south}, ${east} ${north}, ${west} ${north}, ${west} ${south}))`;
    setWktPolygon(wkt);
    setSearchPerformed(false);
  };

  // Clear defined AOI and remove vector layers from map
  const handleClearAoi = () => {
    setWktPolygon('');
    setGranules([]);
    setBeforeGranule(null);
    setAfterGranule(null);
    setIsPairConfirmed(false);
    setAnalysisError(null);
    setRoadAssessment(null);
    setRoadAssessmentError(null);
    setSelectedRoad(null);
    setRoutePlan(null);
    setRouteError(null);
    setSearchPerformed(false);
    setSearchMessage(null);
    setPairSearchResponse(null);
    setRecommendedPair(null);
    setSelectedPair(null);
    setPairSearchMessage(null);
    if (mapInstance && (mapInstance as any).pm) {
      const layers = (mapInstance as any).pm.getGeomanLayers();
      if (layers && layers.length > 0) {
        layers.forEach((l: any) => {
          try {
            mapInstance.removeLayer(l);
          } catch {
            // ignore
          }
        });
      }
    }
  };

  // Load self-contained isolated synthetic demonstration scenario
  const handleLoadDemoFloodScenario = async () => {
    setIsLoadingDemo(true);
    setIsDemoMode(true);
    setSearchPerformed(false);
    setAnalysisError(null);
    setRoadAssessmentError(null);
    setRouteError(null);
    setRoutePlan(null);
    setSelectedRoad(null);
    setGranules([]);
    setBeforeGranule(null);
    setAfterGranule(null);
    setSelectedPair(null);
    setBeforeProductResult(null);
    setAfterProductResult(null);

    try {
      const demoData = await loadDemoFloodScenario();
      setAnalysisResult(demoData.sar_result);
      setRoadAssessment(demoData.road_assessment);
      setShowRoadsLayer(true);
      setShowSarLayer(true);
      setWktPolygon('POLYGON((-122.50 37.70, -122.40 37.70, -122.40 37.80, -122.50 37.80, -122.50 37.70))');
      if (demoData.sar_result.bounds) {
        setFlyTarget(demoData.sar_result.bounds);
      }
      setRightOpen(true);
    } catch (err: any) {
      setAnalysisResult(null);
      setRoadAssessment(null);
      setAnalysisError(err.message || 'Failed to load DEMO flood scenario.');
    } finally {
      setIsLoadingDemo(false);
    }
  };

  // Exit DEMO mode and return to clean OPERATIONAL mode
  const handleExitDemoMode = () => {
    setIsDemoMode(false);
    setAnalysisResult(null);
    setRoadAssessment(null);
    setRoutePlan(null);
    setSelectedRoad(null);
    setAnalysisError(null);
    setRoadAssessmentError(null);
    setRouteError(null);
    handleClearAoi();
  };

  // Fetch real OpenStreetMap road geometries for the defined AOI
  const handleFetchRoads = async () => {
    if (!wktPolygon) {
      setRoadAssessmentError('Please define an AOI bounding box or polygon first.');
      return;
    }
    setIsAssessingRoads(true);
    setRoadAssessmentError(null);
    try {
      const res = await assessRoadImpact({
        aoi_wkt: wktPolygon,
        proximity_meters: roadProximityMeters,
        mask_geojson: analysisResult?.mask_geojson || null,
        is_demo: isDemoMode,
      });
      setRoadAssessment(res);
      setShowRoadsLayer(true);
    } catch (err: any) {
      setRoadAssessment(null);
      setRoadAssessmentError(err.message || 'Failed to fetch OpenStreetMap road network.');
    } finally {
      setIsAssessingRoads(false);
    }
  };

  // Execute Live NASA ASF Search for selected region
  const handleSearch = async () => {
    if (!wktPolygon) {
      setSearchMessage('Please define a geographic region or bounding box before searching.');
      return;
    }
    setIsSearching(true);
    setSearchPerformed(true);
    setSearchMessage(null);
    setBeforeGranule(null);
    setAfterGranule(null);
    setIsPairConfirmed(false);
    setAnalysisError(null);

    try {
      const res = await searchGranules({
        wkt_polygon: wktPolygon,
        dataset: dataset,
        start_date: startDate ? `${startDate}T00:00:00Z` : undefined,
        end_date: endDate ? `${endDate}T23:59:59Z` : undefined,
        max_results: 25,
      });

      const rawGranules = Array.isArray(res?.granules) ? res.granules : [];

      // Sort observations chronologically by acquisition date
      const sorted = [...rawGranules].sort((a, b) => {
        const ta = a?.acquisition_time ? new Date(a.acquisition_time).getTime() : 0;
        const tb = b?.acquisition_time ? new Date(b.acquisition_time).getTime() : 0;
        return (isNaN(ta) ? 0 : ta) - (isNaN(tb) ? 0 : tb);
      });

      setGranules(sorted);

      if (sorted.length === 0) {
        setSearchMessage(res?.message || '0 granules found for this AOI and date range.');
      } else if (sorted.length === 1) {
        setBeforeGranule(sorted[0]);
        setAfterGranule(null);
        setIsPairConfirmed(false);
      } else {
        // Chronological suggestion; explicit user confirmation is strictly required
        setBeforeGranule(sorted[0]);
        setAfterGranule(sorted[sorted.length - 1]);
        setIsPairConfirmed(false);
      }
    } catch (err: any) {
      setSearchMessage(err.message || 'ASF live search request failed.');
      setGranules([]);
    } finally {
      setIsSearching(false);
    }
  };

  // Automatically discover and rank best compatible observation pair (Task 11)
  const handleFindBestPair = async () => {
    if (!wktPolygon) {
      setSearchMessage('Please define a geographic region or bounding box before finding observation pairs.');
      return;
    }
    setIsFindingPairs(true);
    setPairSearchMessage(null);
    setAnalysisError(null);

    try {
      const res = await searchObservationPairs({
        wkt_polygon: wktPolygon,
        start_date: startDate ? `${startDate}` : undefined,
        end_date: endDate ? `${endDate}` : undefined,
        dataset_preference: dataset,
        provider_preference: 'ALL',
        max_candidates: 30,
      });

      setPairSearchResponse(res);
      if (res.status === 'SUCCESS' && res.recommended_pair) {
        setRecommendedPair(res.recommended_pair);
        setSelectedPair(res.recommended_pair);

        const bGranule = commonObsToGranule(res.recommended_pair.before_observation);
        const aGranule = commonObsToGranule(res.recommended_pair.after_observation);
        setBeforeGranule(bGranule);
        setAfterGranule(aGranule);
        setIsPairConfirmed(false); // Explicit confirmation strictly required
        setPairSearchMessage(res.message || 'Optimal observation pair identified.');
        setBeforeProductResult(null);
        setAfterProductResult(null);
        setProductPreparationStatus(null);
        setAnalysisResult(null);
      } else {
        setRecommendedPair(null);
        setSelectedPair(null);
        setPairSearchMessage(res.message || 'No compatible observation pairs found for this AOI.');
        setBeforeProductResult(null);
        setAfterProductResult(null);
        setProductPreparationStatus(null);
      }
    } catch (err: any) {
      setPairSearchMessage(err.message || 'Observation pair search failed.');
      setRecommendedPair(null);
      setSelectedPair(null);
      setBeforeProductResult(null);
      setAfterProductResult(null);
      setProductPreparationStatus(null);
    } finally {
      setIsFindingPairs(false);
    }
  };

  const handleSelectAlternativePair = (pair: ObservationPair) => {
    setSelectedPair(pair);
    const bGranule = commonObsToGranule(pair.before_observation);
    const aGranule = commonObsToGranule(pair.after_observation);
    setBeforeGranule(bGranule);
    setAfterGranule(aGranule);
    setIsPairConfirmed(false);
    setBeforeProductResult(null);
    setAfterProductResult(null);
    setProductPreparationStatus(null);
    setAnalysisResult(null);
  };

  // Automated Satellite Product Download & Verification (Task 13)
  const handleDownloadAndPrepare = async () => {
    if (!selectedPair) return;
    setIsPreparingProducts(true);
    setProductPreparationStatus('Downloading and verifying satellite products from official providers...');
    setAnalysisError(null);

    const bObs = selectedPair.before_observation;
    const aObs = selectedPair.after_observation;

    try {
      const resp = await downloadProductPair({
        before_provider: bObs.provider,
        before_item_id: bObs.original_id,
        before_collection: bObs.collection_id,
        before_download_url: bObs.download_url,
        after_provider: aObs.provider,
        after_item_id: aObs.original_id,
        after_collection: aObs.collection_id,
        after_download_url: aObs.download_url,
        aoi_wkt: wktPolygon || undefined,
      });

      setBeforeProductResult(resp.before_product);
      setAfterProductResult(resp.after_product);

      if (resp.pair_status === 'PAIR_READY_FOR_ANALYSIS') {
        setProductPreparationStatus('Both products downloaded, SHA-256 verified, and ready for SAR analysis.');
      } else if (resp.pair_status === 'PARTIAL') {
        setProductPreparationStatus(resp.message || 'Partial download completed. One product failed.');
      } else if (resp.pair_status === 'PAIR_UNSUPPORTED') {
        setProductPreparationStatus(resp.message || 'Products downloaded but unsupported by SAR engine.');
      } else {
        setProductPreparationStatus(resp.message || 'Failed to download satellite observation pair.');
      }
    } catch (err: any) {
      setProductPreparationStatus(err.message || 'Product download request failed.');
    } finally {
      setIsPreparingProducts(false);
    }
  };

  // Run Real Change Detection on Selected Granules
  const handleRunAnalysis = async () => {
    if (!beforeGranule || !afterGranule) return;
    if (!isPairConfirmed) {
      setAnalysisError('Please explicitly confirm the observation pair before executing analysis.');
      return;
    }
    if (!sensorCompatibility.ok) {
      setAnalysisError(sensorCompatibility.reason);
      return;
    }
    if (!productLevelCheck.ok) {
      setAnalysisError(productLevelCheck.reason);
      return;
    }
    if (!sceneIdentityCheck.ok) {
      setAnalysisError(sceneIdentityCheck.reason);
      return;
    }

    setIsAnalyzing(true);
    setAnalysisError(null);
    setRoadAssessment(null);
    setRoadAssessmentError(null);
    setRoutePlan(null);
    setRouteError(null);
    setSelectedRoad(null);

    try {
      let res: AnalysisResult;
      // If DEMO mode is active, execute isolated synthetic flood scenario
      if (isDemoMode) {
        const demoData = await loadDemoFloodScenario();
        res = demoData.sar_result;
        setAnalysisResult(res);
        setRoadAssessment(demoData.road_assessment);
        setShowRoadsLayer(true);
        setShowSarLayer(true);
        setRightOpen(true);
        if (res.bounds) {
          setFlyTarget(res.bounds);
        }
        return;
      } else if (selectedPair && beforeProductResult?.sar_preflight_ok && afterProductResult?.sar_preflight_ok) {
        res = await analyzeCachedPair({
          before_provider: selectedPair.before_observation.provider,
          before_item_id: selectedPair.before_observation.original_id,
          before_collection: selectedPair.before_observation.collection_id,
          after_provider: selectedPair.after_observation.provider,
          after_item_id: selectedPair.after_observation.original_id,
          after_collection: selectedPair.after_observation.collection_id,
          aoi_wkt: wktPolygon || undefined,
          threshold_db: thresholdDb,
          speckle_filter: speckleFilter,
        });
      } else {
        if (!beforeGranule || !afterGranule) {
          throw new Error('Please select both before and after observations.');
        }
        res = await analyzeASF(
          beforeGranule.id,
          afterGranule.id,
          thresholdDb,
          speckleFilter,
          wktPolygon || undefined
        );
      }

      setAnalysisResult(res);
      setShowSarLayer(true);
      setRightOpen(true);
      if (res.bounds) {
        setFlyTarget(res.bounds);
      }

      // Automatic road impact assessment after successful SAR analysis
      try {
        setIsAssessingRoads(true);
        const impactRes = await assessRoadImpact({
          analysis_id: res.analysis_id,
          aoi_wkt: wktPolygon || undefined,
          bounds: res.bounds as any,
          proximity_meters: roadProximityMeters,
          mask_geojson: res.mask_geojson,
          is_demo: false,
        });
        setRoadAssessment(impactRes);
        setShowRoadsLayer(true);
      } catch (roadErr: any) {
        console.warn('Auto road assessment failed:', roadErr);
        setRoadAssessmentError(roadErr.message || 'Automatic road assessment failed');
      } finally {
        setIsAssessingRoads(false);
      }
    } catch (err: any) {
      setAnalysisResult(null); // Never render stale/fake overlays on failure
      setRoadAssessment(null);
      setAnalysisError(err.message || 'Analysis failed. Please check inputs and NASA ASF service status.');
    } finally {
      setIsAnalyzing(false);
    }
  };

  // Evidence-Based Road Network Impact Assessment
  const handleAssessRoadImpact = async () => {
    if (!analysisResult) return;
    setIsAssessingRoads(true);
    setRoadAssessmentError(null);
    setRoutePlan(null);
    setRouteError(null);
    try {
      // Gather active ground-truth verifications across all roads
      const activeVerifs: Record<string, any> = {};
      roadAssessment?.road_geojson?.features?.forEach((f: any) => {
        if (f.properties?.osm_id && f.properties?.field_status) {
          activeVerifs[String(f.properties.osm_id)] = {
            status: f.properties.field_status,
            verified_by: f.properties.verified_by || 'Field Operator',
            notes: f.properties.verification_notes || '',
          };
        }
      });

      const res = await assessRoadImpact({
        analysis_id: analysisResult.analysis_id,
        aoi_wkt: wktPolygon || undefined,
        bounds: analysisResult.bounds as any,
        proximity_meters: roadProximityMeters,
        mask_geojson: analysisResult.mask_geojson,
        is_demo: isDemoMode,
        verifications: activeVerifs,
      });
      setRoadAssessment(res);
      setShowRoadsLayer(true);
    } catch (err: any) {
      setRoadAssessment(null);
      setRoadAssessmentError(err.message || 'Road network assessment failed');
    } finally {
      setIsAssessingRoads(false);
    }
  };

  // Submit Field Verification for the selected road
  const handleSubmitVerification = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedRoad) return;
    const osmId = String(selectedRoad.properties.osm_id);
    setIsSubmittingVerif(true);
    try {
      const res = await submitRoadVerification({
        osm_id: osmId,
        status: verifStatusInput,
        verified_by: verifOperatorInput || 'Field Operator',
        notes: verifNotesInput || undefined,
      });

      // 1. Instantly update live Leaflet map layer in place
      const layerEntry = roadLayersRef.current.get(osmId);
      if (layerEntry) {
        const { layer } = layerEntry;
        const updatedProps = {
          ...layerEntry.feature.properties,
          field_status: res.status,
          verified_by: res.verified_by,
          verified_at: res.created_at,
          verification_notes: res.notes,
        };
        layerEntry.feature.properties = updatedProps;
        if (layer && typeof layer.setStyle === 'function') {
          layer.setStyle(getRoadStyle(updatedProps));
        }
        if (layer && typeof layer.setPopupContent === 'function') {
          layer.setPopupContent(getRoadPopupHtml(updatedProps));
        }
        if (layer && typeof layer.setTooltipContent === 'function') {
          layer.setTooltipContent(getRoadTooltipHtml(updatedProps));
        }
      }

      // 2. Update in selectedRoad
      setSelectedRoad((prev: any) => ({
        ...prev,
        properties: {
          ...prev.properties,
          field_status: res.status,
          verified_by: res.verified_by,
          verified_at: res.created_at,
          verification_notes: res.notes,
        },
      }));

      // 3. Update in roadAssessment.road_geojson.features
      setRoadAssessment((prev) => {
        if (!prev) return null;
        const updatedFeatures = prev.road_geojson.features.map((f: any) => {
          if (String(f.properties.osm_id) === osmId) {
            return {
              ...f,
              properties: {
                ...f.properties,
                field_status: res.status,
                verified_by: res.verified_by,
                verified_at: res.created_at,
                verification_notes: res.notes,
              },
            };
          }
          return f;
        });
        return {
          ...prev,
          road_geojson: {
            ...prev.road_geojson,
            features: updatedFeatures,
          },
        };
      });
    } catch (err: any) {
      alert(`Verification submission failed: ${err.message}`);
    } finally {
      setIsSubmittingVerif(false);
    }
  };

  // Preliminary Route Planning Execution
  const handlePlanRoute = async () => {
    if (!startLat || !startLon || !destLat || !destLon) {
      setRouteError('Please define both Start (lat, lon) and Destination (lat, lon) coordinates.');
      return;
    }
    setIsPlanningRoute(true);
    setRouteError(null);
    try {
      // Gather active ground-truth verifications across all roads
      const activeVerifs: Record<string, any> = {};
      roadAssessment?.road_geojson?.features?.forEach((f: any) => {
        if (f.properties?.osm_id && f.properties?.field_status) {
          activeVerifs[String(f.properties.osm_id)] = {
            status: f.properties.field_status,
            verified_by: f.properties.verified_by || 'Field Operator',
            notes: f.properties.verification_notes || '',
          };
        }
      });

      const res = await planRoute({
        start_lat: parseFloat(startLat),
        start_lon: parseFloat(startLon),
        dest_lat: parseFloat(destLat),
        dest_lon: parseFloat(destLon),
        routing_mode: routingMode,
        permit_restricted: permitRestricted,
        proximity_meters: roadProximityMeters,
        analysis_id: analysisResult?.analysis_id,
        mask_geojson: analysisResult?.mask_geojson,
        aoi_wkt: wktPolygon || undefined,
        bounds: analysisResult?.bounds as any,
        is_demo: isDemoMode,
        verifications: activeVerifs,
      });
      setRoutePlan(res);
      if (res.status === 'NO_ROUTE_FOUND') {
        setRouteError(res.message || 'No route could be found under selected routing rules.');
      }
    } catch (err: any) {
      setRoutePlan(null);
      setRouteError(err.message || 'Route planning failed.');
    } finally {
      setIsPlanningRoute(false);
    }
  };

  // Generate Structured Gemini AI Briefing
  const handleGenerateBriefing = async (focus?: string) => {
    if (!analysisResult) return;
    setIsBriefingLoading(true);
    try {
      const briefing = await generateBriefing(analysisResult.analysis_id, focus);
      setAnalysisResult((prev) => (prev ? { ...prev, briefing } : null));
    } catch (err: any) {
      alert(`Briefing failed: ${err.message}`);
    } finally {
      setIsBriefingLoading(false);
    }
  };

  // Quick geocoder search via Nominatim
  const handleGeocodeSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!geocoderQuery.trim()) return;
    setIsGeocoding(true);
    try {
      const res = await fetch(
        `https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(
          geocoderQuery
        )}`
      );
      const data = await res.json();
      if (data && data.length > 0) {
        const item = data[0];
        const bb = item.boundingbox; // [south, north, west, east]
        const south = parseFloat(bb[0]);
        const north = parseFloat(bb[1]);
        const west = parseFloat(bb[2]);
        const east = parseFloat(bb[3]);
        setFlyTarget([[south, west], [north, east]]);

        // Auto-set as bounding box WKT
        const wkt = `POLYGON((${west} ${south}, ${east} ${south}, ${east} ${north}, ${west} ${north}, ${west} ${south}))`;
        setWktPolygon(wkt);
      } else {
        alert('Location not found.');
      }
    } catch {
      alert('Geocoding request failed.');
    } finally {
      setIsGeocoding(false);
    }
  };

  // Export GeoJSON Mask
  const handleExportGeoJSON = () => {
    if (!analysisResult?.mask_geojson) return;
    const blob = new Blob([JSON.stringify(analysisResult.mask_geojson, null, 2)], {
      type: 'application/json',
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `nisar_pulse_mask_${analysisResult.analysis_id.slice(0, 8)}.geojson`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="relative w-full h-[calc(100vh-52px)] overflow-hidden flex bg-canvas-sand">
      {/* --- LEFT RAIL: Mission & Granules Discovery (320px) --- */}
      <aside
        className={`relative shrink-0 h-full bg-surface-cream border-r border-border-sandstone transition-all duration-200 ease-mechanical flex flex-col shadow-panel z-10 ${
          leftOpen ? 'w-[320px]' : 'w-0 overflow-hidden border-r-0'
        }`}
      >
        {/* Rail Header */}
        <div className="h-11 border-b border-border-subtle px-3.5 flex items-center justify-between shrink-0 bg-surface-cream">
          <div className="flex items-center space-x-2">
            <Layers className="w-4 h-4 text-accent-espresso" />
            <h2 className="text-xs font-semibold uppercase tracking-wider text-text-roast">
              Mission Parameters
            </h2>
          </div>
          <button
            onClick={() => setLeftOpen(false)}
            className="w-6 h-6 rounded flex items-center justify-center text-text-taupe hover:text-text-roast hover:bg-surface-recessed cursor-pointer"
          >
            <ChevronLeft className="w-4 h-4" />
          </button>
        </div>

        {/* Scrollable Criteria Body */}
        <div className="p-3.5 overflow-y-auto space-y-3 flex-1 text-xs">
          {/* Location Search Bar */}
          <form onSubmit={handleGeocodeSearch} className="flex items-center space-x-1.5">
            <input
              type="text"
              placeholder="Search location or placename..."
              value={geocoderQuery}
              onChange={(e) => setGeocoderQuery(e.target.value)}
              className="flex-1 text-xs px-2.5 py-1.5 rounded bg-surface-recessed border border-border-sandstone text-text-roast placeholder:text-text-taupe/60 focus:outline-none focus:border-accent-espresso"
            />
            <Button
              size="sm"
              variant="secondary"
              type="submit"
              isLoading={isGeocoding}
              icon={<Search className="w-3.5 h-3.5" />}
            />
          </form>

          {/* Mission Mode Switcher: OPERATIONAL vs DEMO */}
          <div className="p-2.5 rounded bg-surface-recessed border border-border-sandstone space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-[10px] font-bold uppercase tracking-wider text-text-taupe">
                Execution Mode
              </span>
              <span className={`text-[9px] font-mono font-bold px-1.5 py-0.5 rounded border ${
                isDemoMode
                  ? 'bg-amber-500/20 text-amber-300 border-amber-500/40'
                  : 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40'
              }`}>
                {isDemoMode ? 'DEMO MODE' : 'OPERATIONAL'}
              </span>
            </div>

            <div className="grid grid-cols-2 gap-1 bg-surface-cream p-1 rounded border border-border-subtle">
              <button
                type="button"
                onClick={() => {
                  if (isDemoMode) handleExitDemoMode();
                }}
                className={`py-1 text-[11px] font-semibold rounded text-center cursor-pointer transition-colors ${
                  !isDemoMode
                    ? 'bg-accent-espresso text-canvas-sand shadow-sm'
                    : 'text-text-taupe hover:text-text-roast'
                }`}
              >
                Operational
              </button>
              <button
                type="button"
                onClick={() => {
                  if (!isDemoMode) handleLoadDemoFloodScenario();
                }}
                className={`py-1 text-[11px] font-semibold rounded text-center cursor-pointer transition-colors ${
                  isDemoMode
                    ? 'bg-amber-600 text-white shadow-sm'
                    : 'text-text-taupe hover:text-text-roast'
                }`}
              >
                Demo Scenario
              </button>
            </div>

            {isDemoMode ? (
              <div className="space-y-2 pt-1 border-t border-border-subtle/50">
                <p className="text-[10px] text-amber-700 dark:text-amber-300 leading-tight font-medium">
                  Active: Simulated flood inundation scenario with synthetic SAR rasters and benchmark roads. Isolated from operational archives.
                </p>
                <div className="flex space-x-1.5">
                  <Button
                    size="sm"
                    variant="primary"
                    className="flex-1 bg-amber-600 hover:bg-amber-700 text-white"
                    isLoading={isLoadingDemo}
                    onClick={handleLoadDemoFloodScenario}
                    icon={<RefreshCw className="w-3.5 h-3.5" />}
                  >
                    Reload DEMO
                  </Button>
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={handleExitDemoMode}
                  >
                    Exit Demo
                  </Button>
                </div>
              </div>
            ) : (
              <div className="space-y-2 pt-1 border-t border-border-subtle/50">
                <p className="text-[10px] text-text-taupe leading-tight">
                  Real satellite observations & live OpenStreetMap road network.
                </p>
                <Button
                  size="sm"
                  variant="primary"
                  className="w-full bg-amber-600 hover:bg-amber-700 text-white"
                  isLoading={isLoadingDemo}
                  onClick={handleLoadDemoFloodScenario}
                  icon={<AlertTriangle className="w-3.5 h-3.5" />}
                >
                  Load DEMO Flood Scenario
                </Button>
              </div>
            )}
          </div>

          {/* Dataset & Platform Picker */}
          <div>
            <label className="text-[11px] font-semibold text-text-taupe uppercase block mb-1">
              Satellite Platform
            </label>
            <div className="grid grid-cols-2 gap-1.5 bg-surface-recessed p-1 rounded border border-border-subtle">
              <button
                type="button"
                onClick={() => {
                  setDataset('NISAR');
                  setGranules([]);
                  setBeforeGranule(null);
                  setAfterGranule(null);
                  setSearchPerformed(false);
                  setSearchMessage(null);
                }}
                className={`py-1 text-xs rounded font-medium transition-all ${
                  dataset === 'NISAR'
                    ? 'bg-surface-cream text-accent-espresso shadow-subtle border border-border-sandstone'
                    : 'text-text-taupe hover:text-text-roast'
                }`}
              >
                NISAR (L/S Band)
              </button>
              <button
                type="button"
                onClick={() => {
                  setDataset('SENTINEL-1');
                  setGranules([]);
                  setBeforeGranule(null);
                  setAfterGranule(null);
                  setSearchPerformed(false);
                  setSearchMessage(null);
                }}
                className={`py-1 text-xs rounded font-medium transition-all ${
                  dataset === 'SENTINEL-1'
                    ? 'bg-surface-cream text-accent-espresso shadow-subtle border border-border-sandstone'
                    : 'text-text-taupe hover:text-text-roast'
                }`}
              >
                Sentinel-1 (C Band)
              </button>
            </div>
            {dataset === 'NISAR' ? (
              <p className="text-[10px] text-text-taupe mt-1 font-mono">
                Prefers Frequency B provisional products
              </p>
            ) : (
              <p className="text-[10px] text-text-taupe mt-1 font-mono">
                Global operational Copernicus radar coverage
              </p>
            )}
          </div>

          {/* Date Horizon */}
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="text-[11px] font-semibold text-text-taupe uppercase block mb-1">
                Start Date
              </label>
              <input
                type="date"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
                className="w-full text-xs px-2 py-1 rounded bg-surface-recessed border border-border-sandstone font-mono text-text-roast"
              />
            </div>
            <div>
              <label className="text-[11px] font-semibold text-text-taupe uppercase block mb-1">
                End Date
              </label>
              <input
                type="date"
                value={endDate}
                onChange={(e) => setEndDate(e.target.value)}
                className="w-full text-xs px-2 py-1 rounded bg-surface-recessed border border-border-sandstone font-mono text-text-roast"
              />
            </div>
          </div>

          {/* Dynamic Geographic AOI Selection Controls */}
          <div className="bg-surface-recessed/60 p-2.5 rounded border border-border-subtle space-y-2">
            <div className="flex items-center justify-between text-[11px] font-semibold text-text-taupe">
              <span>Geographic AOI Region</span>
              {wktPolygon ? (
                <span className="text-success-sage font-mono text-[10px] font-bold">
                  [DEFINED]
                </span>
              ) : (
                <span className="text-text-taupe font-mono text-[10px]">
                  [NO REGION SELECTED]
                </span>
              )}
            </div>

            {wktPolygon ? (
              <div className="space-y-1.5">
                <p className="text-[10px] font-mono text-text-roast truncate bg-surface-cream px-2 py-1 rounded border border-border-subtle" title={wktPolygon}>
                  {wktPolygon}
                </p>
                <div className="flex items-center justify-between pt-0.5">
                  <div className="flex items-center space-x-2">
                    <button
                      type="button"
                      onClick={handleStartDrawPolygon}
                      className="text-[10px] text-accent-espresso font-semibold underline hover:text-alert-terracotta flex items-center space-x-1 cursor-pointer"
                    >
                      <PenTool className="w-2.5 h-2.5" />
                      <span>Redraw</span>
                    </button>
                    <button
                      type="button"
                      onClick={handleUseCurrentView}
                      className="text-[10px] text-accent-espresso font-semibold underline hover:text-alert-terracotta flex items-center space-x-1 cursor-pointer"
                    >
                      <Eye className="w-2.5 h-2.5" />
                      <span>Use Viewport</span>
                    </button>
                  </div>
                  <button
                    type="button"
                    onClick={handleClearAoi}
                    className="text-[10px] text-alert-terracotta font-semibold hover:underline cursor-pointer flex items-center space-x-1"
                  >
                    <X className="w-2.5 h-2.5" />
                    <span>Clear AOI</span>
                  </button>
                </div>
                <div className="flex items-center justify-between pt-1 border-t border-border-subtle/50">
                  <button
                    type="button"
                    onClick={handleFetchRoads}
                    disabled={isAssessingRoads}
                    className="text-[10px] text-accent-espresso font-semibold hover:text-alert-terracotta flex items-center space-x-1 cursor-pointer bg-surface-cream px-2 py-1 rounded border border-border-sandstone"
                  >
                    <Navigation className="w-3 h-3 text-accent-espresso" />
                    <span>{isAssessingRoads ? 'Loading Roads...' : 'Load Roads (OSM)'}</span>
                  </button>
                  {roadAssessment && (
                    <span className="text-[10px] font-mono text-text-taupe">
                      {roadAssessment.total_roads_assessed} roads {roadAssessment.status === 'UNASSESSED_NEUTRAL' ? '(unassessed)' : '(assessed)'}
                    </span>
                  )}
                </div>
                {roadAssessment && roadAssessment.status === 'OSM_UNAVAILABLE' && (
                  <p className="text-[9px] text-alert-terracotta font-mono pt-0.5">
                    OSM service unavailable for this AOI. No fake roads substituted.
                  </p>
                )}
                {roadAssessment && roadAssessment.total_roads_assessed === 0 && roadAssessment.status !== 'OSM_UNAVAILABLE' && (
                  <p className="text-[9px] text-text-taupe font-mono pt-0.5">
                    0 driveable OSM roads found in selected AOI.
                  </p>
                )}
              </div>
            ) : (
              <div className="grid grid-cols-3 gap-1.5">
                <button
                  type="button"
                  onClick={handleStartDrawPolygon}
                  className="py-1.5 px-1 bg-surface-cream hover:bg-surface-recessed border border-border-sandstone rounded text-center text-[10px] text-accent-espresso font-medium flex flex-col items-center justify-center space-y-1 group transition-all cursor-pointer shadow-subtle"
                  title="Draw custom polygon on map"
                >
                  <PenTool className="w-3.5 h-3.5 text-accent-espresso" />
                  <span>Draw Polygon</span>
                </button>

                <button
                  type="button"
                  onClick={handleStartDrawRectangle}
                  className="py-1.5 px-1 bg-surface-cream hover:bg-surface-recessed border border-border-sandstone rounded text-center text-[10px] text-accent-espresso font-medium flex flex-col items-center justify-center space-y-1 group transition-all cursor-pointer shadow-subtle"
                  title="Draw bounding box rectangle on map"
                >
                  <Square className="w-3.5 h-3.5 text-accent-espresso" />
                  <span>Draw Bbox</span>
                </button>

                <button
                  type="button"
                  onClick={handleUseCurrentView}
                  className="py-1.5 px-1 bg-surface-cream hover:bg-surface-recessed border border-border-sandstone rounded text-center text-[10px] text-accent-espresso font-medium flex flex-col items-center justify-center space-y-1 group transition-all cursor-pointer shadow-subtle"
                  title="Capture current map view bounds as AOI"
                >
                  <Eye className="w-3.5 h-3.5 text-accent-espresso" />
                  <span>Use Viewport</span>
                </button>
              </div>
            )}
          </div>

          {/* Action Triggers: Query Granules & Auto-Select Best Pair */}
          <div className="space-y-1.5">
            <Button
              variant="primary"
              className="w-full"
              isLoading={isSearching}
              disabled={!wktPolygon || isSearching || isFindingPairs}
              onClick={handleSearch}
              icon={<Search className="w-3.5 h-3.5" />}
            >
              Query NASA ASF Granules
            </Button>

            <button
              type="button"
              disabled={!wktPolygon || isSearching || isFindingPairs}
              onClick={handleFindBestPair}
              className={`w-full py-2 px-3 rounded text-xs font-semibold flex items-center justify-center space-x-1.5 transition-all shadow-subtle ${
                !wktPolygon || isSearching || isFindingPairs
                  ? 'bg-surface-recessed text-text-taupe border border-border-subtle cursor-not-allowed opacity-60'
                  : 'bg-surface-cream text-accent-espresso hover:bg-surface-recessed border border-accent-espresso/40 hover:border-accent-espresso cursor-pointer'
              }`}
            >
              {isFindingPairs ? (
                <>
                  <div className="w-3.5 h-3.5 border-2 border-accent-espresso border-t-transparent rounded-full animate-spin shrink-0" />
                  <span>Evaluating Observation Pairs...</span>
                </>
              ) : (
                <>
                  <Compass className="w-3.5 h-3.5 text-accent-espresso" />
                  <span>Auto-Select Best Observation Pair</span>
                </>
              )}
            </button>
          </div>

          {/* Pair Search Notice if returned */}
          {pairSearchMessage && (
            <div className="p-2 rounded text-[11px] bg-surface-cream border border-border-sandstone text-text-taupe">
              {pairSearchMessage}
            </div>
          )}

          {/* 5 Distinct Data Discovery States (Requirement 4) */}
          {isSearching ? (
            <div className="p-3 rounded bg-surface-recessed border border-accent-espresso/40 text-xs space-y-1.5">
              <div className="flex items-center space-x-2 text-accent-espresso font-semibold uppercase text-[11px]">
                <div className="w-3.5 h-3.5 border-2 border-accent-espresso border-t-transparent rounded-full animate-spin shrink-0" />
                <span>State: Searching for Data</span>
              </div>
              <p className="text-[11px] text-text-taupe leading-snug">
                Querying NASA Alaska Satellite Facility archive for real {dataset} observations within the specified AOI bounds...
              </p>
            </div>
          ) : searchPerformed && granules.length === 0 ? (
            <div className="p-3 rounded bg-surface-recessed border border-border-sandstone text-xs space-y-1.5">
              <div className="flex items-center space-x-1.5 text-text-roast font-semibold uppercase text-[11px]">
                <AlertTriangle className="w-3.5 h-3.5 text-warning-ochre shrink-0" />
                <span>State: No Observations Found</span>
              </div>
              <p className="text-[11px] text-text-taupe leading-snug">
                Zero satellite observations found for this region and date window. Try widening the date range or toggling to Sentinel-1 for broader historical coverage.
              </p>
            </div>
          ) : searchPerformed && granules.length === 1 ? (
            <div className="p-3 rounded bg-surface-recessed border border-warning-ochre/40 text-xs space-y-1.5">
              <div className="flex items-center space-x-1.5 text-warning-ochre font-semibold uppercase text-[11px]">
                <AlertTriangle className="w-3.5 h-3.5 text-warning-ochre shrink-0" />
                <span>State: Insufficient Observations (1 found)</span>
              </div>
              <p className="text-[11px] text-text-taupe leading-snug">
                Only 1 observation found in this AOI. SAR change detection requires at least 2 distinct temporal observations (pre-event and post-event). Expand your date window to find a second scene.
              </p>
            </div>
          ) : searchPerformed && granules.length >= 2 && (!beforeGranule || !afterGranule) ? (
            <div className="p-3 rounded bg-surface-recessed border border-accent-espresso/40 text-xs space-y-1.5">
              <div className="flex items-center space-x-1.5 text-accent-espresso font-semibold uppercase text-[11px]">
                <Layers className="w-3.5 h-3.5 text-accent-espresso shrink-0" />
                <span>State: Observations Available ({granules.length} scenes)</span>
              </div>
              <p className="text-[11px] text-text-taupe leading-snug">
                Real observations discovered. Select one scene as [BEFORE] and another as [AFTER] below to initialize change detection.
              </p>
            </div>
          ) : searchPerformed && beforeGranule && afterGranule ? (
            <div className="p-3 rounded bg-surface-cream border border-success-sage/50 text-xs space-y-1.5 shadow-subtle">
              <div className="flex items-center space-x-1.5 text-success-sage font-semibold uppercase text-[11px]">
                <CheckCircle className="w-3.5 h-3.5 text-success-sage shrink-0" />
                <span>State: Analysis Ready</span>
              </div>
              <div className="text-[10px] text-text-taupe leading-snug font-mono space-y-0.5">
                <div>Before: {beforeGranule.platform} ({beforeGranule.acquisition_time?.slice(0, 10)})</div>
                <div>After: {afterGranule.platform} ({afterGranule.acquisition_time?.slice(0, 10)})</div>
              </div>
            </div>
          ) : null}

          {/* Search Message Notice if returned */}
          {searchMessage && !isSearching && granules.length === 0 && (
            <div className="p-2 rounded text-[11px] bg-surface-cream border border-border-subtle text-text-taupe">
              {searchMessage}
            </div>
          )}

          {/* Real Granules List */}
          {granules.length > 0 && (
            <div className="pt-2 border-t border-border-subtle">
              <div className="flex items-center justify-between mb-2">
                <span className="text-[11px] font-semibold uppercase tracking-wider text-text-taupe">
                  Retrieved Granules ({granules.length})
                </span>
                <span className="text-[10px] text-text-taupe font-mono">Earliest → Latest</span>
              </div>

              <div className="space-y-2 max-h-60 overflow-y-auto pr-1">
                {granules.map((g, idx) => {
                  const isBefore = beforeGranule?.id === g.id;
                  const isAfter = afterGranule?.id === g.id;
                  const isEarliest = idx === 0;
                  const isLatest = idx === granules.length - 1;

                  return (
                    <div
                      key={g.id}
                      onClick={() => {
                        if (isValidFootprint(g.footprint_geojson)) {
                          const coords = (g.footprint_geojson!.coordinates as any)[0];
                          if (Array.isArray(coords) && coords.length > 0) {
                            const lats = coords.map((c: any) => c[1]).filter((v: any) => typeof v === 'number' && !isNaN(v));
                            const lons = coords.map((c: any) => c[0]).filter((v: any) => typeof v === 'number' && !isNaN(v));
                            if (lats.length > 0 && lons.length > 0) {
                              setFlyTarget([
                                [Math.min(...lats), Math.min(...lons)],
                                [Math.max(...lats), Math.max(...lons)],
                              ]);
                            }
                          }
                        }
                      }}
                      className="p-2 rounded bg-surface-recessed/70 border border-border-sandstone hover:border-accent-espresso transition-colors cursor-pointer"
                    >
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-[11px] font-mono font-bold text-accent-espresso truncate max-w-[170px]" title={g.granule_name}>
                          {g.granule_name}
                        </span>
                        <span className="text-[9px] font-mono px-1 rounded bg-surface-cream text-text-roast font-semibold border border-border-subtle">
                          {g.platform}
                        </span>
                      </div>

                      <div className="text-[10px] font-mono text-text-taupe flex items-center justify-between mb-1.5">
                        <span>
                          {formatAcqDate(g.acquisition_time)}
                        </span>
                        <span>{g.polarization || 'HH'}</span>
                      </div>

                      <div className="flex items-center justify-between text-[9px] text-text-taupe font-mono mb-1.5">
                        <span>Level: {g.processing_level || 'L1/L2'}</span>
                        {isEarliest && <span className="text-accent-espresso font-bold">[Baseline / Earliest]</span>}
                        {isLatest && granules.length > 1 && <span className="text-alert-terracotta font-bold">[Latest Scene]</span>}
                      </div>

                      {/* Before / After Assignment Controls */}
                      <div className="flex items-center space-x-2 pt-1 border-t border-border-subtle/50 text-[10px]">
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            setBeforeGranule(g);
                            setIsPairConfirmed(false);
                            setAnalysisError(null);
                          }}
                          className={`px-2 py-0.5 rounded font-mono font-semibold transition-all ${
                            isBefore
                              ? 'bg-accent-espresso text-surface-cream shadow-subtle'
                              : 'bg-surface-cream text-text-taupe hover:text-text-roast border border-border-subtle'
                          }`}
                        >
                          {isBefore ? '✓ [BEFORE]' : '[Set Before]'}
                        </button>
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            setAfterGranule(g);
                            setIsPairConfirmed(false);
                            setAnalysisError(null);
                          }}
                          className={`px-2 py-0.5 rounded font-mono font-semibold transition-all ${
                            isAfter
                              ? 'bg-alert-terracotta text-surface-cream shadow-subtle'
                              : 'bg-surface-cream text-text-taupe hover:text-text-roast border border-border-subtle'
                          }`}
                        >
                          {isAfter ? '✓ [AFTER]' : '[Set After]'}
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Change Detection Execution Panel */}
          {beforeGranule && afterGranule && (
            <div className="p-3 bg-surface-recessed rounded border border-border-sandstone space-y-3">
              {/* Recommended Observation Pair Card (Task 11) */}
              {selectedPair && (
                <div className="p-2.5 rounded bg-surface-cream border border-accent-espresso/30 space-y-2 shadow-subtle">
                  <div className="flex items-center justify-between border-b border-border-subtle/50 pb-1.5">
                    <div className="flex items-center space-x-1.5">
                      <Compass className="w-3.5 h-3.5 text-accent-espresso" />
                      <span className="text-[11px] font-bold text-accent-espresso tracking-tight">
                        {selectedPair.pair_id === recommendedPair?.pair_id ? 'Recommended Observation Pair' : 'Selected Alternative Pair'}
                      </span>
                    </div>
                    <span className="text-[9px] font-mono font-bold px-1.5 py-0.5 rounded bg-accent-espresso/10 text-accent-espresso border border-accent-espresso/20">
                      {selectedPair.status}
                    </span>
                  </div>

                  <div className="text-[10px] text-text-taupe space-y-1">
                    <div className="flex items-center justify-between text-[10px] font-mono">
                      <span>Score: <strong className="text-accent-espresso">{(selectedPair.ranking_score * 100).toFixed(0)}%</strong></span>
                      <span>AOI Overlap: <strong className="text-text-roast">{selectedPair.aoi_coverage_percent}%</strong></span>
                      <span>Interval: <strong className="text-text-roast">{selectedPair.temporal_delta_days}d</strong></span>
                    </div>
                    <p className="text-[10px] text-text-taupe italic leading-snug">
                      {selectedPair.ranking_explanation}
                    </p>
                  </div>

                  {/* Compatibility Highlights */}
                  {selectedPair.compatibility_reasons.length > 0 && (
                    <div className="text-[9px] font-mono text-success-sage space-y-0.5 pt-1 border-t border-border-subtle/30">
                      {selectedPair.compatibility_reasons.map((cr, idx) => (
                        <div key={idx} className="flex items-center space-x-1">
                          <CheckCircle className="w-2.5 h-2.5 shrink-0" />
                          <span className="truncate">{cr}</span>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Warnings if any */}
                  {selectedPair.warnings.length > 0 && (
                    <div className="text-[9px] font-mono text-warning-ochre space-y-0.5 pt-1 border-t border-border-subtle/30">
                      {selectedPair.warnings.map((cw, idx) => (
                        <div key={idx} className="flex items-center space-x-1">
                          <AlertTriangle className="w-2.5 h-2.5 shrink-0" />
                          <span className="truncate">{cw}</span>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Alternative Compatible Pairs selector */}
                  {pairSearchResponse?.alternative_pairs && pairSearchResponse.alternative_pairs.length > 0 && (
                    <div className="pt-1.5 border-t border-border-subtle/40 space-y-1">
                      <div className="text-[9px] font-semibold text-text-taupe uppercase tracking-wider">
                        Alternative Compatible Pairs ({pairSearchResponse.alternative_pairs.length})
                      </div>
                      <div className="space-y-1 max-h-24 overflow-y-auto pr-0.5">
                        {pairSearchResponse.alternative_pairs.map((alt) => {
                          const isCur = selectedPair.pair_id === alt.pair_id;
                          return (
                            <button
                              key={alt.pair_id}
                              type="button"
                              onClick={() => handleSelectAlternativePair(alt)}
                              className={`w-full text-left p-1 rounded text-[9px] font-mono flex items-center justify-between transition-colors cursor-pointer ${
                                isCur
                                  ? 'bg-accent-espresso text-surface-cream font-bold'
                                  : 'bg-surface-recessed text-text-roast hover:bg-surface-cream border border-border-subtle/50'
                              }`}
                            >
                              <span className="truncate max-w-[140px]">
                                {alt.before_observation.acquisition_time?.slice(0, 10)} → {alt.after_observation.acquisition_time?.slice(0, 10)}
                              </span>
                              <span>Score: {(alt.ranking_score * 100).toFixed(0)}%</span>
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  )}
                </div>
              )}

              <div className="flex items-center justify-between">
                <span className="text-[11px] font-semibold uppercase tracking-wider text-accent-espresso">
                  Selected Observations
                </span>
                <button
                  type="button"
                  onClick={handleSwapPair}
                  className="px-2 py-0.5 rounded text-[10px] font-mono bg-surface-cream text-text-roast hover:bg-surface-recessed border border-border-subtle flex items-center space-x-1 cursor-pointer transition-colors"
                  title="Swap Before and After observations"
                >
                  <ArrowUpDown className="w-3 h-3 text-accent-espresso" />
                  <span>Swap</span>
                </button>
              </div>

              {/* BEFORE Observation Card */}
              <div className="p-2 rounded bg-surface-cream border border-border-subtle space-y-1">
                <div className="flex items-center justify-between">
                  <span className="text-[9px] font-mono font-bold px-1 rounded bg-accent-espresso text-surface-cream">
                    Historical Baseline — BEFORE
                  </span>
                  <span className="text-[9px] font-mono text-text-roast font-semibold">
                    {beforeGranule.platform}
                  </span>
                </div>
                <div className="text-[10px] font-mono font-semibold text-text-roast truncate" title={beforeGranule.granule_name}>
                  {beforeGranule.granule_name}
                </div>
                <div className="flex items-center justify-between text-[9px] font-mono text-text-taupe">
                  <span>
                    {formatAcqDate(beforeGranule.acquisition_time)}
                  </span>
                  <span>{beforeGranule.processing_level || 'L1/L2'} • {beforeGranule.polarization || 'HH'}</span>
                </div>
              </div>

              {/* AFTER Observation Card */}
              <div className="p-2 rounded bg-surface-cream border border-border-subtle space-y-1">
                <div className="flex items-center justify-between">
                  <span className="text-[9px] font-mono font-bold px-1 rounded bg-alert-terracotta text-surface-cream">
                    Recent Observation — AFTER
                  </span>
                  <span className="text-[9px] font-mono text-text-roast font-semibold">
                    {afterGranule.platform}
                  </span>
                </div>
                <div className="text-[10px] font-mono font-semibold text-text-roast truncate" title={afterGranule.granule_name}>
                  {afterGranule.granule_name}
                </div>
                <div className="flex items-center justify-between text-[9px] font-mono text-text-taupe">
                  <span>
                    {formatAcqDate(afterGranule.acquisition_time)}
                  </span>
                  <span>{afterGranule.processing_level || 'L1/L2'} • {afterGranule.polarization || 'HH'}</span>
                </div>
              </div>

              {/* Compatibility / Validation Alerts */}
              {!sensorCompatibility.ok && (
                <div className="p-2 rounded bg-alert-terracotta/10 border border-alert-terracotta/40 text-[10px] text-alert-terracotta flex items-start space-x-1.5">
                  <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
                  <span>{sensorCompatibility.reason}</span>
                </div>
              )}

              {!productLevelCheck.ok && (
                <div className="p-2 rounded bg-alert-terracotta/10 border border-alert-terracotta/40 text-[10px] text-alert-terracotta flex items-start space-x-1.5">
                  <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
                  <span>{productLevelCheck.reason}</span>
                </div>
              )}

              {!sceneIdentityCheck.ok && (
                <div className="p-2 rounded bg-alert-terracotta/10 border border-alert-terracotta/40 text-[10px] text-alert-terracotta flex items-start space-x-1.5">
                  <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
                  <span>{sceneIdentityCheck.reason}</span>
                </div>
              )}

              {isPairValid && !isChronologicalOrder && (
                <div className="p-2 rounded bg-warning-ochre/10 border border-warning-ochre/40 text-[10px] text-warning-ochre flex items-start space-x-1.5">
                  <AlertCircle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
                  <span>Note: 'Before' scene was acquired after 'After' scene. Click 'Swap' to correct temporal order.</span>
                </div>
              )}

              {/* Explicit Confirmation Checkbox */}
              {isPairValid && (
                <div className={`p-2 rounded border transition-colors ${
                  isPairConfirmed
                    ? 'bg-surface-cream border-success-sage/60'
                    : 'bg-surface-cream/50 border-border-sandstone'
                }`}>
                  <label className="flex items-start space-x-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={isPairConfirmed}
                      onChange={(e) => {
                        setIsPairConfirmed(e.target.checked);
                        if (e.target.checked) setAnalysisError(null);
                      }}
                      className="mt-0.5 rounded accent-accent-espresso cursor-pointer"
                    />
                    <div className="text-[10px] leading-tight">
                      <span className="font-semibold text-text-roast block">
                        Confirm Observation Pair
                      </span>
                      <span className="text-text-taupe">
                        Explicitly verify these observations represent pre-disaster baseline and post-disaster scene.
                      </span>
                    </div>
                  </label>
                </div>
              )}

              {/* Stage B — Product Preparation (Task 13) */}
              {selectedPair && !isDemoMode && (
                <div className="p-2.5 rounded bg-surface-cream border border-border-sandstone space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] font-bold uppercase tracking-wider text-accent-espresso flex items-center space-x-1">
                      <Download className="w-3 h-3 text-accent-espresso" />
                      <span>Observation Preparation</span>
                    </span>
                    <span className="text-[9px] font-mono text-text-taupe">
                      Local Cache Pipeline
                    </span>
                  </div>

                  {/* Status pills for BEFORE and AFTER */}
                  <div className="grid grid-cols-2 gap-1.5 text-[10px] font-mono">
                    <div className="p-1.5 rounded bg-surface-recessed border border-border-subtle/60 space-y-0.5">
                      <div className="text-[9px] uppercase font-bold text-text-taupe">BEFORE Product</div>
                      <div className="flex items-center justify-between">
                        <span className={`px-1 py-0.5 rounded font-bold text-[9px] ${
                          beforeProductResult?.sar_preflight_ok
                            ? 'bg-success-sage/20 text-success-sage'
                            : beforeProductResult?.status === 'FAILED'
                            ? 'bg-alert-terracotta/20 text-alert-terracotta'
                            : isPreparingProducts
                            ? 'bg-warning-ochre/20 text-warning-ochre animate-pulse'
                            : 'bg-border-subtle text-text-taupe'
                        }`}>
                          {beforeProductResult?.sar_preflight_ok
                            ? 'Ready for SAR'
                            : beforeProductResult?.status
                            ? beforeProductResult.status
                            : isPreparingProducts
                            ? 'Downloading...'
                            : 'Waiting'}
                        </span>
                        {beforeProductResult?.file_size_bytes && (
                          <span className="text-[9px] text-text-taupe">
                            {(beforeProductResult.file_size_bytes / 1048576).toFixed(1)} MB
                          </span>
                        )}
                      </div>
                      {beforeProductResult?.sha256 && (
                        <div className="text-[8px] text-text-taupe truncate" title={beforeProductResult.sha256}>
                          SHA: {beforeProductResult.sha256.slice(0, 8)}...
                        </div>
                      )}
                    </div>

                    <div className="p-1.5 rounded bg-surface-recessed border border-border-subtle/60 space-y-0.5">
                      <div className="text-[9px] uppercase font-bold text-text-taupe">AFTER Product</div>
                      <div className="flex items-center justify-between">
                        <span className={`px-1 py-0.5 rounded font-bold text-[9px] ${
                          afterProductResult?.sar_preflight_ok
                            ? 'bg-success-sage/20 text-success-sage'
                            : afterProductResult?.status === 'FAILED'
                            ? 'bg-alert-terracotta/20 text-alert-terracotta'
                            : isPreparingProducts
                            ? 'bg-warning-ochre/20 text-warning-ochre animate-pulse'
                            : 'bg-border-subtle text-text-taupe'
                        }`}>
                          {afterProductResult?.sar_preflight_ok
                            ? 'Ready for SAR'
                            : afterProductResult?.status
                            ? afterProductResult.status
                            : isPreparingProducts
                            ? 'Downloading...'
                            : 'Waiting'}
                        </span>
                        {afterProductResult?.file_size_bytes && (
                          <span className="text-[9px] text-text-taupe">
                            {(afterProductResult.file_size_bytes / 1048576).toFixed(1)} MB
                          </span>
                        )}
                      </div>
                      {afterProductResult?.sha256 && (
                        <div className="text-[8px] text-text-taupe truncate" title={afterProductResult.sha256}>
                          SHA: {afterProductResult.sha256.slice(0, 8)}...
                        </div>
                      )}
                    </div>
                  </div>

                  {productPreparationStatus && (
                    <p className="text-[9px] font-mono text-text-taupe italic leading-tight">
                      {productPreparationStatus}
                    </p>
                  )}

                  <Button
                    type="button"
                    variant="secondary"
                    className="w-full text-xs py-1"
                    isLoading={isPreparingProducts}
                    disabled={isPreparingProducts || !isPairConfirmed || !isPairValid}
                    onClick={handleDownloadAndPrepare}
                  >
                    <Download className="w-3.5 h-3.5 mr-1" />
                    <span>Download & Prepare Observations</span>
                  </Button>
                </div>
              )}

              {/* Analysis Parameters */}
              <div>
                <div className="flex items-center justify-between text-[10px] font-mono text-text-taupe mb-1">
                  <span>Threshold</span>
                  <span className="font-bold text-accent-espresso">{thresholdDb} dB</span>
                </div>
                <input
                  type="range"
                  min="-12.0"
                  max="-1.0"
                  step="0.5"
                  value={thresholdDb}
                  onChange={(e) => setThresholdDb(parseFloat(e.target.value))}
                  className="w-full accent-accent-espresso"
                />
              </div>

              <div className="flex items-center justify-between text-[11px]">
                <span className="text-text-taupe">Speckle Filter</span>
                <input
                  type="checkbox"
                  checked={speckleFilter}
                  onChange={(e) => setSpeckleFilter(e.target.checked)}
                  className="rounded accent-accent-espresso"
                />
              </div>

              {/* Failure Alert State */}
              {analysisError && (
                <div className="p-2.5 rounded bg-alert-terracotta/10 border border-alert-terracotta/50 text-[11px] text-alert-terracotta space-y-1">
                  <div className="flex items-center space-x-1.5 font-bold uppercase text-[10px]">
                    <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
                    <span>Analysis Error</span>
                  </div>
                  <p className="leading-snug">{analysisError}</p>
                </div>
              )}

              {/* Stage C: Observation Preparation Notice & Run Analysis */}
              {selectedPair && !isDemoMode && (!beforeProductResult?.sar_preflight_ok || !afterProductResult?.sar_preflight_ok) && (
                <div className="p-2 rounded bg-surface-cream border border-border-sandstone text-[10px] text-text-taupe leading-tight flex items-start space-x-1.5">
                  <AlertCircle className="w-3.5 h-3.5 text-accent-espresso shrink-0 mt-0.5" />
                  <span>
                    Observation products must be downloaded and verified before executing SAR analysis. Click <strong>Download & Prepare Observations</strong> above to proceed.
                  </span>
                </div>
              )}

              <Button
                variant="alert"
                className="w-full"
                isLoading={isAnalyzing}
                disabled={
                  !isPairConfirmed ||
                  !isPairValid ||
                  isAnalyzing ||
                  (Boolean(selectedPair) && !isDemoMode && (!beforeProductResult?.sar_preflight_ok || !afterProductResult?.sar_preflight_ok))
                }
                onClick={handleRunAnalysis}
              >
                Execute SAR Log-Ratio Analysis
              </Button>
            </div>
          )}
        </div>
      </aside>

      {/* Tactile Left Rail Expand Tab */}
      {!leftOpen && (
        <button
          onClick={() => setLeftOpen(true)}
          className="absolute top-4 left-4 z-20 h-9 px-2.5 bg-surface-cream border border-border-sandstone rounded shadow-panel text-accent-espresso flex items-center space-x-1 hover:bg-surface-recessed transition-all"
        >
          <Layers className="w-4 h-4" />
          <span className="text-xs font-semibold uppercase">Mission</span>
          <ChevronRight className="w-3.5 h-3.5 ml-1" />
        </button>
      )}

      {/* --- CENTER MAP CANVAS (Leaflet 100vh) --- */}
      <div className={`flex-1 h-full relative z-0 min-w-0 ${!leftOpen ? 'controls-offset-top' : ''}`}>
        <MapContainer
          center={[37.7749, -122.4194]}
          zoom={10}
          className="w-full h-full"
          zoomControl={false}
        >
          {/* Clean Cartographic Basemap (OpenStreetMap - No Watermarks / No API Key Required) */}
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />

          {/* Map Geoman and Controller */}
          <MapController
            onAoiDrawn={(wkt) => {
              setWktPolygon(wkt);
              setLeftOpen(true);
            }}
            flyToBoundsTarget={flyTarget}
            onMapReady={(m) => setMapInstance(m)}
            leftOpen={leftOpen}
            rightOpen={rightOpen}
          />

          {/* Footprints of Granules */}
          {granules.map((g) => {
            if (!isValidFootprint(g.footprint_geojson)) return null;
            return (
              <GeoJSON
                key={g.id}
                data={g.footprint_geojson as any}
                style={{
                  color: beforeGranule?.id === g.id ? '#36CFC9' : afterGranule?.id === g.id ? '#D85B61' : '#64748B',
                  weight: beforeGranule?.id === g.id || afterGranule?.id === g.id ? 2.5 : 1,
                  fillOpacity: beforeGranule?.id === g.id ? 0.2 : afterGranule?.id === g.id ? 0.2 : 0.05,
                }}
              />
            );
          })}

          {/* SAR Microwave Raster Overlay (Only inside selected bounds: Water is Dark, Land/Roads Bright) */}
          {showSarLayer && analysisResult?.mask_image_url && analysisResult?.bounds && (
            <ImageOverlay
              url={analysisResult.mask_image_url}
              bounds={analysisResult.bounds}
              opacity={0.88}
            />
          )}

          {/* Vectorized Change Mask GeoJSON Layer */}
          {showSarLayer && analysisResult?.mask_geojson && analysisResult.mask_geojson.features && analysisResult.mask_geojson.features.length > 0 && (
            <GeoJSON
              key={`mask-${analysisResult.analysis_id}`}
              data={analysisResult.mask_geojson as any}
              style={{
                color: isDemoMode ? '#E06D53' : '#D85B61',
                weight: 2,
                fillColor: isDemoMode ? '#E06D53' : '#D85B61',
                fillOpacity: 0.22,
              }}
              onEachFeature={(_feature, layer) => {
                const label = isDemoMode
                  ? '[SIMULATED CHANGE] Not Real Flood Observation'
                  : analysisResult.change_type || 'Significant Backscatter Decrease';
                layer.bindTooltip(
                  `<strong>${label}</strong><br/>${analysisResult.impacted_km2 ?? 0} km² affected`,
                  { sticky: true }
                );
                layer.bindPopup(
                  `<div style="font-family: 'Space Grotesk', sans-serif; font-size: 11px; line-height: 1.45; min-width: 210px; color: #F1F5F9;">
                    <div style="font-weight: 700; color: #E06D53; text-transform: uppercase; margin-bottom: 4px; border-bottom: 1px solid #2C3E50; padding-bottom: 2px;">
                      ${label}
                    </div>
                    <div><strong>Impacted Area:</strong> <span style="font-family: 'JetBrains Mono', monospace; color: #36CFC9;">${analysisResult.impacted_km2 ?? 'N/A'} km²</span></div>
                    ${analysisResult.mean_db_drop != null ? `<div><strong>Mean dB Drop:</strong> <span style="font-family: 'JetBrains Mono', monospace;">${analysisResult.mean_db_drop} dB</span></div>` : ''}
                    ${analysisResult.valid_pixels != null ? `<div><strong>Valid Pixels:</strong> <span style="font-family: 'JetBrains Mono', monospace;">${analysisResult.valid_pixels.toLocaleString()}</span></div>` : ''}
                    ${analysisResult.crs ? `<div><strong>CRS:</strong> <span style="font-family: 'JetBrains Mono', monospace;">${analysisResult.crs}</span></div>` : ''}
                    <div style="margin-top: 6px; font-size: 10px; color: #AAB7C4; border-top: 1px solid #2C3E50; padding-top: 4px; font-style: italic;">
                      ${analysisResult.scientific_qualification || 'Scientific qualification: Field validation required to confirm ground impact.'}
                    </div>
                  </div>`
                );
              }}
            />
          )}

          {/* Evidence-Based Road Network Assessment GeoJSON Layer */}
          {showRoadsLayer && roadAssessment?.road_geojson && roadAssessment.road_geojson.features.length > 0 && (
            <GeoJSON
              key={`roads-${roadAssessment.assessment_id}-${roadProximityMeters}`}
              data={roadAssessment.road_geojson as any}
              style={(feature: any) => getRoadStyle(feature?.properties)}
              onEachFeature={(feature: any, layer: any) => {
                const p = feature?.properties || {};
                roadLayersRef.current.set(String(p.osm_id), { layer, feature });

                layer.bindTooltip(getRoadTooltipHtml(p), { sticky: true });
                layer.bindPopup(getRoadPopupHtml(p));

                layer.on('click', () => {
                  setSelectedRoad(feature);
                  setVerifStatusInput(p.field_status || 'VERIFIED_PASSABLE');
                  setVerifNotesInput(p.verification_notes || '');
                  if (p.verified_by) setVerifOperatorInput(p.verified_by);
                  setRightOpen(true);
                });
              }}
            />
          )}

          {/* Candidate Route GeoJSON Layer */}
          {showRouteLayer && routePlan?.route_geojson && (
            <GeoJSON
              key={`candidate-route-${routePlan.route_id || routePlan.routing_mode}`}
              data={routePlan.route_geojson as any}
              style={{
                color: '#60A5FA',
                weight: 5,
                opacity: 0.95,
              }}
              onEachFeature={(_f, layer) => {
                layer.bindTooltip(
                  `<strong>Candidate Route (${routePlan.routing_mode})</strong><br/>${routePlan.total_distance_km} km — Ground Verification Required`,
                  { sticky: true }
                );
                layer.bindPopup(
                  `<div style="font-family: 'Space Grotesk', sans-serif; font-size: 11px; min-width: 240px; line-height: 1.4; color: #F1F5F9;">
                    <div style="font-weight: bold; color: #60A5FA; font-size: 11px; margin-bottom: 2px; text-transform: uppercase;">
                      CANDIDATE ROUTE (${routePlan.routing_mode})
                    </div>
                    <div style="font-size: 14px; font-weight: bold; color: #F1F5F9; font-family: 'JetBrains Mono', monospace;">
                      ${routePlan.total_distance_km} km
                    </div>
                    <div style="margin-top: 4px; font-size: 10px; color: #D85B61; font-weight: bold; text-transform: uppercase;">
                      GROUND VERIFICATION REQUIRED
                    </div>
                    <div style="font-size: 9px; color: #AAB7C4; margin-top: 4px; line-height: 1.35; font-style: italic;">
                      ${routePlan.scientific_qualification}
                    </div>
                  </div>`
                );
              }}
            />
          )}
        </MapContainer>

        {/* On-Map Cartographic Legend (Bottom Right) */}
        {(analysisResult || roadAssessment || routePlan) && (
          <div className="absolute bottom-6 right-6 z-10 pointer-events-auto bg-surface-cream/95 backdrop-blur border border-border-sandstone rounded-md p-2.5 shadow-panel max-w-[280px] text-[10px] space-y-1.5 font-mono text-text-roast">
            <div className="text-[10px] font-bold uppercase tracking-wider text-accent-espresso font-sans border-b border-border-subtle pb-1 flex items-center justify-between">
              <span>Map Legend</span>
              <span className="text-[9px] text-text-taupe font-normal font-mono">Tactical Overlays</span>
            </div>
            {analysisResult && (
              <>
                <div className="flex items-center space-x-2">
                  <span className="w-3 h-3 rounded bg-[#0f172a] border border-[#334155] shrink-0" />
                  <span className="text-text-roast truncate" title="Radar backscatter: water is dark black, roads/terrain are bright gray">
                    SAR Microwave (Water Dark)
                  </span>
                </div>
                <div className="flex items-center space-x-2">
                  <span className="w-3 h-3 rounded bg-[#E06D53]/40 border border-[#E06D53] shrink-0" />
                  <span className="text-text-roast truncate" title={isDemoMode ? 'Simulated flood inundation area' : 'Significant backscatter attenuation area'}>
                    {isDemoMode ? '[DEMO] Simulated Flood Change' : 'SAR Attenuation Area'}
                  </span>
                </div>
              </>
            )}
            {roadAssessment && (
              <>
                <div className="flex items-center space-x-2">
                  <span className="w-3.5 h-1 rounded bg-[#22C55E] shrink-0" />
                  <span className="text-text-roast truncate" title="Ground verified passable">
                    Verified Passable (Ground)
                  </span>
                </div>
                <div className="flex items-center space-x-2">
                  <span className="w-3.5 h-1 rounded bg-[#EF4444] shrink-0" />
                  <span className="text-text-roast truncate" title="Ground verified blocked">
                    Verified Blocked (Ground)
                  </span>
                </div>
                <div className="flex items-center space-x-2">
                  <span className="w-3.5 h-1 rounded border-b-2 border-dashed border-[#A855F7] shrink-0" />
                  <span className="text-text-roast truncate" title="Restricted / Emergency only">
                    Restricted Segment (Ground)
                  </span>
                </div>
                <div className="flex items-center space-x-2">
                  <span className="w-3.5 h-1 rounded bg-[#E06D53] shrink-0" />
                  <span className="text-text-roast truncate" title="Intersects detected attenuation polygon">
                    Potentially Affected (SAR)
                  </span>
                </div>
                <div className="flex items-center space-x-2">
                  <span className="w-3.5 h-1 rounded border-b-2 border-dashed border-[#EAB308] shrink-0" />
                  <span className="text-text-roast truncate" title={`Within ${roadAssessment.proximity_threshold_meters}m of attenuation`}>
                    Nearby Change ({roadAssessment.proximity_threshold_meters}m)
                  </span>
                </div>
                <div className="flex items-center space-x-2">
                  <span className="w-3.5 h-0.5 rounded bg-[#64748B] shrink-0" />
                  <span className="text-text-taupe truncate" title="No detected intersection (not confirmed safe)">
                    No Detected Overlap
                  </span>
                </div>
                <div className="flex items-center space-x-2">
                  <span className="w-3.5 h-0.5 rounded border-b border-dashed border-[#94A3B8] shrink-0" />
                  <span className="text-text-taupe truncate" title="Unverified road (pending SAR or ground recon)">
                    Unverified / Neutral Road
                  </span>
                </div>
              </>
            )}
            {routePlan?.route_geojson && (
              <div className="flex items-center space-x-2 border-t border-border-subtle pt-1">
                <span className="w-3.5 h-1 rounded bg-[#60A5FA] shrink-0" />
                <span className="text-text-roast font-semibold truncate" title="Candidate Route — Ground Verification Required">
                  Candidate Route
                </span>
              </div>
            )}
          </div>
        )}

        {/* Isolated DEMO Mode Warning Banner */}
        {isDemoMode && (
          <div className="absolute top-4 left-1/2 -translate-x-1/2 z-20 pointer-events-auto bg-[#321E14]/95 backdrop-blur border border-[#E06D53] text-[#F8FAFC] px-4 py-2 rounded-md shadow-panel text-[11px] font-mono flex items-center space-x-3">
            <AlertTriangle className="w-4 h-4 shrink-0 text-[#E06D53] animate-pulse" />
            <div className="flex flex-col text-left">
              <span className="font-bold tracking-wide text-[#E06D53]">
                DEMO MODE — SYNTHETIC SATELLITE AND ROAD DATA
              </span>
              <span className="text-[10px] text-[#CBD5E1]">
                SIMULATED CHANGE — NOT REAL FLOOD OBSERVATION
              </span>
            </div>
            <button
              type="button"
              onClick={handleExitDemoMode}
              className="ml-2 text-[10px] px-2.5 py-1 rounded bg-[#E06D53]/20 hover:bg-[#E06D53]/35 text-[#F1F5F9] border border-[#E06D53]/50 cursor-pointer font-sans font-semibold transition-colors"
            >
              Exit Demo
            </button>
          </div>
        )}

        {/* HUD Navigational Rose (Top Right) */}
        <div className="absolute top-4 right-4 z-10 flex items-center space-x-2 pointer-events-none">
          <div className="bg-surface-cream/90 backdrop-blur border border-border-sandstone rounded p-2 shadow-panel pointer-events-auto flex items-center space-x-2">
            <Compass className="w-5 h-5 text-accent-espresso animate-pulse" />
            <span className="font-mono text-xs text-text-roast font-semibold">000° N</span>
          </div>
        </div>

        {/* On-Map HUD Compact Analysis Summary (Bottom Left) */}
        {analysisResult && (
          <div className="absolute bottom-6 left-6 z-10 pointer-events-auto bg-surface-cream/95 backdrop-blur border border-border-sandstone rounded-md p-3 shadow-panel max-w-sm text-xs space-y-2">
            <div className="flex items-center justify-between border-b border-border-subtle pb-1.5">
              <span className="font-bold text-alert-terracotta uppercase tracking-wider text-[11px] flex items-center space-x-1.5">
                <span className="w-2 h-2 rounded-full bg-alert-terracotta animate-pulse" />
                <span>{analysisResult.change_type || 'Significant Backscatter Decrease'}</span>
              </span>
              <span className="font-mono text-[10px] px-1.5 py-0.5 rounded bg-surface-recessed text-text-taupe border border-border-subtle">
                {analysisResult.crs || 'CRS: N/A'}
              </span>
            </div>
            <div className="grid grid-cols-3 gap-2 font-mono text-[11px]">
              <div>
                <span className="text-[9px] uppercase text-text-taupe block">Impacted</span>
                <span className="font-bold text-alert-terracotta">{analysisResult.impacted_km2 ?? 0} km²</span>
              </div>
              <div>
                <span className="text-[9px] uppercase text-text-taupe block">Mean Delta</span>
                <span className="font-bold text-text-roast">{analysisResult.mean_db_drop != null ? `${analysisResult.mean_db_drop} dB` : 'N/A'}</span>
              </div>
              <div>
                <span className="text-[9px] uppercase text-text-taupe block">Valid Px</span>
                <span className="font-bold text-text-roast">{analysisResult.valid_pixels != null ? analysisResult.valid_pixels.toLocaleString() : 'N/A'}</span>
              </div>
            </div>
            <p className="text-[10px] text-text-taupe border-t border-border-subtle pt-1.5 leading-snug">
              {analysisResult.scientific_qualification || 'Detected backscatter reduction. Field validation required to confirm flood extent.'}
            </p>
            {/* Observation Pair Details */}
            {(analysisResult.before_date || analysisResult.before_platform) && (
              <div className="text-[10px] font-mono text-text-taupe border-t border-border-subtle pt-1 flex items-center justify-between">
                <span className="font-semibold text-text-roast">
                  {analysisResult.before_platform || 'SAR'}
                </span>
                <span>
                  {analysisResult.before_date ? new Date(analysisResult.before_date).toISOString().slice(0, 10) : 'N/A'}
                  {' → '}
                  {analysisResult.after_date ? new Date(analysisResult.after_date).toISOString().slice(0, 10) : 'N/A'}
                </span>
              </div>
            )}
          </div>
        )}
      </div>

      {/* --- RIGHT RAIL: Telemetry & AI Briefing (360px) --- */}
      <aside
        className={`relative shrink-0 h-full bg-surface-cream border-l border-border-sandstone transition-all duration-200 ease-mechanical flex flex-col shadow-panel z-10 ${
          rightOpen ? 'w-[360px]' : 'w-0 overflow-hidden border-l-0'
        }`}
      >
        {/* Rail Header */}
        <div className="h-11 border-b border-border-subtle px-3.5 flex items-center justify-between shrink-0 bg-surface-cream">
          <button
            onClick={() => setRightOpen(false)}
            className="w-6 h-6 rounded flex items-center justify-center text-text-taupe hover:text-text-roast hover:bg-surface-recessed cursor-pointer"
          >
            <ChevronRight className="w-4 h-4" />
          </button>
          <div className="flex items-center space-x-2">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-text-roast">
              Tactical Telemetry
            </h2>
            <Sliders className="w-4 h-4 text-accent-espresso" />
          </div>
        </div>

        {/* Content Body */}
        <div className="p-3.5 overflow-y-auto space-y-3.5 flex-1 text-xs">
          {analysisResult ? (
            <>
              {/* Telemetry Summary Metrics */}
              <div className="space-y-2">
                <div className="flex items-center justify-between px-1">
                  <span className="text-[11px] font-bold uppercase tracking-wider text-alert-terracotta">
                    {analysisResult.change_type || 'Significant Backscatter Decrease'}
                  </span>
                  <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-surface-recessed text-text-taupe border border-border-subtle">
                    {analysisResult.crs || 'CRS: N/A'}
                  </span>
                </div>

                <div className="grid grid-cols-2 gap-2">
                  <div className="p-2.5 rounded bg-surface-recessed border border-border-sandstone">
                    <span className="text-[10px] uppercase font-semibold text-text-taupe block mb-0.5">
                      Impacted Area
                    </span>
                    <div className="font-mono text-base font-bold text-alert-terracotta">
                      {analysisResult.impacted_km2 ?? 0}{' '}
                      <span className="text-xs font-normal">km²</span>
                    </div>
                  </div>

                  <div className="p-2.5 rounded bg-surface-recessed border border-border-sandstone">
                    <span className="text-[10px] uppercase font-semibold text-text-taupe block mb-0.5">
                      Mean dB Drop
                    </span>
                    <div className="font-mono text-base font-bold text-text-roast">
                      {analysisResult.mean_db_drop != null ? `${analysisResult.mean_db_drop} dB` : 'N/A'}
                    </div>
                  </div>

                  <div className="p-2.5 rounded bg-surface-recessed border border-border-sandstone">
                    <span className="text-[10px] uppercase font-semibold text-text-taupe block mb-0.5">
                      Valid Pixels
                    </span>
                    <div className="font-mono text-xs font-bold text-text-roast">
                      {analysisResult.valid_pixels != null ? analysisResult.valid_pixels.toLocaleString() : 'N/A'}
                    </div>
                  </div>

                  <div className="p-2.5 rounded bg-surface-recessed border border-border-sandstone">
                    <span className="text-[10px] uppercase font-semibold text-text-taupe block mb-0.5">
                      Coordinate System
                    </span>
                    <div className="font-mono text-xs font-bold text-accent-espresso truncate" title={analysisResult.crs || 'N/A'}>
                      {analysisResult.crs || 'N/A'}
                    </div>
                  </div>
                </div>

                {/* Observation Pair Telemetry */}
                {(analysisResult.before_date || analysisResult.before_platform) && (
                  <div className="p-2.5 rounded bg-surface-recessed border border-border-sandstone space-y-1.5 font-mono text-[10px]">
                    <div className="flex items-center justify-between text-[11px] font-semibold uppercase text-accent-espresso font-sans">
                      <span>Observation Pair</span>
                      <span className="text-[9px] px-1 py-0.5 rounded bg-surface-cream text-text-roast border border-border-subtle">
                        {analysisResult.before_platform || 'SAR'}
                        {analysisResult.after_platform && analysisResult.after_platform !== analysisResult.before_platform
                          ? ` / ${analysisResult.after_platform}`
                          : ''}
                      </span>
                    </div>
                    <div className="flex justify-between items-center text-text-taupe">
                      <span>Pre-Event (Before):</span>
                      <span className="text-text-roast font-semibold">
                        {analysisResult.before_date
                          ? new Date(analysisResult.before_date).toISOString().replace('T', ' ').slice(0, 16) + ' UTC'
                          : 'N/A'}
                      </span>
                    </div>
                    <div className="flex justify-between items-center text-text-taupe">
                      <span>Post-Event (After):</span>
                      <span className="text-alert-terracotta font-semibold">
                        {analysisResult.after_date
                          ? new Date(analysisResult.after_date).toISOString().replace('T', ' ').slice(0, 16) + ' UTC'
                          : 'N/A'}
                      </span>
                    </div>
                  </div>
                )}

                {/* Scientific Qualification Notice */}
                <div className="p-2.5 rounded bg-surface-recessed/80 border border-border-sandstone space-y-1">
                  <span className="text-[10px] uppercase font-bold text-text-roast block">
                    Scientific Qualification
                  </span>
                  <p className="text-[11px] text-text-taupe leading-relaxed">
                    {analysisResult.scientific_qualification ||
                      'Detected backscatter reduction of <= threshold. May indicate open water, specular reflection, or soil moisture change. Field validation required to confirm flood extent.'}
                  </p>
                </div>
              </div>

              {/* Histogram Distribution */}
              <Card title="Backscatter Delta Histogram" subtitle="Frequency distribution across dB bins">
                <HistogramChart
                  data={analysisResult.histogram}
                  thresholdDb={analysisResult.threshold_db}
                />
              </Card>

              {/* Gemini AI Briefing Card */}
              <AIBriefingCard
                briefing={analysisResult.briefing}
                isLoading={isBriefingLoading}
                onGenerateBriefing={handleGenerateBriefing}
              />

              {/* Evidence-Based Road Network Impact Assessment Card */}
              <Card
                title="Road Network Impact Assessment"
                subtitle="OpenStreetMap geometric intersection with SAR attenuation"
              >
                <div className="space-y-3">
                  {/* Map Layer Visibility Toggles */}
                  <div className="p-2 rounded bg-surface-recessed border border-border-subtle space-y-1.5">
                    <span className="text-[10px] font-bold uppercase tracking-wider text-text-taupe block">
                      Layer Visibility
                    </span>
                    <div className="grid grid-cols-2 gap-1.5">
                      <label className="flex items-center space-x-1.5 text-[11px] text-text-taupe cursor-pointer">
                        <input
                          type="checkbox"
                          checked={showRoadsLayer}
                          onChange={(e) => setShowRoadsLayer(e.target.checked)}
                          className="rounded accent-accent-espresso cursor-pointer"
                        />
                        <span>Road Overlay</span>
                      </label>
                      <label className="flex items-center space-x-1.5 text-[11px] text-text-taupe cursor-pointer">
                        <input
                          type="checkbox"
                          checked={showSarLayer}
                          onChange={(e) => setShowSarLayer(e.target.checked)}
                          className="rounded accent-accent-espresso cursor-pointer"
                        />
                        <span>SAR Change</span>
                      </label>
                      {routePlan && (
                        <label className="flex items-center space-x-1.5 text-[11px] text-text-taupe cursor-pointer col-span-2">
                          <input
                            type="checkbox"
                            checked={showRouteLayer}
                            onChange={(e) => setShowRouteLayer(e.target.checked)}
                            className="rounded accent-accent-espresso cursor-pointer"
                          />
                          <span>Candidate Route</span>
                        </label>
                      )}
                    </div>
                  </div>

                  <div>
                    <div className="flex items-center justify-between text-[11px] mb-1">
                      <span className="text-text-taupe">Proximity Buffer</span>
                      <span className="font-mono font-bold text-accent-espresso">
                        {roadProximityMeters} m
                      </span>
                    </div>
                    <input
                      type="range"
                      min="10"
                      max="200"
                      step="10"
                      value={roadProximityMeters}
                      onChange={(e) => setRoadProximityMeters(parseInt(e.target.value, 10))}
                      className="w-full accent-accent-espresso"
                    />
                  </div>

                  <div className="flex items-center justify-between pt-1 space-x-2">
                    <Button
                      size="sm"
                      variant="secondary"
                      disabled={isAssessingRoads || (!wktPolygon && !analysisResult)}
                      onClick={handleFetchRoads}
                      icon={<Navigation className="w-3.5 h-3.5" />}
                    >
                      {roadAssessment ? 'Reload Roads' : 'Load Roads'}
                    </Button>

                    <Button
                      size="sm"
                      variant="primary"
                      disabled={!analysisResult}
                      isLoading={isAssessingRoads}
                      onClick={handleAssessRoadImpact}
                      icon={<ShieldAlert className="w-3.5 h-3.5" />}
                    >
                      Assess Impacts
                    </Button>
                  </div>

                  {/* Failure / Unavailable Notice */}
                  {roadAssessmentError && (
                    <div className="p-2.5 rounded bg-alert-terracotta/10 border border-alert-terracotta/40 text-[10px] text-alert-terracotta space-y-1">
                      <div className="flex items-center space-x-1.5 font-bold uppercase text-[9px]">
                        <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
                        <span>Road Assessment Unavailable</span>
                      </div>
                      <p className="leading-snug">{roadAssessmentError}</p>
                      <p className="text-[9px] text-text-taupe pt-0.5">
                        NISAR-Pulse strictly prohibits substituting fabricated road networks when OSM is unreachable.
                      </p>
                    </div>
                  )}

                  {/* Assessment Results Metrics Grid */}
                  {roadAssessment && (
                    <div className="space-y-2 pt-2 border-t border-border-subtle">
                      <div className="flex items-center justify-between text-[10px] font-mono">
                        <span className="text-text-taupe">Status:</span>
                        <span className="font-bold text-accent-espresso px-1.5 py-0.5 rounded bg-surface-recessed border border-border-subtle">
                          {roadAssessment.status}
                        </span>
                      </div>

                      <div className="grid grid-cols-2 gap-2 text-center font-mono">
                        <div className="p-2 rounded bg-surface-recessed border border-border-sandstone">
                          <span className="text-[9px] uppercase text-text-taupe block mb-0.5">
                            Assessed Roads
                          </span>
                          <span className="font-bold text-text-roast text-sm">
                            {roadAssessment.total_roads_assessed}
                          </span>
                        </div>

                        <div className="p-2 rounded bg-alert-terracotta/10 border border-alert-terracotta/40">
                          <span className="text-[9px] uppercase text-alert-terracotta block mb-0.5">
                            Potentially Affected
                          </span>
                          <span className="font-bold text-alert-terracotta text-sm">
                            {roadAssessment.impacted_count}
                          </span>
                        </div>

                        <div className="p-2 rounded bg-warning-ochre/10 border border-warning-ochre/40">
                          <span className="text-[9px] uppercase text-warning-ochre block mb-0.5">
                            Nearby Region
                          </span>
                          <span className="font-bold text-warning-ochre text-sm">
                            {roadAssessment.nearby_count}
                          </span>
                        </div>

                        <div className="p-2 rounded bg-surface-recessed border border-border-sandstone">
                          <span className="text-[9px] uppercase text-text-taupe block mb-0.5">
                            No Intersection
                          </span>
                          <span className="font-bold text-text-taupe text-sm">
                            {roadAssessment.no_intersection_count}
                          </span>
                        </div>
                      </div>

                      {/* Active Ground Truth Breakdown across all roads in the AOI */}
                      {(() => {
                        const feats = roadAssessment.road_geojson?.features || [];
                        let pCount = 0, rCount = 0, bCount = 0, uCount = 0;
                        feats.forEach((f: any) => {
                          const st = f.properties?.field_status;
                          if (st === 'VERIFIED_PASSABLE') pCount++;
                          else if (st === 'RESTRICTED') rCount++;
                          else if (st === 'VERIFIED_BLOCKED') bCount++;
                          else uCount++;
                        });
                        return (
                          <div className="p-2 rounded bg-surface-recessed border border-border-sandstone space-y-1">
                            <span className="text-[9px] uppercase font-bold text-text-roast block">
                              Active Ground Truth (Whole AOI: {feats.length} roads)
                            </span>
                            <div className="grid grid-cols-4 gap-1 text-center font-mono text-[9px]">
                              <div className="p-1 rounded bg-success-sage/15 border border-success-sage/30">
                                <span className="block text-[8px] text-success-sage">Passable</span>
                                <span className="font-bold text-success-sage text-xs">{pCount}</span>
                              </div>
                              <div className="p-1 rounded bg-restricted-purple/15 border border-restricted-purple/30">
                                <span className="block text-[8px] text-restricted-purple">Restricted</span>
                                <span className="font-bold text-restricted-purple text-xs">{rCount}</span>
                              </div>
                              <div className="p-1 rounded bg-alert-terracotta/15 border border-alert-terracotta/30">
                                <span className="block text-[8px] text-alert-terracotta">Blocked</span>
                                <span className="font-bold text-alert-terracotta text-xs">{bCount}</span>
                              </div>
                              <div className="p-1 rounded bg-surface-cream border border-border-sandstone">
                                <span className="block text-[8px] text-text-taupe">Unverified</span>
                                <span className="font-bold text-text-taupe text-xs">{uCount}</span>
                              </div>
                            </div>
                          </div>
                        );
                      })()}

                      <div className="p-2 rounded bg-surface-recessed/80 border border-border-sandstone text-[10px] text-text-taupe leading-relaxed">
                        <span className="font-bold uppercase text-[9px] text-text-roast block mb-0.5">
                          Evidence Grounding
                        </span>
                        {roadAssessment.scientific_qualification}
                      </div>
                    </div>
                  )}
                </div>
              </Card>

              {/* Field Road Verification & Ground Truth Card */}
              <Card
                title="Field Road Verification"
                subtitle="Record operator ground-truth road status"
              >
                {selectedRoad ? (
                  <form onSubmit={handleSubmitVerification} className="space-y-3">
                    <div className="p-2.5 rounded bg-surface-recessed border border-border-sandstone space-y-1.5">
                      <div className="flex items-center justify-between">
                        <span className="font-bold text-text-roast text-xs">
                          {selectedRoad.properties.name || 'Unnamed Road'}
                        </span>
                        <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-surface-cream text-text-taupe border border-border-subtle">
                          way/{selectedRoad.properties.osm_id}
                        </span>
                      </div>
                      <div className="grid grid-cols-2 gap-1.5 text-[10px] font-mono">
                        <div>
                          <span className="text-text-taupe block">Highway Type:</span>
                          <span className="font-semibold text-text-roast">{selectedRoad.properties.highway || 'road'}</span>
                        </div>
                        <div>
                          <span className="text-text-taupe block">SAR Distance:</span>
                          <span className="font-semibold text-text-roast">
                            {selectedRoad.properties.distance_meters != null && selectedRoad.properties.distance_meters >= 0
                              ? `${selectedRoad.properties.distance_meters} m`
                              : 'N/A'}
                          </span>
                        </div>
                      </div>
                      <div className="flex items-center justify-between pt-1 border-t border-border-subtle text-[10px]">
                        <span className="text-text-taupe">Current Ground Status:</span>
                        <span
                          className={`font-mono font-bold px-1.5 py-0.5 rounded text-[10px] ${
                            selectedRoad.properties.field_status === 'VERIFIED_PASSABLE'
                              ? 'bg-success-sage/20 text-success-sage border border-success-sage/40'
                              : selectedRoad.properties.field_status === 'VERIFIED_BLOCKED'
                              ? 'bg-alert-terracotta/20 text-alert-terracotta border border-alert-terracotta/40'
                              : selectedRoad.properties.field_status === 'RESTRICTED'
                              ? 'bg-restricted-purple/20 text-restricted-purple border border-restricted-purple/40'
                              : 'bg-surface-cream text-text-taupe border border-border-subtle'
                          }`}
                        >
                          {(selectedRoad.properties.field_status || 'UNVERIFIED').replace(/_/g, ' ')}
                        </span>
                      </div>
                      {selectedRoad.properties.verified_by && (
                        <div className="text-[9px] text-text-taupe font-mono pt-0.5">
                          Verified by {selectedRoad.properties.verified_by} at{' '}
                          {new Date(selectedRoad.properties.verified_at || Date.now()).toLocaleTimeString()}
                        </div>
                      )}
                    </div>

                    {/* Quick populate coordinates into Route Planner */}
                    <div className="flex items-center space-x-1.5">
                      <Button
                        type="button"
                        size="sm"
                        variant="ghost"
                        className="text-[10px] py-1 h-auto flex-1"
                        onClick={() => {
                          const coords = selectedRoad.geometry?.coordinates;
                          if (coords && coords.length > 0) {
                            const pt = Array.isArray(coords[0]) && typeof coords[0][0] === 'number' ? coords[0] : coords[0][0];
                            setStartLat(pt[1].toFixed(5));
                            setStartLon(pt[0].toFixed(5));
                          }
                        }}
                      >
                        Set as Route Start
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        variant="ghost"
                        className="text-[10px] py-1 h-auto flex-1"
                        onClick={() => {
                          const coords = selectedRoad.geometry?.coordinates;
                          if (coords && coords.length > 0) {
                            const last = coords[coords.length - 1];
                            const pt = Array.isArray(last) && typeof last[0] === 'number' ? last : last[last.length - 1];
                            setDestLat(pt[1].toFixed(5));
                            setDestLon(pt[0].toFixed(5));
                          }
                        }}
                      >
                        Set as Route Dest
                      </Button>
                    </div>

                    <div className="space-y-1.5">
                      <label className="text-[11px] font-semibold text-text-roast block">
                        Update Ground Verification Status
                      </label>
                      <select
                        value={verifStatusInput}
                        onChange={(e) => setVerifStatusInput(e.target.value as FieldVerificationStatus)}
                        className="w-full text-xs font-mono p-1.5 rounded bg-surface-cream border border-border-sandstone text-text-roast"
                      >
                        <option value="VERIFIED_PASSABLE">VERIFIED PASSABLE (Ground Confirmed)</option>
                        <option value="VERIFIED_BLOCKED">VERIFIED BLOCKED (Ground Impassable)</option>
                        <option value="RESTRICTED">RESTRICTED (Emergency / High Clearance Only)</option>
                        <option value="UNVERIFIED">UNVERIFIED (Unconfirmed Status)</option>
                      </select>
                    </div>

                    <div className="space-y-1">
                      <label className="text-[11px] font-semibold text-text-roast block">
                        Verifying Team / Operator ID
                      </label>
                      <input
                        type="text"
                        value={verifOperatorInput}
                        onChange={(e) => setVerifOperatorInput(e.target.value)}
                        placeholder="e.g. Field Team Alpha"
                        className="w-full text-xs p-1.5 rounded bg-surface-cream border border-border-sandstone text-text-roast font-mono"
                        required
                      />
                    </div>

                    <div className="space-y-1">
                      <label className="text-[11px] font-semibold text-text-roast block">
                        Field Observations & Ground Notes
                      </label>
                      <textarea
                        value={verifNotesInput}
                        onChange={(e) => setVerifNotesInput(e.target.value)}
                        placeholder="e.g. Water 0.4m deep over asphalt; bridge culvert intact; passable only by high-clearance truck."
                        rows={2}
                        className="w-full text-xs p-1.5 rounded bg-surface-cream border border-border-sandstone text-text-roast leading-relaxed"
                      />
                    </div>

                    <div className="flex items-center space-x-2 pt-1">
                      <Button
                        type="submit"
                        size="sm"
                        variant="primary"
                        isLoading={isSubmittingVerif}
                        icon={<CheckCircle className="w-3.5 h-3.5" />}
                        className="flex-1"
                      >
                        Save Ground Truth
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        variant="ghost"
                        onClick={() => setSelectedRoad(null)}
                      >
                        Deselect
                      </Button>
                    </div>
                  </form>
                ) : (
                  <div className="p-3 rounded bg-surface-recessed border border-border-sandstone text-[11px] text-text-taupe space-y-1.5 text-center">
                    <Eye className="w-4 h-4 mx-auto text-accent-espresso mb-1" />
                    <div className="font-semibold text-text-roast">No Road Selected</div>
                    <p className="leading-snug">
                      Click any road segment on the map to inspect its SAR impact telemetry and record ground-truth field verification.
                    </p>
                  </div>
                )}
              </Card>

              {/* Evidence-Based Route Planning Card */}
              <Card
                title="Candidate Route Planning"
                subtitle="Topological graph routing over OSM network"
              >
                <div className="space-y-3">
                  {/* Mandatory Safety Notice */}
                  <div className="p-2 rounded bg-alert-terracotta/10 border border-alert-terracotta/40 text-[10px] text-alert-terracotta space-y-0.5">
                    <div className="flex items-center space-x-1.5 font-bold uppercase text-[9px]">
                      <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
                      <span>Ground Verification Required</span>
                    </div>
                    <p className="leading-snug text-text-taupe">
                      All computed paths are candidate routes. Roads outside SAR change polygons are NOT guaranteed safe or passable.
                    </p>
                  </div>

                  {/* Waypoint Coordinates Form */}
                  <div className="space-y-2">
                    <div>
                      <span className="text-[10px] font-semibold uppercase text-text-taupe block mb-1">
                        Start Waypoint (Lat, Lon)
                      </span>
                      <div className="grid grid-cols-2 gap-1.5">
                        <input
                          type="number"
                          step="any"
                          placeholder="Start Lat"
                          value={startLat}
                          onChange={(e) => {
                            setStartLat(e.target.value);
                            setRoutePlan(null);
                            setRouteError(null);
                          }}
                          className="w-full text-xs font-mono p-1.5 rounded bg-surface-cream border border-border-sandstone"
                        />
                        <input
                          type="number"
                          step="any"
                          placeholder="Start Lon"
                          value={startLon}
                          onChange={(e) => {
                            setStartLon(e.target.value);
                            setRoutePlan(null);
                            setRouteError(null);
                          }}
                          className="w-full text-xs font-mono p-1.5 rounded bg-surface-cream border border-border-sandstone"
                        />
                      </div>
                    </div>

                    <div>
                      <span className="text-[10px] font-semibold uppercase text-text-taupe block mb-1">
                        Destination Waypoint (Lat, Lon)
                      </span>
                      <div className="grid grid-cols-2 gap-1.5">
                        <input
                          type="number"
                          step="any"
                          placeholder="Dest Lat"
                          value={destLat}
                          onChange={(e) => {
                            setDestLat(e.target.value);
                            setRoutePlan(null);
                            setRouteError(null);
                          }}
                          className="w-full text-xs font-mono p-1.5 rounded bg-surface-cream border border-border-sandstone"
                        />
                        <input
                          type="number"
                          step="any"
                          placeholder="Dest Lon"
                          value={destLon}
                          onChange={(e) => {
                            setDestLon(e.target.value);
                            setRoutePlan(null);
                            setRouteError(null);
                          }}
                          className="w-full text-xs font-mono p-1.5 rounded bg-surface-cream border border-border-sandstone"
                        />
                      </div>
                    </div>

                    {/* Quick populate sample coordinates from road network */}
                    {roadAssessment?.road_geojson?.features && roadAssessment.road_geojson.features.length >= 2 && (
                      <button
                        type="button"
                        onClick={() => {
                          const feats = roadAssessment.road_geojson.features;
                          if (isDemoMode && feats.length >= 4) {
                            // In demo mode, sample waypoints along the verified relief corridor (DEMO-990004)
                            const corridor = feats[3].geometry?.coordinates as any;
                            if (corridor && corridor.length >= 2) {
                              const p1 = corridor[0];
                              const p2 = corridor[corridor.length - 1];
                              setStartLat(p1[1].toFixed(5));
                              setStartLon(p1[0].toFixed(5));
                              setDestLat(p2[1].toFixed(5));
                              setDestLon(p2[0].toFixed(5));
                              setRoutePlan(null);
                              setRouteError(null);
                              return;
                            }
                          }
                          const c1 = feats[0].geometry?.coordinates as any;
                          const c2 = feats[feats.length - 1].geometry?.coordinates as any;
                          if (c1 && c1.length > 0) {
                            const p1 = Array.isArray(c1[0]) && typeof c1[0][0] === 'number' ? c1[0] : c1[0][0];
                            setStartLat(p1[1].toFixed(5));
                            setStartLon(p1[0].toFixed(5));
                          }
                          if (c2 && c2.length > 0) {
                            const last = c2[c2.length - 1];
                            const p2 = Array.isArray(last) && typeof last[0] === 'number' ? last : last[last.length - 1];
                            setDestLat(p2[1].toFixed(5));
                            setDestLon(p2[0].toFixed(5));
                          }
                          setRoutePlan(null);
                          setRouteError(null);
                        }}
                        className="text-[10px] text-accent-espresso hover:underline font-mono"
                      >
                        ⚡ Sample Waypoints from Network
                      </button>
                    )}
                  </div>

                  {/* Routing Mode */}
                  <div className="space-y-1">
                    <span className="text-[10px] font-semibold uppercase text-text-taupe block">
                      Routing Policy Mode
                    </span>
                    <div className="grid grid-cols-2 gap-1.5">
                      <button
                        type="button"
                        onClick={() => {
                          setRoutingMode('CONSERVATIVE');
                          setRoutePlan(null);
                          setRouteError(null);
                        }}
                        className={`p-2 rounded border text-left cursor-pointer transition-all ${
                          routingMode === 'CONSERVATIVE'
                            ? 'bg-accent-espresso text-surface-cream border-accent-espresso font-semibold'
                            : 'bg-surface-cream text-text-roast border-border-sandstone hover:bg-surface-recessed'
                        }`}
                      >
                        <div className="text-[10px] uppercase font-bold flex items-center space-x-1">
                          <ShieldCheck className="w-3.5 h-3.5 shrink-0" />
                          <span>Conservative</span>
                        </div>
                        <div className="text-[9px] opacity-80 mt-0.5 leading-snug">
                          Verified-passable paths only; unverified roads strictly excluded
                        </div>
                      </button>

                      <button
                        type="button"
                        onClick={() => {
                          setRoutingMode('EXPLORATORY');
                          setRoutePlan(null);
                          setRouteError(null);
                        }}
                        className={`p-2 rounded border text-left cursor-pointer transition-all ${
                          routingMode === 'EXPLORATORY'
                            ? 'bg-accent-espresso text-surface-cream border-accent-espresso font-semibold'
                            : 'bg-surface-cream text-text-roast border-border-sandstone hover:bg-surface-recessed'
                        }`}
                      >
                        <div className="text-[10px] uppercase font-bold flex items-center space-x-1">
                          <Compass className="w-3.5 h-3.5 shrink-0" />
                          <span>Exploratory</span>
                        </div>
                        <div className="text-[9px] opacity-80 mt-0.5 leading-snug">
                          Traverses unverified roads when necessary; warns on each
                        </div>
                      </button>
                    </div>
                  </div>

                  {/* Permit Restricted Roads Checkbox */}
                  <label className="flex items-center space-x-2 text-[11px] text-text-taupe cursor-pointer">
                    <input
                      type="checkbox"
                      checked={permitRestricted}
                      onChange={(e) => {
                        setPermitRestricted(e.target.checked);
                        setRoutePlan(null);
                        setRouteError(null);
                      }}
                      className="rounded accent-accent-espresso cursor-pointer"
                    />
                    <span>Permit Emergency-Restricted Road Segments</span>
                  </label>

                  {/* Plan Button */}
                  <Button
                    size="sm"
                    variant="primary"
                    className="w-full"
                    isLoading={isPlanningRoute}
                    onClick={handlePlanRoute}
                    icon={<Route className="w-3.5 h-3.5" />}
                  >
                    Calculate Candidate Route
                  </Button>

                  {/* Routing Error Notice */}
                  {routeError && (
                    <div className="p-2.5 rounded bg-alert-terracotta/10 border border-alert-terracotta/40 text-[10px] text-alert-terracotta space-y-1">
                      <div className="flex items-center space-x-1.5 font-bold uppercase text-[9px]">
                        <AlertCircle className="w-3.5 h-3.5 shrink-0" />
                        <span>Route Planning Notice</span>
                      </div>
                      <p className="leading-snug">{routeError}</p>
                    </div>
                  )}

                  {/* Successful Candidate Route Results */}
                  {routePlan && routePlan.status === 'ROUTE_FOUND' && (
                    <div className="space-y-2 pt-2 border-t border-border-subtle">
                      <div className="flex items-center justify-between text-[10px] font-mono">
                        <span className="text-text-taupe">Status:</span>
                        <span className="font-bold text-accent-espresso px-1.5 py-0.5 rounded bg-surface-recessed border border-border-subtle">
                          {routePlan.status}
                        </span>
                      </div>

                      <div className="grid grid-cols-2 gap-2 text-center font-mono">
                        <div className="p-2 rounded bg-surface-recessed border border-border-sandstone">
                          <span className="text-[9px] uppercase text-text-taupe block mb-0.5">
                            Total Distance
                          </span>
                          <span className="font-bold text-accent-espresso text-sm">
                            {routePlan.total_distance_km} km
                          </span>
                        </div>

                        <div className="p-2 rounded bg-surface-recessed border border-border-sandstone">
                          <span className="text-[9px] uppercase text-text-taupe block mb-0.5">
                            Routing Mode
                          </span>
                          <span className="font-bold text-text-roast text-sm">
                            {routePlan.routing_mode}
                          </span>
                        </div>
                      </div>

                      {/* Path Segments Breakdown along the chosen route */}
                      <div className="space-y-1">
                        <span className="text-[9px] uppercase font-bold text-text-taupe block">
                          Segments on This Computed Path ({routePlan.total_distance_km} km)
                        </span>
                        <div className="grid grid-cols-3 gap-1.5 text-center font-mono text-[10px]">
                          <div className="p-1.5 rounded bg-success-sage/15 border border-success-sage/30">
                            <span className="text-[8px] uppercase text-success-sage block font-semibold">Path Passable</span>
                            <span className="font-bold text-success-sage text-xs">{routePlan.passable_segments_count}</span>
                          </div>
                          <div className="p-1.5 rounded bg-warning-ochre/15 border border-warning-ochre/30">
                            <span className="text-[8px] uppercase text-warning-ochre block font-semibold">Path Unverified</span>
                            <span className="font-bold text-warning-ochre text-xs">{routePlan.unverified_segments_count}</span>
                          </div>
                          <div className="p-1.5 rounded bg-restricted-purple/15 border border-restricted-purple/30">
                            <span className="text-[8px] uppercase text-restricted-purple block font-semibold">Path Restricted</span>
                            <span className="font-bold text-restricted-purple text-xs">{routePlan.restricted_segments_count}</span>
                          </div>
                        </div>
                        <p className="text-[8px] text-text-taupe italic">
                          Segments comprising this specific path (not total network roads).
                        </p>
                      </div>

                      {/* Mandatory Warnings */}
                      {routePlan.warnings && routePlan.warnings.length > 0 && (
                        <div className="p-2 rounded bg-warning-ochre/10 border border-warning-ochre/40 text-[10px] text-text-roast space-y-1">
                          <div className="flex items-center space-x-1.5 font-bold uppercase text-[9px] text-warning-ochre">
                            <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
                            <span>Route Warnings</span>
                          </div>
                          <ul className="list-disc list-inside space-y-0.5 text-[9px] text-text-taupe">
                            {routePlan.warnings.map((w, idx) => (
                              <li key={idx} className="leading-snug">{w}</li>
                            ))}
                          </ul>
                        </div>
                      )}

                      {/* Mandatory Disclaimer */}
                      <div className="p-2 rounded bg-surface-recessed/80 border border-border-sandstone text-[9px] text-text-taupe leading-relaxed italic">
                        {routePlan.scientific_qualification}
                      </div>

                      <Button
                        size="sm"
                        variant="ghost"
                        className="w-full text-xs"
                        onClick={() => {
                          setRoutePlan(null);
                          setRouteError(null);
                        }}
                      >
                        Clear Candidate Route
                      </Button>
                    </div>
                  )}
                </div>
              </Card>

              {/* Export Panel */}
              <div className="pt-2 border-t border-border-subtle space-y-2">
                <div className="text-[11px] font-semibold uppercase tracking-wider text-text-taupe">
                  Artifact Exports
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <Button
                    size="sm"
                    variant="secondary"
                    icon={<FileCode className="w-3.5 h-3.5" />}
                    onClick={handleExportGeoJSON}
                  >
                    GeoJSON Mask
                  </Button>
                  <Button
                    size="sm"
                    variant="secondary"
                    icon={<Download className="w-3.5 h-3.5" />}
                    onClick={() => {
                      if (analysisResult.mask_image_url) {
                        window.open(analysisResult.mask_image_url, '_blank');
                      }
                    }}
                  >
                    Raster Overlay
                  </Button>
                </div>
              </div>
            </>
          ) : (
            <EmptyState
              icon={Satellite}
              title="Awaiting SAR Pair Execution"
              description="Select a Before and After SAR granule from the left rail (or upload files on /upload) and run log-ratio change detection to unlock tactical telemetry."
            />
          )}
        </div>
      </aside>

      {/* Tactile Right Rail Expand Tab */}
      {!rightOpen && analysisResult && (
        <button
          onClick={() => setRightOpen(true)}
          className="absolute top-4 right-4 z-20 h-9 px-2.5 bg-surface-cream border border-border-sandstone rounded shadow-panel text-accent-espresso flex items-center space-x-1 hover:bg-surface-recessed transition-all"
        >
          <ChevronLeft className="w-3.5 h-3.5 mr-1" />
          <span className="text-xs font-semibold uppercase">Telemetry</span>
          <Sliders className="w-4 h-4 ml-1" />
        </button>
      )}
    </div>
  );
};
