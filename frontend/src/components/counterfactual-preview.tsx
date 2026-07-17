import type { components } from "@/lib/api/schema";

type Hypothesis = components["schemas"]["AcceptedHypothesisResponse"];
type Prediction = components["schemas"]["ProbePredictionResponse"];

function signed(value: number): string {
  return String(value).replace("-", "−");
}

function rankPhrase(ranks: readonly number[]): string {
  if (ranks.length === 1) return `Hypothesis ${ranks[0]}`;
  return `Hypotheses ${ranks.slice(0, -1).join(", ")} and ${ranks.at(-1)}`;
}

export function CounterfactualPreview({
  hypotheses,
  predictions,
}: {
  hypotheses: readonly Hypothesis[];
  predictions: readonly Prediction[];
}) {
  const descriptions = new Map(hypotheses.map((hypothesis) => [hypothesis.rank, hypothesis.description]));
  const grouped = new Map<number, number[]>();
  for (const prediction of predictions) {
    const ranks = grouped.get(prediction.prediction);
    if (ranks === undefined) grouped.set(prediction.prediction, [prediction.rank]);
    else ranks.push(prediction.rank);
  }

  return (
    <section className="counterfactual-preview" aria-labelledby="counterfactual-heading">
      <p className="card-index mono">PREVIEW / PERSISTED PREDICTIONS</p>
      <h3 id="counterfactual-heading">Counterfactual preview, not observed evidence</h3>
      <p>
        These branches describe exact outcomes of the represented procedures before any learner
        response is observed.
      </p>
      <ul className="counterfactual-branches">
        {[...grouped.entries()].map(([answer, ranks]) => {
          const sortedRanks = [...ranks].sort((left, right) => left - right);
          return (
            <li key={answer} aria-label={`If answer ${signed(answer)} were submitted`}>
              <div>
                <span className="mono">IF SUBMITTED</span>
                <strong>{signed(answer)}</strong>
              </div>
              <p>
                {rankPhrase(sortedRanks)} ({sortedRanks.map((rank) => descriptions.get(rank)).join("; ")}):
                {" "}matching represented procedures would be supported and nonmatching ones weakened.
              </p>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
