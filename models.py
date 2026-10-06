"""Model registry (models.yml) and the pre-run price check.

No language model is involved here. The check reads OpenRouter's public model
list and compares it with the reference prices recorded in models.yml. When in
doubt (network error, unexpected format, missing model), the result is "stop":
no model call may be made.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

import requests
import yaml

MODELS_PATH = Path(__file__).parent / "models.yml"
PRICES_URL = "https://openrouter.ai/api/v1/models"
ROLES = (
    "relevance",
    "paraphrase_generation",
    "paraphrase_verification",
    "context",
    "speaker",
    "escalation",
)
PER_MILLION = Decimal(1_000_000)


class ConfigError(ValueError):
    """models.yml is missing or invalid."""


class PriceReadError(Exception):
    """The published prices could not be read."""


@dataclass(frozen=True)
class ModelRef:
    price_in: Decimal   # USD per 1M input tokens
    price_out: Decimal  # USD per 1M output tokens
    price_ref_date: str


@dataclass(frozen=True)
class Config:
    models: dict
    roles: dict


@dataclass
class CheckResult:
    ok: bool
    checked_at: str
    rows: list = field(default_factory=list)
    problems: list = field(default_factory=list)
    notes: list = field(default_factory=list)


# --- helpers ---

def family(model_id: str) -> str:
    """Author part of an OpenRouter id: '~vendor/name' -> 'vendor'."""
    return model_id.lstrip("~").split("/", 1)[0]


def is_alias(model_id: str) -> bool:
    return model_id.startswith("~")


def parse_price(value, what: str = "price") -> Decimal:
    """Exact Decimal from a string or number; rejects bool, NaN, infinity, negatives."""
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError(f"{what}: not a number")
    try:
        d = Decimal(str(value).strip())
    except InvalidOperation:
        raise ValueError(f"{what}: not a number") from None
    if not d.is_finite() or d < 0:
        raise ValueError(f"{what}: must be a finite, non-negative number")
    return d


def _fmt(d: Decimal) -> str:
    return format(d.normalize(), "f")


# --- models.yml ---

def load_models(path=MODELS_PATH) -> Config:
    p = Path(path)
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as e:
        raise ConfigError(f"cannot read {p.name}: {e}") from None
    if not isinstance(raw, dict) or not isinstance(raw.get("models"), dict) \
            or not isinstance(raw.get("roles"), dict) or not raw["models"]:
        raise ConfigError("models.yml needs non-empty 'models' and 'roles' sections")

    models = {}
    for mid, spec in raw["models"].items():
        if not isinstance(mid, str) or not isinstance(spec, dict) or not isinstance(spec.get("price_ref"), dict):
            raise ConfigError(f"model {mid!r}: needs price_ref with input and output")
        try:
            pin = parse_price(spec["price_ref"].get("input"), f"{mid} price_ref.input")
            pout = parse_price(spec["price_ref"].get("output"), f"{mid} price_ref.output")
        except ValueError as e:
            raise ConfigError(str(e)) from None
        d = spec.get("price_ref_date")
        try:
            d = d.isoformat() if isinstance(d, dt.date) else str(dt.date.fromisoformat(str(d)))
        except ValueError:
            raise ConfigError(f"model {mid!r}: price_ref_date must be YYYY-MM-DD") from None
        models[mid] = ModelRef(pin, pout, d)

    roles = raw["roles"]
    unknown = set(roles) - set(ROLES)
    missing = [r for r in ROLES if r not in roles]
    if unknown:
        raise ConfigError(f"unknown role(s): {sorted(unknown)}")
    if missing:
        raise ConfigError(f"missing role(s): {missing}")
    for role, mid in roles.items():
        if mid not in models:
            raise ConfigError(f"role {role!r}: model {mid!r} is not listed under models")
    if family(roles["paraphrase_verification"]) == family(roles["paraphrase_generation"]):
        raise ConfigError("paraphrase_verification must be from another family than paraphrase_generation")
    return Config(models=models, roles=dict(roles))


def model_for(role: str, path=MODELS_PATH) -> str:
    return load_models(path).roles[role]


# --- published prices ---

def fetch_published(get=requests.get, url: str = PRICES_URL, timeout: int = 30) -> dict:
    """{model id: {'input': Decimal, 'output': Decimal} | {'error': str}}, USD per 1M tokens."""
    try:
        r = get(url, timeout=timeout)
    except requests.RequestException as e:
        raise PriceReadError(f"cannot reach {url}: {type(e).__name__}") from None
    if getattr(r, "status_code", None) != 200:
        raise PriceReadError(f"{url} answered HTTP {getattr(r, 'status_code', '?')}")
    try:
        data = r.json()["data"]
    except (ValueError, KeyError, TypeError):
        raise PriceReadError("unexpected format: no 'data' list") from None
    if not isinstance(data, list):
        raise PriceReadError("unexpected format: 'data' is not a list")
    out = {}
    for m in data:
        if not isinstance(m, dict) or not isinstance(m.get("id"), str):
            continue
        try:
            pricing = m["pricing"]
            out[m["id"]] = {
                "input": parse_price(pricing["prompt"], "prompt") * PER_MILLION,
                "output": parse_price(pricing["completion"], "completion") * PER_MILLION,
            }
        except (KeyError, TypeError, ValueError) as e:
            out[m["id"]] = {"error": f"unreadable price ({e})"}
    return out


# --- the check ---

def check_prices(config: Config, published: dict, now: str | None = None) -> CheckResult:
    """Pure comparison: any rise, missing model or unreadable price stops the batch."""
    res = CheckResult(ok=True, checked_at=now or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    for mid, ref in config.models.items():
        pub = published.get(mid)
        row = {"model": mid, "ref_in": ref.price_in, "ref_out": ref.price_out,
               "now_in": None, "now_out": None, "status": "ok"}
        res.rows.append(row)
        if pub is None:
            row["status"] = "missing"
            res.problems.append(f"{mid}: no longer offered by OpenRouter")
            continue
        if "error" in pub:
            row["status"] = "unreadable"
            res.problems.append(f"{mid}: {pub['error']}")
            continue
        row["now_in"], row["now_out"] = pub["input"], pub["output"]
        rose = []
        if pub["input"] > ref.price_in:
            rose.append(f"input {_fmt(ref.price_in)} -> {_fmt(pub['input'])}")
        if pub["output"] > ref.price_out:
            rose.append(f"output {_fmt(ref.price_out)} -> {_fmt(pub['output'])}")
        if rose:
            row["status"] = "rose"
            res.problems.append(f"{mid}: price rose, " + ", ".join(rose) + " (USD per 1M tokens)")
        elif pub["input"] < ref.price_in or pub["output"] < ref.price_out:
            row["status"] = "dropped"
            res.notes.append(f"{mid}: price dropped; update price_ref in models.yml if you want")
        if is_alias(mid):
            res.notes.append(
                f"{mid}: alias priced on its own entry; the public list does not say which "
                "model it points to, so pin the concrete model from the first response")
    res.ok = not res.problems
    return res


def run_check(path=MODELS_PATH, fetch=fetch_published, now: str | None = None) -> CheckResult:
    """Never raises: any failure is a 'stop' result (in doubt, no call is made)."""
    stamp = now or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        config = load_models(path)
    except ConfigError as e:
        return CheckResult(ok=False, checked_at=stamp, problems=[f"models.yml: {e}"])
    try:
        published = fetch()
    except PriceReadError as e:
        return CheckResult(ok=False, checked_at=stamp, problems=[f"prices unreadable: {e}"])
    except Exception as e:  # noqa: BLE001 - in doubt, stop
        return CheckResult(ok=False, checked_at=stamp,
                           problems=[f"prices unreadable: {type(e).__name__}"])
    return check_prices(config, published, now=stamp)


def format_report(res: CheckResult) -> str:
    """Markdown section recorded in the batch report."""
    lines = [
        "## Price check",
        f"- Checked at: {res.checked_at} (source: {PRICES_URL})",
        f"- Result: {'OK' if res.ok else 'STOPPED, no model call was made'}",
    ]
    if res.rows:
        lines += ["", "| Model | Ref in | Ref out | Now in | Now out | Status |", "|---|---|---|---|---|---|"]
        for r in res.rows:
            def f(d):
                return _fmt(d) if d is not None else "-"
            lines.append(f"| {r['model']} | {f(r['ref_in'])} | {f(r['ref_out'])} | "
                         f"{f(r['now_in'])} | {f(r['now_out'])} | {r['status']} |")
        lines.append("")
        lines.append("Prices in USD per 1M tokens.")
    if res.problems:
        lines += ["", "### Problems"] + [f"- {p}" for p in res.problems]
    if res.notes:
        lines += ["", "### Notes"] + [f"- {n}" for n in res.notes]
    return "\n".join(lines) + "\n"
