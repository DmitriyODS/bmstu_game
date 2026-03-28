/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./app/templates/**/*.html",
    "./app/static/js/**/*.js",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['ALS Sector', 'ui-sans-serif', 'system-ui', 'sans-serif'],
      },
    },
  },
  plugins: [require("daisyui")],
  daisyui: {
    themes: [
      {
        bmstu: {
          "primary": "#006CDC",
          "primary-content": "#ffffff",
          "secondary": "#8C2CFF",
          "secondary-content": "#ffffff",
          "accent": "#FF5B9A",
          "accent-content": "#ffffff",
          "neutral": "#374151",
          "neutral-content": "#ffffff",
          "base-100": "#ffffff",
          "base-200": "#f4f6f9",
          "base-300": "#e2e8f0",
          "base-content": "#1e293b",
          "info": "#0ea5e9",
          "info-content": "#ffffff",
          "success": "#22c55e",
          "success-content": "#ffffff",
          "warning": "#f59e0b",
          "warning-content": "#ffffff",
          "error": "#ef4444",
          "error-content": "#ffffff",
        },
      },
    ],
  },
}
