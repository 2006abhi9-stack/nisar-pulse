import React from 'react';
import { Loader2 } from 'lucide-react';

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'alert' | 'hud' | 'ghost';
  size?: 'sm' | 'md' | 'lg' | 'icon';
  isLoading?: boolean;
  icon?: React.ReactNode;
}

export const Button: React.FC<ButtonProps> = ({
  children,
  variant = 'primary',
  size = 'md',
  isLoading = false,
  disabled,
  icon,
  className = '',
  ...props
}) => {
  const baseStyles =
    'inline-flex items-center justify-center font-medium transition-all duration-180 ease-mechanical select-none focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-espresso/40 disabled:cursor-not-allowed';

  const variantStyles = {
    primary:
      'bg-accent-espresso text-canvas-dark font-semibold border border-accent-espresso hover:bg-accent-umber hover:border-accent-umber active:scale-[0.98] shadow-sm disabled:bg-surface-recessed disabled:text-text-muted disabled:border-transparent',
    secondary:
      'bg-surface-recessed text-text-roast border border-border-sandstone hover:bg-border-sandstone hover:text-text-roast active:scale-[0.98] shadow-subtle disabled:bg-surface-cream disabled:text-text-muted disabled:border-border-subtle',
    alert:
      'bg-alert-terracotta-bg text-alert-terracotta border border-alert-terracotta hover:bg-[rgba(216,91,97,0.25)] active:scale-[0.98] disabled:opacity-40',
    hud:
      'bg-surface-cream/90 backdrop-blur text-text-roast border border-border-sandstone shadow-panel hover:bg-surface-recessed hover:text-accent-espresso active:scale-[0.96]',
    ghost:
      'bg-transparent text-text-taupe hover:text-text-roast hover:bg-surface-recessed active:scale-[0.98] disabled:text-text-muted',
  };

  const sizeStyles = {
    sm: 'h-7 px-2.5 text-xs rounded',
    md: 'h-9 px-3.5 text-[13px] rounded',
    lg: 'h-11 px-5 text-sm rounded',
    icon: 'w-8 h-8 p-0 rounded',
  };

  return (
    <button
      className={`${baseStyles} ${variantStyles[variant]} ${sizeStyles[size]} ${className}`}
      disabled={disabled || isLoading}
      {...props}
    >
      {isLoading ? (
        <Loader2 className="w-4 h-4 animate-spin text-current" />
      ) : (
        <>
          {icon && <span className={`${children ? 'mr-1.5' : ''}`}>{icon}</span>}
          {children}
        </>
      )}
    </button>
  );
};
