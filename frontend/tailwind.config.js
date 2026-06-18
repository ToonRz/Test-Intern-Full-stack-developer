/** @type {import('tailwindcss').Config} */
// Tailwind tokens mirror the CSS variables in src/styles/main.css so utility
// classes (e.g. `text-primary`, `bg-canvas`) resolve to the Design.md palette.
export default {
  content: ['./index.html', './src/**/*.{js,jsx,ts,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        canvas: 'var(--color-canvas)',
        'surface-soft': 'var(--color-surface-soft)',
        'surface-card': 'var(--color-surface-card)',
        'surface-cream-strong': 'var(--color-surface-cream-strong)',
        'surface-dark': 'var(--color-surface-dark)',
        'surface-dark-elevated': 'var(--color-surface-dark-elevated)',
        ink: 'var(--color-ink)',
        body: 'var(--color-body)',
        'body-strong': 'var(--color-body-strong)',
        muted: 'var(--color-muted)',
        'muted-soft': 'var(--color-muted-soft)',
        hairline: 'var(--color-hairline)',
        'hairline-soft': 'var(--color-hairline-soft)',
        primary: {
          DEFAULT: 'var(--color-primary)',
          active: 'var(--color-primary-active)',
          disabled: 'var(--color-primary-disabled)',
        },
        'accent-teal': 'var(--color-accent-teal)',
        'accent-amber': 'var(--color-accent-amber)',
        success: 'var(--color-success)',
        warning: 'var(--color-warning)',
        error: 'var(--color-error)',
        severity: {
          critical: 'var(--color-error)',
          high: 'var(--color-accent-amber)',
          medium: 'var(--color-warning)',
          low: 'var(--color-accent-teal)',
        },
      },
      fontFamily: {
        sans: ['Inter', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Roboto', 'sans-serif'],
        display: ['EB Garamond', 'Tiempos Headline', 'Copernicus', 'Garamond', 'Times New Roman', 'serif'],
        mono: ['JetBrains Mono', 'ui-monospace', 'monospace'],
      },
    },
  },
  plugins: [],
}
