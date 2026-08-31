import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import Card from "../components/Card";
import PillButton from "../components/PillButton";
import FieldLabel from "../components/FieldLabel";
import PhoneInput, { toE164, validateNumber } from "../components/PhoneInput";
import logoMark from "../assets/ringback-mark.png";
import { createCase, listCountries } from "../api";

// Namibia is the reference deployment, so it's the default - but a judge
// testing from anywhere else needs their own dial code, not a hardcoded
// +264 they can't get past. Full list comes from the backend
// (app/data/countries.json), not hardcoded here, since CALL-E has already
// expanded its supported-country list once since this was built.
const DEFAULT_COUNTRY = "NA";

export default function IntakePage() {
  const [countries, setCountries] = useState([]);
  const [countryCode, setCountryCode] = useState(DEFAULT_COUNTRY);
  const [phoneLocal, setPhoneLocal] = useState("");
  const [callerName, setCallerName] = useState("");
  const [query, setQuery] = useState("");
  const [studentNumber, setStudentNumber] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    listCountries()
      .then(setCountries)
      .catch(() => {
        // Falls back to just Namibia if the list can't be fetched - the
        // form still works for the reference deployment either way.
        setCountries([{ code: "NA", name: "Namibia", calling_code: "264", line_region: "international" }]);
      });
  }, []);

  const selectedCountry = countries.find((c) => c.code === countryCode);

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");

    if (!selectedCountry) {
      setError("Choose a country.");
      return;
    }
    const numberError = validateNumber(phoneLocal);
    if (numberError) {
      setError(numberError);
      return;
    }
    if (!query.trim()) {
      setError("Let us know what you need help with.");
      return;
    }
    if (!callerName.trim()) {
      setError("Let us know your name.");
      return;
    }

    const phone = toE164(selectedCountry, phoneLocal);
    setSubmitting(true);
    try {
      const res = await createCase({
        phone,
        country_code: countryCode,
        caller_name: callerName.trim(),
        query: query.trim(),
        student_number: studentNumber.trim() || null,
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
    <>
      <div className="mobile-topbar mobile-topbar--split">
        <div className="brand-row" style={{ marginBottom: 0 }}>
          <img src={logoMark} alt="" className="brand-mark" />
          <span className="brand-name">Ringback</span>
        </div>
        <Link to="/dashboard" className="text-link text-link--inline">Staff dashboard</Link>
      </div>
      <div className="page page--mobile">
        <h1 className="page-heading">Ask the Registrar's office</h1>
        <p className="page-subheading">We'll call you back. No queue, no hold.</p>

        <Card>
          <form onSubmit={handleSubmit} className="intake-form">
            <div className="field">
              <FieldLabel>Phone number</FieldLabel>
              {countries.length > 0 && (
                <PhoneInput
                  countries={countries}
                  countryCode={countryCode}
                  onCountryChange={setCountryCode}
                  number={phoneLocal}
                  onNumberChange={setPhoneLocal}
                />
              )}
            </div>

            <div className="field">
              <FieldLabel>Your name</FieldLabel>
              <input
                placeholder="Your full name"
                value={callerName}
                onChange={(e) => setCallerName(e.target.value)}
              />
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

            <PillButton
              type="submit"
              variant="primary"
              className="full-width pill-button--tall"
              disabled={submitting}
            >
              {submitting ? "Requesting…" : "Request a callback"}
            </PillButton>
            <p className="form-note">Usually under 2 minutes</p>
          </form>
        </Card>
      </div>
    </>
  );
}
