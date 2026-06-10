export const sources = ["VIIRS_NOAA20_NRT", "VIIRS_SNPP_NRT", "VIIRS_NOAA21_NRT", "MODIS_NRT"];

export function dateString(offsetDays: number) {
  const d = new Date(Date.now() + offsetDays * 86_400_000);
  return d.toISOString().slice(0, 10);
}

