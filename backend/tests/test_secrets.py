"""Fail-fast secret validation (app.bootstrap.validate_runtime_secrets).

The gate must refuse the shipped defaults in every process (API, worker,
scheduler) and accept explicitly-configured strong values.
"""

from __future__ import annotations

import pytest


def _validate(jwt: str, seed_pw: str) -> None:
    import os
    os.environ.pop("INSECURE_DEV", None)
    os.environ["JWT_SECRET"] = jwt
    os.environ["SEED_ADMIN_PASSWORD"] = seed_pw
    from app.core import config
    config.get_settings.cache_clear()
    from app.bootstrap import validate_runtime_secrets
    validate_runtime_secrets()


@pytest.fixture(autouse=True)
def _restore_env(monkeypatch):
    monkeypatch.delenv("INSECURE_DEV", raising=False)
    yield
    from app.core import config
    config.get_settings.cache_clear()


def test_default_jwt_secret_refused():
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        _validate("change-me-in-production", "S0me-Strong-Seed-PW!")


def test_short_jwt_secret_refused():
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        _validate("tooshort", "S0me-Strong-Seed-PW!")


def test_default_seed_admin_password_refused():
    with pytest.raises(RuntimeError, match="SEED_ADMIN_PASSWORD"):
        _validate("a" * 40, "admin")


def test_strong_values_accepted():
    _validate("a" * 40, "S0me-Strong-Seed-PW!")  # must not raise


def test_insecure_dev_opt_out():
    import os
    os.environ["INSECURE_DEV"] = "1"
    _validate("change-me-in-production", "admin")  # must not raise
