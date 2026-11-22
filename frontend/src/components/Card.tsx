import React from 'react';

export interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
  title?: string;
  subtitle?: string;
  action?: React.ReactNode;
}

export const Card: React.FC<CardProps> = ({
  title,
  subtitle,
  action,
  children,
  className = '',
  ...props
}) => {
  return (
    <div
      className={`bg-surface-cream border border-border-sandstone rounded-md shadow-subtle p-3.5 transition-all duration-180 ease-mechanical ${className}`}
      {...props}
    >
      {(title || action) && (
        <div className="flex items-center justify-between mb-2.5 pb-2 border-b border-border-subtle">
          <div>
            {title && <h3 className="text-xs font-semibold uppercase tracking-wider text-text-roast">{title}</h3>}
            {subtitle && <p className="text-[11px] text-text-taupe">{subtitle}</p>}
          </div>
          {action && <div>{action}</div>}
        </div>
      )}
      {children}
    </div>
  );
};
