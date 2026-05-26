import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: "class",
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      colors: {
        border: "rgb(var(--border) / <alpha-value>)",
        muted: "rgb(var(--muted) / <alpha-value>)",
        card: "rgb(var(--card) / <alpha-value>)",
        fg: "rgb(var(--fg) / <alpha-value>)",
        accent: "rgb(var(--accent) / <alpha-value>)",
        bg: "rgb(var(--bg) / <alpha-value>)",
      },
    },
  },
  plugins: [],
};

export default config;
