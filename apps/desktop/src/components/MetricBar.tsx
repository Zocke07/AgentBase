/** Small accessible bars used where a percentage is more legible than prose. */

export function MetricBar({ value, label, detail }: { value: number; label: string; detail?: string }) {
  const percent = Math.max(0, Math.min(100, Math.round(value * 100)));
  return (
    <div className="metric-bar">
      <div className="metric-bar__label"><span>{label}</span><strong>{detail ?? `${String(percent)}%`}</strong></div>
      <div className="metric-bar__track" role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent}>
        <span className="metric-bar__fill" style={{ width: `${String(percent)}%` }} />
      </div>
    </div>
  );
}
