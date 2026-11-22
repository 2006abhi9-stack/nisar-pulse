import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  MapContainer,
  TileLayer,
  GeoJSON,
  ImageOverlay,
  useMap,
} from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import {
  UploadCloud,
  FileCheck,
  AlertCircle,
  ArrowRight,
  Sliders,
  CheckCircle2,
  Layers,
  MapPin,
} from 'lucide-react';
import { analyzeUpload, generateBriefing } from '../api/client';
import { AnalysisResult } from '../types';
import { Button } from '../components/Button';
import { Card } from '../components/Card';
import { HistogramChart } from '../components/HistogramChart';
import { AIBriefingCard } from '../components/AIBriefingCard';

// Helper controller to auto-zoom to bounds
const MapFitBounds: React.FC<{ bounds?: [[number, number], [number, number]]; geojson?: any }> = ({
  bounds,
  geojson,
}) => {
  const map = useMap();
  useEffect(() => {
    if (!map) return;
    if (bounds && Array.isArray(bounds) && bounds.length === 2) {
      try {
        const b = L.latLngBounds(bounds);
        if (b.isValid()) {
          map.fitBounds(b, { padding: [30, 30] });
          return;
        }
      } catch (e) {
        console.warn('MapFitBounds: bounds invalid', e);
      }
    }
    if (geojson && geojson.features && geojson.features.length > 0) {
      try {
        const layer = L.geoJSON(geojson);
        const b = layer.getBounds();
        if (b.isValid()) {
          map.fitBounds(b, { padding: [30, 30] });
        }
      } catch (e) {
        console.warn('MapFitBounds: geojson bounds invalid', e);
      }
    }
  }, [map, bounds, geojson]);
  return null;
};

export const UploadPage: React.FC = () => {
  const navigate = useNavigate();

  const [beforeFile, setBeforeFile] = useState<File | null>(null);
  const [afterFile, setAfterFile] = useState<File | null>(null);
  const [thresholdDb, setThresholdDb] = useState<number>(-3.0);
  const [speckleFilter, setSpeckleFilter] = useState<boolean>(true);
  const [isProcessing, setIsProcessing] = useState<boolean>(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [isBriefingLoading, setIsBriefingLoading] = useState<boolean>(false);

  const handleUploadAndRun = async () => {
    if (!beforeFile || !afterFile) {
      setErrorMsg('Both Pre-Event and Post-Event SAR files are required.');
      return;
    }
    setErrorMsg(null);
    setIsProcessing(true);
    try {
      const res = await analyzeUpload(
        beforeFile,
        afterFile,
        thresholdDb,
        speckleFilter
      );
      setResult(res);
      // Auto-navigate to live map workspace to display the change polygons and telemetry
      navigate('/', { state: { analysisResult: res } });
    } catch (err: any) {
      setErrorMsg(err.message || 'Change detection failed on uploaded files.');
    } finally {
      setIsProcessing(false);
    }
  };

  const handleGenerateBriefing = async (focus?: string) => {
    if (!result) return;
    setIsBriefingLoading(true);
    try {
      const briefing = await generateBriefing(result.analysis_id, focus);
      setResult((prev) => (prev ? { ...prev, briefing } : null));
    } catch (err: any) {
      alert(`Briefing failed: ${err.message}`);
    } finally {
      setIsBriefingLoading(false);
    }
  };

  return (
    <div className="w-full h-[calc(100vh-52px)] overflow-y-auto bg-canvas-sand p-6">
      <div className="max-w-5xl mx-auto space-y-6">
        {/* Header */}
        <div className="border-b border-border-sandstone pb-4">
          <div className="flex items-center space-x-2 text-accent-espresso mb-1">
            <UploadCloud className="w-5 h-5" />
            <h1 className="text-base font-bold uppercase tracking-wider text-text-roast">
              Direct SAR File Analyzer
            </h1>
          </div>
          <p className="text-xs text-text-taupe leading-relaxed">
            Upload pre- and post-event SAR rasters (.h5 NISAR HDF5, .tif GeoTIFF, or calibrated PNG)
            to execute speckle suppression, log-ratio backscatter change detection, and AI synthesis.
          </p>
        </div>

        {/* Dropzones Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* Pre-Event Dropzone */}
          <div className="bg-surface-cream border border-border-sandstone rounded-md p-4 shadow-subtle flex flex-col justify-between">
            <div>
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs font-semibold uppercase tracking-wider text-text-roast">
                  [1] Baseline / Pre-Event SAR Granule
                </span>
                <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-surface-recessed text-text-taupe border border-border-subtle">
                  BEFORE
                </span>
              </div>
              <p className="text-[11px] text-text-taupe mb-3">
                Reference SAR acquisition before surface disturbance or disaster event.
              </p>
            </div>

            <label className="border-2 border-dashed border-border-sandstone hover:border-accent-espresso rounded-md p-6 flex flex-col items-center justify-center cursor-pointer transition-colors bg-surface-recessed/40">
              <input
                type="file"
                accept=".h5,.hdf5,.tif,.tiff,.png"
                className="hidden"
                onChange={(e) => {
                  if (e.target.files && e.target.files[0]) {
                    setBeforeFile(e.target.files[0]);
                  }
                }}
              />
              {beforeFile ? (
                <div className="flex flex-col items-center text-center">
                  <FileCheck className="w-8 h-8 text-success-sage mb-2" />
                  <span className="text-xs font-mono font-bold text-text-roast truncate max-w-xs">
                    {beforeFile.name}
                  </span>
                  <span className="text-[10px] text-text-taupe font-mono mt-1">
                    {(beforeFile.size / (1024 * 1024)).toFixed(2)} MB
                  </span>
                </div>
              ) : (
                <div className="flex flex-col items-center text-center">
                  <UploadCloud className="w-8 h-8 text-text-taupe mb-2" />
                  <span className="text-xs font-medium text-text-roast">
                    Click to browse or drop Before file
                  </span>
                  <span className="text-[10px] text-text-taupe font-mono mt-1">
                    .h5, .tif, .tiff (Max 50 MB)
                  </span>
                </div>
              )}
            </label>
          </div>

          {/* Post-Event Dropzone */}
          <div className="bg-surface-cream border border-border-sandstone rounded-md p-4 shadow-subtle flex flex-col justify-between">
            <div>
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs font-semibold uppercase tracking-wider text-alert-terracotta">
                  [2] Target / Post-Event SAR Granule
                </span>
                <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-alert-terracotta-bg text-alert-terracotta border border-alert-terracotta/30">
                  AFTER
                </span>
              </div>
              <p className="text-[11px] text-text-taupe mb-3">
                Post-disaster acquisition to measure backscatter loss or structural damage.
              </p>
            </div>

            <label className="border-2 border-dashed border-border-sandstone hover:border-alert-terracotta rounded-md p-6 flex flex-col items-center justify-center cursor-pointer transition-colors bg-surface-recessed/40">
              <input
                type="file"
                accept=".h5,.hdf5,.tif,.tiff,.png"
                className="hidden"
                onChange={(e) => {
                  if (e.target.files && e.target.files[0]) {
                    setAfterFile(e.target.files[0]);
                  }
                }}
              />
              {afterFile ? (
                <div className="flex flex-col items-center text-center">
                  <FileCheck className="w-8 h-8 text-alert-terracotta mb-2" />
                  <span className="text-xs font-mono font-bold text-text-roast truncate max-w-xs">
                    {afterFile.name}
                  </span>
                  <span className="text-[10px] text-text-taupe font-mono mt-1">
                    {(afterFile.size / (1024 * 1024)).toFixed(2)} MB
                  </span>
                </div>
              ) : (
                <div className="flex flex-col items-center text-center">
                  <UploadCloud className="w-8 h-8 text-text-taupe mb-2" />
                  <span className="text-xs font-medium text-text-roast">
                    Click to browse or drop After file
                  </span>
                  <span className="text-[10px] text-text-taupe font-mono mt-1">
                    .h5, .tif, .tiff (Max 50 MB)
                  </span>
                </div>
              )}
            </label>
          </div>
        </div>

        {/* Parameters & Execution Controls */}
        <div className="bg-surface-cream border border-border-sandstone rounded-md p-4 shadow-subtle flex flex-col md:flex-row items-center justify-between gap-4">
          <div className="flex flex-wrap items-center gap-6 text-xs w-full md:w-auto">
            <div>
              <div className="flex items-center justify-between text-[11px] font-mono text-text-taupe mb-1">
                <span>Threshold:</span>
                <span className="font-bold text-accent-espresso ml-1">{thresholdDb} dB</span>
              </div>
              <input
                type="range"
                min="-12.0"
                max="-1.0"
                step="0.5"
                value={thresholdDb}
                onChange={(e) => setThresholdDb(parseFloat(e.target.value))}
                className="w-36 accent-accent-espresso"
              />
            </div>

            <div className="flex items-center space-x-2">
              <input
                type="checkbox"
                id="speckleCheck"
                checked={speckleFilter}
                onChange={(e) => setSpeckleFilter(e.target.checked)}
                className="rounded accent-accent-espresso"
              />
              <label htmlFor="speckleCheck" className="text-text-roast font-medium cursor-pointer">
                Speckle Filter (Bilateral)
              </label>
            </div>
          </div>

          <Button
            variant="alert"
            size="lg"
            isLoading={isProcessing}
            disabled={!beforeFile || !afterFile}
            onClick={handleUploadAndRun}
            icon={<Sliders className="w-4 h-4" />}
          >
            Compute Surface Change
          </Button>
        </div>

        {/* Error notice */}
        {errorMsg && (
          <div className="p-3 bg-alert-terracotta-bg border border-alert-terracotta/40 text-alert-terracotta rounded text-xs flex items-center space-x-2">
            <AlertCircle className="w-4 h-4 shrink-0" />
            <span>{errorMsg}</span>
          </div>
        )}

        {/* Analysis Result Output */}
        {result && (
          <div className="space-y-4 pt-2">
            <div className="flex items-center justify-between border-b border-border-sandstone pb-2">
              <div className="flex items-center space-x-2">
                <CheckCircle2 className="w-5 h-5 text-success-sage" />
                <div>
                  <h2 className="text-sm font-bold uppercase tracking-wider text-text-roast">
                    {result.change_type || 'Significant Backscatter Decrease'}
                  </h2>
                  <span className="text-[10px] text-text-taupe font-mono">
                    ID: {result.analysis_id.slice(0, 8)}... | Threshold: {result.threshold_db} dB
                  </span>
                </div>
              </div>
              <Button
                variant="primary"
                size="sm"
                icon={<ArrowRight className="w-3.5 h-3.5" />}
                onClick={() => navigate('/', { state: { analysisResult: result } })}
              >
                Inspect on Live Map
              </Button>
            </div>

            {/* Compact Metrics Grid */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <div className="p-3 bg-surface-cream border border-border-sandstone rounded">
                <span className="text-[10px] uppercase font-semibold text-text-taupe block mb-0.5">
                  Impacted Area
                </span>
                <span className="font-mono text-sm font-bold text-alert-terracotta">
                  {result.impacted_km2 ?? 0} km²
                </span>
              </div>

              <div className="p-3 bg-surface-cream border border-border-sandstone rounded">
                <span className="text-[10px] uppercase font-semibold text-text-taupe block mb-0.5">
                  Mean dB Drop
                </span>
                <span className="font-mono text-sm font-bold text-text-roast">
                  {result.mean_db_drop != null ? `${result.mean_db_drop} dB` : 'N/A'}
                </span>
              </div>

              <div className="p-3 bg-surface-cream border border-border-sandstone rounded">
                <span className="text-[10px] uppercase font-semibold text-text-taupe block mb-0.5">
                  Valid Pixels
                </span>
                <span className="font-mono text-sm font-bold text-accent-espresso">
                  {result.valid_pixels != null ? result.valid_pixels.toLocaleString() : 'N/A'}
                </span>
              </div>

              <div className="p-3 bg-surface-cream border border-border-sandstone rounded">
                <span className="text-[10px] uppercase font-semibold text-text-taupe block mb-0.5">
                  Coordinate System
                </span>
                <span className="font-mono text-sm font-bold text-text-taupe truncate block" title={result.crs || 'N/A'}>
                  {result.crs || 'N/A'}
                </span>
              </div>
            </div>

            {/* Scientific Qualification Notice */}
            <div className="p-3 bg-surface-cream border border-border-sandstone rounded space-y-1">
              <div className="flex items-center space-x-1.5 text-accent-espresso font-semibold uppercase text-xs">
                <AlertCircle className="w-3.5 h-3.5 text-warning-ochre shrink-0" />
                <span>Scientific Qualification</span>
              </div>
              <p className="text-xs text-text-taupe leading-relaxed">
                {result.scientific_qualification ||
                  'Detected backscatter reduction of <= threshold. May indicate open surface water inundation, specular reflection, soil moisture changes, or vegetation disturbance. Field validation or multi-temporal analysis required to confirm flood extent.'}
              </p>
            </div>

            {/* Map Canvas Card */}
            <Card
              title="Georeferenced Change Mask (Significant Backscatter Decrease)"
              subtitle={result.crs ? `Projected in ${result.crs}` : 'WGS84 Coordinates'}
            >
              <div className="h-80 w-full rounded border border-border-sandstone overflow-hidden relative">
                <MapContainer
                  center={
                    result.bounds && result.bounds.length === 2
                      ? [(result.bounds[0][0] + result.bounds[1][0]) / 2, (result.bounds[0][1] + result.bounds[1][1]) / 2]
                      : [37.77, -122.42]
                  }
                  zoom={10}
                  className="w-full h-full"
                  zoomControl={true}
                >
                  <TileLayer
                    attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
                    url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                  />
                  <MapFitBounds bounds={result.bounds} geojson={result.mask_geojson} />

                  {/* Vectorized Change Mask GeoJSON Layer */}
                  {result.mask_geojson && result.mask_geojson.features && result.mask_geojson.features.length > 0 ? (
                    <GeoJSON
                      key={`upload-mask-${result.analysis_id}`}
                      data={result.mask_geojson as any}
                      style={{
                        color: '#D85B61',
                        weight: 2,
                        fillColor: '#D85B61',
                        fillOpacity: 0.65,
                      }}
                      onEachFeature={(_f, layer) => {
                        const label = result.change_type || 'Significant Backscatter Decrease';
                        layer.bindTooltip(
                          `<strong>${label}</strong><br/>${result.impacted_km2 ?? 0} km² affected`,
                          { sticky: true }
                        );
                        layer.bindPopup(
                          `<div style="font-family: 'Space Grotesk', sans-serif; font-size: 11px; line-height: 1.45; min-width: 200px; color: #F1F5F9;">
                            <div style="font-weight: 700; color: #D85B61; text-transform: uppercase; margin-bottom: 4px; border-bottom: 1px solid #2C3E50; padding-bottom: 2px;">
                              ${label}
                            </div>
                            <div><strong>Impacted Area:</strong> <span style="font-family: 'JetBrains Mono', monospace; color: #36CFC9;">${result.impacted_km2 ?? 0} km²</span></div>
                            ${result.mean_db_drop != null ? `<div><strong>Mean dB Drop:</strong> <span style="font-family: 'JetBrains Mono', monospace;">${result.mean_db_drop} dB</span></div>` : ''}
                            ${result.valid_pixels != null ? `<div><strong>Valid Pixels:</strong> <span style="font-family: 'JetBrains Mono', monospace;">${result.valid_pixels.toLocaleString()}</span></div>` : ''}
                            ${result.crs ? `<div><strong>CRS:</strong> <span style="font-family: 'JetBrains Mono', monospace;">${result.crs}</span></div>` : ''}
                            <div style="margin-top: 6px; font-size: 10px; color: #AAB7C4; border-top: 1px solid #2C3E50; padding-top: 4px; font-style: italic;">
                              <em>${result.scientific_qualification || 'Field validation required to confirm flood extent.'}</em>
                            </div>
                          </div>`
                        );
                      }}
                    />
                  ) : (
                    <div className="leaflet-top leaflet-right p-2 pointer-events-none">
                      <div className="bg-surface-cream/90 backdrop-blur border border-border-sandstone rounded px-2.5 py-1 text-xs text-text-taupe shadow-subtle">
                        No change polygons detected exceeding threshold
                      </div>
                    </div>
                  )}

                  {/* Raster Mask Overlay if bounds present */}
                  {result.mask_image_url && result.bounds && (
                    <ImageOverlay
                      url={result.mask_image_url}
                      bounds={result.bounds}
                      opacity={0.8}
                    />
                  )}
                </MapContainer>
              </div>
            </Card>

            {/* Histogram & Briefing */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <Card title="Backscatter Delta Histogram" subtitle="Pixel distribution">
                <HistogramChart data={result.histogram} thresholdDb={result.threshold_db} />
              </Card>

              <AIBriefingCard
                briefing={result.briefing}
                isLoading={isBriefingLoading}
                onGenerateBriefing={handleGenerateBriefing}
              />
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
