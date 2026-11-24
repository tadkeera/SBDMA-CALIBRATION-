const config = {
  content: ['./src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        brand: {
          50: '#eef6f4',
          100: '#d6ebe7',
          200: '#aed8d0',
          300: '#7dbeb3',
          400: '#4d9e91',
          500: '#2f8375',
          600: '#21695e',
          700: '#1b544c',
          800: '#17433e',
          900: '#123632',
        },
        ink: {
          50: '#f6f7f9',
          100: '#eceef2',
          200: '#d6dae2',
          300: '#b3bac7',
          400: '#8892a4',
          500: '#697488',
          600: '#545d6e',
          700: '#454c59',
          800: '#31373f',
          900: '#1d2127',
        },
      },
      fontFamily: {
        sans: ['system-ui', 'Segoe UI', 'Tahoma', 'Arial', 'sans-serif'],
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
      boxShadow: {
        card: '0 1px 2px rgba(16,24,40,.06), 0 1px 3px rgba(16,24,40,.10)',
        pop: '0 12px 32px rgba(16,24,40,.14)',
      },
    },
  },
  plugins: [],
};
module.exports = config;
