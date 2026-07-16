"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";

import type { components } from "@/lib/api/schema";
import { createBrowserApiClient } from "@/lib/api/browser-client";
import { mutationKey } from "@/lib/idempotency";
import { strictInteger } from "@/lib/validation";

type SourceTier = components["schemas"]["CreateCaseRequest"]["source_tier"];
type CaseRequest = components["schemas"]["CreateCaseRequest"];
type CreatedCase = components["schemas"]["CreateCaseResponse"];

const SOURCE_TIERS: { value: SourceTier; label: string }[] = [
  { value: "educator_authored", label: "Educator authored" },
  { value: "custom", label: "Custom" },
];

export function LabForm() {
  const router = useRouter();
  const [sourceTier, setSourceTier] = useState<SourceTier>("educator_authored");
  const [pending, setPending] = useState(false);
  const [caseCommitted, setCaseCommitted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const createKey = useRef<string | null>(null);
  const analysisKey = useRef<string | null>(null);
  const createdCase = useRef<CreatedCase | null>(null);
  const caseRequest = useRef<CaseRequest | null>(null);

  async function submit(formData: FormData) {
    if (createdCase.current === null) {
      const first = strictInteger(String(formData.get("a") ?? ""), -12, 12);
      const second = strictInteger(String(formData.get("b") ?? ""), -12, 12);
      const observedWork = String(formData.get("observed_work") ?? "").trim();
      const attested = formData.get("deidentified_attestation") === "on";
      if (first === null || second === null) {
        setError("Each problem value must be a whole integer from -12 through 12.");
        return;
      }
      if (!observedWork) {
        setError("Observed work is required.");
        return;
      }
      if (sourceTier === "custom" && !attested) {
        setError("Confirm that custom content is de-identified before continuing.");
        return;
      }
      caseRequest.current = {
        source_tier: sourceTier,
        problem: { a: first, b: second },
        observed_work: observedWork,
        deidentified_attestation: attested,
      };
    }

    setPending(true);
    setError(null);
    const client = createBrowserApiClient();
    try {
      let created = createdCase.current;
      if (created === null) {
        if (caseRequest.current === null) throw new Error("case request is unavailable");
        const result = await client.POST("/v1/cases", {
          params: { header: { "Idempotency-Key": mutationKey(createKey) } },
          body: caseRequest.current,
        });
        if (result.data === undefined) {
          setError("The case was not accepted. Review the fields and retry.");
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
        setError("Analysis did not complete. You can retry the same command safely.");
        return;
      }
      router.push(`/case/${analysis.data.workflow_id}`);
    } catch {
      setError("The request could not reach the service. You can retry safely.");
    } finally {
      setPending(false);
    }
  }

  return (
    <form
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        void submit(new FormData(event.currentTarget));
      }}
    >
      <label htmlFor="source-tier">Source tier</label>
      <select
        id="source-tier"
        name="source_tier"
        value={sourceTier}
        disabled={caseCommitted}
        onChange={(event) => setSourceTier(event.target.value as SourceTier)}
      >
        {SOURCE_TIERS.map((tier) => (
          <option key={tier.value} value={tier.value}>
            {tier.label}
          </option>
        ))}
      </select>

      <label htmlFor="first-integer">First integer</label>
      <input
        id="first-integer"
        name="a"
        inputMode="numeric"
        required
        disabled={caseCommitted}
      />

      <label htmlFor="second-integer">Second integer</label>
      <input
        id="second-integer"
        name="b"
        inputMode="numeric"
        required
        disabled={caseCommitted}
      />

      <label htmlFor="observed-work">Observed work</label>
      <textarea
        id="observed-work"
        name="observed_work"
        rows={5}
        required
        disabled={caseCommitted}
      />

      {sourceTier === "custom" ? (
        <label>
          <input
            name="deidentified_attestation"
            type="checkbox"
            disabled={caseCommitted}
          />
          I confirm this custom content is de-identified and contains no learner identity.
        </label>
      ) : null}

      {error === null ? null : <p role="alert">{error}</p>}
      {caseCommitted ? <p>The case is saved; retry runs only analysis.</p> : null}
      <p aria-live="polite">{pending ? "Creating and analyzing the case…" : ""}</p>
      <button type="submit" disabled={pending}>
        Create and analyze
      </button>
    </form>
  );
}
