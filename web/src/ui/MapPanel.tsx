import { useEffect, useMemo, useRef, useState } from "react";
import { Card, NonIdealState } from "@blueprintjs/core";
import mapboxgl, { type GeoJSONSource, type Map } from "mapbox-gl";
import type { BcwsContext, FireEvent } from "../types";

type Props = {
  token: string;
  events: FireEvent[];
  context: BcwsContext;
};

export function MapPanel({ token, events, context }: Props) {
  const container = useRef<HTMLDivElement | null>(null);
  const map = useRef<Map | null>(null);
  const [loaded, setLoaded] = useState(false);
  const data = useMemo(() => toFeatureCollection(events), [events]);
  const incidentData = useMemo(() => toIncidentCollection(context), [context]);
  const perimeterData = useMemo(() => toPerimeterCollection(context), [context]);
  const windLines = useMemo(() => toWindLineCollection(events), [events]);
  const windHeads = useMemo(() => toWindHeadCollection(events), [events]);

  useEffect(() => {
    if (!token || !container.current || map.current) return;
    mapboxgl.accessToken = token;
    map.current = new mapboxgl.Map({
      container: container.current,
      style: "mapbox://styles/mapbox/dark-v11",
      center: [-123.1207, 49.2827],
      zoom: 5.5,
      attributionControl: true
    });
    map.current.addControl(new mapboxgl.NavigationControl({ showCompass: false }), "top-right");
    map.current.on("load", () => {
      if (!map.current) return;
      map.current.addSource("firms-events", {
        type: "geojson",
        data
      });
      map.current.addSource("bcws-perimeters", {
        type: "geojson",
        data: perimeterData
      });
      map.current.addSource("bcws-incidents", {
        type: "geojson",
        data: incidentData
      });
      map.current.addLayer({
        id: "bcws-perimeters-fill",
        type: "fill",
        source: "bcws-perimeters",
        paint: {
          "fill-color": "#ffb366",
          "fill-opacity": 0.18
        }
      });
      map.current.addLayer({
        id: "bcws-perimeters-outline",
        type: "line",
        source: "bcws-perimeters",
        paint: {
          "line-color": "#ffd27f",
          "line-width": 2,
          "line-opacity": 0.9
        }
      });
      map.current.addLayer({
        id: "firms-events-heat",
        type: "heatmap",
        source: "firms-events",
        paint: {
          "heatmap-weight": ["interpolate", ["linear"], ["coalesce", ["get", "frp"], 0], 0, 0.2, 50, 1],
          "heatmap-intensity": 0.85,
          "heatmap-radius": 22,
          "heatmap-opacity": 0.65
        }
      });
      map.current.addLayer({
        id: "firms-events-points",
        type: "circle",
        source: "firms-events",
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["coalesce", ["get", "frp"], 0], 0, 4, 50, 10],
          "circle-color": "#f15b43",
          "circle-stroke-width": 1,
          "circle-stroke-color": "#ffd7a1",
          "circle-opacity": 0.9
        }
      });
      map.current.addLayer({
        id: "bcws-incidents",
        type: "circle",
        source: "bcws-incidents",
        paint: {
          "circle-radius": 7,
          "circle-color": [
            "match",
            ["get", "status"],
            "Out of Control",
            "#e5484d",
            "Being Held",
            "#f2b84b",
            "Under Control",
            "#2dcc70",
            "Out",
            "#7f8b99",
            "#ffffff"
          ],
          "circle-stroke-width": 2,
          "circle-stroke-color": "#10161d",
          "circle-opacity": 0.95
        }
      });
      map.current.addSource("wind-vectors", {
        type: "geojson",
        data: windLines
      });
      map.current.addSource("wind-vector-heads", {
        type: "geojson",
        data: windHeads
      });
      map.current.addLayer({
        id: "wind-vectors",
        type: "line",
        source: "wind-vectors",
        paint: {
          "line-color": "#6bbcff",
          "line-width": 2,
          "line-opacity": 0.85
        }
      });
      map.current.addLayer({
        id: "wind-vector-heads",
        type: "circle",
        source: "wind-vector-heads",
        paint: {
          "circle-radius": 3,
          "circle-color": "#9fd4ff",
          "circle-opacity": 0.95
        }
      });
      setLoaded(true);
    });
    return () => {
      map.current?.remove();
      map.current = null;
      setLoaded(false);
    };
  }, [token]);

  useEffect(() => {
    const instance = map.current;
    if (!instance || !loaded || !instance.isStyleLoaded()) return;
    const source = instance.getSource("firms-events") as GeoJSONSource | undefined;
    const incidentSource = instance.getSource("bcws-incidents") as GeoJSONSource | undefined;
    const perimeterSource = instance.getSource("bcws-perimeters") as GeoJSONSource | undefined;
    const windSource = instance.getSource("wind-vectors") as GeoJSONSource | undefined;
    const windHeadSource = instance.getSource("wind-vector-heads") as GeoJSONSource | undefined;
    source?.setData(data);
    incidentSource?.setData(incidentData);
    perimeterSource?.setData(perimeterData);
    windSource?.setData(windLines);
    windHeadSource?.setData(windHeads);
    const bounds = boundsFor(events, context);
    if (bounds) {
      instance.fitBounds(bounds, { padding: 48, maxZoom: 9, duration: 400 });
    }
  }, [context, data, events, incidentData, loaded, perimeterData, windHeads, windLines]);

  if (!token) {
    return (
      <Card className="mapPane">
        <NonIdealState icon="map" title="Mapbox token missing" />
      </Card>
    );
  }

  return (
    <Card className="mapPane">
      <div ref={container} className="mapCanvas" />
      <div className="mapLegend">
        <span><i className="legendDot firmsDot" />FIRMS</span>
        <span><i className="legendDot bcwsDot" />BCWS incident</span>
        <span><i className="legendLine" />BCWS perimeter</span>
        <span><i className="legendLine windLine" />Wind</span>
      </div>
    </Card>
  );
}

function toIncidentCollection(context: BcwsContext): GeoJSON.FeatureCollection {
  return {
    type: "FeatureCollection",
    features: context.incidents.flatMap((incident) => {
      if (incident.latitude == null || incident.longitude == null) return [];
      return [
        {
          type: "Feature" as const,
          geometry: {
            type: "Point" as const,
            coordinates: [incident.longitude, incident.latitude]
          },
          properties: {
            number: incident.fire_number ?? "",
            name: incident.incident_name ?? "",
            status: incident.fire_status ?? "",
            size: incident.current_size_ha ?? 0
          }
        }
      ];
    })
  };
}

function toPerimeterCollection(context: BcwsContext): GeoJSON.FeatureCollection {
  return {
    type: "FeatureCollection",
    features: context.perimeters.flatMap((perimeter) => {
      if (!perimeter.geometry) return [];
      return [
        {
          type: "Feature" as const,
          geometry: perimeter.geometry,
          properties: {
            number: perimeter.fire_number ?? "",
            status: perimeter.fire_status ?? "",
            size: perimeter.fire_size_hectares ?? 0
          }
        }
      ];
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
      return [
        {
          type: "Feature" as const,
          geometry: {
            type: "LineString" as const,
            coordinates: [[event.longitude, event.latitude], end]
          },
          properties: {
            speed: weather.wind_speed_10m,
            direction: weather.wind_direction_10m,
            source: weather.source
          }
        }
      ];
    })
  };
}

function toWindHeadCollection(events: FireEvent[]): GeoJSON.FeatureCollection {
  return {
    type: "FeatureCollection",
    features: events.flatMap((event) => {
      const weather = event.weather;
      if (!weather || weather.wind_speed_10m == null || weather.wind_direction_10m == null) return [];
      return [
        {
          type: "Feature" as const,
          geometry: {
            type: "Point" as const,
            coordinates: windEndpoint(event.longitude, event.latitude, weather.wind_direction_10m, weather.wind_speed_10m)
          },
          properties: {
            speed: weather.wind_speed_10m,
            direction: weather.wind_direction_10m,
            source: weather.source
          }
        }
      ];
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

function toFeatureCollection(events: FireEvent[]): GeoJSON.FeatureCollection {
  return {
    type: "FeatureCollection",
    features: events.map((event) => ({
      type: "Feature",
      geometry: {
        type: "Point",
        coordinates: [event.longitude, event.latitude]
      },
      properties: {
        source: event.source,
        acquired_at: event.acquired_at,
        confidence: event.confidence ?? "",
        frp: event.frp ?? 0
      }
    }))
  };
}

function boundsFor(events: FireEvent[], context: BcwsContext) {
  if (!events.length && !context.incidents.length && !context.perimeters.length) return null;
  const bounds = new mapboxgl.LngLatBounds();
  for (const event of events) {
    bounds.extend([event.longitude, event.latitude]);
  }
  for (const incident of context.incidents) {
    if (incident.latitude != null && incident.longitude != null) {
      bounds.extend([incident.longitude, incident.latitude]);
    }
  }
  for (const perimeter of context.perimeters) {
    extendGeometryBounds(bounds, perimeter.geometry);
  }
  return bounds;
}

function extendGeometryBounds(bounds: mapboxgl.LngLatBounds, geometry?: GeoJSON.Geometry) {
  if (!geometry) return;
  if (geometry.type === "Polygon") {
    for (const ring of geometry.coordinates) {
      for (const coordinate of ring) bounds.extend(coordinate as [number, number]);
    }
  }
  if (geometry.type === "MultiPolygon") {
    for (const polygon of geometry.coordinates) {
      for (const ring of polygon) {
        for (const coordinate of ring) bounds.extend(coordinate as [number, number]);
      }
    }
  }
}
