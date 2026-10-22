import type { Config } from 'tailwindcss'
import { TOKENS } from './src/theme/tokens'
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: { ...TOKENS },
      fontFamily: { hanzi: ['"Noto Serif SC"', 'serif'], ui: ['"Inter Variable"', 'system-ui', 'sans-serif'] },
    },
  },
  plugins: [],
} satisfies Config
