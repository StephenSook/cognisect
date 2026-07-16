import Link from "next/link";

export default function HomePage() {
  return (
    <article>
      <h1>Counterexamples for teacher review</h1>
      <p>
        COGNISECT maps de-identified signed-integer work to bounded hypotheses, then uses a
        deterministic compiler to find a problem that separates represented alternatives.
      </p>
      <p>
        It does not diagnose a learner or prove a cognitive state. A teacher controls probe
        release and the final note.
      </p>
      <p>
        The closed registry is narrowly grounded in published work on negative-integer
        reasoning and interpretations of the minus sign, including {" "}
        <a href="https://doi.org/10.1016/j.learninstruc.2004.06.012">Vlassis (2004)</a>, {" "}
        <a href="https://doi.org/10.5951/jresematheduc.45.2.0194">Bofferding (2014)</a>, and {" "}
        <a href="https://doi.org/10.1177/2158244016671375">Maphosa (2017)</a>. Educator review
        is still required before public validation claims.
      </p>
      <p>
        <Link href="/lab">Open the teacher lab</Link>
      </p>
    </article>
  );
}
