export const sources = ["VIIRS_NOAA20_SP", "VIIRS_SNPP_SP", "MODIS_SP"];

export function dateString(offsetDays: number) {
  const d = new Date(Date.now() + offsetDays * 86_400_000);
  return d.toISOString().slice(0, 10);
}
