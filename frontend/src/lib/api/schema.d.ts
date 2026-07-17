export interface paths {
    "/health": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Health Route */
        get: operations["health_route_health_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/ready": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Ready Route */
        get: operations["ready_route_ready_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/cases": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Create Case Route */
        post: operations["create_case_route_v1_cases_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/cases/{case_id}/analysis": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Analyze Case Route */
        post: operations["analyze_case_route_v1_cases__case_id__analysis_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/respond/{token}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Learner Probe Route */
        get: operations["get_learner_probe_route_v1_respond__token__get"];
        put?: never;
        /** Submit Learner Route */
        post: operations["submit_learner_route_v1_respond__token__post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/workflows/{workflow_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Workflow Route */
        get: operations["get_workflow_route_v1_workflows__workflow_id__get"];
        put?: never;
        post?: never;
        /** Delete Workflow Route */
        delete: operations["delete_workflow_route_v1_workflows__workflow_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/workflows/{workflow_id}/audit": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Audit Route */
        get: operations["audit_route_v1_workflows__workflow_id__audit_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/workflows/{workflow_id}/probe-approval": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Approve Probe Route */
        post: operations["approve_probe_route_v1_workflows__workflow_id__probe_approval_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/workflows/{workflow_id}/receipt": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Receipt Route */
        get: operations["receipt_route_v1_workflows__workflow_id__receipt_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/workflows/{workflow_id}/review": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Review Workflow Route */
        post: operations["review_workflow_route_v1_workflows__workflow_id__review_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/version": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Version Route */
        get: operations["version_route_version_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
}
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /**
         * AcceptedHypothesisResponse
         * @description One persisted teacher-visible accepted hypothesis.
         */
        AcceptedHypothesisResponse: {
            /** Description */
            description: string;
            /** Evidence Refs */
            evidence_refs: string[];
            /** Rank */
            rank: number;
            /** Template Id */
            template_id: string;
            /** Truth Table Hash */
            truth_table_hash: string;
        };
        /**
         * AnalysisRequest
         * @description CAS input for an analysis command.
         */
        AnalysisRequest: {
            /**
             * Expected Version
             * @default 0
             */
            expected_version: number;
        };
        /**
         * AnswerConstraints
         * @description Strict numeric bounds disclosed to a learner.
         */
        AnswerConstraints: {
            /**
             * Maximum
             * @default 10000
             * @constant
             */
            maximum: 10000;
            /**
             * Minimum
             * @default -10000
             * @constant
             */
            minimum: -10000;
        };
        /**
         * AuditEventResponse
         * @description One append-only transition event.
         */
        AuditEventResponse: {
            /** From State */
            from_state: string | null;
            /**
             * Occurred At
             * Format: date-time
             */
            occurred_at: string;
            /** Sequence */
            sequence: number;
            /** To State */
            to_state: string;
            /** Version */
            version: number;
        };
        /**
         * AuditResponse
         * @description Complete transition readback for one owned workflow.
         */
        AuditResponse: {
            /** Events */
            events: components["schemas"]["AuditEventResponse"][];
            /**
             * Workflow Id
             * Format: uuid
             */
            workflow_id: string;
        };
        /**
         * CompiledProbeResponse
         * @description The persisted deterministic probe specification shown only to teachers.
         */
        CompiledProbeResponse: {
            /** Compiler Version */
            compiler_version: string;
            /** Correct Prediction */
            correct_prediction: number;
            original_problem: components["schemas"]["SignedProblemDTO"];
            /** Predictions */
            predictions: components["schemas"]["ProbePredictionResponse"][];
            problem: components["schemas"]["SignedProblemDTO"];
            proof: components["schemas"]["CompilerSearchProof"];
            /** Registry Version */
            registry_version: string;
            /** Specification Hash */
            specification_hash: string;
        };
        /**
         * CompilerCandidateProof
         * @description One ranked separating candidate exposed to the authorized teacher.
         */
        CompilerCandidateProof: {
            /** Correct Result Magnitude */
            correct_result_magnitude: number;
            /** Distinct Output Count */
            distinct_output_count: number;
            /** Distinguished Pair Count */
            distinguished_pair_count: number;
            /** Operand Magnitude */
            operand_magnitude: number;
            /** Predictions */
            predictions: number[];
            problem: components["schemas"]["SignedProblemDTO"];
            /** Rank */
            rank: number;
            /** Top Two Separated */
            top_two_separated: boolean;
        };
        /**
         * CompilerSearchProof
         * @description Complete bounded-domain counts and up to five deterministic finalists.
         */
        CompilerSearchProof: {
            /**
             * Chosen Candidate Rank
             * @constant
             */
            chosen_candidate_rank: 1;
            /**
             * Domain Problem Count
             * @constant
             */
            domain_problem_count: 625;
            /**
             * Eligible Candidate Count
             * @constant
             */
            eligible_candidate_count: 624;
            /** Separating Candidate Count */
            separating_candidate_count: number;
            /** Top Candidates */
            top_candidates: components["schemas"]["CompilerCandidateProof"][];
        };
        /**
         * CreateCaseRequest
         * @description A de-identified teacher case without learner identity fields.
         */
        CreateCaseRequest: {
            /**
             * Deidentified Attestation
             * @default false
             */
            deidentified_attestation: boolean;
            /** Observed Work */
            observed_work: string;
            problem: components["schemas"]["SignedProblemDTO"];
            /** Provenance Record Id */
            provenance_record_id?: string | null;
            /**
             * Source Tier
             * @enum {string}
             */
            source_tier: "authentic" | "synthetic" | "mixed" | "published_exemplar" | "educator_authored" | "custom";
        };
        /**
         * CreateCaseResponse
         * @description Opaque identifiers for the newly owned case and workflow.
         */
        CreateCaseResponse: {
            /**
             * Case Id
             * Format: uuid
             */
            case_id: string;
            /**
             * Workflow Id
             * Format: uuid
             */
            workflow_id: string;
        };
        /**
         * ErrorResponse
         * @description Strict JSON envelope for public string-detail failures.
         */
        ErrorResponse: {
            /** Detail */
            detail: string;
        };
        /**
         * EvidenceReceiptHypothesis
         * @description One prose-free closed-registry hypothesis proof.
         */
        EvidenceReceiptHypothesis: {
            /** Rank */
            rank: number;
            /** Template Id */
            template_id: string;
            /** Truth Table Hash */
            truth_table_hash: string;
        };
        /**
         * EvidenceReceiptResponse
         * @description Owner-authorized receipt with a canonical payload hash.
         */
        EvidenceReceiptResponse: {
            /** Accepted Hypotheses */
            accepted_hypotheses: components["schemas"]["EvidenceReceiptHypothesis"][];
            /** Audit Events */
            audit_events: components["schemas"]["AuditEventResponse"][];
            /**
             * Case Id
             * Format: uuid
             */
            case_id: string;
            compiled_probe: components["schemas"]["CompiledProbeResponse"] | null;
            /** Compiler Version */
            compiler_version: string;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /** Deterministic Evidence */
            deterministic_evidence: components["schemas"]["EvidenceStatusResponse"][];
            /** Prompt Version */
            prompt_version: string;
            /** Provenance Record Id */
            provenance_record_id: string | null;
            /** Receipt Hash */
            receipt_hash: string;
            /**
             * Receipt Version
             * @default evidence_receipt.v1
             * @constant
             */
            receipt_version: "evidence_receipt.v1";
            /** Registry Version */
            registry_version: string;
            /** Review Decision */
            review_decision: ("approved" | "edited" | "rejected" | "abstained") | null;
            /** Reviewed At */
            reviewed_at: string | null;
            /** Schema Version */
            schema_version: string;
            /**
             * Source Tier
             * @enum {string}
             */
            source_tier: "authentic" | "synthetic" | "mixed" | "published_exemplar" | "educator_authored" | "custom";
            /** State */
            state: string;
            /**
             * Updated At
             * Format: date-time
             */
            updated_at: string;
            /**
             * Workflow Id
             * Format: uuid
             */
            workflow_id: string;
            /** Workflow Version */
            workflow_version: number;
        };
        /**
         * EvidenceStatusResponse
         * @description One deterministic status from the closed evidence vocabulary.
         */
        EvidenceStatusResponse: {
            /** Rank */
            rank: number;
            /**
             * Status
             * @enum {string}
             */
            status: "supported" | "weakened" | "unresolved" | "abstained";
            /** Template Id */
            template_id: string;
        };
        /** HTTPValidationError */
        HTTPValidationError: {
            /** Detail */
            detail?: components["schemas"]["ValidationError"][];
        };
        /**
         * LearnerProbeResponse
         * @description Deliberately minimal learner-facing DTO.
         */
        LearnerProbeResponse: {
            answer_constraints: components["schemas"]["AnswerConstraints"];
            /**
             * Expires At
             * Format: date-time
             */
            expires_at: string;
            /**
             * Instructions
             * @default Submit one signed integer.
             * @constant
             */
            instructions: "Submit one signed integer.";
            problem: components["schemas"]["SignedProblemDTO"];
        };
        /**
         * LearnerReceiptResponse
         * @description Content-minimal receipt for the accepted response.
         */
        LearnerReceiptResponse: {
            /**
             * Accepted At
             * Format: date-time
             */
            accepted_at: string;
            /**
             * Receipt Id
             * Format: uuid
             */
            receipt_id: string;
        };
        /**
         * LearnerSubmitRequest
         * @description Strict one-answer learner submission.
         */
        LearnerSubmitRequest: {
            /** Answer */
            answer: number;
            /** Rationale */
            rationale?: string | null;
        };
        /**
         * LearnerTokenResponse
         * @description Teacher decision result with a capability only when the probe is approved.
         */
        LearnerTokenResponse: {
            /** Expires At */
            expires_at: string | null;
            /** Response Url */
            response_url: string | null;
            workflow: components["schemas"]["WorkflowResponse"];
        };
        /**
         * OwnerBootstrapResponse
         * @description Privacy-safe signal that an owner session exists before mutation.
         */
        OwnerBootstrapResponse: {
            /**
             * Detail
             * @default owner session initialized; retry the exact command
             * @constant
             */
            detail: "owner session initialized; retry the exact command";
        };
        /**
         * ProbeApprovalRequest
         * @description Teacher decision at the first workflow interrupt.
         */
        ProbeApprovalRequest: {
            /** Approved */
            approved: boolean;
            /** Expected Version */
            expected_version: number;
            /**
             * Expires In Seconds
             * @default 86400
             */
            expires_in_seconds: number;
        };
        /**
         * ProbePredictionResponse
         * @description One persisted alternative prediction committed with the probe.
         */
        ProbePredictionResponse: {
            /** Prediction */
            prediction: number;
            /** Rank */
            rank: number;
            /** Template Id */
            template_id: string;
        };
        /**
         * ReviewRequest
         * @description Teacher decision at the final workflow interrupt.
         */
        ReviewRequest: {
            /**
             * Decision
             * @enum {string}
             */
            decision: "approved" | "edited" | "rejected" | "abstained";
            /** Edited Text */
            edited_text?: string | null;
            /** Expected Version */
            expected_version: number;
            /** Note */
            note?: string | null;
        };
        /**
         * ReviewResultResponse
         * @description The persisted final teacher decision and separately stored edit.
         */
        ReviewResultResponse: {
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /**
             * Decision
             * @enum {string}
             */
            decision: "approved" | "edited" | "rejected" | "abstained";
            /** Edited Text */
            edited_text: string | null;
            /** Note */
            note: string | null;
        };
        /**
         * SignedProblemDTO
         * @description One signed-subtraction problem in the frozen compiler domain.
         */
        SignedProblemDTO: {
            /** A */
            a: number;
            /** B */
            b: number;
        };
        /** ValidationError */
        ValidationError: {
            /** Context */
            ctx?: Record<string, never>;
            /** Input */
            input?: unknown;
            /** Location */
            loc: (string | number)[];
            /** Message */
            msg: string;
            /** Error Type */
            type: string;
        };
        /**
         * VersionResponse
         * @description Public build and deterministic-contract versions.
         */
        VersionResponse: {
            /** Compiler Version */
            compiler_version: string;
            /** Registry Version */
            registry_version: string;
            /** Schema Version */
            schema_version: string;
            /** Source Revision */
            source_revision: string;
            /** Version */
            version: string;
        };
        /**
         * WorkflowResponse
         * @description Teacher-facing workflow snapshot with reproducibility metadata.
         */
        WorkflowResponse: {
            /** Accepted Hypotheses */
            accepted_hypotheses: components["schemas"]["AcceptedHypothesisResponse"][];
            /**
             * Case Id
             * Format: uuid
             */
            case_id: string;
            compiled_probe: components["schemas"]["CompiledProbeResponse"] | null;
            /** Compiler Version */
            compiler_version: string;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /** Deterministic Evidence */
            deterministic_evidence: components["schemas"]["EvidenceStatusResponse"][];
            /** Edited Text */
            edited_text?: string | null;
            /** Generated Proposal */
            generated_proposal?: string | null;
            /** Learner Rationale */
            learner_rationale: string | null;
            /** Learner Response Url */
            learner_response_url: string | null;
            /** Model Request Id */
            model_request_id: string | null;
            /** Model Response Id */
            model_response_id: string | null;
            /** Model Snapshot */
            model_snapshot: string | null;
            /** Prompt Version */
            prompt_version: string;
            /** Provenance Record Id */
            provenance_record_id: string | null;
            /** Registry Version */
            registry_version: string;
            review_result: components["schemas"]["ReviewResultResponse"] | null;
            /** Schema Version */
            schema_version: string;
            /**
             * Source Tier
             * @enum {string}
             */
            source_tier: "authentic" | "synthetic" | "mixed" | "published_exemplar" | "educator_authored" | "custom";
            /** State */
            state: string;
            /**
             * Updated At
             * Format: date-time
             */
            updated_at: string;
            /** Version */
            version: number;
            /**
             * Workflow Id
             * Format: uuid
             */
            workflow_id: string;
        };
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
    health_route_health_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: string;
                    };
                };
            };
        };
    };
    ready_route_ready_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: string;
                    };
                };
            };
            /** @description Not ready */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    create_case_route_v1_cases_post: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
            };
            path?: never;
            cookie?: {
                cognisect_owner?: string | null;
            };
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CreateCaseRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CreateCaseResponse"];
                };
            };
            /** @description Invalid proxy identity */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
            /** @description Owner session initialized before educational mutation */
            428: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["OwnerBootstrapResponse"];
                };
            };
            /** @description Fixed-window request quota exceeded */
            429: {
                headers: {
                    /** @description Seconds until the current quota window expires */
                    "Retry-After"?: number;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    analyze_case_route_v1_cases__case_id__analysis_post: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
            };
            path: {
                case_id: string;
            };
            cookie?: {
                cognisect_owner?: string | null;
            };
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AnalysisRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["WorkflowResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
            /** @description Fixed-window request quota exceeded */
            429: {
                headers: {
                    /** @description Seconds until the current quota window expires */
                    "Retry-After"?: number;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    get_learner_probe_route_v1_respond__token__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                token: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LearnerProbeResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    submit_learner_route_v1_respond__token__post: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
            };
            path: {
                token: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["LearnerSubmitRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LearnerReceiptResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_workflow_route_v1_workflows__workflow_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workflow_id: string;
            };
            cookie?: {
                cognisect_owner?: string | null;
            };
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["WorkflowResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_workflow_route_v1_workflows__workflow_id__delete: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
            };
            path: {
                workflow_id: string;
            };
            cookie?: {
                cognisect_owner?: string | null;
            };
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    audit_route_v1_workflows__workflow_id__audit_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workflow_id: string;
            };
            cookie?: {
                cognisect_owner?: string | null;
            };
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AuditResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    approve_probe_route_v1_workflows__workflow_id__probe_approval_post: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
            };
            path: {
                workflow_id: string;
            };
            cookie?: {
                cognisect_owner?: string | null;
            };
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ProbeApprovalRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LearnerTokenResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    receipt_route_v1_workflows__workflow_id__receipt_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workflow_id: string;
            };
            cookie?: {
                cognisect_owner?: string | null;
            };
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["EvidenceReceiptResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    review_workflow_route_v1_workflows__workflow_id__review_post: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
            };
            path: {
                workflow_id: string;
            };
            cookie?: {
                cognisect_owner?: string | null;
            };
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ReviewRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["WorkflowResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    version_route_version_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["VersionResponse"];
                };
            };
        };
    };
}
