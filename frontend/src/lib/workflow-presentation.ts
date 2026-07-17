import type { components } from "@/lib/api/schema";
import type { JudgeTourStage } from "@/components/judge-tour";

type Workflow = components["schemas"]["WorkflowResponse"];

const RESPONSE_PERSISTED_STATES = new Set([
  "RESPONSE_RECORDED",
  "RESUME_PENDING",
  "UPDATING",
  "AWAITING_REVIEW",
  "APPROVED",
  "EDITED",
  "REJECTED",
]);
const UPDATE_IN_PROGRESS_STATES = new Set(["RESPONSE_RECORDED", "RESUME_PENDING", "UPDATING"]);
const FINAL_REVIEW_STATES = new Set(["APPROVED", "EDITED", "REJECTED"]);

export type WorkflowPresentation = {
  judgeStage: JudgeTourStage;
  probeDeclined: boolean;
  teacherStage: string;
  learnerStage: string;
  updateStage: string;
};

export function workflowPresentation(workflow: Workflow): WorkflowPresentation {
  const evidenceStatuses = [
    ...new Set(workflow.deterministic_evidence.map((item) => item.status)),
  ];
  const hasRecordedResponse =
    RESPONSE_PERSISTED_STATES.has(workflow.state) ||
    workflow.deterministic_evidence.length > 0 ||
    workflow.review_result !== null;
  const probeDeclined =
    workflow.state === "ABSTAINED" && workflow.review_result === null && !hasRecordedResponse;

  let judgeStage: JudgeTourStage;
  if (workflow.state === "CREATED" || workflow.state === "ANALYZING") {
    judgeStage = "model-mapping";
  } else if (workflow.state === "PROBE_READY" || probeDeclined) {
    judgeStage = "teacher-gate-one";
  } else if (workflow.state === "AWAITING_RESPONSE") {
    judgeStage = "learner-handoff";
  } else if (UPDATE_IN_PROGRESS_STATES.has(workflow.state)) {
    judgeStage = "evidence-update";
  } else if (workflow.state === "AWAITING_REVIEW") {
    judgeStage = "teacher-gate-two";
  } else if (FINAL_REVIEW_STATES.has(workflow.state) || workflow.state === "ABSTAINED") {
    judgeStage = "evidence-receipt";
  } else if (workflow.state === "FAILED") {
    if (hasRecordedResponse) judgeStage = "evidence-update";
    else if (workflow.learner_response_url !== null) judgeStage = "learner-handoff";
    else if (workflow.compiled_probe !== null) judgeStage = "compiler-scan";
    else judgeStage = "model-mapping";
  } else if (workflow.compiled_probe !== null) {
    judgeStage = "compiler-scan";
  } else {
    judgeStage = "model-mapping";
  }

  const teacherStage = workflow.state === "PROBE_READY"
    ? "Awaiting teacher"
    : probeDeclined
      ? "Abstained"
      : workflow.state === "CREATED" || workflow.state === "ANALYZING"
        ? "Not reached"
        : workflow.state === "FAILED"
          ? "Workflow failed"
          : "Approved for release";

  const learnerStage = hasRecordedResponse
    ? "Response recorded"
    : workflow.state === "AWAITING_RESPONSE"
      ? "Awaiting response"
      : "Not released";

  let updateStage: string;
  if (evidenceStatuses.length > 0) updateStage = evidenceStatuses.join(" / ");
  else if (probeDeclined) updateStage = "No update · abstained";
  else if (workflow.state === "FAILED") updateStage = "Update unavailable · failed";
  else if (UPDATE_IN_PROGRESS_STATES.has(workflow.state)) updateStage = "Update in progress";
  else if (
    workflow.state === "AWAITING_REVIEW" ||
    FINAL_REVIEW_STATES.has(workflow.state) ||
    (workflow.state === "ABSTAINED" && !probeDeclined)
  ) {
    updateStage = "Update complete";
  } else if (workflow.state === "CREATED" || workflow.state === "ANALYZING") {
    updateStage = "Not started";
  } else {
    updateStage = "Pending response";
  }

  return { judgeStage, probeDeclined, teacherStage, learnerStage, updateStage };
}
