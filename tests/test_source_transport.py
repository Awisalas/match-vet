from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest


class _Clock:
    def __init__(self) -> None:
        self.elapsed = 0.0
        self.sleeps: list[float] = []
        self.origin = datetime(2026, 10, 10, tzinfo=UTC)

    def monotonic(self) -> float:
        return self.elapsed

    def now(self) -> datetime:
        return self.origin + timedelta(seconds=self.elapsed)

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.elapsed += seconds


class _Response:
    def __init__(
        self,
        status: int = 200,
        *,
        headers: Mapping[str, str] | None = None,
        body: bytes = b"synthetic response",
    ) -> None:
        self.status = status
        self.headers = {key.casefold(): value for key, value in (headers or {}).items()}
        self.body = body
        self.closed = False

    def read(self, size: int = -1) -> bytes:
        result, self.body = self.body[:size], self.body[size:]
        return result

    def set_timeout(self, timeout_seconds: float) -> None:
        del timeout_seconds

    def close(self) -> None:
        self.closed = True


class _Transport:
    def __init__(self, *responses: _Response | Exception) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def request(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout_seconds: float,
        resolved_ips: tuple[str, ...],
    ) -> _Response:
        self.calls.append(
            {
                "url": url,
                "headers": dict(headers),
                "timeout_seconds": timeout_seconds,
                "resolved_ips": resolved_ips,
            }
        )
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class _Authorization:
    def __init__(self, url: str, *, requests: int = 8, bytes_limit: int = 1024) -> None:
        self.url = url
        self.requests = requests
        self.bytes_limit = bytes_limit
        self.digests: list[str] = []
        self.refused = False

    def require_current(self, decision_digest: str) -> dict[str, Any]:
        self.digests.append(decision_digest)
        if self.refused:
            raise ValueError("synthetic withdrawal")
        return {
            "contract": "research-source-use-manifest-v1",
            "purpose": "RESEARCH_ONLY",
            "issue": 70,
            "stage": "ACQUISITION",
            "entries": [
                {
                    "endpoint": self.url,
                    "source_type": "AUTOMATED_API",
                    "access_type": "PUBLIC",
                    "requested_operations": [
                        "AUTOMATED_ACCESS",
                        "RAW_RETENTION",
                        "NORMALIZED_RETENTION",
                        "PRIVATE_BACKUP_RESTORE_REPLAY",
                        "DERIVED_STATISTICAL_USE",
                    ],
                    "technical_limits": {
                        "requests": self.requests,
                        "bytes": self.bytes_limit,
                        "timeout_seconds": 3,
                        "bypass_access_controls": False,
                    },
                }
            ],
        }


def _build_downloader(
    tmp_path: Path,
    url: str,
    transport: _Transport,
    *,
    policy_overrides: dict[str, object] | None = None,
    hosts: tuple[str, ...] = ("source.example",),
    resolver: Any = None,
    authorization: _Authorization | None = None,
    clock: _Clock | None = None,
) -> tuple[Any, _Authorization, _Clock]:
    from matchvet.ingestion import (
        ResumableSourceDownloader,
        SourceTransportEndpoint,
        SourceTransportPolicy,
    )

    selected_authorization = authorization or _Authorization(url)
    limits: dict[str, object] = {
        "max_request_count": 16,
        "max_total_bytes": 4096,
        "per_request_timeout_seconds": 2.0,
        "total_elapsed_budget_seconds": 20.0,
        "minimum_pacing_interval_seconds": 0,
        "retry_count": 0,
        "base_backoff_seconds": 1.0,
        "maximum_backoff_seconds": 5.0,
        "redirect_count": 3,
    }
    limits.update(policy_overrides or {})
    endpoints = tuple(SourceTransportEndpoint(host, "/feed/") for host in hosts)
    policy = SourceTransportPolicy(allowed_endpoints=endpoints, **limits)
    selected_clock = clock or _Clock()
    downloader = ResumableSourceDownloader(
        tmp_path,
        policy=policy,
        authorization_repository=selected_authorization,
        http_transport=transport,
        resolve_public_ips=resolver or (lambda _host: ("93.184.216.34",)),
        monotonic=selected_clock.monotonic,
        utcnow=selected_clock.now,
        sleep=selected_clock.sleep,
    )
    return downloader, selected_authorization, selected_clock


def _endpoint(url: str) -> tuple[object, ...]:
    from matchvet.ingestion import SourceTransportEndpoint

    return (SourceTransportEndpoint("source.example", "/feed/"),)


def test_default_resolver_validates_and_returns_only_public_addresses(monkeypatch: Any) -> None:
    import socket

    from matchvet.ingestion import _resolve_public_source_ips

    records = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
    ]
    monkeypatch.setattr("matchvet.ingestion.socket.getaddrinfo", lambda *_args, **_kwargs: records)

    assert _resolve_public_source_ips("source.example") == ("93.184.216.34",)


def test_default_resolver_rejects_private_addresses(monkeypatch: Any) -> None:
    import socket

    from matchvet.ingestion import SourcePolicyError, _resolve_public_source_ips

    records = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]
    monkeypatch.setattr("matchvet.ingestion.socket.getaddrinfo", lambda *_args, **_kwargs: records)

    with pytest.raises(SourcePolicyError, match="nonpublic address"):
        _resolve_public_source_ips("source.example")


def test_live_fetch_requires_current_authorization_before_http_contact(tmp_path: Path) -> None:
    from matchvet.ingestion import (
        ResumableSourceDownloader,
        SourceRefused,
        SourceTransportEndpoint,
        SourceTransportPolicy,
    )

    class NoContactTransport:
        calls = 0

        def request(self, *args: object, **kwargs: object) -> object:
            del args, kwargs
            self.calls += 1
            raise AssertionError("HTTP transport was contacted without authorization")

    transport = NoContactTransport()
    policy = SourceTransportPolicy(
        allowed_endpoints=(SourceTransportEndpoint("source.example", "/feed/"),)
    )
    downloader = ResumableSourceDownloader(
        tmp_path,
        policy=policy,
        http_transport=transport,
        resolve_public_ips=lambda _host: ("93.184.216.34",),
    )

    with pytest.raises(SourceRefused, match="current source authorization"):
        downloader.fetch("https://source.example/feed/schedule.json", cache_key="schedule")

    assert transport.calls == 0


def test_valid_bounded_https_request_records_exact_response_provenance(
    tmp_path: Path,
) -> None:
    from matchvet.ingestion import (
        ResumableSourceDownloader,
        SourceTransportPolicy,
    )

    url = "https://source.example/feed/schedule.json"
    content = b'{"fixtures": []}'
    authorization = _Authorization(url)
    transport = _Transport(_Response(body=content))
    clock = _Clock()
    downloader = ResumableSourceDownloader(
        tmp_path,
        policy=SourceTransportPolicy(
            allowed_endpoints=_endpoint(url),
            max_request_count=3,
            max_total_bytes=128,
            per_request_timeout_seconds=2.0,
            total_elapsed_budget_seconds=20.0,
            minimum_pacing_interval_seconds=0,
            retry_count=0,
            maximum_backoff_seconds=1.0,
            redirect_count=1,
        ),
        authorization_repository=authorization,
        http_transport=transport,
        resolve_public_ips=lambda host: ("93.184.216.34",),
        monotonic=clock.monotonic,
        utcnow=clock.now,
        sleep=clock.sleep,
    )

    downloaded = downloader.fetch(
        url,
        cache_key="bounded",
        authorization_decision_digest="synthetic-current-decision",
    )

    assert downloaded.content == content
    assert downloaded.response_status == 200
    assert downloaded.retrieved_at_utc == "2026-10-10T00:00:00+00:00"
    assert downloaded.bytes_downloaded == len(content)
    assert len(transport.calls) == 1
    assert transport.calls[0]["url"] == url
    assert transport.calls[0]["timeout_seconds"] == 2.0
    assert transport.calls[0]["resolved_ips"] == ("93.184.216.34",)
    assert authorization.digests == ["synthetic-current-decision"] * 4
    assert downloaded.transport_provenance is not None
    assert downloaded.transport_provenance.requested_url == url
    assert downloaded.transport_provenance.final_url == url
    assert downloaded.transport_provenance.response_digest == hashlib.sha256(content).hexdigest()
    assert downloaded.transport_provenance.attempts[0].classification == "SUCCESS"


@pytest.mark.parametrize(
    "url",
    [
        "https://not-allowed.example/feed/file.json",
        "http://source.example/feed/file.json",
        "https://user@source.example/feed/file.json",
        "https://source.example:8443/feed/file.json",
        "https://source.example/private/file.json",
        "https://localhost/feed/file.json",
        "https://127.0.0.1/feed/file.json",
    ],
)
def test_disallowed_initial_target_is_rejected_before_resolution_or_contact(
    tmp_path: Path, url: str
) -> None:
    from matchvet.ingestion import (
        ResumableSourceDownloader,
        SourcePolicyError,
        SourceTransportPolicy,
    )

    transport = _Transport(_Response())
    resolutions: list[str] = []
    downloader = ResumableSourceDownloader(
        tmp_path,
        policy=SourceTransportPolicy(
            allowed_endpoints=_endpoint("https://source.example/feed/file.json")
        ),
        http_transport=transport,
        resolve_public_ips=lambda host: resolutions.append(host) or ("93.184.216.34",),
    )

    with pytest.raises(SourcePolicyError):
        downloader.fetch(url, cache_key="blocked")

    assert resolutions == []
    assert transport.calls == []


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.5", "169.254.10.5", "::1", "fe80::1"])
def test_nonpublic_dns_destination_is_refused_before_http_contact(
    tmp_path: Path, address: str
) -> None:
    from matchvet.ingestion import SourceRefused

    url = "https://source.example/feed/private.json"
    transport = _Transport(_Response())
    downloader, _authorization, _clock = _build_downloader(
        tmp_path,
        url,
        transport,
        resolver=lambda _host: (address,),
    )

    with pytest.raises(SourceRefused, match="nonpublic address"):
        downloader.fetch(url, cache_key="private-dns", authorization_decision_digest="current")

    assert transport.calls == []


def test_same_host_redirect_is_validated_then_followed_and_retained(tmp_path: Path) -> None:
    url = "https://source.example/feed/start.json"
    transport = _Transport(
        _Response(302, headers={"Location": "/feed/final.json"}, body=b""),
        _Response(body=b'{"ok": true}'),
    )
    downloader, _authorization, _clock = _build_downloader(
        tmp_path,
        url,
        transport,
        policy_overrides={"redirect_count": 1},
    )

    downloaded = downloader.fetch(
        url, cache_key="same-host", authorization_decision_digest="current"
    )

    assert [call["url"] for call in transport.calls] == [
        url,
        "https://source.example/feed/final.json",
    ]
    assert downloaded.transport_provenance is not None
    assert downloaded.transport_provenance.redirect_chain == (
        "https://source.example/feed/final.json",
    )
    assert downloaded.transport_provenance.final_url == "https://source.example/feed/final.json"


def test_cross_host_redirect_requires_an_explicit_source_target_pair(tmp_path: Path) -> None:
    url = "https://source.example/feed/start.json"
    transport = _Transport(
        _Response(302, headers={"Location": "https://other.example/feed/final.json"}, body=b""),
        _Response(body=b"cross-host-approved"),
    )
    downloader, _, _ = _build_downloader(
        tmp_path,
        url,
        transport,
        hosts=("source.example", "other.example"),
        policy_overrides={"allowed_cross_host_redirects": (("source.example", "other.example"),)},
    )

    downloaded = downloader.fetch(
        url, cache_key="approved-cross-host", authorization_decision_digest="current"
    )

    assert downloaded.content == b"cross-host-approved"
    assert len(transport.calls) == 2
    assert downloaded.transport_provenance is not None
    assert downloaded.transport_provenance.final_url == "https://other.example/feed/final.json"


def test_unapproved_cross_host_redirect_is_refused_before_target_contact(tmp_path: Path) -> None:
    from matchvet.ingestion import SourceRefused

    url = "https://source.example/feed/start.json"
    transport = _Transport(
        _Response(302, headers={"Location": "https://other.example/feed/final.json"}, body=b"")
    )
    downloader, _authorization, _clock = _build_downloader(
        tmp_path, url, transport, hosts=("source.example", "other.example")
    )

    with pytest.raises(SourceRefused, match="redirect target") as failure:
        downloader.fetch(url, cache_key="cross-host", authorization_decision_digest="current")

    assert len(transport.calls) == 1
    assert failure.value.transport_provenance is not None
    assert failure.value.transport_provenance.redirects[0].validated is False


def test_private_redirect_target_is_refused_before_target_contact(tmp_path: Path) -> None:
    from matchvet.ingestion import SourceRefused

    url = "https://source.example/feed/start.json"
    transport = _Transport(
        _Response(302, headers={"Location": "https://other.example/feed/private.json"}, body=b""),
        _Response(body=b"must not be requested"),
    )
    resolutions = iter((("93.184.216.34",), ("10.0.0.5",)))
    downloader, _authorization, _clock = _build_downloader(
        tmp_path,
        url,
        transport,
        hosts=("source.example", "other.example"),
        policy_overrides={"allowed_cross_host_redirects": (("source.example", "other.example"),)},
        resolver=lambda _host: next(resolutions),
    )

    with pytest.raises(SourceRefused, match="redirect target"):
        downloader.fetch(url, cache_key="private-redirect", authorization_decision_digest="current")

    assert len(transport.calls) == 1


def test_redirect_loop_and_count_exhaustion_stop_before_another_request(tmp_path: Path) -> None:
    from matchvet.ingestion import SourceBudgetExceeded, SourceRefused

    url = "https://source.example/feed/a.json"
    loop_transport = _Transport(
        _Response(302, headers={"Location": "/feed/b.json"}, body=b""),
        _Response(302, headers={"Location": "/feed/a.json"}, body=b""),
    )
    loop_downloader, _, _ = _build_downloader(tmp_path / "loop", url, loop_transport)
    with pytest.raises(SourceRefused, match="redirect target"):
        loop_downloader.fetch(url, cache_key="loop", authorization_decision_digest="current")
    assert len(loop_transport.calls) == 2

    count_transport = _Transport(
        _Response(302, headers={"Location": "/feed/b.json"}, body=b""),
        _Response(302, headers={"Location": "/feed/c.json"}, body=b""),
        _Response(body=b"must not be requested"),
    )
    count_downloader, _, _ = _build_downloader(
        tmp_path / "count", url, count_transport, policy_overrides={"redirect_count": 1}
    )
    with pytest.raises(SourceBudgetExceeded, match="configured bound"):
        count_downloader.fetch(
            url, cache_key="redirect-limit", authorization_decision_digest="current"
        )
    assert len(count_transport.calls) == 2


@pytest.mark.parametrize("status", [401, 403])
def test_authentication_and_access_refusals_are_not_retried(tmp_path: Path, status: int) -> None:
    from matchvet.ingestion import SourceRefused

    url = f"https://source.example/feed/{status}.json"
    transport = _Transport(_Response(status, body=b"access refused"), _Response(body=b"retry"))
    downloader, _, _ = _build_downloader(
        tmp_path, url, transport, policy_overrides={"retry_count": 3}
    )

    with pytest.raises(SourceRefused) as failure:
        downloader.fetch(
            url, cache_key=f"refusal-{status}", authorization_decision_digest="current"
        )

    assert failure.value.http_status == status
    assert failure.value.failure_classification in {
        "AUTHENTICATION_REFUSED",
        "ACCESS_REFUSED",
    }
    assert len(transport.calls) == 1


def test_fixture_acquirer_does_not_fallback_after_a_technical_refusal() -> None:
    from matchvet.ingestion import (
        TARGET_LEAGUES,
        FixtureHistoryAcquirer,
        IngestionPlan,
        SourceRefused,
        football_data_url,
    )

    class RefusingFetcher:
        def __init__(self) -> None:
            self.urls: list[str] = []

        def fetch(self, url: str, *, cache_key: str, refresh: bool = False) -> Any:
            del cache_key, refresh
            self.urls.append(url)
            raise SourceRefused("Synthetic provider access refusal.", http_status=403)

    fetcher = RefusingFetcher()
    acquirer = FixtureHistoryAcquirer(None, fetcher)
    plan = IngestionPlan(
        current_season="2026-27",
        leagues=(TARGET_LEAGUES[0],),
        use_openfootball_fallback=True,
    )

    with pytest.raises(SourceRefused):
        acquirer.acquire(plan)

    assert fetcher.urls == [football_data_url(TARGET_LEAGUES[0], "2026-27")]


@pytest.mark.parametrize(
    "body",
    [b"<html>CAPTCHA: verify you are human</html>", b"Request blocked by web application firewall"],
)
def test_captcha_and_waf_pages_are_technical_refusals(tmp_path: Path, body: bytes) -> None:
    from matchvet.ingestion import SourceRefused

    url = "https://source.example/feed/protected.json"
    transport = _Transport(_Response(body=body))
    downloader, _, _ = _build_downloader(
        tmp_path, url, transport, policy_overrides={"retry_count": 2}
    )

    with pytest.raises(SourceRefused, match="response contained") as failure:
        downloader.fetch(url, cache_key="challenge", authorization_decision_digest="current")

    assert len(transport.calls) == 1
    provenance = failure.value.transport_provenance
    assert provenance is not None
    assert provenance.content_byte_count == len(body)
    assert provenance.response_digest == hashlib.sha256(body).hexdigest()
    assert provenance.retrieved_at_utc is not None


def test_transient_failure_retries_once_then_succeeds_with_bounded_backoff(
    tmp_path: Path,
) -> None:
    url = "https://source.example/feed/retry.json"
    transport = _Transport(
        _Response(503, body=b"busy"),
        _Response(body=b"recovered"),
    )
    resolutions: list[str] = []

    def resolver(host: str) -> tuple[str, ...]:
        resolutions.append(host)
        return ("93.184.216.34", "8.8.8.8")

    downloader, _, clock = _build_downloader(
        tmp_path,
        url,
        transport,
        resolver=resolver,
        policy_overrides={
            "retry_count": 1,
            "base_backoff_seconds": 0.25,
            "maximum_backoff_seconds": 1.0,
        },
    )

    downloaded = downloader.fetch(
        url, cache_key="transient", authorization_decision_digest="current"
    )

    assert downloaded.content == b"recovered"
    assert len(transport.calls) == 2
    assert resolutions == ["source.example"]
    assert transport.calls[0]["resolved_ips"] == transport.calls[1]["resolved_ips"]
    assert clock.sleeps == [0.25]
    assert downloaded.transport_provenance is not None
    assert downloaded.transport_provenance.retry_count == 1
    assert [attempt.classification for attempt in downloaded.transport_provenance.attempts] == [
        "HTTP_503",
        "SUCCESS",
    ]


def test_retry_exhaustion_stops_after_the_configured_retry_count(tmp_path: Path) -> None:
    from matchvet.ingestion import SourceUnavailable

    url = "https://source.example/feed/exhausted.json"
    transport = _Transport(_Response(503, body=b"busy"), _Response(503, body=b"still busy"))
    downloader, _, clock = _build_downloader(
        tmp_path, url, transport, policy_overrides={"retry_count": 1}
    )

    with pytest.raises(SourceUnavailable) as failure:
        downloader.fetch(url, cache_key="exhausted", authorization_decision_digest="current")

    assert failure.value.failure_classification == "RETRY_EXHAUSTED"
    assert len(transport.calls) == 2
    assert clock.sleeps == [1.0]


def test_minimum_pacing_interval_is_observed_between_requests(tmp_path: Path) -> None:
    url = "https://source.example/feed/paced.json"
    transport = _Transport(_Response(body=b"one"), _Response(body=b"two"))
    downloader, _, clock = _build_downloader(
        tmp_path,
        url,
        transport,
        policy_overrides={"minimum_pacing_interval_seconds": 2.0},
    )

    downloader.fetch(url, cache_key="paced-one", authorization_decision_digest="current")
    downloader.fetch(url, cache_key="paced-two", authorization_decision_digest="current")

    assert len(transport.calls) == 2
    assert clock.sleeps == [2.0]


def test_retry_after_is_honored_before_the_next_provider_request(tmp_path: Path) -> None:
    url = "https://source.example/feed/rate-limited.json"
    transport = _Transport(
        _Response(429, headers={"Retry-After": "3"}, body=b"rate limited"),
        _Response(body=b"ready"),
    )
    downloader, _, clock = _build_downloader(
        tmp_path,
        url,
        transport,
        policy_overrides={"retry_count": 1, "maximum_backoff_seconds": 5.0},
    )

    downloaded = downloader.fetch(
        url, cache_key="retry-after", authorization_decision_digest="current"
    )

    assert downloaded.content == b"ready"
    assert len(transport.calls) == 2
    assert clock.sleeps == [3.0]
    assert downloaded.transport_provenance is not None
    assert downloaded.transport_provenance.attempts[0].retry_after_seconds == 3.0
    assert downloaded.transport_provenance.attempts[0].retry_delay_seconds == 3.0


def test_http_date_retry_after_preserves_fractional_wait(tmp_path: Path) -> None:
    url = "https://source.example/feed/http-date-rate-limited.json"
    transport = _Transport(
        _Response(429, headers={"Retry-After": "Sat, 10 Oct 2026 00:00:10 GMT"}),
        _Response(body=b"ready"),
    )
    clock = _Clock()
    clock.origin += timedelta(milliseconds=500)
    downloader, _, clock = _build_downloader(
        tmp_path,
        url,
        transport,
        policy_overrides={"retry_count": 1, "maximum_backoff_seconds": 12.0},
        clock=clock,
    )

    downloaded = downloader.fetch(
        url, cache_key="http-date-retry-after", authorization_decision_digest="current"
    )

    assert downloaded.content == b"ready"
    assert len(transport.calls) == 2
    assert clock.sleeps == [9.5]
    assert downloaded.transport_provenance is not None
    assert downloaded.transport_provenance.attempts[0].retry_after_seconds == 9.5
    assert downloaded.transport_provenance.attempts[0].retry_delay_seconds == 9.5


def test_retry_after_past_remaining_budget_defers_without_sleep_or_early_request(
    tmp_path: Path,
) -> None:
    from matchvet.ingestion import SourceDeferred

    url = "https://source.example/feed/deferred.json"
    transport = _Transport(
        _Response(429, headers={"Retry-After": "3"}, body=b"rate limited"),
        _Response(body=b"too early"),
    )
    downloader, _, clock = _build_downloader(
        tmp_path,
        url,
        transport,
        policy_overrides={
            "retry_count": 1,
            "maximum_backoff_seconds": 5.0,
            "total_elapsed_budget_seconds": 2.0,
        },
    )

    with pytest.raises(SourceDeferred):
        downloader.fetch(url, cache_key="deferred", authorization_decision_digest="current")

    assert len(transport.calls) == 1
    assert clock.sleeps == []


def test_request_budget_prevents_a_retry_without_waiting(tmp_path: Path) -> None:
    from matchvet.ingestion import SourceBudgetExceeded

    url = "https://source.example/feed/request-budget.json"
    transport = _Transport(_Response(503, body=b"busy"), _Response(body=b"must not retry"))
    downloader, _, clock = _build_downloader(
        tmp_path,
        url,
        transport,
        policy_overrides={"max_request_count": 1, "retry_count": 1},
    )

    with pytest.raises(SourceBudgetExceeded) as failure:
        downloader.fetch(url, cache_key="request-budget", authorization_decision_digest="current")

    assert failure.value.failure_classification == "REQUEST_BUDGET_EXHAUSTED"
    assert len(transport.calls) == 1
    assert clock.sleeps == []


def test_provider_error_response_bytes_count_toward_the_total_byte_budget(
    tmp_path: Path,
) -> None:
    from matchvet.ingestion import SourceBudgetExceeded

    url = "https://source.example/feed/error-byte-budget.json"
    transport = _Transport(_Response(503, body=b"12345"), _Response(body=b"must not retry"))
    downloader, _, _ = _build_downloader(
        tmp_path,
        url,
        transport,
        policy_overrides={"max_total_bytes": 4, "retry_count": 1},
    )

    with pytest.raises(SourceBudgetExceeded) as failure:
        downloader.fetch(
            url, cache_key="error-byte-budget", authorization_decision_digest="current"
        )

    assert failure.value.failure_classification == "BYTE_BUDGET_EXHAUSTED"
    assert downloader.network_bytes == 4
    assert len(transport.calls) == 1


def test_byte_budget_stops_response_body_at_the_configured_limit(tmp_path: Path) -> None:
    from matchvet.ingestion import SourceBudgetExceeded

    url = "https://source.example/feed/byte-budget.json"
    transport = _Transport(_Response(headers={"Content-Length": "5"}, body=b"12345"))
    downloader, _, _ = _build_downloader(
        tmp_path,
        url,
        transport,
        policy_overrides={"max_total_bytes": 4},
    )

    with pytest.raises(SourceBudgetExceeded) as failure:
        downloader.fetch(url, cache_key="byte-budget", authorization_decision_digest="current")

    assert failure.value.failure_classification == "BYTE_BUDGET_EXHAUSTED"
    assert len(transport.calls) == 1


def test_request_timeout_is_classified_and_not_retried(tmp_path: Path) -> None:

    from matchvet.ingestion import SourceUnavailable

    url = "https://source.example/feed/timeout.json"
    transport = _Transport(TimeoutError("synthetic timeout"), _Response(body=b"too late"))
    downloader, _, _ = _build_downloader(
        tmp_path, url, transport, policy_overrides={"retry_count": 0}
    )

    with pytest.raises(SourceUnavailable) as failure:
        downloader.fetch(url, cache_key="timeout", authorization_decision_digest="current")

    assert failure.value.failure_classification == "REQUEST_TIMEOUT"
    assert len(transport.calls) == 1


def test_body_read_cannot_outlive_the_per_request_timeout(tmp_path: Path) -> None:
    from matchvet.ingestion import SourceUnavailable

    url = "https://source.example/feed/slow-body.json"
    clock = _Clock()

    class SlowResponse(_Response):
        def read(self, size: int = -1) -> bytes:
            chunk = super().read(size)
            clock.elapsed += 2.1
            return chunk

    transport = _Transport(SlowResponse(body=b"late"))
    downloader, _, _ = _build_downloader(
        tmp_path,
        url,
        transport,
        clock=clock,
        policy_overrides={
            "per_request_timeout_seconds": 2.0,
            "total_elapsed_budget_seconds": 10.0,
        },
    )

    with pytest.raises(SourceUnavailable) as failure:
        downloader.fetch(url, cache_key="slow-body", authorization_decision_digest="current")

    assert failure.value.failure_classification == "REQUEST_TIMEOUT"
    assert failure.value.transport_provenance is not None
    assert failure.value.transport_provenance.content_byte_count == 4
    assert len(transport.calls) == 1


def test_total_elapsed_budget_exhaustion_prevents_cache_admission(tmp_path: Path) -> None:
    from matchvet.ingestion import SourceBudgetExceeded

    url = "https://source.example/feed/slow.json"
    clock = _Clock()

    class SlowTransport(_Transport):
        def request(self, *args: Any, **kwargs: Any) -> _Response:
            response = super().request(*args, **kwargs)
            clock.elapsed = 2.0
            return response

    transport = SlowTransport(_Response(body=b"late"))
    downloader, _, _ = _build_downloader(
        tmp_path,
        url,
        transport,
        policy_overrides={"total_elapsed_budget_seconds": 1.0},
        clock=clock,
    )

    with pytest.raises(SourceBudgetExceeded) as failure:
        downloader.fetch(url, cache_key="elapsed", authorization_decision_digest="current")

    assert failure.value.failure_classification == "TOTAL_ELAPSED_BUDGET_EXHAUSTED"
    assert len(transport.calls) == 1
    assert downloader.inspect_cache("elapsed") is None


def test_cache_replay_uses_retained_digest_and_never_contacts_http(tmp_path: Path) -> None:
    from matchvet.ingestion import (
        ResumableSourceDownloader,
        SourceIntegrityError,
        SourceTransportEndpoint,
        SourceTransportPolicy,
    )

    url = "https://source.example/feed/replay.json"
    transport = _Transport(_Response(body=b"retained"))
    downloader, _, clock = _build_downloader(tmp_path, url, transport)
    downloaded = downloader.fetch(url, cache_key="replay", authorization_decision_digest="current")
    replay_only = ResumableSourceDownloader(
        tmp_path,
        policy=SourceTransportPolicy(
            allowed_endpoints=(SourceTransportEndpoint("source.example", "/feed/"),)
        ),
        http_transport=_Transport(),
        resolve_public_ips=lambda _host: pytest.fail("cache replay must not resolve DNS"),
        monotonic=clock.monotonic,
        utcnow=clock.now,
        sleep=clock.sleep,
    )

    cached = replay_only.fetch(url, cache_key="replay")

    assert cached.from_cache is True
    assert cached.content == b"retained"
    assert cached.transport_provenance == downloaded.transport_provenance
    assert len(transport.calls) == 1
    data_path, _meta_path, _part_path = replay_only._paths("replay")
    data_path.write_bytes(b"corrupted")
    with pytest.raises(SourceIntegrityError, match="digest"):
        replay_only.inspect_cache("replay")


@pytest.mark.parametrize("provenance_state", ["missing", "null"])
def test_schema_two_cache_without_transport_provenance_fails_closed(
    tmp_path: Path, provenance_state: str
) -> None:
    import json

    from matchvet.ingestion import SourceIntegrityError

    url = "https://source.example/feed/cache-provenance.json"
    content = b"retained bytes"
    transport = _Transport(_Response(body=content))
    downloader, _, _ = _build_downloader(tmp_path, url, transport)
    downloader.fetch(url, cache_key="cache-provenance", authorization_decision_digest="current")
    _data_path, meta_path, _part_path = downloader._paths("cache-provenance")
    metadata = json.loads(meta_path.read_bytes())
    if provenance_state == "missing":
        del metadata["transport"]
    else:
        metadata["transport"] = None
    meta_path.write_text(
        json.dumps(metadata, sort_keys=True, separators=(",", ":")), encoding="utf-8"
    )

    with pytest.raises(SourceIntegrityError, match="unsupported shape"):
        downloader.inspect_cache("cache-provenance")
    assert len(transport.calls) == 1


def test_exact_transport_provenance_is_retained_with_the_source_capture(tmp_path: Path) -> None:
    import json

    from matchvet.ingestion import (
        FixtureHistoryImporter,
        FootballDataCSVParser,
        SourceCaptureInput,
        league_by_key,
    )
    from matchvet.store import open_store

    url = "https://source.example/feed/fixtures.csv"
    content = (
        b"Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR\n"
        b"E0,21/08/2026,20:00,Arsenal,Coventry,2,1,H\n"
    )
    transport = _Transport(_Response(body=content))
    downloader, _, _ = _build_downloader(tmp_path, url, transport)
    downloaded = downloader.fetch(url, cache_key="capture", authorization_decision_digest="current")
    parsed = FootballDataCSVParser().parse(
        downloaded.content,
        league=league_by_key("premier_league"),
        season="2026-27",
    )

    with open_store(tmp_path / "store.sqlite3", private_root=tmp_path) as store:
        importer = FixtureHistoryImporter(store, private_root=tmp_path)
        result = importer.import_dataset(
            parsed,
            downloaded.content,
            SourceCaptureInput(
                source_url=url,
                retrieved_at_utc=downloaded.retrieved_at_utc,
                response_status=downloaded.response_status,
                content_type=downloaded.content_type,
                observed_terms="synthetic public source",
                cache_key="capture",
                transport_provenance=downloaded.transport_provenance,
            ),
        )

        capture = next(
            item
            for item in importer.source_captures()
            if item.capture_id == result.source_capture_id
        )

    assert capture.transport_provenance_json is not None
    provenance = json.loads(capture.transport_provenance_json)
    assert provenance["requested_url"] == url
    assert provenance["final_url"] == url
    assert provenance["response_status"] == 200
    assert provenance["content_digest"] == hashlib.sha256(content).hexdigest()
    assert provenance["attempts"][0]["classification"] == "SUCCESS"


def test_legacy_retained_cache_without_transport_metadata_remains_replayable(
    tmp_path: Path,
) -> None:
    import json

    url = "https://source.example/feed/legacy-cache.json"
    content = b'{"retained": true}'
    transport = _Transport()
    clock = _Clock()
    downloader, _, _ = _build_downloader(tmp_path, url, transport, clock=clock)
    data_path, meta_path, _part_path = downloader._paths("legacy-cache")
    data_path.write_bytes(content)
    metadata = {
        "content_sha256": hashlib.sha256(content).hexdigest(),
        "content_type": "application/json",
        "retrieved_at_utc": clock.now().isoformat(),
        "response_status": 200,
        "url": url,
    }
    meta_path.write_text(
        json.dumps(metadata, sort_keys=True, separators=(",", ":")), encoding="utf-8"
    )

    replayed = downloader.fetch(url, cache_key="legacy-cache")

    assert replayed.content == content
    assert replayed.from_cache is True
    assert replayed.transport_provenance is None
    assert transport.calls == []


def test_invalid_current_authority_refuses_before_dns_or_http_contact(tmp_path: Path) -> None:
    from matchvet.ingestion import SourceRefused

    url = "https://source.example/feed/withdrawn.json"
    authorization = _Authorization(url)
    authorization.refused = True
    resolutions: list[str] = []
    transport = _Transport(_Response(body=b"should not contact"))
    downloader, _, _ = _build_downloader(
        tmp_path,
        url,
        transport,
        authorization=authorization,
        resolver=lambda host: resolutions.append(host) or ("93.184.216.34",),
    )

    with pytest.raises(SourceRefused, match="invalid or withdrawn"):
        downloader.fetch(url, cache_key="withdrawn", authorization_decision_digest="stale")

    assert resolutions == []
    assert transport.calls == []


def test_withdrawal_after_a_transient_response_stops_before_retry_contact(tmp_path: Path) -> None:
    from matchvet.ingestion import SourceRefused

    url = "https://source.example/feed/withdraw-during-retry.json"
    authorization = _Authorization(url)

    class RevokingTransport(_Transport):
        def request(self, *args: Any, **kwargs: Any) -> _Response:
            response = super().request(*args, **kwargs)
            authorization.refused = True
            return response

    transport = RevokingTransport(
        _Response(503, body=b"busy"),
        _Response(body=b"must not retry after withdrawal"),
    )
    resolutions: list[str] = []
    downloader, _, _ = _build_downloader(
        tmp_path,
        url,
        transport,
        authorization=authorization,
        policy_overrides={"retry_count": 2},
        resolver=lambda host: resolutions.append(host) or ("93.184.216.34",),
    )

    with pytest.raises(SourceRefused, match="changed before destination validation"):
        downloader.fetch(
            url, cache_key="withdraw-during-retry", authorization_decision_digest="current"
        )

    assert len(transport.calls) == 1
    assert resolutions == ["source.example"]


def test_stale_cached_success_does_not_authorize_a_new_live_request(tmp_path: Path) -> None:
    from matchvet.ingestion import SourceRefused

    url = "https://source.example/feed/stale-cache.json"
    clock = _Clock()
    transport = _Transport(_Response(body=b"cached"), _Response(body=b"unauthorized refresh"))
    downloader, _, _ = _build_downloader(
        tmp_path,
        url,
        transport,
        clock=clock,
    )
    downloader.fetch(url, cache_key="stale", authorization_decision_digest="current")
    clock.elapsed = 7 * 60 * 60
    replay_only = type(downloader)(
        tmp_path,
        policy=downloader.policy,
        http_transport=transport,
        resolve_public_ips=lambda _host: pytest.fail("stale-cache refusal must precede DNS"),
        monotonic=clock.monotonic,
        utcnow=clock.now,
        sleep=clock.sleep,
    )

    with pytest.raises(SourceRefused, match="current source authorization"):
        replay_only.fetch(url, cache_key="stale")

    assert len(transport.calls) == 1
    assert replay_only.inspect_cache("stale") is not None
