import type { Metadata } from "next";

import { LabForm } from "@/components/lab-form";

export const metadata: Metadata = { title: "Teacher lab" };

export default function LabPage() {
  return (
    <article>
      <h1>Teacher lab</h1>
      <p>
        Enter educator-authored work or attested de-identified custom work for one subtraction
        problem. Provenance-cleared built-in records are not yet available in this interface.
      </p>
      <LabForm />
    </article>
  );
}
