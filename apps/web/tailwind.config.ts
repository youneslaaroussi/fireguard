import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        command: "#091016",
        panel: "#101a22",
        line: "#24323d",
        fire: "#ff5a2f",
        amber: "#ffbe3d",
        shelter: "#48a7ff",
        zone: "#a878ff",
      },
    },
  },
  plugins: [require("@tailwindcss/forms")],
};

export default config;
