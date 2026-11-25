"""Guards that keep the end-to-end suite aligned with the backend.

The Playwright suite lives outside pytest, so nothing would notice if the reference
dataset it types into the browser drifted away from the one the API tests assert on,
or if a seeded password variable were renamed. These tests close that gap: they read
the same files the browser reads and compare them with the backend's own source of
truth.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.test_api_runs import COMPLIANT_INPUTS

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "e2e" / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_e2e_dataset_matches_the_reference_compliant_inputs() -> None:
    """The browser types exactly the dataset the API tests prove is a full PASS."""
    fixture = _load("compliant_inputs.json")
    assert fixture == COMPLIANT_INPUTS
    assert len(fixture) == 13
    # every protocol test has inputs, and every metric key is present
    assert sum(len(values) for values in fixture.values()) == 61


def test_e2e_accounts_exist_in_the_seed_and_have_passwords() -> None:
    """`accounts.json` names accounts the seeder creates, and carries a password."""
    from app.seed.seed_users import SEED_USERS

    seeded = {row[0]: row[6] for row in SEED_USERS}  # username -> password env var
    accounts = _load("accounts.json")

    entries = {key: value for key, value in accounts.items() if not key.startswith("_")}
    assert entries, "accounts.json declares no accounts"

    for key, entry in entries.items():
        assert entry["password"], f"{key} has an empty password"
        assert entry["username"] in seeded, f"{entry['username']} is not seeded"
        assert entry["env"] == seeded[entry["username"]], (
            f"{key} expects {entry['env']} but the seeder reads {seeded[entry['username']]}"
        )


def test_e2e_second_factor_accounts_are_the_enforced_roles() -> None:
    """The accounts the suite enrols are exactly the roles MFA is enforced for.

    Enrolling an account the server does not challenge would hide a real gap; leaving
    an enforced role out would make the suite fail at sign-in instead of testing it.
    """
    from app.core.rbac import ROLE_PERMISSIONS
    from app.seed.seed_users import SEED_USERS

    from app.core.config import get_settings

    enforced = {role.strip() for role in get_settings().mfa_enforced_roles.split(",") if role.strip()}
    roles = {row[0]: row[5] for row in SEED_USERS}  # username -> primary role
    accounts = _load("accounts.json")
    mfa_accounts = [key for key in accounts if not key.startswith("_") and key in ("reviewer", "qa")]

    assert mfa_accounts == ["reviewer", "qa"], "the suite enrols the reviewer and the QA officer"
    for key in mfa_accounts:
        username = accounts[key]["username"]
        assert roles[username] in enforced, f"{username} does not mandate a second factor"
        assert roles[username] in ROLE_PERMISSIONS
    # and the analyst deliberately does not: it is the account used for the many
    # sign-ins the suite performs.
    assert roles[accounts["analyst"]["username"]] not in enforced


def test_playwright_config_points_at_the_e2e_database() -> None:
    """The suite must never be able to run its lifecycle against a real database."""
    config = (REPO_ROOT / "playwright.config.ts").read_text(encoding="utf-8")
    assert "sbdma_e2e" in config
    # the loopback cookie exception is explicit, not accidental
    assert "COOKIE_SECURE: 'false'" in config.replace('"', "'")
    assert "globalSetup" in config and "webServer" in config


@pytest.mark.parametrize(
    "spec",
    ["auth.spec.ts", "calibration-lifecycle.spec.ts", "registers.spec.ts"],
)
def test_e2e_specs_exist(spec: str) -> None:
    path = REPO_ROOT / "e2e" / spec
    assert path.is_file(), f"{spec} is missing from the suite"
    assert "test(" in path.read_text(encoding="utf-8")
