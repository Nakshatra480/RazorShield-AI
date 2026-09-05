import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: ["class"],
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "Fira Code", "monospace"],
      },
      colors: {
        background: "#090D16",
        surface: "#111827",
        "surface-2": "#1F2937",
        border: "#374151",
        "border-subtle": "#1F2937",
        brand: {
          blue: "#3B82F6",
          indigo: "#6366F1",
          "blue-dim": "#1D4ED8",
        },
        risk: {
          safe: "#10B981",
          "safe-dim": "#064E3B",
          warning: "#F59E0B",
          "warning-dim": "#78350F",
          danger: "#EF4444",
          "danger-dim": "#7F1D1D",
        },
        slate: {
          750: "#2D3748",
          850: "#1A202C",
          950: "#090D16",
        },
      },
      backgroundImage: {
        "gradient-radial": "radial-gradient(var(--tw-gradient-stops))",
        "scanner-grid":
          "linear-gradient(rgba(59,130,246,0.03) 1px, transparent 1px), linear-gradient(90deg, rgba(59,130,246,0.03) 1px, transparent 1px)",
      },
      backgroundSize: {
        grid: "32px 32px",
      },
      animation: {
        "pulse-slow": "pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite",
        "scan-sweep": "scanSweep 2s ease-in-out infinite",
        "dot-blink": "dotBlink 1.4s ease-in-out infinite",
        "glow-pulse": "glowPulse 2s ease-in-out infinite",
        float: "float 6s ease-in-out infinite",
      },
      keyframes: {
        scanSweep: {
          "0%": { transform: "translateX(-100%)", opacity: "0" },
          "50%": { opacity: "1" },
          "100%": { transform: "translateX(100%)", opacity: "0" },
        },
        dotBlink: {
          "0%, 80%, 100%": { opacity: "0.3", transform: "scale(0.8)" },
          "40%": { opacity: "1", transform: "scale(1)" },
        },
        glowPulse: {
          "0%, 100%": { boxShadow: "0 0 0 0 rgba(59,130,246,0)" },
          "50%": { boxShadow: "0 0 0 4px rgba(59,130,246,0.15)" },
        },
        float: {
          "0%, 100%": { transform: "translateY(0px)" },
          "50%": { transform: "translateY(-6px)" },
        },
      },
      boxShadow: {
        "brand-sm": "0 0 12px rgba(59,130,246,0.15)",
        "brand-md": "0 0 24px rgba(59,130,246,0.2)",
        "surface-sm": "0 1px 3px rgba(0,0,0,0.5), 0 1px 2px rgba(0,0,0,0.4)",
        "surface-md": "0 4px 16px rgba(0,0,0,0.5)",
      },
    },
  },
  plugins: [],
};

export default config;
