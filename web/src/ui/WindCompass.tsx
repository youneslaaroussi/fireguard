import { memo, useEffect, useState } from "react";
import type { BcwsContext, FireEvent } from "../types";

type Props = {
  events: FireEvent[];
  context: BcwsContext;
};

/**
 * Picks the freshest wind reading from streamed weather observations,
 * falling back to the snapshot included in the BCWS context.
 */
function pickWind(events: FireEvent[], context: BcwsContext) {
  for (let i = events.length - 1; i >= Math.max(0, events.length - 64); i--) {
    const w = events[i]?.weather;
    if (w && w.wind_speed_10m != null && w.wind_direction_10m != null) {
      return {
        speed: w.wind_speed_10m,
        dir: w.wind_direction_10m,
        source: w.source ?? "OBS",
      };
    }
  }
  const snap = context.weather_snapshot;
  if (snap?.wind_speed_kph != null && snap.wind_direction_degrees != null) {
    return { speed: snap.wind_speed_kph, dir: snap.wind_direction_degrees, source: snap.source ?? "FORECAST" };
  }
  return null;
}

function compassName(deg: number): string {
  const dirs = ["N","NNE","NE","ENE","E","ESE","SE","SSE","S","SSW","SW","WSW","W","WNW","NW","NNW"];
  return dirs[Math.round((deg % 360) / 22.5) % 16];
}

export const WindCompass = memo(function WindCompass({ events, context }: Props) {
  const wind = pickWind(events, context);
  const [animatedDir, setAnimatedDir] = useState(wind?.dir ?? 0);

  // Smooth rotation when direction changes
  useEffect(() => {
    if (wind == null) return;
    const target = wind.dir;
    let raf = 0;
    const tick = () => {
      setAnimatedDir((prev) => {
        let delta = target - prev;
        if (delta > 180) delta -= 360;
        if (delta < -180) delta += 360;
        const next = prev + delta * 0.18;
        if (Math.abs(delta) < 0.4) return target;
        raf = requestAnimationFrame(tick);
        return next;
      });
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [wind?.dir, wind]);

  if (!wind) return null;

  const speedClass = wind.speed >= 30 ? "windCompass--gale" : wind.speed >= 15 ? "windCompass--breeze" : "windCompass--calm";

  return (
    <div className={`windCompass ${speedClass}`}>
      <div className="windCompassDial">
        <span className="windCompassN">N</span>
        <span className="windCompassE">E</span>
        <span className="windCompassS">S</span>
        <span className="windCompassW">W</span>
        <div className="windCompassRing" />
        <div
          className="windCompassArrow"
          style={{ transform: `translate(-50%, -50%) rotate(${(animatedDir + 180) % 360}deg)` }}
          aria-hidden="true"
        >
          <svg width="28" height="28" viewBox="0 0 28 28">
            <path d="M14 3l4 8h-3v14h-2V11h-3l4-8z" fill="currentColor"/>
          </svg>
        </div>
      </div>
      <div className="windCompassReadout">
        <div className="windCompassSpeed">{wind.speed.toFixed(0)}<span className="windCompassUnit">kph</span></div>
        <div className="windCompassDir">{compassName(wind.dir)} · {Math.round(wind.dir)}°</div>
      </div>
    </div>
  );
});
