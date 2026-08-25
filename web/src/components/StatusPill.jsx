const STATUS_STYLES = {
  received: { bg: "var(--border)", fg: "var(--grey600)", label: "Received" },
  classified: { bg: "var(--border)", fg: "var(--grey600)", label: "Classified" },
  calling: { bg: "var(--amber-tint)", fg: "var(--amber)", label: "Calling" },
  resolved: { bg: "var(--green-tint)", fg: "var(--green)", label: "Resolved" },
  routed: { bg: "var(--blue-tint)", fg: "var(--blue)", label: "Routed" },
  failed: { bg: "var(--red-tint)", fg: "var(--red)", label: "Failed" },
};

export default function StatusPill({ status }) {
  const style = STATUS_STYLES[status] || STATUS_STYLES.received;
  return (
    <span className="status-pill" style={{ background: style.bg, color: style.fg }}>
      <span className="status-pill__dot" style={{ background: style.fg }} />
      {style.label}
    </span>
  );
}
