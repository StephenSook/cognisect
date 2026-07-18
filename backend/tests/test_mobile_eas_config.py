"""Release guards for the Expo cloud-build environment."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


def _merge(parent: Mapping[str, Any], child: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(parent)
    for key, value in child.items():
        inherited = merged.get(key)
        if isinstance(inherited, Mapping) and isinstance(value, Mapping):
            merged[key] = _merge(inherited, value)
        else:
            merged[key] = value
    return merged


def _resolved_profile(
    profiles: Mapping[str, Mapping[str, Any]], profile_name: str
) -> dict[str, Any]:
    profile = profiles[profile_name]
    parent_name = profile.get("extends")
    if not isinstance(parent_name, str):
        return dict(profile)
    return _merge(_resolved_profile(profiles, parent_name), profile)


def test_every_mobile_build_uses_the_sdk_57_environment() -> None:
    config = json.loads((ROOT / "mobile" / "eas.json").read_text(encoding="utf-8"))
    profiles = config["build"]

    for profile_name in ("development", "preview", "production"):
        profile = _resolved_profile(profiles, profile_name)
        assert profile["node"] == "22.23.1"
        assert profile["android"]["image"] == "sdk-57"
        assert profile["ios"]["image"] == "sdk-57"


def test_preview_remains_an_installable_apk() -> None:
    config = json.loads((ROOT / "mobile" / "eas.json").read_text(encoding="utf-8"))
    preview = _resolved_profile(config["build"], "preview")

    assert preview["distribution"] == "internal"
    assert preview["android"]["buildType"] == "apk"
