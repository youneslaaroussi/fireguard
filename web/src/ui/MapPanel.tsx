import { useEffect, useMemo, useRef, useState } from "react";
import { NonIdealState } from "@blueprintjs/core";
import mapboxgl, { type GeoJSONSource, type Map } from "mapbox-gl";
import type { BcwsContext, FireEvent, ThreatPayload } from "../types";
import type { MapAnnotation, MapAnnotationMarker } from "../intelligence/types";
import { LOGOS } from "../intelligence/logos";

// ── Icon SVGs (white on transparent → SDF-tintable at runtime) ──────────────

const ICON_FLAME = `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="30" viewBox="0 0 24 30">
  <path d="M12 1C10.4 6.5 7 10 7 16a5 5 0 0 0 10 0c0-3.2-1.6-5.6-2.6-7.2-.45 2.4-1.5 3.8-2 4.4C12.2 10.8 11.7 6.2 12 1z" fill="white"/>
</svg>`;

const ICON_SHELTER = `<svg xmlns="http://www.w3.org/2000/svg" width="26" height="26" viewBox="0 0 26 26">
  <path d="M13 2L1 12h3.5v12h6v-6h5v6h6V12H25L13 2z" fill="white"/>
</svg>`;

const ICON_WARNING = `<svg xmlns="http://www.w3.org/2000/svg" width="26" height="24" viewBox="0 0 26 24">
  <path d="M13 2L1 23h24L13 2z" fill="white"/>
</svg>`;

const ICON_SHIELD = `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="28" viewBox="0 0 24 28">
  <path d="M12 1L1 5.5v10c0 6 5 10.5 11 12 6-1.5 11-6 11-12v-10L12 1z" fill="white"/>
</svg>`;

async function loadMapIcons(m: Map): Promise<void> {
  await Promise.all([
    loadSvgIcon(m, "icon-flame",   ICON_FLAME,   24, 30),
    loadSvgIcon(m, "icon-shelter", ICON_SHELTER, 26, 26),
    loadSvgIcon(m, "icon-warning", ICON_WARNING, 26, 24),
    loadSvgIcon(m, "icon-shield",  ICON_SHIELD,  24, 28),
  ]);
}

function loadSvgIcon(m: Map, id: string, svg: string, w: number, h: number): Promise<void> {
  return new Promise((resolve, reject) => {
    const img = new Image(w, h);
    const blob = new Blob([svg], { type: "image/svg+xml" });
    const url = URL.createObjectURL(blob);
    img.onload = () => {
      URL.revokeObjectURL(url);
      if (!m.hasImage(id)) m.addImage(id, img, { sdf: true });
      resolve();
    };
    img.onerror = reject;
    img.src = url;
  });
}

// ── Annotation marker SVGs ───────────────────────────────────────────────────

const ANN_ICON_HOTSPOT = `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="20" viewBox="0 0 16 20">
  <path d="M8 0C7 4 4 6.5 4 10.5a4 4 0 0 0 8 0c0-2.2-1.3-4-2.2-5.2-.45 1.8-1.2 2.8-1.8 3.2C7.8 7 7.4 4 8 0z" fill="white"/>
</svg>`;

const ANN_ICON_SHELTER = `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16">
  <path d="M8 1L1 7h2v8h4v-4h2v4h4V7h2L8 1z" fill="white"/>
</svg>`;

const ANN_ICON_ZONE = `<svg xmlns="http://www.w3.org/2000/svg" width="14" height="18" viewBox="0 0 14 18">
  <path d="M7 0C4.2 0 2 2.2 2 5c0 4.4 5 13 5 13s5-8.6 5-13c0-2.8-2.2-5-5-5zm0 7a2 2 0 1 1 0-4 2 2 0 0 1 0 4z" fill="white"/>
</svg>`;

const ANN_ICON_BLOCKAGE = `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="14" viewBox="0 0 16 14">
  <path d="M8 1L1 13h14L8 1z" fill="white"/>
</svg>`;

const ANN_ICON_ALTERNATE = `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16">
  <path d="M8 1a7 7 0 1 0 0 14A7 7 0 0 0 8 1zm-1 10L3.5 7.5l1.4-1.4L7 8.6l4.1-4.1 1.4 1.4L7 11z" fill="white"/>
</svg>`;

const ANN_MARKER_ICONS: Record<string, string> = {
  hotspot:       ANN_ICON_HOTSPOT,
  shelter_open:  ANN_ICON_SHELTER,
  shelter_closed: ANN_ICON_SHELTER,
  zone:          ANN_ICON_ZONE,
  blockage:      ANN_ICON_BLOCKAGE,
  alternate:     ANN_ICON_ALTERNATE,
};

const ANN_MARKER_COLORS: Record<string, string> = {
  hotspot:        "#ff4422",
  shelter_open:   "#10b981",
  shelter_closed: "#64748b",
  zone:           "#8b5cf6",
  blockage:       "#ef4444",
  alternate:      "#f97316",
};

const ANN_ROUTE_COLORS: Record<string, string> = {
  safe:      "#10b981",
  blocked:   "#ef4444",
  alternate: "#f97316",
};

const FADE_LAYERS: Array<[string, string]> = [
  ["firms-events-heat",      "heatmap-opacity"],
  ["firms-events-points",    "circle-opacity"],
  ["firms-events-symbols",   "icon-opacity"],
  ["bcws-incidents",         "icon-opacity"],
  ["bcws-perimeters-fill",   "fill-opacity"],
  ["bcws-perimeters-outline","line-opacity"],
  ["bcws-perimeters-labels", "text-opacity"],
  ["wind-vectors",           "line-opacity"],
  ["wind-vector-heads",      "circle-opacity"],
  ["snapshot-wind-vectors",  "line-opacity"],
  ["snapshot-wind-vector-heads", "circle-opacity"],
];

type Props = {
  token: string;
  googleMapsKey?: string;
  events: FireEvent[];
  context: BcwsContext;
  lat: number;
  lon: number;
  radiusKm: number;
  annotation?: MapAnnotation | null;
  threat?: ThreatPayload | null;
  simDate?: string | null;
  annotationActive?: boolean;
  busy?: boolean;
  onAreaChange: (lat: number, lon: number, radiusKm: number) => void;
};

export function MapPanel({ token, googleMapsKey = "", events, context, lat, lon, radiusKm, annotation = null, threat = null, simDate = null, annotationActive = false, busy = false, onAreaChange }: Props) {
  const container = useRef<HTMLDivElement | null>(null);
  const map = useRef<Map | null>(null);
  const [loaded, setLoaded] = useState(false);
  const centerMarker = useRef<mapboxgl.Marker | null>(null);
  const edgeMarker = useRef<mapboxgl.Marker | null>(null);
  const annMarkers = useRef<mapboxgl.Marker[]>([]);
  const annPopups = useRef<mapboxgl.Popup[]>([]);
  const areaRef = useRef({ lat, lon, radiusKm });
  const isDragging = useRef(false);
  const onAreaChangeRef = useRef(onAreaChange);
  const autoFitSignature = useRef("");
  const [enhancing, setEnhancing] = useState(false);
  const enhanceThreatRef = useRef<ThreatPayload | null>(null);
  const [hotspotPx, setHotspotPx] = useState<{ x: number; y: number } | null>(null);

  const data = useMemo(() => toFeatureCollection(events), [events]);
  const incidentData = useMemo(() => toIncidentCollection(context), [context]);
  const perimeterData = useMemo(() => toPerimeterCollection(context), [context]);
  const evacuationZoneData = useMemo(() => toEvacuationZoneCollection(context), [context]);
  const evacuationRecordData = useMemo(() => toEvacuationRecordCollection(context), [context]);
  const essData = useMemo(() => toEssCollection(context), [context]);
  const roadData = useMemo(() => toRoadEventCollection(context), [context]);
  const windLines = useMemo(() => toWindLineCollection(events), [events]);
  const windHeads = useMemo(() => toWindHeadCollection(events), [events]);
  const snapshotWindLines = useMemo(() => toSnapshotWindLineCollection(context), [context]);
  const snapshotWindHeads = useMemo(() => toSnapshotWindHeadCollection(context), [context]);

  useEffect(() => { areaRef.current = { lat, lon, radiusKm }; }, [lat, lon, radiusKm]);
  useEffect(() => { onAreaChangeRef.current = onAreaChange; }, [onAreaChange]);

  useEffect(() => {
    if (!map.current || !loaded) return;
    const m = map.current;
    for (const [layerId, prop] of FADE_LAYERS) {
      if (!m.getLayer(layerId)) continue;
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      m.setPaintProperty(layerId, prop as any, annotationActive ? 0.08 : undefined);
    }
  }, [annotationActive, loaded]);

  useEffect(() => {
    if (!token || !container.current || map.current) return;
    mapboxgl.accessToken = token;
    map.current = new mapboxgl.Map({
      container: container.current,
      style: "mapbox://styles/mapbox/satellite-streets-v12",
      center: [areaRef.current.lon, areaRef.current.lat],
      zoom: 5.5,
      attributionControl: true
    });
    map.current.addControl(new mapboxgl.NavigationControl({ showCompass: false }), "top-right");
    map.current.on("load", () => {
      if (!map.current) return;
      void loadMapIcons(map.current).then(() => setupLayers(map.current!));
    });
    function setupLayers(m: Map) {

      // Area circle — render below fire data
      m.addSource("area-circle", {
        type: "geojson",
        data: makeCircleGeoJSON(areaRef.current.lat, areaRef.current.lon, areaRef.current.radiusKm)
      });
      m.addLayer({ id: "area-circle-fill", type: "fill", source: "area-circle", paint: { "fill-color": "#4aaeff", "fill-opacity": 0.08 } });
      m.addLayer({ id: "area-circle-outline", type: "line", source: "area-circle", paint: { "line-color": "#4aaeff", "line-width": 4, "line-opacity": 1, "line-dasharray": [6, 3] } });

      m.addSource("firms-events",           { type: "geojson", data });
      m.addSource("bcws-perimeters",        { type: "geojson", data: perimeterData });
      m.addSource("bcws-incidents",         { type: "geojson", data: incidentData });
      m.addSource("evacuation-zones",       { type: "geojson", data: evacuationZoneData });
      m.addSource("evacuation-records",     { type: "geojson", data: evacuationRecordData });
      m.addSource("ess-facilities",         { type: "geojson", data: essData });
      m.addSource("road-events",            { type: "geojson", data: roadData });
      m.addSource("wind-vectors",           { type: "geojson", data: windLines });
      m.addSource("wind-vector-heads",      { type: "geojson", data: windHeads });
      m.addSource("snapshot-wind-vectors",  { type: "geojson", data: snapshotWindLines });
      m.addSource("snapshot-wind-vector-heads", { type: "geojson", data: snapshotWindHeads });

      // Polygon layers first (bottom of stack)
      m.addLayer({ id: "evacuation-zones-fill",    type: "fill", source: "evacuation-zones",  paint: { "fill-color": "#d982ff", "fill-opacity": 0.14 } });
      m.addLayer({ id: "evacuation-zones-outline",  type: "line", source: "evacuation-zones",  paint: { "line-color": "#e7a8ff", "line-width": 1.8, "line-opacity": 0.9 } });
      m.addLayer({ id: "bcws-perimeters-fill",     type: "fill", source: "bcws-perimeters",   paint: { "fill-color": "#ffb366", "fill-opacity": 0.18 } });
      m.addLayer({ id: "bcws-perimeters-outline",   type: "line", source: "bcws-perimeters",   paint: { "line-color": "#ffd27f", "line-width": 2,   "line-opacity": 0.9 } });
      m.addLayer({
        id: "bcws-perimeters-labels",
        type: "symbol",
        source: "bcws-perimeters",
        minzoom: 6,
        layout: {
          "text-field": ["coalesce", ["get", "number"], ""],
          "text-font": ["DIN Pro Bold", "Arial Unicode MS Bold"],
          "text-size": 11,
          "text-anchor": "center",
          "text-allow-overlap": false,
          "symbol-placement": "point",
        },
        paint: {
          "text-color": "#ffd27f",
          "text-halo-color": "rgba(0,0,0,0.75)",
          "text-halo-width": 1.5,
        },
      });
      m.addLayer({
        id: "evacuation-zones-labels",
        type: "symbol",
        source: "evacuation-zones",
        minzoom: 6,
        layout: {
          "text-field": ["coalesce", ["get", "name"], ""],
          "text-font": ["DIN Pro Bold", "Arial Unicode MS Bold"],
          "text-size": 11,
          "text-anchor": "center",
          "text-max-width": 10,
          "text-allow-overlap": false,
          "symbol-placement": "point",
        },
        paint: {
          "text-color": "#e7a8ff",
          "text-halo-color": "rgba(0,0,0,0.8)",
          "text-halo-width": 1.5,
        },
      });

      // FIRMS heatmap (overview) — wider, brighter, deeper color stops
      m.addLayer({
        id: "firms-events-heat",
        type: "heatmap",
        source: "firms-events",
        maxzoom: 11,
        paint: {
          "heatmap-weight":     ["interpolate", ["linear"], ["coalesce", ["get", "frp"], 0], 0, 0.15, 25, 0.6, 80, 1],
          "heatmap-intensity":  ["interpolate", ["linear"], ["zoom"], 4, 1, 9, 2.2],
          "heatmap-radius":     ["interpolate", ["linear"], ["zoom"], 4, 14, 9, 38],
          "heatmap-color":      [
            "interpolate", ["linear"], ["heatmap-density"],
            0,    "rgba(20, 4, 0, 0)",
            0.2,  "rgba(120, 30, 40, 0.55)",
            0.4,  "rgba(220, 70, 30, 0.7)",
            0.6,  "rgba(255, 130, 30, 0.85)",
            0.8,  "rgba(255, 200, 90, 0.95)",
            1,    "rgba(255, 255, 220, 1)"
          ],
          "heatmap-opacity":    ["interpolate", ["linear"], ["zoom"], 5, 0.85, 10, 0.55, 11, 0]
        }
      });

      // FIRMS circles at mid zoom
      m.addLayer({
        id: "firms-events-points",
        type: "circle",
        source: "firms-events",
        minzoom: 7,
        maxzoom: 10,
        paint: {
          "circle-radius":        ["interpolate", ["linear"], ["coalesce", ["get", "frp"], 0], 0, 3, 50, 8],
          "circle-color":         "#f15b43",
          "circle-stroke-width":  0,
          "circle-opacity":       0.85
        }
      });

      // FIRMS flame icons at high zoom
      m.addLayer({
        id: "firms-events-symbols",
        type: "symbol",
        source: "firms-events",
        minzoom: 10,
        layout: {
          "icon-image":           "icon-flame",
          "icon-size":            ["interpolate", ["linear"], ["coalesce", ["get", "frp"], 0], 0, 0.55, 100, 1.2],
          "icon-allow-overlap":   true,
          "icon-anchor":          "bottom"
        },
        paint: {
          "icon-color": ["interpolate", ["linear"], ["coalesce", ["get", "frp"], 0],
            0, "#f4a060", 30, "#f15b43", 100, "#ff2200"
          ],
          "icon-halo-color":  "#1a0500",
          "icon-halo-width":  1.5
        }
      });

      // BCWS incidents — flame icon, colored by fire status
      m.addLayer({
        id: "bcws-incidents",
        type: "symbol",
        source: "bcws-incidents",
        layout: {
          "icon-image":         "icon-flame",
          "icon-size":          1.1,
          "icon-allow-overlap": true,
          "icon-anchor":        "bottom"
        },
        paint: {
          "icon-color": ["match", ["get", "status"],
            "Out of Control", "#e5484d",
            "Being Held",     "#f2b84b",
            "Under Control",  "#3acc7a",
            "Out",            "#6a7a8a",
            "#ff8844"
          ],
          "icon-halo-color": "#080808",
          "icon-halo-width": 1.5
        }
      });

      // Evacuation records — shield icon, colored by alert level
      m.addLayer({
        id: "evacuation-records",
        type: "symbol",
        source: "evacuation-records",
        layout: {
          "icon-image":         "icon-shield",
          "icon-size":          0.9,
          "icon-allow-overlap": true,
          "icon-anchor":        "bottom"
        },
        paint: {
          "icon-color": ["match", ["get", "status"],
            "Order", "#ff5555",
            "Alert", "#ffca5c",
            "#d982ff"
          ],
          "icon-halo-color": "#0a0005",
          "icon-halo-width": 1.5
        }
      });

      // ESS emergency shelters — house icon
      m.addLayer({
        id: "ess-facilities",
        type: "symbol",
        source: "ess-facilities",
        layout: {
          "icon-image":         "icon-shelter",
          "icon-size":          0.95,
          "icon-allow-overlap": true,
          "icon-anchor":        "bottom"
        },
        paint: {
          "icon-color":       "#43d9ad",
          "icon-halo-color":  "#011a10",
          "icon-halo-width":  1.5
        }
      });

      // Road events — warning triangle icon
      m.addLayer({
        id: "road-events",
        type: "symbol",
        source: "road-events",
        layout: {
          "icon-image":         "icon-warning",
          "icon-size":          0.9,
          "icon-allow-overlap": true,
          "icon-anchor":        "center"
        },
        paint: {
          "icon-color":       "#f6f08d",
          "icon-halo-color":  "#141400",
          "icon-halo-width":  1
        }
      });

      // Wind vectors — fade as zoom increases so they read as context, not clutter
      m.addLayer({ id: "wind-vectors", type: "line", source: "wind-vectors", paint: {
        "line-color": "#6bbcff",
        "line-width": 1.5,
        "line-opacity": ["interpolate", ["linear"], ["zoom"], 5, 0.5, 8, 0.28, 11, 0.1]
      } });
      m.addLayer({ id: "wind-vector-heads", type: "circle", source: "wind-vector-heads", paint: {
        "circle-radius": 2.5,
        "circle-color": "#9fd4ff",
        "circle-opacity": ["interpolate", ["linear"], ["zoom"], 5, 0.6, 8, 0.35, 11, 0.12]
      } });
      m.addLayer({ id: "snapshot-wind-vectors",   type: "line",   source: "snapshot-wind-vectors",   paint: { "line-color": "#34e7ff", "line-width": 2.5, "line-opacity": 0.9, "line-dasharray": [2, 2] } });
      m.addLayer({ id: "snapshot-wind-vector-heads", type: "circle", source: "snapshot-wind-vector-heads", paint: { "circle-radius": 4, "circle-color": "#34e7ff", "circle-opacity": 0.95 } });

      // Threat score labels — shown at each scored detection above zoom 6
      m.addSource("threat-scores", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      m.addLayer({
        id: "threat-score-labels",
        type: "symbol",
        source: "threat-scores",
        minzoom: 5,
        layout: {
          "text-field": ["get", "label"],
          "text-font": ["DIN Pro Bold", "Arial Unicode MS Bold"],
          "text-size": ["interpolate", ["linear"], ["zoom"], 5, 9, 8, 12, 11, 14],
          "text-allow-overlap": false,
          "text-ignore-placement": false,
          "text-offset": [0, -1.2],
          "text-anchor": "bottom",
        },
        paint: {
          "text-color": ["get", "color"],
          "text-halo-color": "rgba(0,0,0,0.85)",
          "text-halo-width": 1.5,
          "text-opacity": ["interpolate", ["linear"], ["zoom"], 5, 0.7, 9, 1],
        },
      });
      m.addLayer({
        id: "threat-score-dots",
        type: "circle",
        source: "threat-scores",
        minzoom: 5,
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 5, 3, 9, 5],
          "circle-color": ["get", "color"],
          "circle-opacity": 0.85,
          "circle-stroke-width": 1,
          "circle-stroke-color": "rgba(0,0,0,0.5)",
        },
      });

      // Threat persistent pulse halo (large fading circle)
      m.addSource("threat-pulse", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      m.addLayer({
        id: "threat-pulse-outer",
        type: "circle",
        source: "threat-pulse",
        paint: {
          "circle-radius": ["get", "outerRadius"],
          "circle-color": "#ff2a1a",
          "circle-opacity": 0.06,
          "circle-stroke-color": "#ff2a1a",
          "circle-stroke-width": 1.5,
          "circle-stroke-opacity": 0.45,
        },
      });
      m.addLayer({
        id: "threat-pulse-mid",
        type: "circle",
        source: "threat-pulse",
        paint: {
          "circle-radius": ["get", "midRadius"],
          "circle-color": "#ff2a1a",
          "circle-opacity": 0.1,
          "circle-stroke-color": "#ff4a2a",
          "circle-stroke-width": 1,
          "circle-stroke-opacity": 0.6,
        },
      });
      m.addLayer({
        id: "threat-pulse-core",
        type: "circle",
        source: "threat-pulse",
        paint: {
          "circle-radius": ["get", "coreRadius"],
          "circle-color": "#ffd54a",
          "circle-opacity": 0.85,
          "circle-stroke-color": "#ff2a1a",
          "circle-stroke-width": 2,
          "circle-stroke-opacity": 0.95,
        },
      });

      // Fire spread cone — wedge projecting downwind toward zone
      m.addSource("fire-cone", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      m.addLayer({
        id: "fire-cone-fill",
        type: "fill",
        source: "fire-cone",
        paint: {
          "fill-color": "#ff5530",
          "fill-opacity": ["interpolate", ["linear"], ["get", "intensity"], 0, 0.05, 1, 0.32],
        },
      });
      m.addLayer({
        id: "fire-cone-outline",
        type: "line",
        source: "fire-cone",
        paint: {
          "line-color": "#ff7a3a",
          "line-width": 1.4,
          "line-opacity": 0.55,
          "line-dasharray": [3, 2],
        },
      });

      setLoaded(true);
    }
    return () => {
      centerMarker.current?.remove();
      centerMarker.current = null;
      edgeMarker.current?.remove();
      edgeMarker.current = null;
      map.current?.remove();
      map.current = null;
      setLoaded(false);
    };
  }, [token]);

  // Create draggable gizmo markers once the map is ready
  useEffect(() => {
    if (!map.current || !loaded) return;

    const { lat: iLat, lon: iLon, radiusKm: iR } = areaRef.current;

    // Center — targeting reticle
    const centerEl = document.createElement("div");
    centerEl.className = "mapMarkerCenter";
    centerEl.innerHTML =
      '<div class="markerRing"></div>' +
      '<div class="markerCross markerCrossH"></div>' +
      '<div class="markerCross markerCrossV"></div>' +
      '<div class="markerDot"></div>';
    centerMarker.current = new mapboxgl.Marker({ element: centerEl, draggable: true, anchor: "center" })
      .setLngLat([iLon, iLat])
      .addTo(map.current!);

    // Edge — diamond handle at due-east of circle
    const edgeEl = document.createElement("div");
    edgeEl.className = "mapMarkerEdge";
    edgeMarker.current = new mapboxgl.Marker({ element: edgeEl, draggable: true, anchor: "center" })
      .setLngLat(edgeLngLat(iLat, iLon, iR))
      .addTo(map.current!);

    centerMarker.current.on("drag", () => {
      isDragging.current = true;
      const { lat: cLat, lng: cLon } = centerMarker.current!.getLngLat();
      const r = areaRef.current.radiusKm;
      edgeMarker.current?.setLngLat(edgeLngLat(cLat, cLon, r));
      setCircleSource(map.current, cLat, cLon, r);
    });

    centerMarker.current.on("dragend", () => {
      const { lat: cLat, lng: cLon } = centerMarker.current!.getLngLat();
      onAreaChangeRef.current(cLat, cLon, areaRef.current.radiusKm);
      isDragging.current = false;
    });

    edgeMarker.current.on("drag", () => {
      isDragging.current = true;
      const { lat: eLat, lng: eLon } = edgeMarker.current!.getLngLat();
      const { lat: cLat, lon: cLon } = areaRef.current;
      setCircleSource(map.current, cLat, cLon, haversineKm(cLat, cLon, eLat, eLon));
    });

    edgeMarker.current.on("dragend", () => {
      const { lat: eLat, lng: eLon } = edgeMarker.current!.getLngLat();
      const { lat: cLat, lon: cLon } = areaRef.current;
      onAreaChangeRef.current(cLat, cLon, haversineKm(cLat, cLon, eLat, eLon));
      isDragging.current = false;
    });

    return () => {
      centerMarker.current?.remove();
      centerMarker.current = null;
      edgeMarker.current?.remove();
      edgeMarker.current = null;
    };
  }, [loaded]);

  // Sync markers + circle when lat/lon/radius props change (not during drag)
  useEffect(() => {
    if (isDragging.current || !loaded) return;
    centerMarker.current?.setLngLat([lon, lat]);
    edgeMarker.current?.setLngLat(edgeLngLat(lat, lon, radiusKm));
    setCircleSource(map.current, lat, lon, radiusKm);
  }, [lat, lon, radiusKm, loaded]);

  // Update fire / weather data sources
  useEffect(() => {
    const instance = map.current;
    if (!instance || !loaded || !instance.isStyleLoaded()) return;
    (instance.getSource("firms-events") as GeoJSONSource | undefined)?.setData(data);
    (instance.getSource("bcws-incidents") as GeoJSONSource | undefined)?.setData(incidentData);
    (instance.getSource("bcws-perimeters") as GeoJSONSource | undefined)?.setData(perimeterData);
    (instance.getSource("evacuation-zones") as GeoJSONSource | undefined)?.setData(evacuationZoneData);
    (instance.getSource("evacuation-records") as GeoJSONSource | undefined)?.setData(evacuationRecordData);
    (instance.getSource("ess-facilities") as GeoJSONSource | undefined)?.setData(essData);
    (instance.getSource("road-events") as GeoJSONSource | undefined)?.setData(roadData);
    (instance.getSource("wind-vectors") as GeoJSONSource | undefined)?.setData(windLines);
    (instance.getSource("wind-vector-heads") as GeoJSONSource | undefined)?.setData(windHeads);
    (instance.getSource("snapshot-wind-vectors") as GeoJSONSource | undefined)?.setData(snapshotWindLines);
    (instance.getSource("snapshot-wind-vector-heads") as GeoJSONSource | undefined)?.setData(snapshotWindHeads);
  }, [context, data, essData, evacuationRecordData, evacuationZoneData, incidentData, loaded, perimeterData, roadData, snapshotWindHeads, snapshotWindLines, windHeads, windLines]);

  // Update threat score markers — throttled to every 2 s to avoid GeoJSON churn on 34k events
  const scoreUpdateTimer = useRef<number | null>(null);
  const pendingEvents = useRef<FireEvent[]>(events);
  pendingEvents.current = events;
  useEffect(() => {
    if (!loaded) return;
    if (scoreUpdateTimer.current !== null) return; // already scheduled
    scoreUpdateTimer.current = window.setTimeout(() => {
      scoreUpdateTimer.current = null;
      const instance = map.current;
      if (!instance || !instance.isStyleLoaded()) return;
      (instance.getSource("threat-scores") as GeoJSONSource | undefined)
        ?.setData(toScoreCollection(pendingEvents.current));
    }, 2000);
    return () => {
      if (scoreUpdateTimer.current !== null) {
        window.clearTimeout(scoreUpdateTimer.current);
        scoreUpdateTimer.current = null;
      }
    };
  }, [events, loaded]);

  // Fit the camera when a replay data set loads, then leave user pan/zoom alone.
  useEffect(() => {
    const instance = map.current;
    if (!instance || !loaded || !instance.isStyleLoaded() || isDragging.current) return;

    const signature = autoFitKey(events, context);
    if (!signature) {
      autoFitSignature.current = "";
      return;
    }
    if (autoFitSignature.current === signature) return;
    autoFitSignature.current = signature;

    const bounds = boundsFor(events, context);
    if (bounds) {
      instance.fitBounds(bounds, { padding: 48, maxZoom: 9, duration: 400 });
    }
  }, [context, events, loaded]);

  // "ZOOM AND ENHANCE" — fly to threat hotspot with sci-fi overlay
  useEffect(() => {
    const instance = map.current;
    if (!threat || !instance || !loaded) return;
    if (enhanceThreatRef.current === threat) return;
    enhanceThreatRef.current = threat;

    const lngLat: [number, number] = [threat.hotspot.lon, threat.hotspot.lat];

    // Track the projected pixel position of the hotspot on every map move.
    // Throttled: "move" fires every frame during flyTo — unthrottled setHotspotPx
    // triggers a full React re-render per frame and crashes the page.
    let lastPxUpdate = 0;
    const PX_INTERVAL = 1000 / 15;
    function updatePx() {
      const now = performance.now();
      if (now - lastPxUpdate < PX_INTERVAL) return;
      lastPxUpdate = now;
      if (!map.current) return;
      const pt = map.current.project(lngLat);
      setHotspotPx({ x: pt.x, y: pt.y });
    }

    instance.on("move", updatePx);
    updatePx();

    // Phase 1: pull back slightly for drama
    const startZoom = instance.getZoom();
    instance.flyTo({
      center: lngLat,
      zoom: Math.max(4, startZoom - 1.5),
      duration: 800,
      easing: (t) => t * (2 - t),
    });

    // Phase 2: snap overlay on, zoom into the hotspot
    const t1 = setTimeout(() => {
      setEnhancing(true);
      instance.flyTo({
        center: lngLat,
        zoom: 12,
        duration: 1800,
        easing: (t) => t < 0.5 ? 2 * t * t : -1 + (4 - 2 * t) * t,
      });
    }, 900);

    // Phase 3: fade overlay out, stop tracking — hold the lock-on long enough to read
    const t2 = setTimeout(() => {
      setEnhancing(false);
      instance.off("move", updatePx);
    }, 7000);

    return () => {
      clearTimeout(t1);
      clearTimeout(t2);
      instance.off("move", updatePx);
    };
  }, [threat, loaded]);

  // Animated pulsing threat halo + fire spread cone
  useEffect(() => {
    const m = map.current;
    if (!m || !loaded) return;
    const pulseSrc = m.getSource("threat-pulse") as GeoJSONSource | undefined;
    const coneSrc = m.getSource("fire-cone") as GeoJSONSource | undefined;
    if (!pulseSrc || !coneSrc) return;

    if (!threat) {
      pulseSrc.setData({ type: "FeatureCollection", features: [] });
      coneSrc.setData({ type: "FeatureCollection", features: [] });
      return;
    }

    // Wind direction at this hotspot — fall back to bearing-toward-zone if absent
    const weather = context.weather_snapshot;
    let bearingTo: number;
    if (threat.zone.latitude != null && threat.zone.longitude != null) {
      bearingTo = bearingDeg(threat.hotspot.lat, threat.hotspot.lon, threat.zone.latitude, threat.zone.longitude);
    } else if (weather?.wind_direction_degrees != null) {
      // Wind comes FROM that direction → fire travels TO opposite
      bearingTo = (weather.wind_direction_degrees + 180) % 360;
    } else {
      bearingTo = 0;
    }
    const reach = Math.max(
      4,
      Math.min(40, (threat.hotspot.frp / 10) + (weather?.wind_speed_kph ?? 12) * 0.6),
    );
    const coneFeature = makeFireCone(threat.hotspot.lat, threat.hotspot.lon, bearingTo, reach, 28);
    coneSrc.setData({ type: "FeatureCollection", features: [coneFeature] });

    // Pulse animation — drives outer/mid/core radii in pixels
    // Throttled to ~15fps: setData() at 60fps forces Mapbox to reparse GeoJSON every frame
    let raf = 0;
    let lastPulse = 0;
    const PULSE_INTERVAL = 1000 / 15;
    const start = performance.now();
    function tick(now: number) {
      raf = requestAnimationFrame(tick);
      if (now - lastPulse < PULSE_INTERVAL) return;
      lastPulse = now;
      const t = ((now - start) % 1800) / 1800;
      const outer = 22 + Math.sin(t * Math.PI) * 28;
      const mid = 12 + Math.sin(t * Math.PI) * 16;
      const core = 5 + Math.sin(t * Math.PI * 2) * 2;
      pulseSrc!.setData({
        type: "FeatureCollection",
        features: [{
          type: "Feature",
          geometry: { type: "Point", coordinates: [threat!.hotspot.lon, threat!.hotspot.lat] },
          properties: { outerRadius: outer, midRadius: mid, coreRadius: core },
        }],
      });
    }
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [threat, loaded, context]);

  // Animated dashed route — cycles a sliding dash pattern
  useEffect(() => {
    const mm = map.current;
    if (!mm || !loaded) return;
    if (!annotation || annotation.routes.length === 0) return;
    const activeMap = mm;
    let raf = 0;
    let step = 0;
    let lastDash = 0;
    const DASH_INTERVAL = 1000 / 20;
    const animate = (now: number) => {
      raf = requestAnimationFrame(animate);
      if (now - lastDash < DASH_INTERVAL) return;
      lastDash = now;
      if (!activeMap.getLayer("ann-routes-line")) return;
      step = (step + 1) % 30;
      const dashArrays: number[][] = [
        [0,    4, 3, step / 10],
        [0.5,  4, 2.5, step / 10],
        [1,    4, 2, step / 10],
        [1.5,  4, 1.5, step / 10],
      ];
      const arr = dashArrays[Math.floor(step / 8) % dashArrays.length];
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      activeMap.setPaintProperty("ann-routes-line", "line-dasharray", arr as any);
    };
    raf = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(raf);
  }, [annotation, loaded]);

  // Render agent annotation markers + routes on the main map
  useEffect(() => {
    const m = map.current;
    if (!m || !loaded) return;

    // Remove previous annotation markers/popups
    for (const marker of annMarkers.current) marker.remove();
    for (const popup of annPopups.current) popup.remove();
    annMarkers.current = [];
    annPopups.current = [];

    // Remove previous annotation layers/sources
    if (m.getLayer("ann-routes-line")) m.removeLayer("ann-routes-line");
    if (m.getLayer("ann-routes-casing")) m.removeLayer("ann-routes-casing");
    if (m.getSource("ann-routes")) m.removeSource("ann-routes");

    if (!annotation) return;

    // Add route lines
    const routeGeoJSON: GeoJSON.FeatureCollection = {
      type: "FeatureCollection",
      features: annotation.routes.map((r) => ({
        type: "Feature",
        geometry: { type: "LineString", coordinates: [[r.from_lon, r.from_lat], [r.to_lon, r.to_lat]] },
        properties: { color: ANN_ROUTE_COLORS[r.status] ?? "#6366f1", label: r.label },
      })),
    };
    m.addSource("ann-routes", { type: "geojson", data: routeGeoJSON });
    m.addLayer({ id: "ann-routes-casing", type: "line", source: "ann-routes", paint: { "line-color": "#000", "line-width": 7, "line-opacity": 0.3 } });
    m.addLayer({ id: "ann-routes-line",   type: "line", source: "ann-routes", paint: { "line-color": ["get", "color"], "line-width": 4, "line-opacity": 0.95 } });

    // Add markers
    const bounds = new mapboxgl.LngLatBounds();
    for (const marker of annotation.markers) {
      const el = document.createElement("div");
      el.className = "annMarker";
      el.style.setProperty("--ann-color", ANN_MARKER_COLORS[marker.type] ?? "#6366f1");
      el.innerHTML = `<div class="annMarkerIcon">${ANN_MARKER_ICONS[marker.type] ?? ANN_ICON_ZONE}</div>`;

      const popup = new mapboxgl.Popup({ offset: 18, closeButton: false, className: "annPopup" })
        .setHTML(buildAnnPopupHTML(marker, googleMapsKey));

      const mbMarker = new mapboxgl.Marker({ element: el, anchor: "bottom" })
        .setLngLat([marker.lon, marker.lat])
        .setPopup(popup)
        .addTo(m);

      if (marker.type === "hotspot" || marker.type === "shelter_open" || marker.type === "alternate") {
        popup.addTo(m);
      }

      annMarkers.current.push(mbMarker);
      annPopups.current.push(popup);
      bounds.extend([marker.lon, marker.lat]);
    }

    for (const route of annotation.routes) {
      bounds.extend([route.from_lon, route.from_lat]);
      bounds.extend([route.to_lon, route.to_lat]);
    }

    if (!bounds.isEmpty()) {
      m.fitBounds(bounds, { padding: 80, maxZoom: 8, duration: 600 });
    }
  }, [annotation, loaded]);


  if (!token) {
    return (
      <div className="mapFullScreen">
        <NonIdealState icon="map" title="Mapbox token missing" />
      </div>
    );
  }

  const latestEvent = events[events.length - 1];
  const ingestSource = latestEvent?.source ?? null;

  return (
    <div className="mapFullScreen">
      <div ref={container} className="mapCanvas" />
      {annotation?.message && (
        <div className="annMessageBar">
          <img src={LOGOS.googlemaps.src} alt="Maps" width={11} height={11} style={{ opacity: 0.9, flexShrink: 0 }} />
          <span>{annotation.message}</span>
        </div>
      )}
      {threat && hotspotPx && <ThreatEnhanceOverlay threat={threat} active={enhancing} px={hotspotPx} />}
      {simDate && <div className="mapSimDate">{simDate}</div>}
      {events.length > 0 && (
        <div className="mapEventCounter">
          <span className="mapEventCounterDot" />
          <span className="mapEventCounterNum">{events.length.toLocaleString()}</span>
          <span className="mapEventCounterLabel">DETECTIONS</span>
        </div>
      )}
    </div>
  );
}

// ── Sci-fi "ZOOM AND ENHANCE" overlay ────────────────────────────────────────
// All positions are derived from map.project() pixel coords — not CSS percentages.

const BOX = 110; // half-size of the target box in px

function ThreatEnhanceOverlay({ threat, active, px }: { threat: ThreatPayload; active: boolean; px: { x: number; y: number } }) {
  const { x, y } = px;
  const frp = threat.hotspot.frp.toFixed(1);
  const conf = threat.hotspot.confidence ?? "–";
  const dist = threat.zone.distance_km != null ? `${threat.zone.distance_km.toFixed(1)} km` : "–";
  const zone = threat.zone.name;

  return (
    <div className={`enhanceOverlay${active ? " enhanceOverlay--on" : ""}`} aria-hidden="true">
      {/* corner brackets — offset from projected pixel position */}
      <div className="enhanceCorner enhanceCorner--tl" style={{ left: x - BOX, top: y - BOX }} />
      <div className="enhanceCorner enhanceCorner--tr" style={{ left: x + BOX, top: y - BOX }} />
      <div className="enhanceCorner enhanceCorner--bl" style={{ left: x - BOX, top: y + BOX }} />
      <div className="enhanceCorner enhanceCorner--br" style={{ left: x + BOX, top: y + BOX }} />

      {/* horizontal scan line — pinned to hotspot Y, full width */}
      <div className="enhanceScanH" style={{ top: y }} />
      {/* vertical scan line — pinned to hotspot X, full height */}
      <div className="enhanceScanV" style={{ left: x }} />

      {/* reticle centered on projected pixel */}
      <div className="enhanceReticle" style={{ left: x, top: y }}>
        <div className="enhanceReticleRing" />
        <div className="enhanceReticleDot" />
      </div>

      {/* HUD — anchored to top-left corner of box */}
      <div className="enhanceHud enhanceHud--tl" style={{ left: x - BOX, top: y - BOX - 52 }}>
        <span className="enhanceHudLabel">TARGET ACQUIRED</span>
        <span className="enhanceHudVal">{zone}</span>
      </div>

      {/* HUD — anchored to bottom-right corner of box */}
      <div className="enhanceHud enhanceHud--br" style={{ left: x + BOX - 140, top: y + BOX + 8 }}>
        <span className="enhanceHudRow"><span className="enhanceHudKey">FRP</span><span className="enhanceHudVal">{frp} MW</span></span>
        <span className="enhanceHudRow"><span className="enhanceHudKey">CONF</span><span className="enhanceHudVal">{conf}</span></span>
        <span className="enhanceHudRow"><span className="enhanceHudKey">DIST</span><span className="enhanceHudVal">{dist}</span></span>
        <span className="enhanceHudRow"><span className="enhanceHudKey">LAT</span><span className="enhanceHudVal">{threat.hotspot.lat.toFixed(4)}</span></span>
        <span className="enhanceHudRow"><span className="enhanceHudKey">LON</span><span className="enhanceHudVal">{threat.hotspot.lon.toFixed(4)}</span></span>
      </div>
    </div>
  );
}

// ── helpers ──────────────────────────────────────────────────────────────────

function buildAnnPopupHTML(marker: MapAnnotationMarker, googleMapsKey: string): string {
  const detail = marker.detail ? `<div class="annPopupDetail">${marker.detail}</div>` : "";
  let photo = "";
  if (googleMapsKey) {
    const w = 280, h = 160;
    // Street View Static for shelters/zones; satellite for hotspots
    if (marker.type === "hotspot") {
      const params = new URLSearchParams({
        center: `${marker.lat},${marker.lon}`,
        zoom: "13",
        size: `${w}x${h}`,
        maptype: "satellite",
        key: googleMapsKey,
      });
      photo = `<img class="annPopupPhoto" src="https://maps.googleapis.com/maps/api/staticmap?${params}" width="${w}" height="${h}" loading="lazy" />`;
    } else {
      const params = new URLSearchParams({
        location: `${marker.lat},${marker.lon}`,
        size: `${w}x${h}`,
        fov: "90",
        pitch: "10",
        key: googleMapsKey,
      });
      photo = `<img class="annPopupPhoto" src="https://maps.googleapis.com/maps/api/streetview?${params}" width="${w}" height="${h}" loading="lazy" />`;
    }
  }
  return `<div class="annPopupInner">${photo}<div class="annPopupBody"><strong>${marker.label}</strong>${detail}</div></div>`;
}

function setCircleSource(mapInstance: Map | null, cLat: number, cLon: number, r: number) {
  if (!mapInstance || !mapInstance.isStyleLoaded()) return;
  (mapInstance.getSource("area-circle") as GeoJSONSource | undefined)
    ?.setData(makeCircleGeoJSON(cLat, cLon, r));
}

function makeCircleGeoJSON(lat: number, lon: number, radiusKm: number, steps = 72): GeoJSON.FeatureCollection {
  const cosLat = Math.cos(lat * Math.PI / 180);
  const coords: [number, number][] = [];
  for (let i = 0; i <= steps; i++) {
    const angle = (i / steps) * 2 * Math.PI;
    coords.push([
      lon + Math.sin(angle) * (radiusKm / (111 * cosLat)),
      lat + Math.cos(angle) * (radiusKm / 111)
    ]);
  }
  return {
    type: "FeatureCollection",
    features: [{ type: "Feature", geometry: { type: "Polygon", coordinates: [coords] }, properties: {} }]
  };
}

function edgeLngLat(lat: number, lon: number, radiusKm: number): [number, number] {
  return [lon + radiusKm / (111 * Math.cos(lat * Math.PI / 180)), lat];
}

function bearingDeg(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const φ1 = lat1 * Math.PI / 180;
  const φ2 = lat2 * Math.PI / 180;
  const dλ = (lon2 - lon1) * Math.PI / 180;
  const y = Math.sin(dλ) * Math.cos(φ2);
  const x = Math.cos(φ1) * Math.sin(φ2) - Math.sin(φ1) * Math.cos(φ2) * Math.cos(dλ);
  return (Math.atan2(y, x) * 180 / Math.PI + 360) % 360;
}

function makeFireCone(lat: number, lon: number, bearing: number, reachKm: number, halfAngleDeg: number): GeoJSON.Feature<GeoJSON.Polygon> {
  const cosLat = Math.cos(lat * Math.PI / 180);
  const startAngle = (bearing - halfAngleDeg + 360) % 360;
  const endAngle = (bearing + halfAngleDeg) % 360;
  const steps = 18;
  const coords: [number, number][] = [[lon, lat]];
  // Sample along inner (50% reach) and outer arc to make a teardrop with intensity falloff
  for (let i = 0; i <= steps; i++) {
    const frac = i / steps;
    const a = startAngle + ((endAngle - startAngle + 360) % 360) * frac;
    const rad = a * Math.PI / 180;
    // Reach varies — full reach at center, ~60% at edges (teardrop shape)
    const angleFromCenter = Math.abs(((a - bearing + 540) % 360) - 180);
    const reachAtAngle = reachKm * (0.55 + 0.45 * Math.cos(angleFromCenter * Math.PI / 180));
    coords.push([
      lon + Math.sin(rad) * (reachAtAngle / (111 * Math.max(0.2, cosLat))),
      lat + Math.cos(rad) * (reachAtAngle / 111),
    ]);
  }
  coords.push([lon, lat]);
  return {
    type: "Feature",
    geometry: { type: "Polygon", coordinates: [coords] },
    properties: { intensity: Math.min(1, reachKm / 30) },
  };
}

function haversineKm(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const R = 6371;
  const dLat = (lat2 - lat1) * Math.PI / 180;
  const dLon = (lon2 - lon1) * Math.PI / 180;
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) * Math.sin(dLon / 2) ** 2;
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

function toIncidentCollection(context: BcwsContext): GeoJSON.FeatureCollection {
  return {
    type: "FeatureCollection",
    features: context.incidents.flatMap((incident) => {
      if (incident.latitude == null || incident.longitude == null) return [];
      return [{
        type: "Feature" as const,
        geometry: { type: "Point" as const, coordinates: [incident.longitude, incident.latitude] },
        properties: {
          number: incident.fire_number ?? "",
          name: incident.incident_name ?? "",
          status: incident.fire_status ?? "",
          size: incident.current_size_ha ?? 0
        }
      }];
    })
  };
}

function toPerimeterCollection(context: BcwsContext): GeoJSON.FeatureCollection {
  return {
    type: "FeatureCollection",
    features: context.perimeters.flatMap((perimeter) => {
      if (!perimeter.geometry) return [];
      return [{
        type: "Feature" as const,
        geometry: perimeter.geometry,
        properties: {
          number: perimeter.fire_number ?? "",
          status: perimeter.fire_status ?? "",
          size: perimeter.fire_size_hectares ?? 0
        }
      }];
    })
  };
}

function toEvacuationZoneCollection(context: BcwsContext): GeoJSON.FeatureCollection {
  return {
    type: "FeatureCollection",
    features: context.evacuation_zones.flatMap((zone) => {
      if (!zone.geometry) return [];
      return [{
        type: "Feature" as const,
        geometry: zone.geometry,
        properties: {
          id: zone.id ?? "",
          name: zone.order_alert_name ?? zone.event_name ?? "",
          status: zone.status ?? "",
          agency: zone.issuing_agency ?? "",
          population: zone.population ?? 0,
          homes: zone.homes ?? 0
        }
      }];
    })
  };
}

function toEvacuationRecordCollection(context: BcwsContext): GeoJSON.FeatureCollection {
  return {
    type: "FeatureCollection",
    features: context.evacuation_records.flatMap((record) => {
      if (record.latitude == null || record.longitude == null) return [];
      return [{
        type: "Feature" as const,
        geometry: { type: "Point" as const, coordinates: [record.longitude, record.latitude] },
        properties: {
          id: record.order_alert_id ?? "",
          name: record.order_alert_name ?? record.event_name ?? "",
          status: record.status ?? "",
          agency: record.issuing_agency ?? "",
          population: record.population ?? 0,
          homes: record.homes ?? 0
        }
      }];
    })
  };
}

function toEssCollection(context: BcwsContext): GeoJSON.FeatureCollection {
  return {
    type: "FeatureCollection",
    features: context.ess_facilities.flatMap((facility) => {
      if (facility.latitude == null || facility.longitude == null) return [];
      return [{
        type: "Feature" as const,
        geometry: { type: "Point" as const, coordinates: [facility.longitude, facility.latitude] },
        properties: {
          id: facility.facility_id ?? "",
          name: facility.name ?? "",
          type: facility.facility_type ?? "",
          community: facility.community ?? "",
          status: facility.status ?? ""
        }
      }];
    })
  };
}

function toRoadEventCollection(context: BcwsContext): GeoJSON.FeatureCollection {
  return {
    type: "FeatureCollection",
    features: context.road_events.flatMap((event) => {
      const geometry = event.geometry ?? (
        event.latitude == null || event.longitude == null
          ? null
          : { type: "Point" as const, coordinates: [event.longitude, event.latitude] }
      );
      if (!geometry) return [];
      return [{
        type: "Feature" as const,
        geometry,
        properties: {
          id: event.external_id ?? "",
          title: event.title ?? "",
          severity: event.severity ?? "",
          road: event.road_name ?? ""
        }
      }];
    })
  };
}

function toWindLineCollection(events: FireEvent[]): GeoJSON.FeatureCollection {
  return {
    type: "FeatureCollection",
    features: events.flatMap((event) => {
      const weather = event.weather;
      if (!weather || weather.wind_speed_10m == null || weather.wind_direction_10m == null) return [];
      const end = windEndpoint(event.longitude, event.latitude, weather.wind_direction_10m, weather.wind_speed_10m);
      return [{
        type: "Feature" as const,
        geometry: { type: "LineString" as const, coordinates: [[event.longitude, event.latitude], end] },
        properties: { speed: weather.wind_speed_10m, direction: weather.wind_direction_10m, source: weather.source }
      }];
    })
  };
}

function toWindHeadCollection(events: FireEvent[]): GeoJSON.FeatureCollection {
  return {
    type: "FeatureCollection",
    features: events.flatMap((event) => {
      const weather = event.weather;
      if (!weather || weather.wind_speed_10m == null || weather.wind_direction_10m == null) return [];
      return [{
        type: "Feature" as const,
        geometry: {
          type: "Point" as const,
          coordinates: windEndpoint(event.longitude, event.latitude, weather.wind_direction_10m, weather.wind_speed_10m)
        },
        properties: { speed: weather.wind_speed_10m, direction: weather.wind_direction_10m, source: weather.source }
      }];
    })
  };
}

function windEndpoint(lon: number, lat: number, directionFrom: number, speed: number): [number, number] {
  const bearing = ((directionFrom + 180) % 360) * Math.PI / 180;
  const km = Math.min(Math.max(speed / 2, 2), 30);
  const lat2 = lat + Math.cos(bearing) * (km / 111);
  const lon2 = lon + Math.sin(bearing) * (km / (111 * Math.max(0.2, Math.cos(lat * Math.PI / 180))));
  return [lon2, lat2];
}

function toSnapshotWindLineCollection(context: BcwsContext): GeoJSON.FeatureCollection {
  const weather = context.weather_snapshot;
  if (!weather || weather.latitude == null || weather.longitude == null || weather.wind_speed_kph == null || weather.wind_direction_degrees == null) {
    return { type: "FeatureCollection", features: [] };
  }
  const end = windEndpoint(weather.longitude, weather.latitude, weather.wind_direction_degrees, weather.wind_speed_kph);
  return {
    type: "FeatureCollection",
    features: [{
      type: "Feature",
      geometry: { type: "LineString", coordinates: [[weather.longitude, weather.latitude], end] },
      properties: {
        speed: weather.wind_speed_kph,
        direction: weather.wind_direction_degrees,
        source: weather.source ?? ""
      }
    }]
  };
}

function toSnapshotWindHeadCollection(context: BcwsContext): GeoJSON.FeatureCollection {
  const weather = context.weather_snapshot;
  if (!weather || weather.latitude == null || weather.longitude == null || weather.wind_speed_kph == null || weather.wind_direction_degrees == null) {
    return { type: "FeatureCollection", features: [] };
  }
  return {
    type: "FeatureCollection",
    features: [{
      type: "Feature",
      geometry: {
        type: "Point",
        coordinates: windEndpoint(weather.longitude, weather.latitude, weather.wind_direction_degrees, weather.wind_speed_kph)
      },
      properties: {
        speed: weather.wind_speed_kph,
        direction: weather.wind_direction_degrees,
        source: weather.source ?? ""
      }
    }]
  };
}

function scoreColor(score: number): string {
  if (score >= 75) return "#ff2a1a";
  if (score >= 50) return "#ff7a0a";
  if (score >= 25) return "#facc15";
  return "#86efac";
}

function toScoreCollection(events: FireEvent[]): GeoJSON.FeatureCollection {
  // Show every event that has a score (all events with FRP > 0)
  const scored = events.filter((e) => (e.threat_score ?? 0) > 0);
  // Deduplicate to ~1 km grid — keep highest score per cell
  const best: Record<string, FireEvent> = {};
  for (const e of scored) {
    const key = `${e.latitude.toFixed(2)},${e.longitude.toFixed(2)}`;
    if (!best[key] || (e.threat_score ?? 0) > (best[key].threat_score ?? 0)) {
      best[key] = e;
    }
  }
  return {
    type: "FeatureCollection",
    features: Object.values(best).map((e) => {
      const score = e.threat_score!;
      return {
        type: "Feature",
        geometry: { type: "Point", coordinates: [e.longitude, e.latitude] },
        properties: { score, label: String(score), color: scoreColor(score) },
      };
    }),
  };
}

// ── NASA Ingestion Banner ─────────────────────────────────────────────────────

function abbrevSource(source: string): string {
  return source
    .replace("VIIRS_NOAA20_NRT", "VIIRS·NOAA-20")
    .replace("VIIRS_NOAA21_NRT", "VIIRS·NOAA-21")
    .replace("VIIRS_SNPP_NRT",   "VIIRS·SNPP")
    .replace("VIIRS_NOAA20_SP",  "VIIRS·NOAA-20")
    .replace("VIIRS_NOAA21_SP",  "VIIRS·NOAA-21")
    .replace("VIIRS_SNPP_SP",    "VIIRS·SNPP")
    .replace("MODIS_NRT",        "MODIS")
    .replace("MODIS_SP",         "MODIS");
}

function NasaIngestBanner({ source, count }: { source: string; count: number }) {
  return (
    <div className="nasaBanner">
      <img src={LOGOS.nasa.src} alt="NASA" className="nasaBannerLogo" />
      <div className="nasaBannerText">
        <span className="nasaBannerSource">{abbrevSource(source)}</span>
        <span className="nasaBannerLabel">LIVE ACQUISITION</span>
      </div>
      <div className="nasaBannerCount">{count.toLocaleString()}</div>
      <div className="nasaBannerPulse" />
    </div>
  );
}

function toFeatureCollection(events: FireEvent[]): GeoJSON.FeatureCollection {
  return {
    type: "FeatureCollection",
    features: events.map((event) => ({
      type: "Feature",
      geometry: { type: "Point", coordinates: [event.longitude, event.latitude] },
      properties: {
        source: event.source,
        acquired_at: event.acquired_at,
        confidence: event.confidence ?? "",
        frp: event.frp ?? 0
      }
    }))
  };
}

function autoFitKey(events: FireEvent[], context: BcwsContext) {
  const contextCount =
    context.incidents.length +
    context.perimeters.length +
    context.evacuation_zones.length +
    context.evacuation_records.length +
    context.ess_facilities.length +
    context.road_events.length +
    (context.weather_snapshot ? 1 : 0);
  if (contextCount > 0) {
    return [
      context.incidents.length,
      context.perimeters.length,
      context.evacuation_zones.length,
      context.evacuation_records.length,
      context.ess_facilities.length,
      context.road_events.length,
      context.weather_snapshot?.latitude ?? "",
      context.weather_snapshot?.longitude ?? "",
      context.weather_snapshot?.wind_speed_kph ?? "",
      context.weather_snapshot?.wind_direction_degrees ?? "",
    ].join(":");
  }
  const firstEvent = events[0];
  return firstEvent ? `event:${firstEvent.source}:${firstEvent.acquired_at}:${firstEvent.latitude}:${firstEvent.longitude}` : "";
}

function boundsFor(events: FireEvent[], context: BcwsContext) {
  const hasContext =
    context.incidents.length ||
    context.perimeters.length ||
    context.evacuation_zones.length ||
    context.evacuation_records.length ||
    context.ess_facilities.length ||
    context.road_events.length ||
    context.weather_snapshot;
  if (!events.length && !hasContext) return null;
  const bounds = new mapboxgl.LngLatBounds();
  for (const event of events) bounds.extend([event.longitude, event.latitude]);
  for (const incident of context.incidents) {
    if (incident.latitude != null && incident.longitude != null) {
      bounds.extend([incident.longitude, incident.latitude]);
    }
  }
  for (const perimeter of context.perimeters) extendGeometryBounds(bounds, perimeter.geometry);
  for (const zone of context.evacuation_zones) extendGeometryBounds(bounds, zone.geometry);
  for (const record of context.evacuation_records) {
    if (record.latitude != null && record.longitude != null) bounds.extend([record.longitude, record.latitude]);
  }
  for (const facility of context.ess_facilities) {
    if (facility.latitude != null && facility.longitude != null) bounds.extend([facility.longitude, facility.latitude]);
  }
  for (const event of context.road_events) {
    if (event.geometry) extendGeometryBounds(bounds, event.geometry);
    else if (event.latitude != null && event.longitude != null) bounds.extend([event.longitude, event.latitude]);
  }
  const weather = context.weather_snapshot;
  if (weather?.latitude != null && weather.longitude != null) bounds.extend([weather.longitude, weather.latitude]);
  return bounds;
}

function extendGeometryBounds(bounds: mapboxgl.LngLatBounds, geometry?: GeoJSON.Geometry) {
  if (!geometry) return;
  if (geometry.type === "Point") {
    bounds.extend(geometry.coordinates as [number, number]);
  }
  if (geometry.type === "LineString") {
    for (const coordinate of geometry.coordinates) bounds.extend(coordinate as [number, number]);
  }
  if (geometry.type === "Polygon") {
    for (const ring of geometry.coordinates)
      for (const coordinate of ring) bounds.extend(coordinate as [number, number]);
  }
  if (geometry.type === "MultiPolygon") {
    for (const polygon of geometry.coordinates)
      for (const ring of polygon)
        for (const coordinate of ring) bounds.extend(coordinate as [number, number]);
  }
}
