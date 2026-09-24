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

export function MemoryStatusBar({ proposed, approved, archived }: { proposed: number; approved: number; archived: number }) {
  const total = proposed + approved + archived;
  const width = (value: number) => total === 0 ? "0%" : `${String((value / total) * 100)}%`;
  return (
    <div className="memory-status-viz" role="img" aria-label={`Memory status: ${String(proposed)} proposed, ${String(approved)} approved, ${String(archived)} archived`}>
      <div className="memory-status-viz__bar">
        <span className="memory-status-viz__segment memory-status-viz__segment--proposed" style={{ width: width(proposed) }} />
        <span className="memory-status-viz__segment memory-status-viz__segment--approved" style={{ width: width(approved) }} />
        <span className="memory-status-viz__segment memory-status-viz__segment--archived" style={{ width: width(archived) }} />
      </div>
      <div className="memory-status-viz__legend">
        <span><i className="memory-status-viz__key memory-status-viz__key--proposed" />{proposed} proposed</span>
        <span><i className="memory-status-viz__key memory-status-viz__key--approved" />{approved} approved</span>
        <span><i className="memory-status-viz__key memory-status-viz__key--archived" />{archived} archived</span>
      </div>
    </div>
  );
}
