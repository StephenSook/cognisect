"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";

import type { components } from "@/lib/api/schema";
import { createBrowserApiClient } from "@/lib/api/browser-client";
import { mutationKey } from "@/lib/idempotency";
import {
  DEFAULT_PUBLIC_EDUCATOR_CASE,
  PUBLIC_EDUCATOR_CASES,
} from "@/lib/public-cases";
import { strictInteger } from "@/lib/validation";

type CaseRequest = components["schemas"]["CreateCaseRequest"];
type CreatedCase = components["schemas"]["CreateCaseResponse"];
type SourceMode = "public_exemplar" | "educator_authored" | "custom";
type FieldErrors = Partial<Record<"first" | "second" | "observed" | "attestation", string>>;

const SOURCE_OPTIONS: { value: SourceMode; label: string }[] = [
  { value: "public_exemplar", label: "COGNISECT educator-authored public exemplar" },
  { value: "educator_authored", label: "Educator-authored free entry" },
  { value: "custom", label: "Custom de-identified entry" },
];

export function LabForm() {
  const router = useRouter();
  const [sourceMode, setSourceMode] = useState<SourceMode>("educator_authored");
  const [publicCaseId, setPublicCaseId] = useState(
    DEFAULT_PUBLIC_EDUCATOR_CASE.record_id,
  );
  const [first, setFirst] = useState("");
  const [second, setSecond] = useState("");
  const [observedWork, setObservedWork] = useState("");
  const [attested, setAttested] = useState(false);
  const [pending, setPending] = useState(false);
  const [commandLocked, setCommandLocked] = useState(false);
  const [caseCommitted, setCaseCommitted] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [error, setError] = useState<string | null>(null);
  const createKey = useRef<string | null>(null);
  const analysisKey = useRef<string | null>(null);
  const createdCase = useRef<CreatedCase | null>(null);
  const caseRequest = useRef<CaseRequest | null>(null);

  function selectSource(next: SourceMode) {
    setSourceMode(next);
    setAttested(false);
    setFieldErrors({});
    if (next === "public_exemplar") {
      setPublicCaseId(DEFAULT_PUBLIC_EDUCATOR_CASE.record_id);
      setFirst(String(DEFAULT_PUBLIC_EDUCATOR_CASE.content.problem.a));
      setSecond(String(DEFAULT_PUBLIC_EDUCATOR_CASE.content.problem.b));
      setObservedWork(DEFAULT_PUBLIC_EDUCATOR_CASE.content.observed_work);
    } else {
      setFirst("");
      setSecond("");
      setObservedWork("");
    }
  }

  function selectPublicCase(recordId: string) {
    const selected = PUBLIC_EDUCATOR_CASES.find(
      (record) => record.record_id === recordId,
    );
    if (selected === undefined) return;
    setPublicCaseId(selected.record_id);
    setFirst(String(selected.content.problem.a));
    setSecond(String(selected.content.problem.b));
    setObservedWork(selected.content.observed_work);
  }

  function prepareRequest(): CaseRequest | null {
    const firstInteger = strictInteger(first, -12, 12);
    const secondInteger = strictInteger(second, -12, 12);
    const nextErrors: FieldErrors = {};
    if (firstInteger === null) nextErrors.first = "Enter an integer from -12 through 12.";
    if (secondInteger === null) nextErrors.second = "Enter an integer from -12 through 12.";
    const trimmedWork = observedWork.trim();
    if (!trimmedWork) nextErrors.observed = "Observed work is required.";
    else if (observedWork.length > 10_000) {
      nextErrors.observed = "Observed work must be 10,000 characters or fewer.";
    }
    if (sourceMode === "custom" && !attested) {
      nextErrors.attestation =
        "Confirm that custom content is de-identified before continuing.";
    }
    setFieldErrors(nextErrors);
    if (Object.keys(nextErrors).length > 0 || firstInteger === null || secondInteger === null) {
      return null;
    }
    return {
      source_tier: sourceMode === "custom" ? "custom" : "educator_authored",
      problem: { a: firstInteger, b: secondInteger },
      observed_work: trimmedWork,
      deidentified_attestation: sourceMode === "custom" ? attested : false,
    };
  }

  async function submit() {
    if (caseRequest.current === null) {
      const prepared = prepareRequest();
      if (prepared === null) return;
      caseRequest.current = prepared;
      setCommandLocked(true);
    }

    setPending(true);
    setError(null);
    const client = createBrowserApiClient();
    try {
      let created = createdCase.current;
      if (created === null) {
        const result = await client.POST("/v1/cases", {
          params: { header: { "Idempotency-Key": mutationKey(createKey) } },
          body: caseRequest.current,
        });
        if (result.data === undefined) {
          setError(
            result.response.status === 428
              ? "The private owner session is ready. Retry sends the exact locked command."
              : "The case was not accepted. Retry sends the exact locked command.",
          );
          return;
        }
        created = result.data;
        createdCase.current = created;
        setCaseCommitted(true);
      }
      const analysis = await client.POST("/v1/cases/{case_id}/analysis", {
        params: {
          path: { case_id: created.case_id },
          header: { "Idempotency-Key": mutationKey(analysisKey) },
        },
        body: { expected_version: 0 },
      });
      if (analysis.data === undefined) {
        setError("Analysis did not complete. Retry sends the exact locked command.");
        return;
      }
      router.push(`/case/${analysis.data.workflow_id}`);
    } catch {
      setError("The request could not reach the service. You can retry safely.");
    } finally {
      setPending(false);
    }
  }

  const fieldsLocked = commandLocked || caseCommitted;
  return (
    <form
      className="case-form"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        void submit();
      }}
    >
      <div className="form-section-heading">
        <span className="mono">01</span>
        <div>
          <h2>Source and evidence</h2>
          <p>Choose the provenance tier before entering the observed work.</p>
        </div>
      </div>
      <label htmlFor="source-tier">Case source</label>
      <select
        id="source-tier"
        name="source_tier"
        value={sourceMode}
        disabled={fieldsLocked}
        onChange={(event) => selectSource(event.target.value as SourceMode)}
      >
        {SOURCE_OPTIONS.map((source) => (
          <option key={source.value} value={source.value}>
            {source.label}
          </option>
        ))}
      </select>
      {sourceMode === "public_exemplar" ? (
        <>
          <label htmlFor="public-case">Public case</label>
          <select
            id="public-case"
            name="public_case"
            value={publicCaseId}
            disabled={fieldsLocked}
            onChange={(event) => selectPublicCase(event.target.value)}
          >
            {PUBLIC_EDUCATOR_CASES.map((record) => (
              <option key={record.record_id} value={record.record_id}>
                {record.record_id}: {record.content.problem.a} − {record.content.problem.b}
              </option>
            ))}
          </select>
          <p className="field-note">
            Educator-authored public exemplar {publicCaseId}. It is not learner work or a
            published student record.
          </p>
        </>
      ) : null}

      <fieldset className="operand-fields">
        <legend>Subtraction problem</legend>
        <div>
          <label htmlFor="first-integer">First integer</label>
          <input
            id="first-integer"
            name="a"
            inputMode="numeric"
            required
            value={first}
            readOnly={sourceMode === "public_exemplar"}
            disabled={fieldsLocked}
            aria-describedby={fieldErrors.first ? "first-integer-error" : undefined}
            onChange={(event) => setFirst(event.target.value)}
          />
          {fieldErrors.first ? (
            <p id="first-integer-error" role="alert">{fieldErrors.first}</p>
          ) : null}
        </div>
        <span className="operand-symbol" aria-hidden="true">−</span>
        <div>
          <label htmlFor="second-integer">Second integer</label>
          <input
            id="second-integer"
            name="b"
            inputMode="numeric"
            required
            value={second}
            readOnly={sourceMode === "public_exemplar"}
            disabled={fieldsLocked}
            aria-describedby={fieldErrors.second ? "second-integer-error" : undefined}
            onChange={(event) => setSecond(event.target.value)}
          />
          {fieldErrors.second ? (
            <p id="second-integer-error" role="alert">{fieldErrors.second}</p>
          ) : null}
        </div>
      </fieldset>

      <label htmlFor="observed-work">Observed work</label>
      <textarea
        id="observed-work"
        name="observed_work"
        rows={5}
        required
        maxLength={10_000}
        value={observedWork}
        readOnly={sourceMode === "public_exemplar"}
        disabled={fieldsLocked}
        aria-describedby={fieldErrors.observed ? "observed-work-error" : undefined}
        onChange={(event) => setObservedWork(event.target.value)}
      />
      {fieldErrors.observed ? (
        <p id="observed-work-error" role="alert">{fieldErrors.observed}</p>
      ) : null}

      {sourceMode === "custom" ? (
        <>
          <label>
            <input
              name="deidentified_attestation"
              type="checkbox"
              checked={attested}
              disabled={fieldsLocked}
              aria-describedby={fieldErrors.attestation ? "attestation-error" : undefined}
              onChange={(event) => setAttested(event.target.checked)}
            />
            I confirm this custom content is de-identified and contains no learner identity.
          </label>
          {fieldErrors.attestation ? (
            <p id="attestation-error" role="alert">{fieldErrors.attestation}</p>
          ) : null}
        </>
      ) : null}

      {error === null ? null : <p className="form-alert" role="alert">{error}</p>}
      {commandLocked ? (
        <p>The command fields are locked so every retry sends the exact same request.</p>
      ) : null}
      {caseCommitted ? <p>The case is saved; retry runs only analysis.</p> : null}
      <p aria-live="polite">{pending ? "Creating and analyzing the case…" : ""}</p>
      <button className="primary-button" type="submit" disabled={pending}>
        {commandLocked ? "Retry exact command" : "Create and analyze"}
      </button>
    </form>
  );
}
