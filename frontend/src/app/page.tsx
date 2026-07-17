import Link from "next/link";

import { EvidenceTopology } from "@/components/evidence-topology";
import { JudgeTour } from "@/components/judge-tour";

const METHOD_HYPOTHESES = [
  { rank: 1, label: "Adds the written second operand", prediction: -9 },
  { rank: 2, label: "Uses a non-negative magnitude difference", prediction: 5 },
] as const;

export default function HomePage() {
  return (
    <article className="landing-page">
      <section className="hero" aria-labelledby="hero-heading">
        <div className="hero-copy">
          <p className="eyebrow">
            <span>Education</span>
            <span>Signed-integer subtraction</span>
          </p>
          <h1 id="hero-heading">
            625 problems.
            <span>One teacher-controlled probe.</span>
          </h1>
          <p className="hero-summary">
            The compiler scans the frozen 25 by 25 domain, excludes the original problem to leave
            624 eligible follow-ups, and persists the deterministic rank-one separator.
          </p>
          <div className="hero-actions">
            <Link className="primary-action" href="/lab">
              <span aria-hidden="true">↗</span>
              Run the live evidence tour
            </Link>
            <a className="text-action" href="#method">
              Inspect the method
            </a>
          </div>
          <div className="claim-guard">
            <span className="claim-guard__mark" aria-hidden="true">!</span>
            <p>
              The compiler proves disagreement between formalized rules. It does not prove a
              learner&apos;s cognitive state.
            </p>
          </div>
        </div>

        <div className="hero-instrument" aria-label="Worked compiler example">
          <div className="instrument-index mono">
            <span>OBS / 01</span>
            <span>BOUNDED DOMAIN −12…12</span>
          </div>
          <EvidenceTopology
            label="Worked compiler example"
            statusLabel="Illustration · deterministic"
            probeLabel="−2 − (−7)"
            teacherStage="Teacher reviews"
            learnerStage="One signed integer"
            updateStage="Exact matching"
            hypotheses={METHOD_HYPOTHESES}
          />
        </div>
      </section>

      <JudgeTour currentStage="case-input" />

      <section id="method" className="method-section" aria-labelledby="method-heading">
        <div className="section-heading">
          <p className="eyebrow">One controlled evidence loop</p>
          <h2 id="method-heading">Proof begins after constrained model mapping.</h2>
        </div>
        <ol className="method-grid">
          <li>
            <span className="method-number mono">01</span>
            <p className="method-kicker">Constrained mapping</p>
            <h3>GPT maps observed work.</h3>
            <p>
              The model can select only templates from a closed, literature-grounded rule
              registry. Unknown or equivalent rules are rejected.
            </p>
          </li>
          <li>
            <span className="method-number mono">02</span>
            <p className="method-kicker">Deterministic separation</p>
            <h3>The compiler finds the probe.</h3>
            <p>
              A bounded search ranks the smallest problem on which the leading alternatives
              predict different answers.
            </p>
          </li>
          <li>
            <span className="method-number mono">03</span>
            <p className="method-kicker">Human custody</p>
            <h3>The teacher controls release.</h3>
            <p>
              One learner answer updates the evidence exactly; the teacher approves, edits,
              rejects, or abstains.
            </p>
          </li>
        </ol>
      </section>

      <section className="boundary-section" aria-labelledby="boundary-heading">
        <div>
          <p className="eyebrow">The narrow claim</p>
          <h2 id="boundary-heading">Inspect the separation, not a confidence score.</h2>
        </div>
        <div className="boundary-copy">
          <p>
            Every prediction, rule version, compiler version, and probe hash is persisted
            before the learner sees the question. Ambiguous evidence remains unresolved.
          </p>
          <ul className="signal-list">
            <li><span>01</span> Supported</li>
            <li><span>02</span> Weakened</li>
            <li><span>03</span> Unresolved</li>
            <li><span>04</span> Abstained</li>
          </ul>
        </div>
      </section>

      <section className="sources-section" aria-labelledby="sources-heading">
        <p className="eyebrow">Registry grounding</p>
        <h2 id="sources-heading">Published work informs the closed rule registry.</h2>
        <p>
          The current domain is deliberately narrow and still requires educator review before
          public validation claims.
        </p>
        <div className="source-links">
          <a href="https://doi.org/10.1016/j.learninstruc.2004.06.012">Vlassis, 2004</a>
          <a href="https://doi.org/10.5951/jresematheduc.45.2.0194">Bofferding, 2014</a>
          <a href="https://doi.org/10.1177/2158244016671375">Maphosa, 2017</a>
        </div>
      </section>
    </article>
  );
}
