import { useEffect, useMemo, useRef, useState } from "react";
import { Card, HTMLTable, NonIdealState, Tag } from "@blueprintjs/core";
import type { BcwsMatch, FireEvent, WeatherResult } from "../types";

type Props = {
  events: FireEvent[];
  runId: number;
  active: boolean;
  onProgress: (value: number) => void;
};

export function EventStream({ events, runId, active, onProgress }: Props) {
  const [elapsed, setElapsed] = useState(0);
  const duration = useMemo(() => events.length ? Math.max(...events.map((event) => event.replay_second)) : 0, [events]);
  const durationRef = useRef(0);
  const activeRef = useRef(false);

  useEffect(() => {
    durationRef.current = duration;
  }, [duration]);

  useEffect(() => {
    activeRef.current = active;
  }, [active]);

  useEffect(() => {
    setElapsed(0);
    onProgress(0);
    const start = performance.now();
    let frame = 0;
    const loop = () => {
      const currentDuration = durationRef.current;
      const raw = (performance.now() - start) / 1000;
      const next = currentDuration > 0 ? Math.min(raw, currentDuration) : raw;
      setElapsed(next);
      onProgress(currentDuration > 0 ? next / currentDuration : 0);
      if (activeRef.current || next < currentDuration) {
        frame = requestAnimationFrame(loop);
      }
    };
    frame = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(frame);
  }, [runId]);

  const visible = useMemo(() => events.filter((event) => event.replay_second <= elapsed), [events, elapsed]);

  return (
    <Card className="eventPane">
      <div className="eventHeader">
        <div>
          <h2>Replay</h2>
          <span>{visible.length.toLocaleString()} / {events.length.toLocaleString()} events</span>
        </div>
        <Tag minimal intent="warning">{formatClock(elapsed)} / {formatClock(duration)}</Tag>
      </div>
      {!events.length ? (
        <NonIdealState icon="timeline-events" title="No events loaded" description="Collect or replay a selected window." />
      ) : (
        <HTMLTable striped interactive className="eventTable">
          <thead>
            <tr>
              <th>Time</th>
              <th>Source</th>
              <th>Point</th>
              <th>Confidence</th>
              <th>FRP</th>
              <th>Place</th>
              <th>Weather</th>
              <th>BCWS</th>
            </tr>
          </thead>
          <tbody>
            {visible.slice(-200).reverse().map((event, index) => (
              <tr key={`${eventKey(event)}-${index}`}>
                <td>{event.acquired_at}</td>
                <td>{event.source}</td>
                <td>{event.latitude.toFixed(4)}, {event.longitude.toFixed(4)}</td>
                <td>{event.confidence ?? ""}</td>
                <td>{event.frp?.toFixed(2) ?? ""}</td>
                <td>{event.place?.formatted_address ?? ""}</td>
                <td>{formatWeather(event.weather ?? null)}</td>
                <td>{formatBcws(event.bcws)}</td>
              </tr>
            ))}
          </tbody>
        </HTMLTable>
      )}
    </Card>
  );
}

function formatBcws(value?: BcwsMatch) {
  if (!value) return "";
  const incident = value.incident;
  if (incident) {
    const name = incident.incident_name || incident.fire_number || "Incident";
    const distance = incident.distance_km == null ? "" : ` ${incident.distance_km.toFixed(1)} km`;
    const size = incident.current_size_ha == null ? "" : ` ${incident.current_size_ha} ha`;
    return `${name} ${incident.fire_status ?? ""}${size}${distance}`.trim();
  }
  const perimeter = value.perimeter;
  if (perimeter) {
    const size = perimeter.fire_size_hectares == null ? "" : ` ${perimeter.fire_size_hectares} ha`;
    return `${perimeter.fire_number ?? "Perimeter"} ${perimeter.fire_status ?? ""}${size}`.trim();
  }
  return "";
}

function eventKey(event: FireEvent) {
  return `${event.source}-${event.acquired_at}-${event.latitude}-${event.longitude}`;
}

function formatWeather(value: WeatherResult | null) {
  if (!value) return "No weather data";
  const wind = value.wind_speed_10m == null ? "wind n/a" : `${value.wind_speed_10m} km/h`;
  const direction = value.wind_direction_10m == null ? "" : ` ${Math.round(value.wind_direction_10m)} deg`;
  const gusts = value.wind_gusts_10m == null ? "" : ` gust ${value.wind_gusts_10m}`;
  const temp = value.temperature_2m == null ? "" : ` temp ${value.temperature_2m} C`;
  const humidity = value.relative_humidity_2m == null ? "" : ` RH ${value.relative_humidity_2m}%`;
  return `${wind}${direction}${gusts}${temp}${humidity}`;
}

function formatClock(value: number) {
  const minutes = Math.floor(value / 60).toString().padStart(2, "0");
  const seconds = Math.floor(value % 60).toString().padStart(2, "0");
  return `${minutes}:${seconds}`;
}
