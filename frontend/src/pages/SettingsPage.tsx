import React, { useEffect, useState } from 'react';
import {
  Settings2,
  Database,
  Globe2,
  Sparkles,
  HardDrive,
  CheckCircle2,
  AlertTriangle,
  RefreshCw,
  ExternalLink,
  ShieldCheck,
} from 'lucide-react';
import { fetchHealth } from '../api/client';
import { HealthStatus } from '../types';
import { Button } from '../components/Button';
import { Card } from '../components/Card';

export const SettingsPage: React.FC = () => {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);

  const checkStatus = async () => {
    setIsLoading(true);
    try {
      const data = await fetchHealth();
      setHealth(data);
    } catch {
      setHealth(null);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    checkStatus();
  }, []);

  return (
    <div className="w-full h-[calc(100vh-52px)] overflow-y-auto bg-canvas-sand p-6">
      <div className="max-w-4xl mx-auto space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border-sandstone pb-4">
          <div>
            <div className="flex items-center space-x-2 text-accent-espresso mb-1">
              <Settings2 className="w-5 h-5" />
              <h1 className="text-base font-bold uppercase tracking-wider text-text-roast">
                API & System Diagnostics
              </h1>
            </div>
            <p className="text-xs text-text-taupe">
              Verification of upstream satellite endpoints, AI inference services, and local database storage.
            </p>
          </div>

          <Button
            variant="secondary"
            size="sm"
            isLoading={isLoading}
            onClick={checkStatus}
            icon={<RefreshCw className="w-3.5 h-3.5" />}
          >
            Run System Ping
          </Button>
        </div>

        {/* Status Cards Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* NASA Earthdata Card */}
          <Card
            title="NASA Earthdata Authentication"
            subtitle="Alaska Satellite Facility (ASF) DAAC Access"
            action={
              <span
                className={`text-[10px] font-mono font-bold px-2 py-0.5 rounded ${
                  health?.earthdata_configured
                    ? 'bg-success-sage/10 text-success-sage border border-success-sage/30'
                    : 'bg-warning-ochre/10 text-warning-ochre border border-warning-ochre/30'
                }`}
              >
                {health?.earthdata_configured ? 'AUTHENTICATED' : 'ANONYMOUS / BROWSE'}
              </span>
            }
          >
            <div className="space-y-3 text-xs">
              <div className="flex items-start space-x-2.5">
                <Globe2 className="w-4 h-4 text-accent-espresso mt-0.5 shrink-0" />
                <p className="text-text-taupe leading-relaxed">
                  Controls full-resolution granule streaming via <code className="text-text-roast font-mono font-semibold">earthaccess</code>.
                  When unset, the engine operates in open browse imagery mode.
                </p>
              </div>

              <div className="bg-surface-recessed p-2.5 rounded border border-border-subtle font-mono text-[11px] space-y-1">
                <div className="flex justify-between">
                  <span className="text-text-taupe">Environment Key:</span>
                  <span className="text-text-roast font-bold">EARTHDATA_TOKEN</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-text-taupe">Status:</span>
                  <span className={health?.earthdata_configured ? 'text-success-sage' : 'text-warning-ochre'}>
                    {health?.earthdata_configured ? 'Configured (Active)' : 'Not Set in /backend/.env'}
                  </span>
                </div>
              </div>

              <a
                href="https://urs.earthdata.nasa.gov/"
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center space-x-1 text-accent-espresso hover:underline text-[11px] font-semibold"
              >
                <span>Generate NASA Earthdata Token</span>
                <ExternalLink className="w-3 h-3" />
              </a>
            </div>
          </Card>

          {/* Google Gemini Card */}
          <Card
            title="Google Gemini AI Inference"
            subtitle="Tactical Mission Briefing Synthesis"
            action={
              <span
                className={`text-[10px] font-mono font-bold px-2 py-0.5 rounded ${
                  health?.gemini_configured
                    ? 'bg-success-sage/10 text-success-sage border border-success-sage/30'
                    : 'bg-warning-ochre/10 text-warning-ochre border border-warning-ochre/30'
                }`}
              >
                {health?.gemini_configured ? 'ONLINE' : 'FALLBACK MODE'}
              </span>
            }
          >
            <div className="space-y-3 text-xs">
              <div className="flex items-start space-x-2.5">
                <Sparkles className="w-4 h-4 text-accent-espresso mt-0.5 shrink-0" />
                <p className="text-text-taupe leading-relaxed">
                  Synthesizes structured risk evaluations and actionable checklists using{' '}
                  <code className="text-text-roast font-mono font-semibold">gemini-2.5-flash</code> with strict Pydantic schemas.
                </p>
              </div>

              <div className="bg-surface-recessed p-2.5 rounded border border-border-subtle font-mono text-[11px] space-y-1">
                <div className="flex justify-between">
                  <span className="text-text-taupe">Environment Key:</span>
                  <span className="text-text-roast font-bold">GEMINI_API_KEY</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-text-taupe">Status:</span>
                  <span className={health?.gemini_configured ? 'text-success-sage' : 'text-warning-ochre'}>
                    {health?.gemini_configured ? 'Configured (Active)' : 'Not Set in /backend/.env'}
                  </span>
                </div>
              </div>

              <a
                href="https://aistudio.google.com/"
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center space-x-1 text-accent-espresso hover:underline text-[11px] font-semibold"
              >
                <span>Obtain Google AI Studio Key</span>
                <ExternalLink className="w-3 h-3" />
              </a>
            </div>
          </Card>

          {/* Database Card */}
          <Card
            title="Local SQLite Database"
            subtitle="aiosqlite Async Engine"
            action={
              <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded bg-success-sage/10 text-success-sage border border-success-sage/30">
                CONNECTED
              </span>
            }
          >
            <div className="space-y-3 text-xs">
              <div className="flex items-start space-x-2.5">
                <Database className="w-4 h-4 text-accent-espresso mt-0.5 shrink-0" />
                <p className="text-text-taupe leading-relaxed">
                  Persists all AOI polygon searches, NASA granule footprints, analysis runs, and generated briefings.
                </p>
              </div>

              <div className="bg-surface-recessed p-2.5 rounded border border-border-subtle font-mono text-[11px] space-y-1">
                <div className="flex justify-between">
                  <span className="text-text-taupe">Database URL:</span>
                  <span className="text-text-roast font-bold truncate max-w-[200px]">
                    sqlite+aiosqlite:///./nisar_pulse.db
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-text-taupe">Schema State:</span>
                  <span className="text-success-sage">Tables Initialized</span>
                </div>
              </div>
            </div>
          </Card>

          {/* Storage Directory Card */}
          <Card
            title="Mask Storage Subsystem"
            subtitle="Static Mask Serving"
            action={
              <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded bg-success-sage/10 text-success-sage border border-success-sage/30">
                WRITABLE
              </span>
            }
          >
            <div className="space-y-3 text-xs">
              <div className="flex items-start space-x-2.5">
                <HardDrive className="w-4 h-4 text-accent-espresso mt-0.5 shrink-0" />
                <p className="text-text-taupe leading-relaxed">
                  Generates and serves high-contrast Burnt Terracotta (<code className="font-mono text-alert-terracotta">#B84A27</code>)
                  change masks to Leaflet map overlays.
                </p>
              </div>

              <div className="bg-surface-recessed p-2.5 rounded border border-border-subtle font-mono text-[11px] space-y-1">
                <div className="flex justify-between">
                  <span className="text-text-taupe">Mount Path:</span>
                  <span className="text-text-roast font-bold">/storage/masks/</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-text-taupe">Serving Endpoint:</span>
                  <span className="text-accent-espresso">http://localhost:8000/masks/</span>
                </div>
              </div>
            </div>
          </Card>
        </div>

        {/* Security & Secrets Note */}
        <div className="bg-surface-cream border border-border-sandstone rounded-md p-4 shadow-subtle flex items-start space-x-3 text-xs">
          <ShieldCheck className="w-5 h-5 text-accent-espresso mt-0.5 shrink-0" />
          <div className="space-y-1">
            <span className="font-bold text-text-roast uppercase tracking-wider block">
              Security & Environment Isolation
            </span>
            <p className="text-text-taupe leading-relaxed">
              In adherence to <code className="font-mono text-accent-espresso font-semibold">/docs/SECURITY.md</code>,
              secrets are loaded exclusively via server-side environment variables and are never transmitted to the browser.
              Paste your credentials into <code className="font-mono text-text-roast bg-surface-recessed px-1 rounded">/backend/.env</code> and restart the server.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
};
