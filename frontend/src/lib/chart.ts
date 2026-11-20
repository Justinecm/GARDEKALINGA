/** Fit the y-axis to the data (and both reference lines) instead of starting at 0. */
export function moistureDomain(points: { mean: number | null; S1: number | null; S2: number | null; S3: number | null }[], pmin: number, thr: number): [number, number] {
  const vals = points.flatMap((p) => [p.mean, p.S1, p.S2, p.S3]).filter((v): v is number => v != null);
  const lo = Math.min(pmin, thr, ...vals);
  const hi = Math.max(pmin, thr, ...vals);
  return [Math.max(0, Math.floor((lo - 3) / 5) * 5), Math.min(100, Math.ceil((hi + 3) / 5) * 5)];
}
