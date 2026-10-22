import type { Config } from 'tailwindcss'
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        bg: '#0b0e12', panel: '#111418', panel2: '#161b21', line: '#2a3139',
        fg: '#cfd6dd', fgdim: '#7c8793', fghi: '#f2f5f7',
        ref: '#8fb3d9', you: '#e0a33a', ok: '#4caf7d', warn: '#e0a33a', bad: '#d9534f', accent: '#4a86c8', sound: '#c678dd',
      },
      fontFamily: { hanzi: ['"Noto Sans SC"', 'sans-serif'], ui: ['"Inter Variable"', 'system-ui', 'sans-serif'] },
    },
  },
  plugins: [],
} satisfies Config
