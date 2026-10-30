import type { Config } from "tailwindcss";

// Clean Light Industrial — white/cream surfaces, near-black ink, mPower-orange
// accent. Minimal motion. Tokens are the single source of truth for brand color;
// swapping a client palette later is a one-file change.
const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        ink: "#1C1F26",
        "mpower-orange": "#F26522",
        canvas: "#F7F5F2",
        surface: "#FFFFFF",
        "ok-green": "#16A34A",
        "warn-amber": "#F59E0B",
        "err-red": "#DC2626",
      },
      fontFamily: {
        heading: ['"Space Grotesk"', "sans-serif"],
        body: ['"Inter"', "sans-serif"],
        mono: ['"Space Mono"', "monospace"],
      },
      borderRadius: {
        xl: "0.75rem",
        "2xl": "1.25rem",
      },
    },
  },
  plugins: [],
};
export default config;
