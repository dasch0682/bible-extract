"""Tests for models.yml loading and the pre-run price check (no network)."""
import re
from decimal import Decimal
from pathlib import Path

import pytest
import requests

import check_prices
from models import (
    ConfigError, PriceReadError, check_prices as compare, family, fetch_published, format_report,
    load_models, model_for, parse_price, run_check,
)

ROOT = Path(__file__).resolve().parent.parent
FLASH = "deepseek/deepseek-v4.1-flash"
MISTRAL = "mistralai/mistral-large-4-0"
ALIAS = "~deepseek/deepseek-pro-latest"

YAML = f"""
models:
  "{FLASH}":
    price_ref: {{input: "0.055", output: "1.32"}}
    price_ref_date: "2026-10-06"
  "{MISTRAL}":
    price_ref: {{input: "0.68", output: "2.09"}}
    price_ref_date: "2026-10-06"
  "{ALIAS}":
    price_ref: {{input: "0.2464", output: "4.2"}}
    price_ref_date: "2026-10-06"
roles:
  relevance: "{FLASH}"
  paraphrase_generation: "{FLASH}"
  paraphrase_verification: "{MISTRAL}"
  context: "{FLASH}"
  speaker: "{FLASH}"
  escalation: "{ALIAS}"
"""

# What the public list says, in USD per 1M tokens.
PUBLISHED = {
    FLASH: {"input": Decimal("0.055"), "output": Decimal("1.32")},
    MISTRAL: {"input": Decimal("0.68"), "output": Decimal("2.09")},
    ALIAS: {"input": Decimal("0.2464"), "output": Decimal("4.2")},
}


@pytest.fixture
def cfg_path(tmp_path):
    p = tmp_path / "models.yml"
    p.write_text(YAML, encoding="utf-8")
    return p


@pytest.fixture
def cfg(cfg_path):
    return load_models(cfg_path)


def published(**changes):
    out = {k: dict(v) for k, v in PUBLISHED.items()}
    for k, v in changes.items():
        mid = {"flash": FLASH, "mistral": MISTRAL, "alias": ALIAS}[k]
        if v is None:
            del out[mid]
        else:
            out[mid] = v
    return out


# --- loading ---

def test_shipped_models_yml_is_valid():
    cfg = load_models(ROOT / "models.yml")
    assert set(cfg.roles) == {"relevance", "paraphrase_generation", "paraphrase_verification",
                              "context", "speaker", "escalation"}
    assert family(cfg.roles["paraphrase_verification"]) != family(cfg.roles["paraphrase_generation"])

def test_load_valid(cfg):
    assert cfg.roles["relevance"] == FLASH
    assert cfg.models[FLASH].price_in == Decimal("0.055")
    assert cfg.models[ALIAS].price_out == Decimal("4.2")
    assert cfg.models[FLASH].price_ref_date == "2026-10-06"

def test_model_for(cfg_path):
    assert model_for("paraphrase_verification", cfg_path) == MISTRAL

def test_unquoted_date_is_accepted(tmp_path):
    p = tmp_path / "m.yml"
    p.write_text(YAML.replace('"2026-10-06"', "2026-10-06"), encoding="utf-8")
    assert load_models(p).models[FLASH].price_ref_date == "2026-10-06"

def test_missing_file(tmp_path):
    with pytest.raises(ConfigError):
        load_models(tmp_path / "nope.yml")

def test_missing_role(tmp_path):
    p = tmp_path / "m.yml"
    p.write_text(YAML.replace(f'  speaker: "{FLASH}"\n', ""), encoding="utf-8")
    with pytest.raises(ConfigError, match="missing role"):
        load_models(p)

def test_unknown_role(tmp_path):
    p = tmp_path / "m.yml"
    p.write_text(YAML + f'  extra: "{FLASH}"\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="unknown role"):
        load_models(p)

def test_role_model_must_be_listed(tmp_path):
    p = tmp_path / "m.yml"
    p.write_text(YAML.replace(f'context: "{FLASH}"', 'context: "other/unlisted"'), encoding="utf-8")
    with pytest.raises(ConfigError, match="not listed"):
        load_models(p)

def test_bad_price(tmp_path):
    p = tmp_path / "m.yml"
    p.write_text(YAML.replace('input: "0.055"', 'input: "cheap"'), encoding="utf-8")
    with pytest.raises(ConfigError):
        load_models(p)

def test_negative_price(tmp_path):
    p = tmp_path / "m.yml"
    p.write_text(YAML.replace('input: "0.055"', 'input: "-1"'), encoding="utf-8")
    with pytest.raises(ConfigError):
        load_models(p)

def test_missing_price_ref(tmp_path):
    p = tmp_path / "m.yml"
    p.write_text(YAML.replace('    price_ref: {input: "0.68", output: "2.09"}\n', ""), encoding="utf-8")
    with pytest.raises(ConfigError):
        load_models(p)

def test_bad_date(tmp_path):
    p = tmp_path / "m.yml"
    p.write_text(YAML.replace('"2026-10-06"', '"yesterday"', 1), encoding="utf-8")
    with pytest.raises(ConfigError, match="YYYY-MM-DD"):
        load_models(p)

def test_verifier_must_be_another_family(tmp_path):
    p = tmp_path / "m.yml"
    p.write_text(YAML.replace(f'paraphrase_verification: "{MISTRAL}"', f'paraphrase_verification: "{ALIAS}"'),
                 encoding="utf-8")
    with pytest.raises(ConfigError, match="another family"):
        load_models(p)

def test_family_ignores_alias_tilde():
    assert family(ALIAS) == family(FLASH) == "deepseek"


# --- prices ---

def test_parse_price_is_exact():
    assert parse_price("0.000000055") * Decimal(1_000_000) == Decimal("0.055")

@pytest.mark.parametrize("bad", [None, True, "abc", "NaN", "Infinity", "-0.1", [], {}])
def test_parse_price_rejects(bad):
    with pytest.raises(ValueError):
        parse_price(bad)


# --- comparison ---

def test_same_prices_ok(cfg):
    res = compare(cfg, published())
    assert res.ok and res.problems == []

def test_input_price_rise_stops(cfg):
    res = compare(cfg, published(flash={"input": Decimal("0.07"), "output": Decimal("1.32")}))
    assert not res.ok
    assert res.problems == [f"{FLASH}: price rose, input 0.055 -> 0.07 (USD per 1M tokens)"]

def test_output_price_rise_stops(cfg):
    res = compare(cfg, published(mistral={"input": Decimal("0.68"), "output": Decimal("2.5")}))
    assert not res.ok
    assert "output 2.09 -> 2.5" in res.problems[0]

def test_both_prices_rise_are_both_reported(cfg):
    res = compare(cfg, published(flash={"input": Decimal("1"), "output": Decimal("2")}))
    assert "input 0.055 -> 1" in res.problems[0] and "output 1.32 -> 2" in res.problems[0]

def test_only_the_model_that_rose_is_listed(cfg):
    res = compare(cfg, published(mistral={"input": Decimal("0.9"), "output": Decimal("2.09")}))
    assert len(res.problems) == 1 and res.problems[0].startswith(MISTRAL)

def test_price_drop_continues_with_note(cfg):
    res = compare(cfg, published(flash={"input": Decimal("0.01"), "output": Decimal("1.0")}))
    assert res.ok
    assert any("price dropped" in n and FLASH in n for n in res.notes)

def test_one_cheaper_one_dearer_still_stops(cfg):
    res = compare(cfg, published(flash={"input": Decimal("0.01"), "output": Decimal("1.9")}))
    assert not res.ok

def test_missing_model_stops(cfg):
    res = compare(cfg, published(mistral=None))
    assert not res.ok and "no longer offered" in res.problems[0]

def test_unreadable_price_stops(cfg):
    res = compare(cfg, published(flash={"error": "unreadable price (completion)"}))
    assert not res.ok and "unreadable" in res.problems[0]

def test_alias_same_price_ok_with_note(cfg):
    res = compare(cfg, published())
    assert any(ALIAS in n and "alias" in n for n in res.notes)

def test_alias_dearer_stops(cfg):
    res = compare(cfg, published(alias={"input": Decimal("0.5"), "output": Decimal("4.2")}))
    assert not res.ok and res.problems[0].startswith(ALIAS)

def test_alias_missing_stops(cfg):
    res = compare(cfg, published(alias=None))
    assert not res.ok


# --- fetching ---

class FakeResponse:
    def __init__(self, payload=None, status=200, bad_json=False):
        self._payload, self.status_code, self._bad_json = payload, status, bad_json

    def json(self):
        if self._bad_json:
            raise ValueError("not json")
        return self._payload


def entry(mid, prompt, completion):
    return {"id": mid, "pricing": {"prompt": prompt, "completion": completion}}


def test_fetch_converts_to_per_million():
    payload = {"data": [entry(FLASH, "0.000000055", "0.00000132")]}
    out = fetch_published(get=lambda url, timeout: FakeResponse(payload))
    assert out[FLASH] == {"input": Decimal("0.055"), "output": Decimal("1.32")}

def test_fetch_network_error():
    def boom(url, timeout):
        raise requests.ConnectionError("down")
    with pytest.raises(PriceReadError, match="cannot reach"):
        fetch_published(get=boom)

def test_fetch_http_error():
    with pytest.raises(PriceReadError, match="HTTP 503"):
        fetch_published(get=lambda url, timeout: FakeResponse(status=503))

def test_fetch_not_json():
    with pytest.raises(PriceReadError):
        fetch_published(get=lambda url, timeout: FakeResponse(bad_json=True))

def test_fetch_no_data_key():
    with pytest.raises(PriceReadError):
        fetch_published(get=lambda url, timeout: FakeResponse({"models": []}))

def test_fetch_data_not_a_list():
    with pytest.raises(PriceReadError):
        fetch_published(get=lambda url, timeout: FakeResponse({"data": {}}))

def test_fetch_marks_malformed_entry_without_failing_the_rest():
    payload = {"data": [entry(FLASH, "0.000000055", "oops"), entry(MISTRAL, "0.00000068", "0.00000209"),
                        {"id": "x/no-pricing"}, "junk"]}
    out = fetch_published(get=lambda url, timeout: FakeResponse(payload))
    assert "error" in out[FLASH] and "error" in out["x/no-pricing"]
    assert out[MISTRAL]["input"] == Decimal("0.68")


# --- run_check never raises, and stops in doubt ---

def test_run_check_ok(cfg_path):
    res = run_check(cfg_path, fetch=lambda: published(), now="2026-10-06T10:00:00Z")
    assert res.ok and res.checked_at == "2026-10-06T10:00:00Z"

def test_run_check_stops_on_price_read_error(cfg_path):
    def fail():
        raise PriceReadError("cannot reach")
    res = run_check(cfg_path, fetch=fail)
    assert not res.ok and "prices unreadable" in res.problems[0]

def test_run_check_stops_on_unexpected_exception(cfg_path):
    def fail():
        raise RuntimeError("boom")
    res = run_check(cfg_path, fetch=fail)
    assert not res.ok and "RuntimeError" in res.problems[0]

def test_run_check_stops_on_bad_config(tmp_path):
    res = run_check(tmp_path / "missing.yml", fetch=lambda: published())
    assert not res.ok and res.problems[0].startswith("models.yml:")


# --- report ---

def test_report_ok_lists_prices_and_date(cfg):
    text = format_report(compare(cfg, published(), now="2026-10-06T10:00:00Z"))
    assert "Result: OK" in text and "2026-10-06T10:00:00Z" in text
    assert f"| {FLASH} | 0.055 | 1.32 | 0.055 | 1.32 | ok |" in text

def test_report_stopped_shows_old_and_new_price(cfg):
    text = format_report(compare(cfg, published(flash={"input": Decimal("0.07"), "output": Decimal("1.32")})))
    assert "STOPPED" in text and "input 0.055 -> 0.07" in text


# --- command line ---

def test_cli_exit_0_when_ok(cfg_path, capsys):
    assert check_prices.main(["--models", str(cfg_path)], fetch=lambda: published()) == 0
    assert "Result: OK" in capsys.readouterr().out

def test_cli_exit_1_on_rise(cfg_path, capsys):
    rose = published(flash={"input": Decimal("0.07"), "output": Decimal("1.32")})
    assert check_prices.main(["--models", str(cfg_path)], fetch=lambda: rose) == 1
    assert "no model call was made" in capsys.readouterr().err

def test_cli_exit_1_when_prices_unreadable(cfg_path):
    def fail():
        raise PriceReadError("down")
    assert check_prices.main(["--models", str(cfg_path)], fetch=fail) == 1

def test_cli_has_no_bypass_option(cfg_path):
    with pytest.raises(SystemExit):
        check_prices.main(["--models", str(cfg_path), "--force"], fetch=lambda: published())

def test_cli_writes_github_step_summary(cfg_path, tmp_path, monkeypatch):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    check_prices.main(["--models", str(cfg_path)], fetch=lambda: published())
    assert "## Price check" in summary.read_text(encoding="utf-8")


# --- wiring and no hard-coded model ids ---

def test_no_model_id_hard_coded_in_code():
    ids = list(load_models(ROOT / "models.yml").models)
    families = {family(i) + "/" for i in ids}
    offenders = []
    for py in list(ROOT.glob("*.py")) + list((ROOT / "scripts").glob("*.py")):
        text = py.read_text(encoding="utf-8")
        for needle in ids + sorted(families):
            if needle in text:
                offenders.append(f"{py.name}: {needle}")
    assert offenders == []

def test_workflow_runs_price_check_before_extraction_and_has_no_model_env():
    text = (ROOT / ".github" / "workflows" / "extract.yml").read_text(encoding="utf-8")
    assert "python check_prices.py" in text
    assert text.index("python check_prices.py") < text.index("python extract.py")
    assert not re.search(r"^\s*MODEL:", text, re.M)

def test_extract_runs_price_check_before_creating_the_client():
    text = (ROOT / "extract.py").read_text(encoding="utf-8")
    assert text.index("run_check()") < text.index("make_client(a.provider")
    assert "--model" not in text
