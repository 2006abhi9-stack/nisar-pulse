/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        canvas: {
          sand: '#101820', // Default dark mission-control background
          dark: '#101820',
          base: '#0D141C',
        },
        surface: {
          cream: '#1B2935', // Secondary panels / cards
          panel: '#1B2935',
          recessed: '#233442', // Elevated surfaces / inset panels / chips
          elevated: '#233442',
          highlight: '#2C3E50',
        },
        border: {
          sandstone: '#2C3E50', // Tactical crisp border
          subtle: '#1E2D3B',   // Subtle divider
          panel: '#2C3E50',
          focus: '#36CFC9',
        },
        accent: {
          espresso: '#36CFC9', // Primary accent (cyan/teal mission control)
          cyan: '#36CFC9',
          umber: '#20B2AA',    // Accent hover / secondary
          teal: '#2DD4BF',
        },
        alert: {
          terracotta: '#D85B61', // Verified blocked / SAR potential impact
          'terracotta-bg': 'rgba(216, 91, 97, 0.15)',
        },
        warning: {
          ochre: '#D9A441',      // Nearby SAR change / warnings
          'ochre-bg': 'rgba(217, 164, 65, 0.15)',
        },
        success: {
          sage: '#4DB58A',       // Verified passable / operational nominal
          'sage-bg': 'rgba(77, 181, 138, 0.15)',
        },
        route: {
          blue: '#60A5FA',       // Candidate route blue
          'blue-bg': 'rgba(96, 165, 250, 0.15)',
        },
        restricted: {
          purple: '#A78BFA',     // Restricted road segments
          'purple-bg': 'rgba(167, 139, 250, 0.15)',
        },
        text: {
          roast: '#F1F5F9',      // Primary high-contrast mission text
          taupe: '#AAB7C4',      // Secondary telemetry & label text
          muted: '#64748B',      // Inactive / placeholder text
          primary: '#F1F5F9',
          secondary: '#AAB7C4',
        },
      },
      fontFamily: {
        sans: ['"Space Grotesk"', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'monospace'],
      },
      borderRadius: {
        DEFAULT: '6px',
        md: '6px',
        lg: '8px',
      },
      boxShadow: {
        panel: '0 4px 16px rgba(0, 0, 0, 0.35)',
        subtle: '0 1px 3px rgba(0, 0, 0, 0.25)',
        floating: '0 12px 32px rgba(0, 0, 0, 0.50)',
        glow: '0 0 12px rgba(54, 207, 201, 0.25)',
      },
      transitionTimingFunction: {
        mechanical: 'cubic-bezier(0.22, 1, 0.36, 1)',
      },
      transitionDuration: {
        fast: '150ms',
        normal: '200ms',
        slow: '300ms',
      },
    },
  },
  plugins: [],
};
