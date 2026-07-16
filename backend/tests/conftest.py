"""Shared deterministic property-test configuration."""

from hypothesis import HealthCheck, settings

settings.register_profile(
    "cognisect",
    max_examples=200,
    deadline=None,
    derandomize=True,
    suppress_health_check=(HealthCheck.too_slow,),
)
settings.load_profile("cognisect")
