"use client";

import { Button, ButtonGroup, Classes, Dialog, H4, H5, Intent, Tag } from "@blueprintjs/core";
import { useEffect, useMemo, useRef, useState } from "react";
import mapboxgl, { GeoJSONSource, Map } from "mapbox-gl";

import type { AssessmentResult, IncidentContext, RouteOption } from "@/lib/types";

type Props = {
  context: IncidentContext | null;
  assessment: AssessmentResult | null;
};

type LayerKey = "fires" | "perimeters" | "roads" | "zones" | "shelters" | "routes" | "public" | "liveFires" | "livePerimeters" | "liveRoads";
type BasemapKey = "dark" | "satellite" | "streets" | "outdoors";
type SelectedMapFeature = {
  coordinates: [number, number];
  properties: Record<string, unknown>;
};

const MAPBOX_TOKEN = process.env.NEXT_PUBLIC_MAPBOX_TOKEN || "";

const BASEMAPS: Array<{ key: BasemapKey; label: string; styleUrl: string }> = [
  { key: "dark", label: "Dark", styleUrl: "mapbox://styles/mapbox/dark-v11" },
  { key: "satellite", label: "Satellite", styleUrl: "mapbox://styles/mapbox/satellite-streets-v12" },
  { key: "streets", label: "Streets", styleUrl: "mapbox://styles/mapbox/streets-v12" },
  { key: "outdoors", label: "Terrain", styleUrl: "mapbox://styles/mapbox/outdoors-v12" },
];

const LAYER_IDS: Record<LayerKey, string[]> = {
  fires: ["fires"],
  perimeters: ["perimeters-fill", "perimeters-line"],
  roads: ["roads"],
  zones: ["zones-fill", "zones-line"],
  shelters: ["shelters"],
  routes: ["routes"],
  public: ["public-orders", "public-ess"],
  liveFires: ["live-fires"],
  livePerimeters: ["live-perimeters-fill", "live-perimeters-line"],
  liveRoads: ["live-roads"],
};

const INTERACTIVE_LAYER_IDS = [
  "fires",
  "live-fires",
  "roads",
  "live-roads",
  "shelters",
  "public-orders",
  "public-ess",
  "routes",
  "zones-fill",
  "perimeters-fill",
  "live-perimeters-fill",
  "live-perimeters-line",
];

function styleUrlForBasemap(key: BasemapKey) {
  return BASEMAPS.find((style) => style.key === key)?.styleUrl || BASEMAPS[0].styleUrl;
}

function pointFeature(id: string, coordinates: [number, number], properties: Record<string, unknown>) {
  return {
    type: "Feature" as const,
    id,
    properties,
    geometry: {
      type: "Point" as const,
      coordinates,
    },
  };
}

function routeFeature(route: RouteOption) {
  return {
    type: "Feature" as const,
    id: `${route.origin_id}-${route.destination_id}`,
    properties: {
      safe: route.safe,
      label: `${route.origin_id} -> ${route.destination_id}`,
      flags: route.risk_flags.join("; "),
      duration: `${route.duration_minutes} min`,
      distance: `${route.distance_km} km`,
      source_label: "Google Routes result with FireGuard route-safety validation",
      evidence_ids: route.evidence_ids.join(", "),
      assumption_ids: route.assumption_ids?.join(", ") || "",
    },
    geometry: {
      type: "LineString" as const,
      coordinates: route.polyline.map((point) => [point.lon, point.lat]),
    },
  };
}

function setSourceData(map: Map, id: string, data: GeoJSON.FeatureCollection) {
  const source = map.getSource(id) as GeoJSONSource | undefined;
  if (source) {
    source.setData(data);
  }
}

function collectBounds(collections: ReturnType<typeof buildCollections>) {
  const bounds = new mapboxgl.LngLatBounds();
  let count = 0;
  const visit = (coordinates: unknown) => {
    if (!Array.isArray(coordinates)) return;
    if (typeof coordinates[0] === "number" && typeof coordinates[1] === "number") {
      bounds.extend([coordinates[0], coordinates[1]]);
      count += 1;
      return;
    }
    coordinates.forEach(visit);
  };
  for (const [key, collection] of Object.entries(collections)) {
    if (key.startsWith("live")) continue;
    collection.features.forEach((feature) => visit(feature.geometry.coordinates));
  }
  return count ? bounds : null;
}

function buildCollections(context: IncidentContext | null, assessment: AssessmentResult | null) {
  const empty = { type: "FeatureCollection" as const, features: [] };
  if (!context) {
    return { zones: empty, shelters: empty, fires: empty, roads: empty, perimeters: empty, publicOrders: empty, publicEss: empty, routes: empty, liveFires: empty, liveRoads: empty, livePerimeters: empty };
  }

  return {
    zones: {
      type: "FeatureCollection" as const,
      features: context.zones.map((zone) => ({
        type: "Feature" as const,
        id: zone.zone_id,
        properties: {
          label: zone.name,
          population: zone.population,
          vulnerable: zone.vulnerable_count,
          zone_id: zone.zone_id,
          households: zone.households,
          source_label: zone.source_label || "Synthetic municipal evacuation zone",
          data_origin: zone.data_origin || "synthetic_demo_municipality",
          synthetic: zone.synthetic ? "yes" : "no",
        },
        geometry: zone.geometry,
      })),
    },
    shelters: {
      type: "FeatureCollection" as const,
      features: context.shelters.map((shelter) =>
        pointFeature(shelter.shelter_id, [shelter.location.lon, shelter.location.lat], {
          label: shelter.name,
          capacity: `${shelter.capacity_available}/${shelter.capacity_total}`,
          status: shelter.status,
          id: shelter.shelter_id,
          source_label: shelter.source_label || shelter.capacity_source_label || "BC ESS facility context with operator capacity feed",
          data_origin: shelter.data_origin || "shelter_context",
          capacity_source: shelter.capacity_source_label || "capacity source not reported",
          official_status: shelter.official_facility_status || shelter.status,
        }),
      ),
    },
    fires: {
      type: "FeatureCollection" as const,
      features: context.fires.map((fire) =>
        pointFeature(fire.external_id, [fire.location.lon, fire.location.lat], {
          label: fire.external_id,
          confidence: fire.confidence,
          frp: fire.frp,
          source: fire.source,
          source_label: "NASA FIRMS hotspot indexed through FireGuard operational memory",
          scope: "REPLAY DECISION",
          decision_eligible: "yes",
        }),
      ),
    },
    roads: {
      type: "FeatureCollection" as const,
      features: context.road_events.map((event) => ({
        type: "Feature" as const,
        id: event.external_id,
        properties: {
          label: event.title,
          severity: event.severity,
          road: event.road_name,
          id: event.external_id,
          source_label: "DriveBC/Open511 road event indexed through FireGuard operational memory",
          scope: "REPLAY DECISION",
          decision_eligible: "yes",
        },
        geometry:
          event.geometry ||
          ({
            type: "Point" as const,
            coordinates: [event.location.lon, event.location.lat],
          }),
      })),
    },
    perimeters: {
      type: "FeatureCollection" as const,
      features: context.perimeters.map((perimeter) => ({
        type: "Feature" as const,
        id: perimeter.fire_number,
        properties: {
          label: perimeter.fire_name,
          status: perimeter.status,
          id: perimeter.fire_number,
          source_label: "BC Wildfire perimeter record indexed through FireGuard operational memory",
          scope: "REPLAY DECISION",
          decision_eligible: "yes",
        },
        geometry: perimeter.geometry,
      })),
    },
    liveFires: {
      type: "FeatureCollection" as const,
      features: (context.live_context?.fires || []).map((fire) =>
        pointFeature(fire.external_id, [fire.location.lon, fire.location.lat], {
          label: fire.external_id,
          confidence: fire.confidence,
          frp: fire.frp,
          source: fire.source,
          source_label: "NASA FIRMS hotspot from the current Fivetran live overlay",
          scope: "LIVE CURRENT",
          decision_eligible: "no",
        }),
      ),
    },
    liveRoads: {
      type: "FeatureCollection" as const,
      features: (context.live_context?.road_events || []).map((event) => ({
        type: "Feature" as const,
        id: event.external_id,
        properties: {
          label: event.title,
          severity: event.severity,
          road: event.road_name,
          id: event.external_id,
          source_label: "DriveBC/Open511 road event from the current Fivetran live overlay",
          scope: "LIVE CURRENT",
          decision_eligible: "no",
        },
        geometry:
          event.geometry ||
          ({
            type: "Point" as const,
            coordinates: [event.location.lon, event.location.lat],
          }),
      })),
    },
    livePerimeters: {
      type: "FeatureCollection" as const,
      features: (context.live_context?.perimeters || []).map((perimeter) => ({
        type: "Feature" as const,
        id: perimeter.fire_number,
        properties: {
          label: perimeter.fire_name,
          status: perimeter.status,
          id: perimeter.fire_number,
          source_label: "BC Wildfire perimeter from the current Fivetran live overlay",
          scope: "LIVE CURRENT",
          decision_eligible: "no",
        },
        geometry: perimeter.geometry,
      })),
    },
    publicOrders: {
      type: "FeatureCollection" as const,
      features: (context.public_evacuation_orders || []).map((order) =>
        pointFeature(order.order_alert_id, [order.location.lon, order.location.lat], {
          label: order.order_alert_name,
          status: order.status,
          agency: order.issuing_agency,
          population: order.population,
          homes: order.homes,
          source_label: "EmergencyMapBC public evacuation order/alert feed",
          source_url: order.source_url || "",
        }),
      ),
    },
    publicEss: {
      type: "FeatureCollection" as const,
      features: (context.public_ess_facilities || []).map((facility) =>
        pointFeature(facility.facility_id, [facility.location.lon, facility.location.lat], {
          label: facility.name,
          status: facility.status,
          community: facility.community,
          municipality: facility.municipality,
          facility_type: facility.facility_type,
          source_label: "BC public ESS facility feed",
          source_url: facility.source_url || "",
        }),
      ),
    },
    routes: {
      type: "FeatureCollection" as const,
      features: assessment?.plan.routes.map(routeFeature) || [],
    },
  };
}

function addSourcesAndLayers(map: Map) {
  for (const sourceId of ["perimeters", "zones", "roads", "routes", "fires", "shelters", "public-orders", "public-ess", "live-fires", "live-roads", "live-perimeters"]) {
    if (!map.getSource(sourceId)) {
      map.addSource(sourceId, { type: "geojson", data: { type: "FeatureCollection", features: [] } });
    }
  }

  if (!map.getLayer("perimeters-fill")) {
    map.addLayer({
      id: "perimeters-fill",
      type: "fill",
      source: "perimeters",
      paint: { "fill-color": "#d9822b", "fill-opacity": 0.22 },
    });
    map.addLayer({
      id: "perimeters-line",
      type: "line",
      source: "perimeters",
      paint: { "line-color": "#f29d49", "line-width": 3 },
    });
    map.addLayer({
      id: "zones-fill",
      type: "fill",
      source: "zones",
      paint: { "fill-color": "#8f57ff", "fill-opacity": 0.22 },
    });
    map.addLayer({
      id: "zones-line",
      type: "line",
      source: "zones",
      paint: { "line-color": "#c0a0ff", "line-width": 2 },
    });
    map.addLayer({
      id: "roads",
      type: "line",
      source: "roads",
      paint: { "line-color": "#f2b824", "line-width": 5, "line-dasharray": [1, 0.8] },
    });
    map.addLayer({
      id: "routes",
      type: "line",
      source: "routes",
      paint: {
        "line-color": ["case", ["==", ["get", "safe"], true], "#0f9960", "#db3737"],
        "line-width": ["case", ["==", ["get", "safe"], true], 4, 6],
        "line-opacity": 0.9,
      },
    });
    map.addLayer({
      id: "fires",
      type: "circle",
      source: "fires",
      paint: {
        "circle-color": "#db3737",
        "circle-radius": 8,
        "circle-blur": 0.2,
        "circle-stroke-color": "#ffb366",
        "circle-stroke-width": 2,
      },
    });
    map.addLayer({
      id: "live-perimeters-fill",
      type: "fill",
      source: "live-perimeters",
      paint: { "fill-color": "#48aff0", "fill-opacity": 0.12 },
    });
    map.addLayer({
      id: "live-perimeters-line",
      type: "line",
      source: "live-perimeters",
      paint: { "line-color": "#48aff0", "line-width": 2, "line-dasharray": [2, 1] },
    });
    map.addLayer({
      id: "live-roads",
      type: "line",
      source: "live-roads",
      paint: { "line-color": "#72cae8", "line-width": 4, "line-dasharray": [0.4, 1.2], "line-opacity": 0.9 },
    });
    map.addLayer({
      id: "live-fires",
      type: "circle",
      source: "live-fires",
      paint: {
        "circle-color": "#ff6e4a",
        "circle-radius": 5,
        "circle-stroke-color": "#ffffff",
        "circle-stroke-width": 1.5,
        "circle-opacity": 0.85,
      },
    });
    map.addLayer({
      id: "shelters",
      type: "circle",
      source: "shelters",
      paint: {
        "circle-color": "#2d72d2",
        "circle-radius": 7,
        "circle-stroke-color": "#d8ecff",
        "circle-stroke-width": 2,
      },
    });
    map.addLayer({
      id: "public-orders",
      type: "circle",
      source: "public-orders",
      paint: {
        "circle-color": ["case", ["==", ["get", "status"], "Order"], "#db3737", "#d9822b"],
        "circle-radius": 6,
        "circle-stroke-color": "#fff2d6",
        "circle-stroke-width": 1.5,
      },
    });
    map.addLayer({
      id: "public-ess",
      type: "circle",
      source: "public-ess",
      paint: {
        "circle-color": ["case", ["==", ["get", "status"], "OPEN"], "#0f9960", "#5c7080"],
        "circle-radius": 5,
        "circle-stroke-color": "#d9f2ff",
        "circle-stroke-width": 1.5,
      },
    });
  }
}

function applyMapFog(map: Map) {
  map.setFog?.({
    color: "rgb(16, 22, 30)",
    "high-color": "rgb(45, 65, 88)",
    "horizon-blend": 0.12,
  });
}

function setOperationalData(map: Map, collections: ReturnType<typeof buildCollections>) {
  setSourceData(map, "zones", collections.zones);
  setSourceData(map, "shelters", collections.shelters);
  setSourceData(map, "fires", collections.fires);
  setSourceData(map, "roads", collections.roads);
  setSourceData(map, "perimeters", collections.perimeters);
  setSourceData(map, "public-orders", collections.publicOrders);
  setSourceData(map, "public-ess", collections.publicEss);
  setSourceData(map, "routes", collections.routes);
  setSourceData(map, "live-fires", collections.liveFires);
  setSourceData(map, "live-roads", collections.liveRoads);
  setSourceData(map, "live-perimeters", collections.livePerimeters);
}

function applyLayerVisibility(map: Map, visible: Record<LayerKey, boolean>) {
  for (const [layerKey, layerIds] of Object.entries(LAYER_IDS) as Array<[LayerKey, string[]]>) {
    for (const layerId of layerIds) {
      if (map.getLayer(layerId)) {
        map.setLayoutProperty(layerId, "visibility", visible[layerKey] ? "visible" : "none");
      }
    }
  }
}

function hydrateOperationalLayers(map: Map, collections: ReturnType<typeof buildCollections>, visible: Record<LayerKey, boolean>) {
  applyMapFog(map);
  addSourcesAndLayers(map);
  setOperationalData(map, collections);
  applyLayerVisibility(map, visible);
}

function escapeHtml(value: unknown) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function popupKind(properties: mapboxgl.GeoJSONFeature["properties"]) {
  const scope = String(properties?.scope || "").toLowerCase();
  const status = String(properties?.status || "").toLowerCase();
  const safe = String(properties?.safe || "").toLowerCase();
  if (safe === "true") return "route-safe";
  if (safe === "false") return "route-blocked";
  if (scope.includes("live")) return "live";
  if (properties?.frp !== undefined || properties?.confidence !== undefined) return "fire";
  if (properties?.capacity !== undefined) return "shelter";
  if (properties?.road !== undefined || properties?.severity !== undefined) return "road";
  if (properties?.population !== undefined || properties?.vulnerable !== undefined) return "zone";
  if (properties?.agency !== undefined) return "public";
  if (status === "open") return "ess";
  return "record";
}

function popupKindLabel(kind: string) {
  if (kind === "route-safe") return "Safe route";
  if (kind === "route-blocked") return "Blocked route";
  if (kind === "live") return "Live overlay";
  if (kind === "fire") return "Fire signal";
  if (kind === "shelter") return "Shelter";
  if (kind === "road") return "Road event";
  if (kind === "zone") return "Evacuation zone";
  if (kind === "public") return "Evacuation notice";
  if (kind === "ess") return "ESS facility";
  return "Operational record";
}

function fieldLabel(key: string) {
  return key.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function featureHtml(properties: mapboxgl.GeoJSONFeature["properties"]) {
  if (!properties) return '<div class="fg-map-card"><strong>Operational record</strong></div>';
  const kind = popupKind(properties);
  const primary = String(properties.label || properties.id || "Operational record");
  const rows = Object.entries(properties)
    .filter(([key]) => !["label"].includes(key))
    .filter(([, value]) => value !== undefined && value !== null && String(value).length > 0)
    .slice(0, 7)
    .map(([key, value]) => `<div class="fg-map-row"><span>${escapeHtml(fieldLabel(key))}</span><strong>${escapeHtml(value)}</strong></div>`)
    .join("");
  return `
    <div class="fg-map-card fg-map-card-${kind}">
      <div class="fg-map-card-top">
        <span>${escapeHtml(popupKindLabel(kind))}</span>
        <i>${properties.decision_eligible === "yes" ? "Decision evidence" : properties.scope ? escapeHtml(properties.scope) : "Map layer"}</i>
      </div>
      <h3>${escapeHtml(primary)}</h3>
      <div class="fg-map-card-grid">${rows}</div>
    </div>
  `;
}

function featureTitle(properties: Record<string, unknown>) {
  return String(properties.label || properties.id || "Operational record");
}

function selectedFeatureKind(selected: SelectedMapFeature | null) {
  return selected ? popupKind(selected.properties) : "record";
}

function selectedFeatureRows(properties: Record<string, unknown>) {
  return Object.entries(properties)
    .filter(([, value]) => value !== undefined && value !== null && String(value).length > 0)
    .filter(([key]) => !["label"].includes(key))
    .slice(0, 18);
}

function sourceSummary(properties: Record<string, unknown>) {
  return String(properties.source_label || properties.source || properties.data_origin || "Source not reported on this record");
}

function mapboxStaticImageUrl(selected: SelectedMapFeature | null) {
  if (!selected || !MAPBOX_TOKEN) return "";
  const [lon, lat] = selected.coordinates;
  const marker = `pin-l+ff6e4a(${lon.toFixed(5)},${lat.toFixed(5)})`;
  return `https://api.mapbox.com/styles/v1/mapbox/satellite-streets-v12/static/${marker}/${lon.toFixed(5)},${lat.toFixed(5)},10.5,0/760x320@2x?access_token=${encodeURIComponent(MAPBOX_TOKEN)}`;
}

export function MapPanel({ context, assessment }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<Map | null>(null);
  const styleRef = useRef<BasemapKey>("dark");
  const [basemap, setBasemap] = useState<BasemapKey>("dark");
  const [layersOpen, setLayersOpen] = useState(false);
  const [selectedFeature, setSelectedFeature] = useState<SelectedMapFeature | null>(null);
  const [visible, setVisible] = useState<Record<LayerKey, boolean>>({
    fires: true,
    perimeters: true,
    roads: true,
    zones: true,
    shelters: true,
    routes: true,
    public: true,
    liveFires: true,
    livePerimeters: true,
    liveRoads: true,
  });

  const collections = useMemo(() => buildCollections(context, assessment), [context, assessment]);
  const collectionsRef = useRef(collections);
  const visibleRef = useRef(visible);
  const mapboxConfigured = Boolean(MAPBOX_TOKEN);

  useEffect(() => {
    collectionsRef.current = collections;
  }, [collections]);

  useEffect(() => {
    visibleRef.current = visible;
  }, [visible]);

  useEffect(() => {
    if (!containerRef.current || mapRef.current || !mapboxConfigured) return;
    mapboxgl.accessToken = MAPBOX_TOKEN;

    const map = new mapboxgl.Map({
      container: containerRef.current,
      center: [-121.82, 52.45],
      zoom: 8.1,
      pitch: 42,
      bearing: -18,
      attributionControl: false,
      style: styleUrlForBasemap(styleRef.current),
    });

    map.addControl(new mapboxgl.NavigationControl({ showCompass: true }), "top-left");
    map.addControl(new mapboxgl.AttributionControl({ compact: true }), "bottom-right");

    map.on("load", () => {
      applyMapFog(map);
      addSourcesAndLayers(map);
      const hoverPopup = new mapboxgl.Popup({
        closeButton: false,
        closeOnClick: false,
        className: "fireguard-map-hover-popup",
        maxWidth: "440px",
        offset: 18,
      });
      map.on("click", (event) => {
        const queryableLayers = INTERACTIVE_LAYER_IDS.filter((layerId) => map.getLayer(layerId));
        if (!queryableLayers.length) return;
        const tolerance = 16;
        const features = map.queryRenderedFeatures(
          [
            [event.point.x - tolerance, event.point.y - tolerance],
            [event.point.x + tolerance, event.point.y + tolerance],
          ],
          { layers: queryableLayers },
        );
        const feature = features[0];
        if (!feature) return;
        hoverPopup.remove();
        setSelectedFeature({
          coordinates: [event.lngLat.lng, event.lngLat.lat],
          properties: { ...(feature.properties || {}) },
        });
      });
      for (const layerId of INTERACTIVE_LAYER_IDS) {
        map.on("mousemove", layerId, (event) => {
          const feature = event.features?.[0];
          if (!feature || !event.lngLat) return;
          map.getCanvas().style.cursor = "pointer";
          hoverPopup
            .setLngLat(event.lngLat)
            .setHTML(featureHtml(feature.properties))
            .addTo(map);
        });
        map.on("mouseenter", layerId, () => {
          map.getCanvas().style.cursor = "pointer";
        });
        map.on("mouseleave", layerId, () => {
          map.getCanvas().style.cursor = "";
          hoverPopup.remove();
        });
      }
    });

    mapRef.current = map;
    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, [mapboxConfigured]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || styleRef.current === basemap) return;
    styleRef.current = basemap;
    const rehydrate = () => hydrateOperationalLayers(map, collectionsRef.current, visibleRef.current);
    map.once("style.load", rehydrate);
    map.setStyle(styleUrlForBasemap(basemap));
    return () => {
      map.off("style.load", rehydrate);
    };
  }, [basemap]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const apply = () => {
      hydrateOperationalLayers(map, collections, visible);
      const bounds = collectBounds(collections);
      if (bounds && !bounds.isEmpty()) {
        map.fitBounds(bounds, { padding: 80, maxZoom: 9.5, duration: 900 });
      }
    };
    if (map.loaded()) apply();
    else map.once("load", apply);
  }, [collections]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map?.loaded()) return;
    applyLayerVisibility(map, visible);
  }, [visible]);

  return (
    <section className="fireguard-map-panel">
      {mapboxConfigured ? <div ref={containerRef} className="absolute inset-0" /> : <MapboxTokenPending context={context} assessment={assessment} />}
      <div className="absolute right-4 top-4 max-w-[460px]">
        <div className="fireguard-map-layer-control shadow-lg">
          <div className="fireguard-map-style-row">
            <ButtonGroup minimal>
              {BASEMAPS.map((style) => (
                <Button
                  key={style.key}
                  active={basemap === style.key}
                  small
                  text={style.label}
                  onClick={() => setBasemap(style.key)}
                />
              ))}
            </ButtonGroup>
            <Button small icon="layers" text="Layers" onClick={() => setLayersOpen((open) => !open)} />
          </div>
          {layersOpen ? (
            <ButtonGroup className="mt-3 flex flex-wrap" minimal>
              {([
                ["fires", "Fires"],
                ["perimeters", "Perimeters"],
                ["roads", "Roads"],
                ["zones", "Zones"],
                ["shelters", "Shelters"],
                ["routes", "Routes"],
                ["public", "Public"],
                ["liveFires", "Live fire"],
                ["livePerimeters", "Live perimeters"],
                ["liveRoads", "Live roads"],
              ] as Array<[LayerKey, string]>).map(([key, label]) => (
                <Button
                  key={key}
                  active={visible[key]}
                  small
                  icon={visible[key] ? "eye-open" : "eye-off"}
                  text={label}
                  onClick={() => setVisible((current) => ({ ...current, [key]: !current[key] }))}
                />
              ))}
            </ButtonGroup>
          ) : null}
        </div>
      </div>
      <div className="absolute bottom-4 left-4 text-xs">
        <div className="fireguard-map-legend">
          <MapLegendItem tone="fire" label="Fire" />
          <MapLegendItem tone="road" label="Road event" />
          <MapLegendItem tone="live" label="Live overlay" />
          <MapLegendItem tone="shelter" label="Shelter" />
          <MapLegendItem tone="zone" label="Zone" />
          {assessment ? (
            <>
              <MapLegendItem tone="route-safe" label="Safe route" />
              <MapLegendItem tone="route-blocked" label="Blocked route" />
            </>
          ) : null}
        </div>
      </div>
      <MapFeatureDetailDialog selected={selectedFeature} onClose={() => setSelectedFeature(null)} />
    </section>
  );
}

function MapFeatureDetailDialog({ selected, onClose }: { selected: SelectedMapFeature | null; onClose: () => void }) {
  const kind = selectedFeatureKind(selected);
  const imageUrl = mapboxStaticImageUrl(selected);
  const coordinates = selected?.coordinates;
  const rows = selectedFeatureRows(selected?.properties || {});
  const sourceUrl = String(selected?.properties.source_url || "");

  return (
    <Dialog className="bp6-dark fireguard-map-detail-dialog" icon="map-marker" isOpen={Boolean(selected)} onClose={onClose} title="Map Record Detail">
      <div className={Classes.DIALOG_BODY}>
        {selected ? (
          <div className="fg-map-detail">
            <section className={`fg-map-detail-hero fg-map-detail-${kind}`}>
              <div>
                <p className="ops-section-kicker">{popupKindLabel(kind)}</p>
                <H4 className="m-0">{featureTitle(selected.properties)}</H4>
                <div className="mt-3 flex flex-wrap gap-2">
                  <Tag intent={kind === "route-blocked" || kind === "fire" || kind === "public" ? Intent.WARNING : Intent.PRIMARY}>
                    {String(selected.properties.scope || selected.properties.status || "operational record")}
                  </Tag>
                  {selected.properties.decision_eligible ? (
                    <Tag minimal intent={selected.properties.decision_eligible === "yes" ? Intent.SUCCESS : Intent.NONE}>
                      {selected.properties.decision_eligible === "yes" ? "decision evidence" : "display overlay"}
                    </Tag>
                  ) : null}
                </div>
              </div>
              <div className="fg-map-coordinate-card">
                <span>Coordinate</span>
                <strong>{coordinates ? `${coordinates[1].toFixed(5)}, ${coordinates[0].toFixed(5)}` : "not available"}</strong>
              </div>
            </section>

            {imageUrl ? (
              <section className="fg-map-detail-image">
                <img src={imageUrl} alt={`Satellite context around ${featureTitle(selected.properties)}`} />
                <div>
                  <Tag minimal intent={Intent.PRIMARY}>Mapbox satellite context</Tag>
                  <span>Image generated from the clicked coordinate.</span>
                </div>
              </section>
            ) : null}

            <section className="fg-map-detail-source">
              <H5 className="m-0">Data Source</H5>
              <p>{sourceSummary(selected.properties)}</p>
              <div className="fg-map-source-grid">
                <DetailLine label="Source" value={String(selected.properties.source || selected.properties.data_origin || "not reported")} />
                <DetailLine label="Record ID" value={String(selected.properties.id || selected.properties.zone_id || "not reported")} />
                <DetailLine label="Decision Use" value={selected.properties.decision_eligible === "yes" ? "Used in decision context" : selected.properties.decision_eligible === "no" ? "Live overlay only" : "Layer reference"} />
              </div>
              {sourceUrl ? (
                <a className="fg-map-source-link" href={sourceUrl} target="_blank" rel="noreferrer">
                  Open source record
                </a>
              ) : null}
            </section>

            <section className="fg-map-detail-fields">
              <H5 className="m-0">Record Fields</H5>
              <div className="fg-map-detail-grid">
                {rows.map(([key, value]) => (
                  <DetailLine key={key} label={fieldLabel(key)} value={String(value)} />
                ))}
              </div>
            </section>
          </div>
        ) : null}
      </div>
      <div className={Classes.DIALOG_FOOTER}>
        <div className={Classes.DIALOG_FOOTER_ACTIONS}>
          <Button text="Close" onClick={onClose} />
        </div>
      </div>
    </Dialog>
  );
}

function DetailLine({ label, value }: { label: string; value: string }) {
  return (
    <div className="fg-map-detail-line">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function MapLegendItem({ tone, label }: { tone: "fire" | "road" | "live" | "shelter" | "zone" | "route-safe" | "route-blocked"; label: string }) {
  return (
    <div className="fireguard-map-legend-item">
      <span className={`fireguard-map-legend-symbol fireguard-map-legend-${tone}`} />
      <span>{label}</span>
    </div>
  );
}

function MapboxTokenPending({ context, assessment }: Props) {
  return (
    <div className="absolute inset-0 bg-[#0b1118]">
      <div className="absolute inset-0 opacity-25" style={{
        backgroundImage: "linear-gradient(#2f3f4f 1px, transparent 1px), linear-gradient(90deg, #2f3f4f 1px, transparent 1px)",
        backgroundSize: "48px 48px",
      }} />
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_50%_45%,rgba(45,114,210,0.20),transparent_42%),radial-gradient(circle_at_32%_34%,rgba(219,55,55,0.18),transparent_18%)]" />
      <div className="absolute inset-x-0 top-1/2 mx-auto w-[min(560px,calc(100%-48px))] -translate-y-1/2 border border-[#5f6b7c] bg-[#182430]/95 p-5 shadow-2xl">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h3 className="m-0 text-lg font-semibold">Map provider offline</h3>
            <p className="m-0 mt-2 max-w-xl text-sm text-[#abb3bf]">
              Assessment controls remain active. Operational records render on the Mapbox basemap when the provider token is present.
            </p>
          </div>
          <Tag intent={Intent.WARNING}>provider offline</Tag>
        </div>
        <div className="mt-4 grid grid-cols-2 gap-2 md:grid-cols-4">
          <MapPendingMetric label="Fires" value={context?.fires.length ?? 0} />
          <MapPendingMetric label="Roads" value={context?.road_events.length ?? 0} />
          <MapPendingMetric label="Shelters" value={context?.shelters.length ?? 0} />
          <MapPendingMetric label="Routes" value={assessment?.plan.routes.length ?? 0} />
        </div>
      </div>
    </div>
  );
}

function MapPendingMetric({ label, value }: { label: string; value: number }) {
  return (
    <div className="border border-[#30404f] bg-[#111a23] p-3">
      <p className="m-0 text-xs uppercase tracking-wide text-[#8f99a8]">{label}</p>
      <p className="m-0 mt-1 text-2xl font-semibold">{value}</p>
    </div>
  );
}
