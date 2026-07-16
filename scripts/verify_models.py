#!/usr/bin/env python3
"""Opt-in live verification for the frozen production model identifiers."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import tempfile
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

from openai import AsyncOpenAI
from pydantic import BaseModel, ConfigDict, Field

from cognisect.model_policy import MODEL_IDS

VERIFIER_TIMEOUT_SECONDS = 30.0


class VerificationOutput(BaseModel):
    """Minimal strict structure used only to verify model access and parsing."""

    model_config = ConfigDict(extra="forbid", strict=True)

    verified: Literal[True]
    sequence: Annotated[int, Field(strict=True, ge=1, le=3)]


def _returned_model_is_allowed(requested: str, returned: str) -> bool:
    """Allow the exact configured model or its dated provider snapshot."""
    return returned == requested or returned.startswith(f"{requested}-")


async def _verify(api_key: str) -> list[dict[str, object]]:
    calls: list[dict[str, object]] = []
    async with AsyncOpenAI(
        api_key=api_key,
        max_retries=0,
        timeout=VERIFIER_TIMEOUT_SECONDS,
    ) as client:
        for model_id in MODEL_IDS.values():
            for sequence in range(1, 4):
                response = await client.responses.parse(
                    model=model_id,
                    instructions=(
                        "Return only the requested strict verification object. "
                        "Do not provide hidden reasoning."
                    ),
                    input=json.dumps({"verified": True, "sequence": sequence}),
                    text_format=VerificationOutput,
                    prompt_cache_key="cognisect.model_verifier.v1",
                    max_output_tokens=100,
                    store=False,
                    metadata={"purpose": "explicit_live_verification"},
                )
                parsed = response.output_parsed
                valid = (
                    isinstance(parsed, VerificationOutput)
                    and parsed.verified is True
                    and parsed.sequence == sequence
                    and _returned_model_is_allowed(model_id, str(response.model))
                )
                if not valid:
                    msg = "live verification result was invalid"
                    raise RuntimeError(msg)
                calls.append(
                    {
                        "requested_model_id": model_id,
                        "returned_model_id": response.model,
                        "request_id": response.id,
                        "sequence": sequence,
                        "structured_output_valid": True,
                    }
                )
    if len(calls) != len(MODEL_IDS) * 3:
        msg = "live verification call count was invalid"
        raise RuntimeError(msg)
    return calls


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(tempfile.gettempdir()) / "cognisect-model-verification.json",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> int:
    """Run nine live calls only with both explicit consent and a credential."""
    args = _parser().parse_args(argv)
    environment = os.environ if environ is None else environ
    api_key = environment.get("OPENAI_API_KEY", "").strip()
    if not args.live or not api_key:
        print("LIVE MODEL VERIFICATION: NOT RUN (--live and OPENAI_API_KEY required)")
        return 0

    try:
        calls = asyncio.run(_verify(api_key))
    except Exception:  # noqa: BLE001 - CLI emits content-free failure only.
        print("LIVE MODEL VERIFICATION: FAILED")
        return 1
    evidence = {
        "status": "LIVE",
        "performed_at": datetime.now(UTC).isoformat(),
        "call_count": len(calls),
        "calls": calls,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    print(f"LIVE MODEL VERIFICATION: PASSED ({len(calls)} calls; redacted evidence written)")
    return 0


if __name__ == "__main__":  # pragma: no cover - script entrypoint
    raise SystemExit(main())
