import type { Config } from 'tailwindcss';

const config: Config = {
  content: ['./app/**/*.{ts,tsx}', './components/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        bg: '#0b0d12',
        panel: '#141820',
        border: '#1f242e',
        accent: '#5be49b',
        warn: '#f7b955',
        bad: '#ef5350',
      },
    },
  },
  plugins: [],
};

export default config;
