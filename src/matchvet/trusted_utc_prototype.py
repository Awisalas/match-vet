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
import os
import platform
import secrets
import subprocess
import tempfile
import time
import urllib.request
import uuid
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

    def accepts_for_request(expected_nonce: str) -> bool:
        authenticated = subprocess.run(command, capture_output=True).returncode == 0
        return authenticated and json.loads(message.read_bytes())["nonce"] == expected_nonce

    fresh_request_accepted = accepts_for_request(nonce)
    distinct_nonce = f"{int(nonce[0], 16) ^ 1:x}" + nonce[1:]
    replay_rejected = not accepts_for_request(distinct_nonce)
    message.write_bytes(payload.replace(b"996", b"990"))
    tamper_rejected = not accepts_for_request(nonce)
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
        "fresh_request_accepted": fresh_request_accepted,
        "new_request_nonce": distinct_nonce,
        "replayed_response_rejected_for_new_request": replay_rejected,
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
        "record_kind": "utc_clock_proof_bundle",
        "schema_version": 1,
        "python": platform.python_version(),
        "platform": platform.system(),
        "boottime_available": hasattr(time, "CLOCK_BOOTTIME"),
        "openssl": subprocess.run(
            ["openssl", "version"], check=True, text=True, capture_output=True
        ).stdout.strip(),
        "proof": scenarios(),
    }
    probes: list[dict[str, object]] = []
    if args.https:
        with ThreadPoolExecutor(max_workers=3) as pool:
            probes = list(
                pool.map(
                    https_probe,
                    (
                        "https://www.cloudflare.com/",
                        "https://www.google.com/",
                        "https://www.microsoft.com/",
                    ),
                )
            )
        result["https_diagnostics"] = probes
    result["clock_confidence"] = {
        "record_kind": "utc_clock_confidence",
        "schema_version": 1,
        "prototype": True,
        "observation_id": str(uuid.uuid4()),
        "observation_scope": "UTC_AT_OBSERVE_RETURN",
        "timescale": "UTC",
        "estimate_utc": probes[0]["wall_estimate_at_start"] if probes else None,
        "estimate_reference": "UNTRUSTED_CLIENT_WALL_SAMPLE_AT_FIRST_REQUEST_START",
        "conservative_lower_bound_utc": None,
        "conservative_upper_bound_utc": None,
        "uncertainty_seconds": None,
        "uncertainty_kind": "UNKNOWN",
        "error_terms": {
            "source_accuracy": None,
            "counter_read_0": None,
            "counter_read_1": None,
            "minimum_counter_rate": None,
            "return_delivery": None,
            "outward_rounding": None,
        },
        "trust_state": "REFUSED",
        "failure_reasons": [
            "NO_SOURCE_ACCURACY_GUARANTEE",
            "NO_ELAPSED_RATE_GUARANTEE",
            "NO_RETURN_DELIVERY_BOUND",
        ],
        "identity": {
            "protocol": "https-date-diagnostic-v1",
            "source_policy_sha256": None,
            "verifier_identity": "stdlib TLS diagnostic; no UTC-bound verifier approved",
            "verifier_content_sha256": None,
            "software_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "dependencies": {"python": platform.python_version(), "openssl": result["openssl"]},
            "dependency_content_digests": None,
            "qualification_profile_sha256": None,
            "trust_profile_sha256": None,
        },
        "sources": probes,
        "observations": {
            "clock_id": "CLOCK_BOOTTIME",
            "boot_identity": None,
            "process_id": os.getpid(),
            "request_receipt_samples": [
                {
                    key: probe[key]
                    for key in (
                        "url",
                        "wall_estimate_at_start",
                        "boottime_before_ns",
                        "boottime_after_ns",
                    )
                }
                for probe in probes
            ],
            "verification_final_sample": None,
            "actual_return_time": None,
        },
        "binding": {
            "freshness": "NOT_ESTABLISHED",
            "request_metadata": [{"method": "HEAD", "url": probe["url"]} for probe in probes],
            "raw_request_response_artifacts": None,
            "request_response_wire_hashes": None,
            "synthetic_signed_experiment_ref": "proof.authenticated_interval",
        },
        "retention": {
            "operational_authority": False,
            "selection_digest": None,
            "completion_receipt_digest": None,
        },
    }
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
