import type { Config } from 'tailwindcss';

const config: Config = {
  content: ['./app/**/*.{ts,tsx}', './components/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        bg: '#141414',
        surface: '#1E1E1E',
        'surface-2': '#282828',
        border: '#333333',
        primary: '#FFFFFF',
        secondary: '#98989D',
        tertiary: '#48484A',
        accent: '#30D158',
        strain: '#FF9F0A',
        recovery: '#30D158',
        sleep: '#5E5CE6',
        warn: '#FF9F0A',
        bad: '#FF453A',
      },
    },
  },
  plugins: [],
};

export default config;
