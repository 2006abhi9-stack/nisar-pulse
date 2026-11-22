import React from 'react';
import { LucideIcon } from 'lucide-react';

export interface EmptyStateProps {
  icon: LucideIcon;
  title: string;
  description: string;
  action?: React.ReactNode;
}

export const EmptyState: React.FC<EmptyStateProps> = ({
  icon: Icon,
  title,
  description,
  action,
}) => {
  return (
    <div className="flex flex-col items-center justify-center text-center p-6 border border-dashed border-border-sandstone rounded-md bg-surface-cream/50 transition-colors duration-180">
      <div className="w-10 h-10 rounded-full bg-surface-recessed flex items-center justify-center text-accent-espresso mb-3 border border-border-subtle shadow-sm">
        <Icon className="w-5 h-5" />
      </div>
      <h4 className="text-xs font-semibold uppercase tracking-wider text-text-roast mb-1">
        {title}
      </h4>
      <p className="text-xs text-text-taupe max-w-xs leading-relaxed mb-4">
        {description}
      </p>
      {action && <div>{action}</div>}
    </div>
  );
};
