"use client";

import { useEffect, useMemo, useRef } from "react";
import maplibregl, { GeoJSONSource, Map } from "maplibre-gl";

import type { AssessmentResult, IncidentContext, RouteOption } from "@/lib/types";

type Props = {
  context: IncidentContext | null;
  assessment: AssessmentResult | null;
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

export function MapPanel({ context, assessment }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<Map | null>(null);

  const collections = useMemo(() => {
    const empty = { type: "FeatureCollection" as const, features: [] };
    if (!context) {
      return { zones: empty, shelters: empty, fires: empty, roads: empty, perimeters: empty, routes: empty };
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
          },
          geometry: perimeter.geometry,
        })),
      },
      routes: {
        type: "FeatureCollection" as const,
        features: assessment?.plan.routes.map(routeFeature) || [],
      },
    };
  }, [context, assessment]);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const map = new maplibregl.Map({
      container: containerRef.current,
      center: [-121.82, 52.45],
      zoom: 8.1,
      attributionControl: false,
      style: {
        version: 8,
        sources: {
          osm: {
            type: "raster",
            tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
            tileSize: 256,
            attribution: "OpenStreetMap",
          },
        },
        layers: [
          {
            id: "osm",
            type: "raster",
            source: "osm",
            paint: { "raster-opacity": 0.42, "raster-saturation": -0.75 },
          },
        ],
      },
    });

    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-left");
    map.on("load", () => {
      for (const sourceId of ["perimeters", "zones", "roads", "routes", "fires", "shelters"]) {
        map.addSource(sourceId, { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      }

      map.addLayer({
        id: "perimeters-fill",
        type: "fill",
        source: "perimeters",
        paint: { "fill-color": "#ff5a2f", "fill-opacity": 0.24 },
      });
      map.addLayer({
        id: "perimeters-line",
        type: "line",
        source: "perimeters",
        paint: { "line-color": "#ff5a2f", "line-width": 3 },
      });
      map.addLayer({
        id: "zones-fill",
        type: "fill",
        source: "zones",
        paint: { "fill-color": "#a878ff", "fill-opacity": 0.22 },
      });
      map.addLayer({
        id: "zones-line",
        type: "line",
        source: "zones",
        paint: { "line-color": "#d4b8ff", "line-width": 2 },
      });
      map.addLayer({
        id: "roads",
        type: "line",
        source: "roads",
        paint: { "line-color": "#ffcc4d", "line-width": 5, "line-dasharray": [1, 0.8] },
      });
      map.addLayer({
        id: "routes",
        type: "line",
        source: "routes",
        paint: {
          "line-color": ["case", ["==", ["get", "safe"], true], "#45d483", "#ff4d4d"],
          "line-width": ["case", ["==", ["get", "safe"], true], 4, 6],
          "line-opacity": 0.85,
        },
      });
      map.addLayer({
        id: "fires",
        type: "circle",
        source: "fires",
        paint: {
          "circle-color": "#ff5a2f",
          "circle-radius": 8,
          "circle-stroke-color": "#ffd1c2",
          "circle-stroke-width": 2,
        },
      });
      map.addLayer({
        id: "shelters",
        type: "circle",
        source: "shelters",
        paint: {
          "circle-color": "#48a7ff",
          "circle-radius": 7,
          "circle-stroke-color": "#d5edff",
          "circle-stroke-width": 2,
        },
      });
    });

    mapRef.current = map;
    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const apply = () => {
      setSourceData(map, "zones", collections.zones);
      setSourceData(map, "shelters", collections.shelters);
      setSourceData(map, "fires", collections.fires);
      setSourceData(map, "roads", collections.roads);
      setSourceData(map, "perimeters", collections.perimeters);
      setSourceData(map, "routes", collections.routes);
    };
    if (map.isStyleLoaded()) apply();
    else map.once("load", apply);
  }, [collections]);

  return (
    <section className="relative min-h-[520px] overflow-hidden border border-line bg-panel">
      <div ref={containerRef} className="absolute inset-0" />
      <div className="absolute left-4 top-4 grid gap-2 text-xs">
        <span className="w-fit border border-line bg-command/90 px-2 py-1 text-slate-100">LIVE/REPLAY OPERATIONAL MAP</span>
        <span className="w-fit border border-fire/50 bg-fire/15 px-2 py-1 text-orange-100">Fire + perimeter</span>
        <span className="w-fit border border-amber/50 bg-amber/15 px-2 py-1 text-amber-100">Road closure</span>
        <span className="w-fit border border-shelter/50 bg-shelter/15 px-2 py-1 text-sky-100">Shelters</span>
      </div>
    </section>
  );
}
