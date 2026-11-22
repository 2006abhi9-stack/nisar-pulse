import React, { useEffect, useState } from 'react';
import { NavLink } from 'react-router-dom';
import {
  Satellite,
  UploadCloud,
  Clock,
  Settings2,
  Activity,
  Globe2,
  Sparkles,
} from 'lucide-react';
import { fetchHealth } from '../api/client';
import { HealthStatus } from '../types';

export const TopCommandBar: React.FC = () => {
  const [utcTime, setUtcTime] = useState<string>('');
  const [health, setHealth] = useState<HealthStatus | null>(null);

  useEffect(() => {
    const updateTime = () => {
      const now = new Date();
      setUtcTime(now.toUTCString().slice(17, 25) + ' UTC');
    };
    updateTime();
    const interval = setInterval(updateTime, 1000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    fetchHealth()
      .then(setHealth)
      .catch(() => setHealth(null));
    const hInterval = setInterval(() => {
      fetchHealth().then(setHealth).catch(() => setHealth(null));
    }, 15000);
    return () => clearInterval(hInterval);
  }, []);

  const navItems = [
    { to: '/', label: 'Mission Workspace', icon: Satellite },
    { to: '/upload', label: 'Local SAR File', icon: UploadCloud },
    { to: '/history', label: 'Run Archive', icon: Clock },
    { to: '/settings', label: 'Diagnostics', icon: Settings2 },
  ];

  return (
    <header className="h-[52px] bg-surface-cream border-b border-border-sandstone px-4 flex items-center justify-between z-30 shrink-0">
      {/* Brand & Monogram */}
      <div className="flex items-center space-x-3">
        <div className="w-8 h-8 rounded bg-accent-espresso flex items-center justify-center text-canvas-dark font-bold text-sm tracking-wider shadow-sm">
          NP
        </div>
        <div className="flex flex-col">
          <div className="flex items-center space-x-1.5">
            <span className="font-bold text-sm tracking-tight text-text-roast">NISAR-Pulse</span>
            <span className="text-[10px] px-1.5 py-0.2 bg-surface-recessed text-text-taupe rounded font-mono font-medium border border-border-subtle">
              v1.0
            </span>
          </div>
          <span className="text-[10px] text-text-taupe font-mono flex items-center">
            <Activity className="w-3 h-3 mr-1 text-accent-espresso inline" />
            {utcTime || '00:00:00 UTC'}
          </span>
        </div>
      </div>

      {/* Nav Pills */}
      <nav className="flex items-center space-x-1 bg-surface-recessed p-1 rounded-md border border-border-subtle">
        {navItems.map((item) => {
          const Icon = item.icon;
          return (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                `flex items-center space-x-1.5 px-3 py-1.5 rounded text-xs font-medium transition-all duration-180 ease-mechanical ${
                  isActive
                    ? 'bg-surface-cream text-accent-espresso shadow-subtle border border-border-sandstone'
                    : 'text-text-taupe hover:text-text-roast hover:bg-surface-cream/50'
                }`
              }
            >
              <Icon className="w-3.5 h-3.5" />
              <span>{item.label}</span>
            </NavLink>
          );
        })}
      </nav>

      {/* Telemetry Status Dots */}
      <div className="flex items-center space-x-3 text-xs">
        <div className="flex items-center space-x-1.5 px-2 py-1 bg-surface-cream rounded border border-border-subtle">
          <Globe2 className="w-3.5 h-3.5 text-text-taupe" />
          <span className="text-[11px] text-text-taupe">ASF</span>
          <span
            className={`w-2 h-2 rounded-full ${
              health?.earthdata_configured ? 'bg-success-sage' : 'bg-warning-ochre'
            }`}
            title={
              health?.earthdata_configured
                ? 'NASA Earthdata Authenticated'
                : 'Earthdata Token Missing (Browse Mode Active)'
            }
          />
        </div>

        <div className="flex items-center space-x-1.5 px-2 py-1 bg-surface-cream rounded border border-border-subtle">
          <Sparkles className="w-3.5 h-3.5 text-text-taupe" />
          <span className="text-[11px] text-text-taupe">Gemini</span>
          <span
            className={`w-2 h-2 rounded-full ${
              health?.gemini_configured ? 'bg-success-sage' : 'bg-warning-ochre'
            }`}
            title={
              health?.gemini_configured
                ? 'Gemini 2.5 Flash Online'
                : 'GEMINI_API_KEY Missing in .env'
            }
          />
        </div>
      </div>
    </header>
  );
};
