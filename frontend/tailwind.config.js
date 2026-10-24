/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'system-ui', 'Segoe UI', 'sans-serif'],
        mono: ['JetBrains Mono', 'ui-monospace', 'Consolas', 'monospace'],
      },
      colors: {
        ink: { 950: '#0b1220', 900: '#111a2e', 800: '#1a2540', 700: '#26334f' },
        accent: { DEFAULT: '#4f46e5', soft: '#eef2ff', dark: '#3730a3' },
      },
    },
  },
  plugins: [],
}
