import type { FireEvent } from "../types";

type Props = {
  events: FireEvent[];
};

export function EventStream({ events }: Props) {
  const feed = events.slice(-14);
  const first = events[0]?.acquired_at;
  const latest = events[events.length - 1]?.acquired_at;

  return (
    <div className="eventFeed">
      <div className="eventLines">
        {feed.map((event, i) => {
          const opacity = feed.length <= 1 ? 0.72 : 0.22 + (i / (feed.length - 1)) * 0.58;
          return (
            <div
              key={`${event.source}-${event.acquired_at}-${event.latitude}-${event.longitude}-${i}`}
              className="eventLine"
              style={{ opacity }}
            >
              <span className="evTime">{event.acquired_at.slice(11, 16)}</span>
              <span className="evSrc">{abbrevSrc(event.source)}</span>
              <span className="evCoord">{event.latitude.toFixed(3)},{event.longitude.toFixed(3)}</span>
              {event.frp != null && <span className="evFrp">FRP:{event.frp.toFixed(1)}</span>}
              {event.bcws?.incident?.incident_name && (
                <span className="evBcws">{event.bcws.incident.incident_name}</span>
              )}
            </div>
          );
        })}
      </div>
      <div className="eventCounter">
        {events.length.toLocaleString()} EVT
        {first && latest && (
          <>
            &nbsp;·&nbsp;
            {formatStamp(first)} / {formatStamp(latest)}
          </>
        )}
      </div>
    </div>
  );
}

function abbrevSrc(s: string) {
  return s
    .replace("VIIRS_NOAA20_SP", "V20S")
    .replace("VIIRS_NOAA21_SP", "V21S")
    .replace("VIIRS_SNPP_SP", "VCSS")
    .replace("VIIRS_NOAA20_NRT", "V20")
    .replace("VIIRS_NOAA21_NRT", "V21")
    .replace("VIIRS_SNPP_NRT", "VCS")
    .replace("MODIS_NRT", "MOD");
}

function formatStamp(value: string) {
  return value.slice(5, 16).replace("T", " ");
}
