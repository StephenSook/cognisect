type TopologyHypothesis = {
  rank: number;
  label: string;
  prediction: number | null;
};

type EvidenceTopologyProps = {
  label: string;
  statusLabel: string;
  probeLabel: string;
  teacherStage: string;
  learnerStage: string;
  updateStage: string;
  hypotheses: readonly TopologyHypothesis[];
};

function signed(value: number | null): string {
  if (value === null) return "Unresolved";
  return String(value).replace("-", "−");
}

export function EvidenceTopology({
  label,
  statusLabel,
  probeLabel,
  teacherStage,
  learnerStage,
  updateStage,
  hypotheses,
}: EvidenceTopologyProps) {
  const centerY = 96 + (Math.max(hypotheses.length, 1) - 1) * 35;
  const stageY = Math.max(centerY + 150, 250);
  const viewHeight = stageY + 88;

  return (
    <figure className="evidence-topology" role="group" aria-label={label}>
      <div className="topology-heading">
        <figcaption>{label}</figcaption>
        <span className="telemetry-pill telemetry-pill--verified">{statusLabel}</span>
      </div>
      <svg
        className="topology-map"
        viewBox={`0 0 820 ${viewHeight}`}
        aria-hidden="true"
        focusable="false"
      >
        <g className="topology-grid">
          {Array.from({ length: 8 }, (_, index) => (
            <line key={`vertical-${index}`} x1={20 + index * 112} y1="20" x2={20 + index * 112} y2={viewHeight - 20} />
          ))}
          {Array.from({ length: 5 }, (_, index) => (
            <line key={`horizontal-${index}`} x1="20" y1={28 + index * 72} x2="800" y2={28 + index * 72} />
          ))}
        </g>
        <g className="topology-traces">
          {hypotheses.map((hypothesis, index) => {
            const y = 70 + index * 74;
            return (
              <line
                key={`trace-${hypothesis.rank}`}
                x1="246"
                y1={y + 28}
                x2="350"
                y2={centerY + 36}
              />
            );
          })}
          <line x1="548" y1={centerY + 36} x2="628" y2={centerY + 36} />
          <path d={`M707 ${centerY + 64} V${stageY - 18} H170 V${stageY}`} />
          <line x1="276" y1={stageY + 28} x2="304" y2={stageY + 28} />
          <line x1="516" y1={stageY + 28} x2="544" y2={stageY + 28} />
        </g>
        <g className="topology-nodes">
          {hypotheses.map((hypothesis, index) => {
            const y = 70 + index * 74;
            return (
              <g key={hypothesis.rank} transform={`translate(34 ${y})`}>
                <rect className="topology-node topology-node--hypothesis" width="212" height="56" rx="2" />
                <text className="topology-kicker" x="16" y="22">
                  HYP {String(hypothesis.rank).padStart(2, "0")}
                </text>
                <text className="topology-value" x="16" y="43">
                  PREDICTS {signed(hypothesis.prediction)}
                </text>
              </g>
            );
          })}
          <g transform={`translate(350 ${centerY - 18})`}>
            <rect className="topology-node topology-node--compiler" width="198" height="108" rx="2" />
            <text className="topology-kicker topology-kicker--dark" x="18" y="28">
              DETERMINISTIC
            </text>
            <text className="topology-compiler-title" x="18" y="57">
              COUNTEREXAMPLE
            </text>
            <text className="topology-compiler-title" x="18" y="80">
              COMPILER
            </text>
            <text className="topology-compiler-foot" x="18" y="98">
              BOUNDED SEARCH
            </text>
          </g>
          <g transform={`translate(628 ${centerY + 8})`}>
            <rect className="topology-node topology-node--probe" width="158" height="56" rx="28" />
            <text className="topology-kicker" x="79" y="20" textAnchor="middle">
              PROBE
            </text>
            <text className="topology-probe-value" x="79" y="42" textAnchor="middle">
              {probeLabel}
            </text>
          </g>
          <g transform={`translate(64 ${stageY})`}>
            <rect className="topology-node topology-node--approval" width="212" height="56" rx="2" />
            <text className="topology-kicker" x="16" y="20">TEACHER GATE</text>
            <text className="topology-stage-value" x="16" y="42">{teacherStage}</text>
          </g>
          <g transform={`translate(304 ${stageY})`}>
            <rect className="topology-node topology-node--learner" width="212" height="56" rx="2" />
            <text className="topology-kicker" x="16" y="20">LEARNER RESPONSE</text>
            <text className="topology-stage-value" x="16" y="42">{learnerStage}</text>
          </g>
          <g transform={`translate(544 ${stageY})`}>
            <rect className="topology-node topology-node--update" width="212" height="56" rx="2" />
            <text className="topology-kicker" x="16" y="20">EVIDENCE UPDATE</text>
            <text className="topology-stage-value" x="16" y="42">{updateStage}</text>
          </g>
        </g>
      </svg>
      <details className="topology-fallback">
        <summary>Open evidence table</summary>
        <div className="table-scroll">
          <table aria-label={`${label} table`}>
            <thead>
              <tr>
                <th scope="col">Stage</th>
                <th scope="col">Evidence</th>
                <th scope="col">Output</th>
              </tr>
            </thead>
            <tbody>
              {hypotheses.map((hypothesis) => (
                <tr key={hypothesis.rank}>
                  <th scope="row">Hypothesis {hypothesis.rank}</th>
                  <td>{hypothesis.label}</td>
                  <td>{signed(hypothesis.prediction)}</td>
                </tr>
              ))}
              <tr>
                <th scope="row">Compiled probe</th>
                <td>Smallest ranked separating problem</td>
                <td>{probeLabel}</td>
              </tr>
              <tr>
                <th scope="row">Teacher approval</th>
                <td>Human release gate</td>
                <td>{teacherStage}</td>
              </tr>
              <tr>
                <th scope="row">Learner response</th>
                <td>One strict signed integer</td>
                <td>{learnerStage}</td>
              </tr>
              <tr>
                <th scope="row">Evidence update</th>
                <td>Exact prediction matching</td>
                <td>{updateStage}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </details>
    </figure>
  );
}
