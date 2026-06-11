/** Maps a platform/tool key → public logo path + display label */
export interface LogoMeta {
  src: string;
  label: string;
  color: string;
}

export const LOGOS: Record<string, LogoMeta> = {
  elastic:     { src: "/logos/elastic.svg",     label: "Elastic",     color: "#00BFB3" },
  nasa:        { src: "/logos/nasa.svg",         label: "NASA",        color: "#E03C31" },
  googlemaps:  { src: "/logos/googlemaps.svg",   label: "Maps",        color: "#4285F4" },
  gemini:      { src: "/logos/gemini.svg",       label: "Gemini",      color: "#8E75B2" },
  bc:          { src: "/logos/bc.svg",           label: "BC Gov",      color: "#0070C0" },
  exa:         { src: "/logos/exa.svg",          label: "Exa",         color: "#f97316" },
};

/** Returns logo meta for a given tool name */
export function logoForTool(toolName: string): LogoMeta | null {
  if (
    toolName === "fireguard_search_zones" ||
    toolName === "fireguard_search_shelters" ||
    toolName === "fireguard_search_road_events" ||
    toolName === "fireguard_bcws_context" ||
    toolName === "fireguard_evaluate_route" ||
    toolName === "fireguard_stats"
  ) return LOGOS.elastic;

  if (toolName === "fireguard_search_events") return LOGOS.nasa;
  if (toolName === "fireguard_map_annotation") return LOGOS.googlemaps;
  if (toolName === "exa_search") return LOGOS.exa;

  return null;
}

export function logoForSource(source: string): LogoMeta | null {
  if (source.startsWith("VIIRS") || source.startsWith("MODIS")) return LOGOS.nasa;
  if (source === "bcws" || source === "BCWS") return LOGOS.bc;
  return null;
}
