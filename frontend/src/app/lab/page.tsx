import type { Metadata } from "next";

import { LabForm } from "@/components/lab-form";

export const metadata: Metadata = { title: "Teacher lab" };

export default function LabPage() {
  return (
    <article>
      <h1>Teacher lab</h1>
      <p>
        Select the provenance-cleared COGNISECT educator-authored public exemplar, enter your
        own educator-authored work, or attest de-identified custom work for one subtraction
        problem.
      </p>
      <LabForm />
    </article>
  );
}
