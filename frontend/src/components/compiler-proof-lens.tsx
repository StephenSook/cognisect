import type { ReactNode } from "react";

import type { components } from "@/lib/api/schema";

type CompiledProbe = components["schemas"]["CompiledProbeResponse"];
type Hypothesis = components["schemas"]["AcceptedHypothesisResponse"];

function signed(value: number): string {
  return String(value).replace("-", "−");
}

function problemLabel(problem: components["schemas"]["SignedProblemDTO"]): string {
  return `${signed(problem.a)} − (${signed(problem.b)})`;
}

function predictionLabel(predictions: readonly number[], hypotheses: readonly Hypothesis[]) {
  const rankedHypotheses = [...hypotheses].sort((left, right) => left.rank - right.rank);
  return rankedHypotheses
    .map((hypothesis, index) => `H${hypothesis.rank}: ${signed(predictions[index]!)}`)
    .join(" · ");
}

export function CompilerProofLens({
  compiledProbe,
  hypotheses,
  custodyGate,
}: {
  compiledProbe: CompiledProbe;
  hypotheses: readonly Hypothesis[];
  custodyGate?: ReactNode;
}) {
  const { proof } = compiledProbe;

  return (
    <div className="proof-lens">
      <div className="domain-grid-wrap" aria-hidden="true">
        <div className="domain-grid" />
        <span className="domain-grid-axis domain-grid-axis--x">b: −12…12</span>
        <span className="domain-grid-axis domain-grid-axis--y">a: −12…12</span>
      </div>
      <p className="sr-only">
        The persisted proof scanned {proof.domain_problem_count} signed subtraction problems,
        excluded the original problem, retained {proof.eligible_candidate_count} eligible
        follow-ups, found {proof.separating_candidate_count} separating candidates, and persisted
        the candidate at rank {proof.chosen_candidate_rank}.
      </p>

      <ol className="proof-sequence" aria-label="Persisted compiler proof sequence">
        <li>
          <span className="proof-step mono">01 / DOMAIN</span>
          <strong data-testid="proof-value">{proof.domain_problem_count}</strong>
          <p>bounded signed-subtraction problems scanned</p>
        </li>
        <li>
          <span className="proof-step mono">02 / ELIGIBLE</span>
          <strong data-testid="proof-value">{proof.eligible_candidate_count}</strong>
          <p>
            follow-ups after <span className="mono">{problemLabel(compiledProbe.original_problem)}</span>
            {" "}was excluded as the original problem
          </p>
        </li>
        <li>
          <span className="proof-step mono">03 / SEPARATING</span>
          <strong data-testid="proof-value">{proof.separating_candidate_count}</strong>
          <p>persisted candidates where represented procedures disagree</p>
        </li>
        <li>
          <span className="proof-step mono">04 / DETERMINISTIC CHOICE</span>
          <strong data-testid="proof-value">Rank {proof.chosen_candidate_rank}</strong>
          <p>selected by the persisted compiler ordering, without a confidence score</p>
        </li>
      </ol>

      <section
        className="chosen-probe"
        data-testid="chosen-probe-reveal"
        aria-labelledby="chosen-probe-heading"
      >
        <div>
          <p className="card-index mono">ONE PERSISTED PROBE</p>
          <h3 id="chosen-probe-heading">Compiled disagreement</h3>
        </div>
        <strong className="chosen-probe-problem mono">{problemLabel(compiledProbe.problem)}</strong>
        <ul aria-label="Persisted predictions for the chosen probe">
          {[...compiledProbe.predictions]
            .sort((left, right) => left.rank - right.rank)
            .map((prediction) => (
              <li key={prediction.rank}>
                <span>H{prediction.rank}</span>
                <strong>{signed(prediction.prediction)}</strong>
              </li>
            ))}
        </ul>
      </section>

      {custodyGate}

      <details className="proof-finalists">
        <summary>Inspect persisted finalists</summary>
        <div className="table-scroll">
          <table aria-label="Persisted compiler finalists">
            <thead>
              <tr>
                <th scope="col">Rank</th>
                <th scope="col">Signed problem</th>
                <th scope="col">Predictions by hypothesis rank</th>
                <th scope="col">Distinct outputs</th>
                <th scope="col">Top two separated</th>
                <th scope="col">Distinguished pairs</th>
                <th scope="col">Operand magnitude</th>
                <th scope="col">Correct-result magnitude</th>
              </tr>
            </thead>
            <tbody>
              {proof.top_candidates.map((candidate) => {
                const chosen = candidate.rank === proof.chosen_candidate_rank;
                return (
                  <tr key={candidate.rank} data-chosen={chosen ? "true" : undefined}>
                    <th scope="row">
                      {candidate.rank}{chosen ? <span className="chosen-label">Chosen</span> : null}
                    </th>
                    <td>{problemLabel(candidate.problem)}</td>
                    <td>{predictionLabel(candidate.predictions, hypotheses)}</td>
                    <td>{candidate.distinct_output_count}</td>
                    <td>{candidate.top_two_separated ? "Yes" : "No"}</td>
                    <td>{candidate.distinguished_pair_count}</td>
                    <td>{candidate.operand_magnitude}</td>
                    <td>{candidate.correct_result_magnitude}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}
