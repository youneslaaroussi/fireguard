import { Card, Checkbox, FormGroup, HTMLSelect, InputGroup, NumericInput, Slider } from "@blueprintjs/core";
import type { ReplayRequest } from "../types";
import { sources } from "./state";

type Props = {
  value: ReplayRequest;
  onChange: (value: ReplayRequest) => void;
};

export function Controls({ value, onChange }: Props) {
  function patch(next: Partial<ReplayRequest>) {
    onChange({ ...value, ...next });
  }

  function toggleSource(source: string) {
    const next = value.sources.includes(source)
      ? value.sources.filter((item) => item !== source)
      : [...value.sources, source];
    patch({ sources: next });
  }

  return (
    <aside className="sidePane">
      <Card>
        <FormGroup label="Latitude">
          <NumericInput fill value={value.latitude} minorStepSize={0.000001} onValueChange={(n) => patch({ latitude: n })} />
        </FormGroup>
        <FormGroup label="Longitude">
          <NumericInput fill value={value.longitude} minorStepSize={0.000001} onValueChange={(n) => patch({ longitude: n })} />
        </FormGroup>
        <FormGroup label="Radius km">
          <NumericInput fill min={1} max={2000} value={value.radius_km} onValueChange={(n) => patch({ radius_km: n })} />
        </FormGroup>
        <FormGroup label="Start">
          <InputGroup type="date" value={value.start_date} onChange={(e) => patch({ start_date: e.currentTarget.value })} />
        </FormGroup>
        <FormGroup label="End">
          <InputGroup type="date" value={value.end_date} onChange={(e) => patch({ end_date: e.currentTarget.value })} />
        </FormGroup>
        <FormGroup label={`Speed: 1s = ${value.speed.toLocaleString()}s`}>
          <Slider min={60} max={86400} stepSize={60} labelStepSize={21600} value={value.speed} onChange={(n) => patch({ speed: n })} />
        </FormGroup>
        <FormGroup label="Event limit">
          <HTMLSelect fill value={value.limit} onChange={(e) => patch({ limit: Number(e.currentTarget.value) })}>
            <option value={1000}>1,000</option>
            <option value={5000}>5,000</option>
            <option value={10000}>10,000</option>
            <option value={25000}>25,000</option>
          </HTMLSelect>
        </FormGroup>
        <FormGroup label="Sources">
          {sources.map((source) => (
            <Checkbox key={source} checked={value.sources.includes(source)} label={source} onChange={() => toggleSource(source)} />
          ))}
        </FormGroup>
      </Card>
    </aside>
  );
}
