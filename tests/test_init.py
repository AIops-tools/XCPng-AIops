"""Tests for the ``xcpng-aiops init`` onboarding wizard.

The wizard is driven end-to-end through Typer's CliRunner with every path
(config.yaml, secrets.enc, rules.yaml) isolated under tmp_path. The master
password comes from XCPNG_AIOPS_MASTER_PASSWORD (the non-interactive path)
and the hidden XO-token prompt is patched at the getpass boundary.
"""

from __future__ import annotations

import getpass as getpass_mod

import pytest
import yaml
from typer.testing import CliRunner

import xcpng_aiops.cli.init as init_mod
import xcpng_aiops.config as config_mod
import xcpng_aiops.doctor as doctor_mod
import xcpng_aiops.secretstore as ss

pytestmark = pytest.mark.unit

MASTER_PW = "init-master-pw"
XO_TOKEN = "xo-personal-token-uuid"  # nosec B105 — test fixture value

# Wizard answers: name, XO URL, accept the TLS confirm default (True),
# blank xo_self_vm_uuid (XO not on this pool / not declared), no second target,
# decline the trailing doctor run.
WIZARD_INPUT = "xo1\nhttps://xo.example.com\n\n\nn\nn\n"


@pytest.fixture
def init_home(tmp_path, monkeypatch):
    """Isolate config + secret store + governance home under tmp_path.

    Module-level path constants are import-time snapshots of ``ops_home()``,
    so the env var alone is not enough — patch every module that captured them.
    """
    config_file = tmp_path / "config.yaml"
    secrets_file = tmp_path / "secrets.enc"
    monkeypatch.setenv("XCPNG_AIOPS_HOME", str(tmp_path))
    monkeypatch.setenv(ss.MASTER_PASSWORD_ENV, MASTER_PW)
    monkeypatch.setattr(init_mod, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(init_mod, "CONFIG_FILE", config_file)
    monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config_mod, "CONFIG_FILE", config_file)
    monkeypatch.setattr(ss, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(ss, "SECRETS_FILE", secrets_file)
    monkeypatch.setattr(ss, "LEGACY_ENV_FILE", tmp_path / ".env")
    monkeypatch.setattr(ss, "_cached", None)
    # The hidden per-target token prompt bypasses CliRunner stdin.
    monkeypatch.setattr(getpass_mod, "getpass", lambda prompt="": XO_TOKEN)
    return tmp_path


def _run_init(input_text: str = WIZARD_INPUT):
    from xcpng_aiops.cli import app

    return CliRunner().invoke(app, ["init"], input=input_text)


def test_init_writes_config_with_entered_values(init_home):
    result = _run_init()
    assert result.exit_code == 0, result.output
    raw = yaml.safe_load((init_home / "config.yaml").read_text("utf-8"))
    assert raw["targets"] == [
        {
            "name": "xo1",
            "url": "https://xo.example.com",
            "verify_ssl": True,  # TLS confirm default=True respected
            "api_path": "/rest/v0",
        }
    ]


def test_init_strips_trailing_slash_from_url(init_home):
    result = _run_init("xo1\nhttps://xo.example.com/\n\n\nn\nn\n")
    assert result.exit_code == 0, result.output
    raw = yaml.safe_load((init_home / "config.yaml").read_text("utf-8"))
    assert raw["targets"][0]["url"] == "https://xo.example.com"


def test_init_tls_decline_writes_verify_ssl_false(init_home):
    # Explicit "n" on the TLS confirm (self-signed lab certs).
    result = _run_init("xo1\nhttps://xo.example.com\nn\n\nn\nn\n")
    assert result.exit_code == 0, result.output
    raw = yaml.safe_load((init_home / "config.yaml").read_text("utf-8"))
    assert raw["targets"][0]["verify_ssl"] is False


def test_init_stores_secret_encrypted_not_in_config(init_home):
    result = _run_init()
    assert result.exit_code == 0, result.output
    # The token is readable back through the secret store API...
    assert ss.SecretStore.unlock(MASTER_PW).get("xo1") == XO_TOKEN
    # ...and never lands in plaintext in config.yaml or secrets.enc.
    assert XO_TOKEN not in (init_home / "config.yaml").read_text("utf-8")
    assert XO_TOKEN not in (init_home / "secrets.enc").read_text("utf-8")


def test_init_seeds_default_rules_with_dual_control_tier(init_home):
    result = _run_init()
    assert result.exit_code == 0, result.output
    rules = yaml.safe_load((init_home / "rules.yaml").read_text("utf-8"))
    tiers = {r["name"]: r for r in rules["risk_tiers"]}
    assert "high-risk-requires-approver" in tiers
    assert tiers["high-risk-requires-approver"]["tier"] == "dual"
    assert tiers["high-risk-requires-approver"]["min_risk_level"] == "high"


def test_init_rerun_does_not_clobber_existing_rules(init_home):
    sentinel = "# operator-authored rules — must survive re-init\nrisk_tiers: []\n"
    (init_home / "rules.yaml").write_text(sentinel, "utf-8")
    result = _run_init()
    assert result.exit_code == 0, result.output
    assert (init_home / "rules.yaml").read_text("utf-8") == sentinel


def test_init_declining_doctor_confirm_skips_doctor(init_home, monkeypatch):
    calls: list[bool] = []
    monkeypatch.setattr(doctor_mod, "run_doctor", lambda: calls.append(True) or 0)
    result = _run_init()  # WIZARD_INPUT ends with an explicit "n"
    assert result.exit_code == 0, result.output
    assert calls == []


def test_init_accepting_doctor_confirm_runs_doctor(init_home, monkeypatch):
    calls: list[bool] = []
    monkeypatch.setattr(doctor_mod, "run_doctor", lambda: calls.append(True) or 0)
    # Empty last answer accepts the confirm's default=True.
    result = _run_init("xo1\nhttps://xo.example.com\n\n\nn\n\n")
    assert result.exit_code == 0, result.output
    assert calls == [True]


def test_init_overwrite_existing_target(init_home):
    result = _run_init()
    assert result.exit_code == 0, result.output
    # Same name again: confirm overwrite, new URL, accept defaults.
    result = _run_init("xo1\ny\nhttps://xo2.example.com\n\n\nn\nn\n")
    assert result.exit_code == 0, result.output
    raw = yaml.safe_load((init_home / "config.yaml").read_text("utf-8"))
    assert [t["url"] for t in raw["targets"]] == ["https://xo2.example.com"]
