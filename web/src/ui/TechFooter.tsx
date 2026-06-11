import { LOGOS } from "../intelligence/logos";

const ITEMS: Array<{ key: string; src: string; label: string; tone?: string }> = [
  { key: "elastic",    src: LOGOS.elastic.src,    label: "Elastic",                tone: "track" },
  { key: "gcp",        src: "/logos/googlecloud.svg", label: "Google Cloud" },
  { key: "gemini",     src: LOGOS.gemini.src,     label: "Gemini · Vertex AI" },
  { key: "nasa",       src: LOGOS.nasa.src,       label: "NASA FIRMS" },
  { key: "bc",         src: LOGOS.bc.src,         label: "BCWS · BC Gov" },
  { key: "maps",       src: LOGOS.googlemaps.src, label: "Google Maps" },
  { key: "mapbox",     src: "/logos/mapbox.svg",  label: "Mapbox GL" },
];

export function TechFooter() {
  return (
    <footer className="techFooter" aria-label="Built with">
      <span className="techFooterLabel">POWERED BY</span>
      <span className="techFooterSep" aria-hidden="true">/</span>
      <div className="techFooterChips">
        {ITEMS.map((item) => (
          <span
            key={item.key}
            className={`techChip${item.tone === "track" ? " techChip--track" : ""}`}
            title={item.label}
          >
            <img src={item.src} alt="" width={11} height={11} className="techChipLogo" />
            <span className="techChipLabel">{item.label}</span>
          </span>
        ))}
      </div>
      <div className="techFooterFill" />
      <span className="techFooterMeta">
        <span className="techFooterMetaKey">SCENARIO</span>
        <span className="techFooterMetaVal">Williams Lake · BC · Jul 21 2024</span>
      </span>
      <span className="techFooterMeta">
        <span className="techFooterMetaKey">BUILD</span>
        <span className="techFooterMetaVal">v0.9 · hackathon</span>
      </span>
    </footer>
  );
}
