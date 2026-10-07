"""THROWAWAY UTC experiments. No production provider or Matchweek artifacts.

Run: PYTHONPATH=src python src/matchvet/trusted_utc_prototype.py [--https]
All absolute values in the scenarios are synthetic. Signatures authenticate a
synthetic server interval; they do not establish a real authority's UTC error.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import platform
import secrets
import subprocess
import tempfile
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from matchvet.matchweek_research import (
    MatchweekResearchError,
    MatchweekResearchRepository,
    TrustedUTCUpperBound,
)
from matchvet.store import open_store


class SyntheticAssertion:
    def __init__(self, upper: int) -> None:
        self.upper = upper

    def observe(self) -> TrustedUTCUpperBound:
        return TrustedUTCUpperBound(
            datetime.fromtimestamp(self.upper, UTC), "throwaway-synthetic", "TRUSTED"
        )


def signed_interval(root: Path) -> dict[str, object]:
    """Sign an interval and actually verify it, entirely in scratch files."""
    nonce = secrets.token_hex(32)
    payload = json.dumps(
        {"protocol": "synthetic-interval-v1", "nonce": nonce, "lower": 995, "upper": 996},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    message = root / "interval.json"
    message.write_bytes(payload)
    key, public, signature = (root / name for name in ("key.pem", "public.pem", "sig.bin"))
    subprocess.run(
        ["openssl", "genpkey", "-algorithm", "ed25519", "-out", str(key)],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["openssl", "pkey", "-in", str(key), "-pubout", "-out", str(public)],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "openssl",
            "pkeyutl",
            "-sign",
            "-rawin",
            "-inkey",
            str(key),
            "-in",
            str(message),
            "-out",
            str(signature),
        ],
        check=True,
        capture_output=True,
    )
    command = [
        "openssl",
        "pkeyutl",
        "-verify",
        "-rawin",
        "-pubin",
        "-inkey",
        str(public),
        "-in",
        str(message),
        "-sigfile",
        str(signature),
    ]
    valid = subprocess.run(command, capture_output=True).returncode == 0
    message.write_bytes(payload.replace(b"996", b"990"))
    tamper_rejected = subprocess.run(command, capture_output=True).returncode != 0
    return {
        "signature_verified": valid,
        "tamper_rejected": tamper_rejected,
        "payload_utf8": payload.decode(),
        "public_key_pem": public.read_text(),
        "signature_base64": base64.b64encode(signature.read_bytes()).decode(),
        "trust_profile": "Synthetic ephemeral Ed25519 key; no production authority",
        "request_nonce_sha256": hashlib.sha256(nonce.encode()).hexdigest(),
        "message_sha256": hashlib.sha256(payload).hexdigest(),
        "public_key_sha256": hashlib.sha256(public.read_bytes()).hexdigest(),
        "source_is_synthetic": True,
        "source_event_upper": 996,
        "actual_client_return": 1005,
        "current_at_return_bound_valid": False,
        "prior_commit_994_causal_bound_valid": valid and 994 <= 995 <= 996 < 1000,
        "replayed_nonce_matches_new_request": nonce == secrets.token_hex(32),
    }


def scenarios() -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="matchvet-utc-PROTOTYPE-") as directory:
        root = Path(directory)
        with open_store(root / "scratch.sqlite3", private_root=root) as store:
            try:
                MatchweekResearchRepository(store)._require_before(
                    datetime.fromtimestamp(1000, UTC).isoformat()
                )
                default = "unexpected acceptance"
            except MatchweekResearchError as error:
                default = str(error)
            cases = []
            for name, upper, actual in (
                ("wall_rollback", 900, 1005),
                ("wall_forward_jump", 1010, 995),
                ("three_https_sources_all_behind_max", max(993, 994, 995), 1005),
                ("signed_server_interval_received_late", 996, 1005),
                ("monotonic_excludes_suspend", 997, 1005),
                ("boottime_rate_assumed_without_evidence", 997, 1005),
                ("synthetic_exact_elapsed_at_final_sample", 998, 998),
                ("pause_after_final_boottime_sample", 998, 1005),
                ("cutoff_equality", 1000, 1000),
            ):
                try:
                    MatchweekResearchRepository(
                        store, clock=SyntheticAssertion(upper)
                    )._require_before(datetime.fromtimestamp(1000, UTC).isoformat())
                    accepted = True
                except MatchweekResearchError:
                    accepted = False
                cases.append(
                    {
                        "scenario": name,
                        "asserted_upper": upper,
                        "synthetic_actual_utc_at_return": actual,
                        "gate_accepted_assertion": accepted,
                        "provider_meets_contract": upper >= actual,
                        "production_confidence": "REFUSED",
                    }
                )
        signed = signed_interval(root)
    return {
        "default_provider": default,
        "gate_cases": cases,
        "authenticated_interval": signed,
        "interpretation": (
            "Gate trusts injected assertions. Unsafe cases violate the provider contract, "
            "not repository validation. Exact elapsed is a synthetic oracle, "
            "never an Android qualification."
        ),
        "synthetic_confidence_record": {
            "schema_version": 1,
            "scope": "RETURN_TIME",
            "estimate_utc": None,
            "upper_bound_utc": None,
            "error_bound_seconds": None,
            "trust_state": "REFUSED",
            "failure_reasons": ["NO_ELAPSED_RATE_GUARANTEE", "NO_RETURN_DELIVERY_BOUND"],
            "source_protocol": "synthetic-interval-v1",
            "software_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "evidence": "authenticated_interval; gate_cases",
            "operational_authority": False,
        },
    }


def https_probe(url: str) -> dict[str, object]:
    start = time.clock_gettime_ns(time.CLOCK_BOOTTIME)
    result: dict[str, object] = {
        "url": url,
        "trust_state": "ESTIMATE_ONLY",
        "upper_bound_utc": None,
        "uncertainty_seconds": None,
        "wall_estimate_at_start": datetime.now(UTC).isoformat(),
        "boottime_before_ns": start,
    }
    try:
        request = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(request, timeout=10) as response:
            result.update(
                status=response.status,
                final_url=response.url,
                date=response.headers.get("Date"),
                age=response.headers.get("Age"),
                via=response.headers.get("Via"),
                cache_control=response.headers.get("Cache-Control"),
                tls_policy="stdlib default certificate and hostname verification",
            )
    except Exception as error:
        result.update(error=f"{type(error).__name__}: {error}", trust_state="REFUSED")
    end = time.clock_gettime_ns(time.CLOCK_BOOTTIME)
    result.update(
        boottime_after_ns=end,
        measured_elapsed_ns=end - start,
        failure_reason="NO_NORMATIVE_DATE_ACCURACY_BOUND",
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--https", action="store_true", help="Three diagnostic HTTPS HEAD requests")
    args = parser.parse_args()
    result: dict[str, object] = {
        "prototype": True,
        "schema_version": 1,
        "python": platform.python_version(),
        "platform": platform.system(),
        "boottime_available": hasattr(time, "CLOCK_BOOTTIME"),
        "openssl": subprocess.run(
            ["openssl", "version"], check=True, text=True, capture_output=True
        ).stdout.strip(),
        "proof": scenarios(),
    }
    if args.https:
        with ThreadPoolExecutor(max_workers=3) as pool:
            result["https_diagnostics"] = list(
                pool.map(
                    https_probe,
                    (
                        "https://www.cloudflare.com/",
                        "https://www.google.com/",
                        "https://www.microsoft.com/",
                    ),
                )
            )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
