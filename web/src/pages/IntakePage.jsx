import { useState } from "react";
import { useNavigate } from "react-router-dom";
import Card from "../components/Card";
import PillButton from "../components/PillButton";
import FieldLabel from "../components/FieldLabel";

export default function IntakePage() {
  const [phoneLocal, setPhoneLocal] = useState("");
  const [query, setQuery] = useState("");
  const [studentNumber, setStudentNumber] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const navigate = useNavigate();

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");

    const digits = phoneLocal.replace(/\D/g, "").replace(/^0+/, "");
    if (digits.length < 7) {
      setError("Enter a valid Namibian phone number.");
      return;
    }
    if (!query.trim()) {
      setError("Let us know what you need help with.");
      return;
    }

    const phone = `+264${digits}`;
    setSubmitting(true);
    try {
      const res = await fetch("/api/cases", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          phone,
          query: query.trim(),
          student_number: studentNumber.trim() || null,
        }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || "Something went wrong. Please try again.");
      }
      navigate("/confirmation", { state: { phone } });
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="page page--mobile">
      <div className="brand-row">
        <span className="brand-mark" />
        <span className="brand-name">Ringback</span>
      </div>

      <h1 className="page-heading">Ask the Registrar's office</h1>
      <p className="page-subheading">We'll call you back. No queue, no hold.</p>

      <Card>
        <form onSubmit={handleSubmit} className="intake-form">
          <div className="field">
            <FieldLabel>Phone number</FieldLabel>
            <div className="phone-input">
              <span className="phone-input__prefix mono">+264</span>
              <input
                className="phone-input__number mono"
                inputMode="numeric"
                placeholder="81 234 5678"
                value={phoneLocal}
                onChange={(e) => setPhoneLocal(e.target.value)}
              />
            </div>
          </div>

          <div className="field">
            <FieldLabel>What do you need help with?</FieldLabel>
            <textarea
              rows={4}
              placeholder="Type your question in your own words"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>

          <div className="field">
            <FieldLabel hint="optional">Student number</FieldLabel>
            <input
              className="mono"
              placeholder="220012345"
              value={studentNumber}
              onChange={(e) => setStudentNumber(e.target.value)}
            />
            <p className="field-help">If you're already registered</p>
          </div>

          {error && <p className="form-error">{error}</p>}

          <PillButton type="submit" variant="primary" className="full-width" disabled={submitting}>
            {submitting ? "Requesting…" : "Request a callback"}
          </PillButton>
          <p className="form-note">Usually under 2 minutes</p>
        </form>
      </Card>
    </div>
  );
}
