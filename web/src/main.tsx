import React from "react";
import { createRoot } from "react-dom/client";
import "@blueprintjs/core/lib/css/blueprint.css";
import "@blueprintjs/icons/lib/css/blueprint-icons.css";
import "@fontsource/source-sans-3/latin-400.css";
import "@fontsource/source-sans-3/latin-600.css";
import "@fontsource/source-sans-3/latin-700.css";
import "@fontsource/source-sans-3/latin-800.css";
import "@fontsource/source-sans-3/latin-900.css";
import "@fontsource/source-sans-3/latin-ext-400.css";
import "@fontsource/source-sans-3/latin-ext-600.css";
import "@fontsource/source-sans-3/latin-ext-700.css";
import "@fontsource/source-sans-3/latin-ext-800.css";
import "@fontsource/source-sans-3/latin-ext-900.css";
import "mapbox-gl/dist/mapbox-gl.css";
import "./styles.css";
import { App } from "./ui/App";

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
