/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        radar: {
          bg: "#0b1120",
          panel: "#111a2e",
          card: "#16223b",
          border: "#253452",
          accent: "#38bdf8",
        },
      },
    },
  },
  plugins: [],
};
