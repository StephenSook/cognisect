import type { Metadata } from "next";

import { LabForm } from "@/components/lab-form";

export const metadata: Metadata = { title: "Teacher lab" };

export default function LabPage() {
  return (
    <article className="workbench lab-workbench">
      <header className="workbench-heading">
        <div>
          <p className="eyebrow eyebrow--ink">New evidence case</p>
          <h1>Teacher lab</h1>
          <p>
            Select the provenance-cleared public exemplar or enter de-identified work for one
            signed-integer subtraction problem.
          </p>
        </div>
        <span className="domain-seal mono">a − b<br />−12…12</span>
      </header>
      <aside className="privacy-note">
        <span aria-hidden="true">◇</span>
        <p>
          No roster or learner identifier is collected. Custom content requires an explicit
          de-identification attestation.
        </p>
      </aside>
      <LabForm />
    </article>
  );
}
