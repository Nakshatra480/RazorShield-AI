import type { Config } from "tailwindcss";

/**
 * RazorShield AI — light design system.
 *
 * Palette is deliberately restrained: one navy ink ramp for text, one blue for
 * brand/interaction, and three semantic risk hues. Everything else is white,
 * or a near-white surface. Borders do the structural work instead of shadows,
 * which keeps dense data tables legible at small sizes.
 */
const config: Config = {
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "system-ui", "-apple-system", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "SFMono-Regular", "monospace"],
      },
      colors: {
        // Structure
        canvas: "#F6F8FB",
        surface: "#FFFFFF",
        "surface-muted": "#F1F4F9",
        "surface-sunken": "#EDF1F7",
        line: "#E3E9F2",
        "line-strong": "#CBD5E6",

        // Text ramp (navy, not neutral grey — reads closer to fintech UI)
        ink: "#0B1B3F",
        "ink-2": "#3D4C6B",
        "ink-3": "#6B7A99",
        "ink-4": "#94A0B8",

        brand: {
          DEFAULT: "#2B6CF6",
          hover: "#1B54D4",
          press: "#1546B4",
          soft: "#EAF1FE",
          border: "#C3D8FD",
          ink: "#12388F",
        },

        risk: {
          safe: "#0F8A5F",
          "safe-soft": "#E7F6EF",
          "safe-border": "#B4E2CD",
          warn: "#B26A00",
          "warn-soft": "#FEF4E3",
          "warn-border": "#F2D9A8",
          danger: "#D0342C",
          "danger-soft": "#FDECEA",
          "danger-border": "#F5C2BD",
        },
      },
      borderRadius: {
        card: "12px",
      },
      boxShadow: {
        // Very low-contrast elevation — light UIs get muddy fast with heavy shadows
        card: "0 1px 2px rgba(11,27,63,0.04), 0 1px 3px rgba(11,27,63,0.06)",
        raised: "0 4px 12px rgba(11,27,63,0.08)",
        pop: "0 8px 28px rgba(11,27,63,0.12)",
        focus: "0 0 0 3px rgba(43,108,246,0.18)",
      },
      animation: {
        "dot-blink": "dotBlink 1.4s ease-in-out infinite",
        shimmer: "shimmer 1.6s linear infinite",
      },
      keyframes: {
        dotBlink: {
          "0%, 80%, 100%": { opacity: "0.35", transform: "scale(0.8)" },
          "40%": { opacity: "1", transform: "scale(1)" },
        },
        shimmer: {
          "0%": { backgroundPosition: "-400px 0" },
          "100%": { backgroundPosition: "400px 0" },
        },
      },
    },
  },
  plugins: [],
};

export default config;
