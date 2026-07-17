import importlib.util
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "generate_dependency_licenses",
    Path(__file__).resolve().parents[2] / "scripts" / "generate_dependency_licenses.py",
)
assert SPEC is not None and SPEC.loader is not None
generate_dependency_licenses = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(generate_dependency_licenses)


def test_node_license_inventory_includes_isolated_openapi_tooling() -> None:
    rows = generate_dependency_licenses._node_rows()

    assert ("openapi-typescript", "7.13.0", "MIT") in rows
    assert ("typescript", "5.9.3", "Apache-2.0") in rows
