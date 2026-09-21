/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{vue,ts}'],
  theme: {
    extend: {
      // Semantic tokens only. Components never name a raw colour, so light/dark
      // stay in sync: the CSS variables in style.css carry the two palettes.
      colors: {
        bg: 'rgb(var(--c-bg) / <alpha-value>)',
        surface: 'rgb(var(--c-surface) / <alpha-value>)',
        elevated: 'rgb(var(--c-elevated) / <alpha-value>)',
        fg: 'rgb(var(--c-fg) / <alpha-value>)',
        subtle: 'rgb(var(--c-subtle) / <alpha-value>)',
        faint: 'rgb(var(--c-faint) / <alpha-value>)',
        border: 'rgb(var(--c-border) / <alpha-value>)',
        'border-strong': 'rgb(var(--c-border-strong) / <alpha-value>)',
        primary: {
          DEFAULT: 'rgb(var(--c-primary) / <alpha-value>)',
          fg: 'rgb(var(--c-primary-fg) / <alpha-value>)',
          // shadcn-vue spells this half `foreground`; `fg` above is the local
          // spelling of the same token. Both point at --c-primary-fg.
          foreground: 'rgb(var(--c-primary-fg) / <alpha-value>)',
          soft: 'rgb(var(--c-primary-soft) / <alpha-value>)',
        },
        'accent-strong': 'rgb(var(--c-accent) / <alpha-value>)',
        danger: {
          DEFAULT: 'rgb(var(--c-danger) / <alpha-value>)',
          soft: 'rgb(var(--c-danger-soft) / <alpha-value>)',
        },
        success: 'rgb(var(--c-success) / <alpha-value>)',

        // shadcn-vue's expected names, aliased onto the --c-* palette above so
        // generated components inherit the current colours and dark mode with no
        // token rename. `primary` above already supplies DEFAULT and `fg`; shadcn
        // spells the foreground half `foreground`, so both are provided.
        background: 'rgb(var(--c-bg) / <alpha-value>)',
        foreground: 'rgb(var(--c-fg) / <alpha-value>)',
        card: {
          DEFAULT: 'rgb(var(--c-surface) / <alpha-value>)',
          foreground: 'rgb(var(--c-fg) / <alpha-value>)',
        },
        popover: {
          DEFAULT: 'rgb(var(--c-elevated) / <alpha-value>)',
          foreground: 'rgb(var(--c-fg) / <alpha-value>)',
        },
        secondary: {
          DEFAULT: 'rgb(var(--c-primary-soft) / <alpha-value>)',
          foreground: 'rgb(var(--c-fg) / <alpha-value>)',
        },
        muted: {
          DEFAULT: 'rgb(var(--c-primary-soft) / <alpha-value>)',
          foreground: 'rgb(var(--c-subtle) / <alpha-value>)',
        },
        accent: {
          DEFAULT: 'rgb(var(--c-primary-soft) / <alpha-value>)',
          foreground: 'rgb(var(--c-fg) / <alpha-value>)',
        },
        destructive: {
          DEFAULT: 'rgb(var(--c-danger) / <alpha-value>)',
          foreground: 'rgb(var(--c-danger-fg) / <alpha-value>)',
        },
        input: 'rgb(var(--c-border) / <alpha-value>)',
        ring: 'rgb(var(--c-primary) / <alpha-value>)',
      },
      fontFamily: {
        sans: ['"DM Sans"', 'ui-sans-serif', 'system-ui', '-apple-system', 'Segoe UI', 'sans-serif'],
        display: ['"Space Grotesk"', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
      borderRadius: {
        bubble: '1.125rem',
      },
      boxShadow: {
        card: '0 1px 2px rgb(var(--c-shadow) / 0.04), 0 8px 24px -12px rgb(var(--c-shadow) / 0.12)',
        pop: '0 8px 32px -8px rgb(var(--c-shadow) / 0.18)',
        glow: '0 0 0 1px rgb(var(--c-primary) / 0.25), 0 8px 24px -8px rgb(var(--c-primary) / 0.45)',
      },
      keyframes: {
        'fade-up': {
          from: { opacity: '0', transform: 'translateY(6px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        'dot-pulse': {
          '0%, 60%, 100%': { opacity: '0.25', transform: 'translateY(0)' },
          '30%': { opacity: '1', transform: 'translateY(-3px)' },
        },
        'ring-pulse': {
          '0%': { transform: 'scale(0.9)', opacity: '0.7' },
          '70%': { transform: 'scale(1.9)', opacity: '0' },
          '100%': { transform: 'scale(1.9)', opacity: '0' },
        },
      },
      animation: {
        'fade-up': 'fade-up 220ms cubic-bezier(0.16, 1, 0.3, 1) both',
        'dot-pulse': 'dot-pulse 1.2s ease-in-out infinite',
        'ring-pulse': 'ring-pulse 2s cubic-bezier(0.16, 1, 0.3, 1) infinite',
      },
    },
  },
  plugins: [],
}
