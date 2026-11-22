import React, { useState } from 'react';
import { Sparkles, CheckCircle2, Circle, AlertCircle, RefreshCw } from 'lucide-react';
import { AIBriefing, SeverityTier } from '../types';
import { Button } from './Button';

export interface AIBriefingCardProps {
  briefing?: AIBriefing | null;
  isLoading?: boolean;
  onGenerateBriefing?: (focus?: string) => void;
}

export const AIBriefingCard: React.FC<AIBriefingCardProps> = ({
  briefing,
  isLoading = false,
  onGenerateBriefing,
}) => {
  const [completedActions, setCompletedActions] = useState<Record<number, boolean>>({});
  const [showFocusInput, setShowFocusInput] = useState<boolean>(false);
  const [customFocus, setCustomFocus] = useState<string>('');

  const toggleAction = (idx: number) => {
    setCompletedActions((prev) => ({ ...prev, [idx]: !prev[idx] }));
  };

  const severityColor = (tier: SeverityTier) => {
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

  if (!briefing && !isLoading) {
    return (
      <div className="bg-surface-cream border border-border-sandstone rounded-md p-3.5 shadow-subtle transition-all duration-180">
        <div className="flex items-center space-x-2 mb-2 pb-2 border-b border-border-subtle">
          <Sparkles className="w-4 h-4 text-accent-espresso" />
          <h3 className="text-xs font-semibold uppercase tracking-wider text-text-roast">
            AI Tactical Field Briefing
          </h3>
        </div>
        <p className="text-xs text-text-taupe mb-3 leading-relaxed">
          Synthesize an actionable disaster response briefing from this SAR run using Google Gemini.
        </p>
        {showFocusInput ? (
          <div className="space-y-2 mb-3">
            <input
              type="text"
              placeholder="e.g. Focus on flood levee breach & road transport"
              className="w-full text-xs px-2.5 py-1.5 rounded bg-surface-recessed border border-border-sandstone text-text-roast placeholder:text-text-taupe/60 focus:outline-none focus:border-accent-espresso focus:ring-1 focus:ring-accent-espresso/40 transition-colors"
              value={customFocus}
              onChange={(e) => setCustomFocus(e.target.value)}
            />
            <div className="flex items-center space-x-2">
              <Button
                size="sm"
                variant="primary"
                onClick={() => onGenerateBriefing?.(customFocus)}
              >
                Synthesize Briefing
              </Button>
              <Button
                size="sm"
                variant="secondary"
                onClick={() => setShowFocusInput(false)}
              >
                Cancel
              </Button>
            </div>
          </div>
        ) : (
          <div className="flex items-center space-x-2">
            <Button
              size="sm"
              variant="primary"
              icon={<Sparkles className="w-3.5 h-3.5" />}
              onClick={() => onGenerateBriefing?.()}
            >
              Synthesize Field Briefing
            </Button>
            <Button
              size="sm"
              variant="secondary"
              onClick={() => setShowFocusInput(true)}
            >
              Custom Focus...
            </Button>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="bg-surface-cream border border-border-sandstone rounded-md p-3.5 shadow-subtle transition-all duration-180">
      {/* Header */}
      <div className="flex items-center justify-between mb-2.5 pb-2 border-b border-border-subtle">
        <div className="flex items-center space-x-2">
          <Sparkles className="w-4 h-4 text-accent-espresso" />
          <h3 className="text-xs font-semibold uppercase tracking-wider text-text-roast">
            AI Tactical Field Briefing
          </h3>
        </div>
        {briefing && (
          <span
            className={`text-[10px] font-mono px-2 py-0.5 rounded ${severityColor(
              briefing.risk_level
            )}`}
          >
            {briefing.risk_level}
          </span>
        )}
      </div>

      {isLoading ? (
        <div className="space-y-2.5 py-2">
          <div className="h-4 shimmer-sand rounded w-3/4" />
          <div className="h-12 shimmer-sand rounded w-full" />
          <div className="h-4 shimmer-sand rounded w-1/2" />
        </div>
      ) : briefing ? (
        <div className="space-y-3">
          {/* Metadata chips */}
          <div className="flex flex-wrap items-center gap-1.5 text-[11px] font-mono">
            <span className="bg-surface-recessed px-2 py-0.5 rounded border border-border-subtle text-text-taupe">
              {briefing.model_name}
            </span>
            <span className="bg-alert-terracotta-bg text-alert-terracotta px-2 py-0.5 rounded border border-alert-terracotta/30 font-semibold">
              {briefing.primary_driver}
            </span>
          </div>

          {/* Executive Summary */}
          <p className="text-xs text-text-roast leading-relaxed bg-surface-recessed/70 p-2.5 rounded border border-border-subtle">
            {briefing.summary_text}
          </p>

          {/* Tactical Checklist */}
          {briefing.recommended_actions && briefing.recommended_actions.length > 0 && (
            <div>
              <div className="text-[11px] font-semibold uppercase tracking-wider text-text-taupe mb-1.5">
                Tactical Response Checklist ({briefing.recommended_actions.length})
              </div>
              <div className="space-y-1.5">
                {briefing.recommended_actions.map((action, i) => {
                  const isDone = completedActions[i];
                  return (
                    <div
                      key={i}
                      onClick={() => toggleAction(i)}
                      className={`flex items-start space-x-2 p-1.5 rounded cursor-pointer transition-colors duration-150 text-xs ${
                        isDone
                          ? 'bg-surface-recessed/40 text-text-muted line-through'
                          : 'hover:bg-surface-recessed text-text-roast'
                      }`}
                    >
                      {isDone ? (
                        <CheckCircle2 className="w-4 h-4 text-success-sage shrink-0 mt-0.5" />
                      ) : (
                        <Circle className="w-4 h-4 text-border-sandstone shrink-0 mt-0.5" />
                      )}
                      <span className="leading-tight">{action}</span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Action Footer */}
          <div className="pt-2 border-t border-border-subtle flex items-center justify-between">
            <span className="text-[10px] text-text-taupe font-mono">
              Generated: {new Date(briefing.created_at).toLocaleTimeString()}
            </span>
            <Button
              size="sm"
              variant="secondary"
              icon={<RefreshCw className="w-3 h-3" />}
              onClick={() => onGenerateBriefing?.()}
            >
              Re-evaluate
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
};
