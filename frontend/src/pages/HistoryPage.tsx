import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Clock,
  Trash2,
  ExternalLink,
  Download,
  Search,
  Filter,
  FileSpreadsheet,
} from 'lucide-react';
import { getHistory, deleteHistoryItem, getHistoryDetail } from '../api/client';
import { HistoryItem, SeverityTier } from '../types';
import { Button } from '../components/Button';
import { EmptyState } from '../components/EmptyState';

export const HistoryPage: React.FC = () => {
  const navigate = useNavigate();

  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [searchTerm, setSearchTerm] = useState<string>('');
  const [filterTier, setFilterTier] = useState<string>('ALL');

  const loadHistory = async () => {
    setIsLoading(true);
    try {
      const data = await getHistory();
      setHistory(data);
    } catch {
      setHistory([]);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadHistory();
  }, []);

  const handleDelete = async (id: string) => {
    if (!window.confirm('Delete this analysis run and associated mask?')) return;
    try {
      await deleteHistoryItem(id);
      setHistory((prev) => prev.filter((item) => item.id !== id));
    } catch (err: any) {
      alert(`Delete failed: ${err.message}`);
    }
  };

  // Export full archive table to CSV
  const handleExportCSV = () => {
    if (history.length === 0) return;
    const headers = [
      'ID',
      'Source Type',
      'Threshold dB',
      'Impacted km2',
      'Mean dB Drop',
      'Severity Tier',
      'Has Briefing',
      'Created At UTC',
    ];
    const rows = history.map((h) => [
      h.id,
      h.source_type,
      h.threshold_db,
      h.impacted_km2,
      h.mean_db_drop,
      h.severity_tier,
      h.has_briefing ? 'YES' : 'NO',
      h.created_at,
    ]);

    const csvContent =
      'data:text/csv;charset=utf-8,' +
      [headers.join(','), ...rows.map((e) => e.join(','))].join('\n');
    const encodedUri = encodeURI(csvContent);
    const link = document.createElement('a');
    link.setAttribute('href', encodedUri);
    link.setAttribute('download', `nisar_pulse_archive_${new Date().toISOString().slice(0, 10)}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const filteredHistory = history.filter((item) => {
    const matchesSearch =
      item.id.toLowerCase().includes(searchTerm.toLowerCase()) ||
      item.source_type.toLowerCase().includes(searchTerm.toLowerCase());
    const matchesTier = filterTier === 'ALL' || item.severity_tier === filterTier;
    return matchesSearch && matchesTier;
  });

  const severityBadge = (tier: SeverityTier) => {
    switch (tier) {
      case 'CRITICAL':
        return 'bg-alert-terracotta text-canvas-dark font-bold';
      case 'ELEVATED':
        return 'bg-warning-ochre text-canvas-dark font-bold';
      case 'MODERATE':
        return 'bg-surface-recessed text-text-roast border border-border-sandstone';
      case 'NOMINAL':
      default:
        return 'bg-surface-recessed text-text-taupe border border-border-subtle';
    }
  };

  return (
    <div className="w-full h-[calc(100vh-52px)] overflow-y-auto bg-canvas-sand p-6">
      <div className="max-w-6xl mx-auto space-y-6">
        {/* Header */}
        <div className="flex flex-col md:flex-row items-start md:items-center justify-between border-b border-border-sandstone pb-4 gap-4">
          <div>
            <div className="flex items-center space-x-2 text-accent-espresso mb-1">
              <Clock className="w-5 h-5" />
              <h1 className="text-base font-bold uppercase tracking-wider text-text-roast">
                Analysis Archive & Audit Trail
              </h1>
            </div>
            <p className="text-xs text-text-taupe">
              Immutable historical record of all SAR surface change detection runs stored in SQLite.
            </p>
          </div>

          <div className="flex items-center space-x-2">
            <Button
              variant="secondary"
              size="sm"
              icon={<FileSpreadsheet className="w-3.5 h-3.5" />}
              onClick={handleExportCSV}
              disabled={history.length === 0}
            >
              Export Archive CSV
            </Button>
            <Button
              variant="primary"
              size="sm"
              onClick={loadHistory}
            >
              Refresh Table
            </Button>
          </div>
        </div>

        {/* Filter & Search Bar */}
        <div className="flex flex-col md:flex-row items-center justify-between gap-3 bg-surface-cream p-3 rounded-md border border-border-sandstone shadow-subtle">
          <div className="relative flex-1 w-full md:w-auto">
            <Search className="w-3.5 h-3.5 text-text-taupe absolute left-3 top-2.5" />
            <input
              type="text"
              placeholder="Search by analysis ID or source type..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="w-full pl-8 pr-3 py-1.5 text-xs rounded bg-surface-recessed border border-border-sandstone text-text-roast placeholder:text-text-taupe/60 focus:outline-none focus:border-accent-espresso"
            />
          </div>

          <div className="flex items-center space-x-2 w-full md:w-auto justify-end text-xs">
            <Filter className="w-3.5 h-3.5 text-text-taupe" />
            <span className="text-text-taupe font-semibold text-[11px] uppercase">Severity:</span>
            <select
              value={filterTier}
              onChange={(e) => setFilterTier(e.target.value)}
              className="text-xs px-2.5 py-1 rounded bg-surface-recessed border border-border-sandstone text-text-roast focus:outline-none focus:border-accent-espresso font-mono"
            >
              <option value="ALL">ALL TIERS</option>
              <option value="CRITICAL">CRITICAL</option>
              <option value="ELEVATED">ELEVATED</option>
              <option value="MODERATE">MODERATE</option>
              <option value="NOMINAL">NOMINAL</option>
            </select>
          </div>
        </div>

        {/* Audit Table */}
        <div className="bg-surface-cream border border-border-sandstone rounded-md shadow-subtle overflow-hidden">
          {isLoading ? (
            <div className="p-8 space-y-3">
              <div className="h-6 shimmer-sand rounded w-full" />
              <div className="h-6 shimmer-sand rounded w-full" />
              <div className="h-6 shimmer-sand rounded w-full" />
            </div>
          ) : filteredHistory.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="bg-surface-recessed border-b border-border-sandstone text-[11px] font-semibold uppercase text-text-taupe">
                  <tr>
                    <th className="py-2.5 px-3">Run ID</th>
                    <th className="py-2.5 px-3">Source</th>
                    <th className="py-2.5 px-3">Threshold</th>
                    <th className="py-2.5 px-3">Impacted Area</th>
                    <th className="py-2.5 px-3">Mean dB Drop</th>
                    <th className="py-2.5 px-3">Severity</th>
                    <th className="py-2.5 px-3">Briefing</th>
                    <th className="py-2.5 px-3">Timestamp (UTC)</th>
                    <th className="py-2.5 px-3 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border-subtle font-mono text-[11px]">
                  {filteredHistory.map((row) => (
                    <tr key={row.id} className="hover:bg-surface-recessed/50 transition-colors">
                      <td className="py-2.5 px-3 font-bold text-accent-espresso">
                        {row.id.slice(0, 8)}...
                      </td>
                      <td className="py-2.5 px-3 text-text-roast">{row.source_type}</td>
                      <td className="py-2.5 px-3 text-text-taupe">{row.threshold_db} dB</td>
                      <td className="py-2.5 px-3 font-semibold text-alert-terracotta">
                        {row.impacted_km2} km²
                      </td>
                      <td className="py-2.5 px-3 text-text-roast">{row.mean_db_drop} dB</td>
                      <td className="py-2.5 px-3">
                        <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${severityBadge(row.severity_tier)}`}>
                          {row.severity_tier}
                        </span>
                      </td>
                      <td className="py-2.5 px-3">
                        <span
                          className={`px-1.5 py-0.5 rounded text-[10px] ${
                            row.has_briefing
                              ? 'bg-success-sage/10 text-success-sage font-bold'
                              : 'text-text-taupe'
                          }`}
                        >
                          {row.has_briefing ? 'READY' : 'PENDING'}
                        </span>
                      </td>
                      <td className="py-2.5 px-3 text-text-taupe">
                        {new Date(row.created_at).toISOString().replace('T', ' ').slice(0, 19)}
                      </td>
                      <td className="py-2.5 px-3 text-right">
                        <div className="flex items-center justify-end space-x-1.5">
                          <button
                            title="Inspect Run on Map Workspace"
                            onClick={() => navigate('/')}
                            className="p-1 rounded text-accent-espresso hover:bg-surface-recessed"
                          >
                            <ExternalLink className="w-3.5 h-3.5" />
                          </button>
                          <button
                            title="Delete Record"
                            onClick={() => handleDelete(row.id)}
                            className="p-1 rounded text-alert-terracotta hover:bg-alert-terracotta-bg"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="p-8">
              <EmptyState
                icon={Clock}
                title="Archive Is Empty"
                description="No SAR change detection runs have been recorded yet. Launch an ASF query on / or upload local rasters on /upload to populate this database table."
              />
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
