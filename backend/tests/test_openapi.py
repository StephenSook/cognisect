"""Frozen OpenAPI artifact drift contract."""

from __future__ import annotations

import json
from pathlib import Path

from cognisect.api import create_app
from cognisect.config import Settings

OPENAPI_PATH = Path(__file__).parents[2] / "openapi" / "openapi.json"


def test_generated_openapi_matches_frozen_artifact():
    settings = Settings(
        app_env="test",
        database_url="postgresql+psycopg://cognisect:cognisect@localhost:54329/cognisect",
        owner_secret_pepper="o" * 32,
        learner_token_pepper="l" * 32,
        public_app_url="http://localhost:3000",
        openai_api_key="",
    )
    generated = create_app(settings=settings, analyzer=None).openapi()
    frozen = json.loads(OPENAPI_PATH.read_text())
    assert generated == frozen


def test_evidence_receipt_preserves_strict_compiler_and_hash_constraints():
    settings = Settings(
        app_env="test",
        database_url="postgresql+psycopg://cognisect:cognisect@localhost:54329/cognisect",
        owner_secret_pepper="o" * 32,
        learner_token_pepper="l" * 32,
        public_app_url="http://localhost:3000",
        openai_api_key="",
    )
    schemas = create_app(settings=settings, analyzer=None).openapi()["components"]["schemas"]
    receipt = schemas["EvidenceReceiptResponse"]["properties"]
    assert receipt["compiled_probe"]["anyOf"][0]["$ref"].endswith(
        "/CompiledProbeResponse"
    )

    compiled = schemas["CompiledProbeResponse"]["properties"]
    assert compiled["proof"]["$ref"].endswith("/CompilerSearchProof")
    assert compiled["specification_hash"] == {
        "maxLength": 64,
        "minLength": 64,
        "pattern": "^[0-9a-f]{64}$",
        "title": "Specification Hash",
        "type": "string",
    }
    prediction_rank = schemas["ProbePredictionResponse"]["properties"]["rank"]
    assert prediction_rank["minimum"] == 1
    assert prediction_rank["maximum"] == 4

    proof = schemas["CompilerSearchProof"]["properties"]
    assert proof["domain_problem_count"]["const"] == 625
    assert proof["eligible_candidate_count"]["const"] == 624
    assert proof["chosen_candidate_rank"]["const"] == 1
    assert proof["top_candidates"]["minItems"] == 1
    assert proof["top_candidates"]["maxItems"] == 5

    candidate = schemas["CompilerCandidateProof"]["properties"]
    assert candidate["predictions"]["minItems"] == 2
    assert candidate["rank"]["minimum"] == 1
    assert candidate["rank"]["maximum"] == 5
    assert candidate["distinct_output_count"]["minimum"] == 2
    assert candidate["distinguished_pair_count"]["minimum"] == 1

    problem = schemas["SignedProblemDTO"]["properties"]
    for operand in (problem["a"], problem["b"]):
        assert operand["minimum"] == -12
        assert operand["maximum"] == 12

    hypothesis = schemas["EvidenceReceiptHypothesis"]["properties"]
    assert hypothesis["rank"]["minimum"] == 1
    assert hypothesis["rank"]["maximum"] == 4
    assert hypothesis["truth_table_hash"]["minLength"] == 64
    assert hypothesis["truth_table_hash"]["maxLength"] == 64
    assert hypothesis["truth_table_hash"]["pattern"] == "^[0-9a-f]{64}$"
