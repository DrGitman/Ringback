export default function FieldLabel({ children, hint }) {
  return (
    <label className="field-label">
      {children}
      {hint && <span> · {hint}</span>}
    </label>
  );
}
