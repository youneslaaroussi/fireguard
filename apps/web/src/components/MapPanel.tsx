"use client";

import { Button, ButtonGroup, Intent, Tag } from "@blueprintjs/core";
import { useEffect, useMemo, useRef, useState } from "react";
import mapboxgl, { GeoJSONSource, Map } from "mapbox-gl";

import type { AssessmentResult, IncidentContext, RouteOption } from "@/lib/types";

type Props = {
  context: IncidentContext | null;
  assessment: AssessmentResult | null;
};

type LayerKey = "fires" | "perimeters" | "roads" | "zones" | "shelters" | "routes" | "public";

const MAPBOX_TOKEN = process.env.NEXT_PUBLIC_MAPBOX_TOKEN || "";

const LAYER_IDS: Record<LayerKey, string[]> = {
  fires: ["fires"],
  perimeters: ["perimeters-fill", "perimeters-line"],
  roads: ["roads"],
  zones: ["zones-fill", "zones-line"],
  shelters: ["shelters"],
  routes: ["routes"],
  public: ["public-orders", "public-ess"],
};

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
  for (const collection of Object.values(collections)) {
    collection.features.forEach((feature) => visit(feature.geometry.coordinates));
  }
  return count ? bounds : null;
}

function buildCollections(context: IncidentContext | null, assessment: AssessmentResult | null) {
  const empty = { type: "FeatureCollection" as const, features: [] };
  if (!context) {
    return { zones: empty, shelters: empty, fires: empty, roads: empty, perimeters: empty, publicOrders: empty, publicEss: empty, routes: empty };
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
  for (const sourceId of ["perimeters", "zones", "roads", "routes", "fires", "shelters", "public-orders", "public-ess"]) {
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

function featureHtml(properties: mapboxgl.GeoJSONFeature["properties"]) {
  if (!properties) return "<strong>Operational record</strong>";
  const rows = Object.entries(properties)
    .filter(([, value]) => value !== undefined && value !== null && String(value).length > 0)
    .slice(0, 6)
    .map(([key, value]) => `<div style="display:flex;gap:8px;justify-content:space-between;"><span style="color:#8f99a8">${key}</span><span>${String(value)}</span></div>`)
    .join("");
  return `<div style="min-width:220px"><strong>${String(properties.label || properties.id || "Operational record")}</strong><div style="margin-top:8px;display:grid;gap:4px;">${rows}</div></div>`;
}

export function MapPanel({ context, assessment }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<Map | null>(null);
  const [layersOpen, setLayersOpen] = useState(false);
  const [visible, setVisible] = useState<Record<LayerKey, boolean>>({
    fires: true,
    perimeters: true,
    roads: true,
    zones: true,
    shelters: true,
    routes: true,
    public: true,
  });

  const collections = useMemo(() => buildCollections(context, assessment), [context, assessment]);
  const mapboxConfigured = Boolean(MAPBOX_TOKEN);

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
      style: "mapbox://styles/mapbox/dark-v11",
    });

    map.addControl(new mapboxgl.NavigationControl({ showCompass: true }), "top-left");
    map.addControl(new mapboxgl.AttributionControl({ compact: true }), "bottom-right");

    map.on("load", () => {
      map.setFog?.({
        color: "rgb(16, 22, 30)",
        "high-color": "rgb(45, 65, 88)",
        "horizon-blend": 0.12,
      });
      addSourcesAndLayers(map);
      for (const layerId of ["fires", "shelters", "public-orders", "public-ess", "routes", "roads"]) {
        map.on("click", layerId, (event) => {
          const feature = event.features?.[0];
          if (!feature || !event.lngLat) return;
          new mapboxgl.Popup({ closeButton: true, closeOnClick: true })
            .setLngLat(event.lngLat)
            .setHTML(featureHtml(feature.properties))
            .addTo(map);
        });
        map.on("mouseenter", layerId, () => {
          map.getCanvas().style.cursor = "pointer";
        });
        map.on("mouseleave", layerId, () => {
          map.getCanvas().style.cursor = "";
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
    if (!map) return;
    const apply = () => {
      addSourcesAndLayers(map);
      setSourceData(map, "zones", collections.zones);
      setSourceData(map, "shelters", collections.shelters);
      setSourceData(map, "fires", collections.fires);
      setSourceData(map, "roads", collections.roads);
      setSourceData(map, "perimeters", collections.perimeters);
      setSourceData(map, "public-orders", collections.publicOrders);
      setSourceData(map, "public-ess", collections.publicEss);
      setSourceData(map, "routes", collections.routes);
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
    for (const [layerKey, layerIds] of Object.entries(LAYER_IDS) as Array<[LayerKey, string[]]>) {
      for (const layerId of layerIds) {
        if (map.getLayer(layerId)) {
          map.setLayoutProperty(layerId, "visibility", visible[layerKey] ? "visible" : "none");
        }
      }
    }
  }, [visible]);

  return (
    <section className="fireguard-map-panel">
      {mapboxConfigured ? <div ref={containerRef} className="absolute inset-0" /> : <MapboxTokenPending context={context} assessment={assessment} />}
      <div className="absolute right-4 top-4 max-w-[460px]">
        <div className="fireguard-map-layer-control shadow-lg">
          <Button small icon="layers" text="Layers" onClick={() => setLayersOpen((open) => !open)} />
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
    </section>
  );
}

function MapLegendItem({ tone, label }: { tone: "fire" | "road" | "shelter" | "zone" | "route-safe" | "route-blocked"; label: string }) {
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
            <h3 className="m-0 text-lg font-semibold">Map basemap unavailable</h3>
            <p className="m-0 mt-2 max-w-xl text-sm text-[#abb3bf]">
              The assessment workflow is still available. Operational records will render on the Mapbox basemap once the map provider is connected for this deployment.
            </p>
          </div>
          <Tag intent={Intent.WARNING}>map provider pending</Tag>
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
