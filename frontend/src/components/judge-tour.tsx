const TOUR_STAGES = [
  ["case-input", "Public case input"],
  ["model-mapping", "Constrained GPT mapping"],
  ["compiler-scan", "625-domain deterministic scan"],
  ["teacher-gate-one", "First teacher gate"],
  ["learner-handoff", "Learner handoff"],
  ["evidence-update", "Exact evidence update"],
  ["teacher-gate-two", "Second teacher gate"],
  ["evidence-receipt", "Evidence receipt"],
] as const;

export type JudgeTourStage = (typeof TOUR_STAGES)[number][0];

export function JudgeTour({ currentStage }: { currentStage: JudgeTourStage }) {
  const currentIndex = TOUR_STAGES.findIndex(([stage]) => stage === currentStage);
  return (
    <nav className="judge-tour" aria-label="Live evidence tour">
      <div className="judge-tour-heading">
        <span className="mono">LIVE / REAL API</span>
        <strong>Judge path</strong>
      </div>
      <ol>
        {TOUR_STAGES.map(([stage, label], index) => (
          <li key={stage} data-stage={index < currentIndex ? "complete" : index === currentIndex ? "current" : "next"}>
            <span className="judge-tour-index mono">{String(index + 1).padStart(2, "0")}</span>
            <span aria-current={index === currentIndex ? "step" : undefined}>{label}</span>
          </li>
        ))}
      </ol>
    </nav>
  );
}
