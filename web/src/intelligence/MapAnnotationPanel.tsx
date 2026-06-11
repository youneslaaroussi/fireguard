import { useEffect, useMemo, useRef, useState } from "react";
import mapboxgl, { type GeoJSONSource, type Map } from "mapbox-gl";
import type { MapAnnotation, MapAnnotationMarker, MapAnnotationRoute } from "./types";

interface Props {
  annotation: MapAnnotation | null;
  mapboxToken: string;
}

const ROUTE_COLORS: Record<string, string> = {
  safe: "#10b981",
  blocked: "#ef4444",
  alternate: "#f97316",
};

const MARKER_COLORS: Record<string, string> = {
  hotspot: "#ff4422",
  shelter_open: "#10b981",
  shelter_closed: "#64748b",
  zone: "#8b5cf6",
  blockage: "#ef4444",
  alternate: "#f97316",
};

const MARKER_ICONS: Record<string, string> = {
  hotspot: "🔥",
  shelter_open: "🏠",
  shelter_closed: "⛔",
  zone: "📍",
  blockage: "🚧",
  alternate: "✅",
};

export function MapAnnotationPanel({ annotation, mapboxToken }: Props) {
  const container = useRef<HTMLDivElement | null>(null);
  const map = useRef<Map | null>(null);
  const [loaded, setLoaded] = useState(false);
  const popups = useRef<mapboxgl.Popup[]>([]);

  const routeGeoJSON = useMemo((): GeoJSON.FeatureCollection => {
    if (!annotation) return { type: "FeatureCollection", features: [] };
    return {
      type: "FeatureCollection",
      features: annotation.routes.map((r) => ({
        type: "Feature",
        geometry: {
          type: "LineString",
          coordinates: [
            [r.from_lon, r.from_lat],
            [r.to_lon, r.to_lat],
          ],
        },
        properties: {
          status: r.status,
          label: r.label,
          distance_km: r.distance_km ?? null,
          duration_minutes: r.duration_minutes ?? null,
          color: ROUTE_COLORS[r.status] ?? "#6366f1",
        },
      })),
    };
  }, [annotation]);

  // Initialize map
  useEffect(() => {
    if (!mapboxToken || !container.current || map.current) return;
    mapboxgl.accessToken = mapboxToken;
    map.current = new mapboxgl.Map({
      container: container.current,
      style: "mapbox://styles/mapbox/dark-v11",
      center: [-122.0, 52.0],
      zoom: 5.5,
    });
    map.current.addControl(new mapboxgl.NavigationControl({ showCompass: false }), "top-right");
    map.current.on("load", () => {
      if (!map.current) return;
      map.current.addSource("routes", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      map.current.addLayer({
        id: "routes-line",
        type: "line",
        source: "routes",
        paint: {
          "line-color": ["get", "color"],
          "line-width": 4,
          "line-opacity": 0.92,
        },
      });
      map.current.addLayer({
        id: "routes-casing",
        type: "line",
        source: "routes",
        paint: {
          "line-color": "#000",
          "line-width": 7,
          "line-opacity": 0.25,
        },
        layout: {},
      });
      // Move casing below line
      map.current.moveLayer("routes-casing", "routes-line");
      setLoaded(true);
    });
    return () => {
      popups.current.forEach((p) => p.remove());
      popups.current = [];
      map.current?.remove();
      map.current = null;
      setLoaded(false);
    };
  }, [mapboxToken]);

  // Update routes + markers when annotation changes
  useEffect(() => {
    const m = map.current;
    if (!m || !loaded) return;

    // Remove old popups
    popups.current.forEach((p) => p.remove());
    popups.current = [];

    // Update route lines
    (m.getSource("routes") as GeoJSONSource | undefined)?.setData(routeGeoJSON);

    if (!annotation) return;

    // Add marker elements for each marker
    const bounds = new mapboxgl.LngLatBounds();

    for (const marker of annotation.markers) {
      const el = document.createElement("div");
      el.className = "ann-marker";
      el.style.setProperty("--color", MARKER_COLORS[marker.type] ?? "#6366f1");
      el.innerHTML = `<span class="ann-marker-icon">${MARKER_ICONS[marker.type] ?? "📌"}</span>`;

      const popup = new mapboxgl.Popup({ offset: 18, closeButton: false, className: "ann-popup" })
        .setHTML(buildPopupHTML(marker));

      new mapboxgl.Marker({ element: el, anchor: "bottom" })
        .setLngLat([marker.lon, marker.lat])
        .setPopup(popup)
        .addTo(m);

      // Show popup immediately for hotspot, zone and recommended routes
      if (marker.type === "hotspot" || marker.type === "shelter_open" || marker.type === "alternate") {
        popup.addTo(m);
      }

      popups.current.push(popup);
      bounds.extend([marker.lon, marker.lat]);
    }

    for (const route of annotation.routes) {
      bounds.extend([route.from_lon, route.from_lat]);
      bounds.extend([route.to_lon, route.to_lat]);
    }

    if (!bounds.isEmpty()) {
      m.fitBounds(bounds, { padding: 80, maxZoom: 8, duration: 600 });
    }
  }, [annotation, loaded, routeGeoJSON]);

  if (!mapboxToken) {
    return (
      <div className="ann-map-empty">
        <span>Mapbox token not configured — map unavailable.</span>
      </div>
    );
  }

  return (
    <div className="ann-map-container">
      {annotation?.message && (
        <div className="ann-message-bar">
          <span className="ann-message-icon">⚡</span>
          <span>{annotation.message}</span>
        </div>
      )}
      {!annotation && (
        <div className="ann-map-idle">
          <span>Agent map annotations will appear here once the route analysis is complete.</span>
        </div>
      )}
      <div ref={container} className="ann-map-canvas" />
      {annotation && (
        <div className="ann-legend">
          {annotation.routes.map((r, i) => (
            <div key={i} className="ann-legend-route">
              <span className="ann-legend-dot" style={{ background: ROUTE_COLORS[r.status] }} />
              <span className="ann-legend-label">{r.label}</span>
              {r.distance_km != null && (
                <span className="ann-legend-meta">{r.distance_km}km · {r.duration_minutes}min</span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function buildPopupHTML(marker: MapAnnotationMarker): string {
  const icon = MARKER_ICONS[marker.type] ?? "📌";
  const detail = marker.detail ? `<div class="ann-popup-detail">${marker.detail}</div>` : "";
  return `<div class="ann-popup-inner"><span class="ann-popup-icon">${icon}</span><div><strong>${marker.label}</strong>${detail}</div></div>`;
}
