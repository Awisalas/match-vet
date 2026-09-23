#!/usr/bin/env python3
"""Opt-in network smoke check.

Run with: PYTHONPATH=src python scripts/live_fixture_smoke.py --live --season 2026-27
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from matchvet.ingestion import (
    OBSERVED,
    TARGET_LEAGUES,
    LeagueConfig,
    OpenFootballJSONParser,
    OpenFootballTextParser,
    SourceParseError,
    openfootball_text_url,
    openfootball_url,
    season_code,
)

MAX_FEED_BYTES = 8 * 1024 * 1024


def _future_unscored_rows(
    content: bytes,
    league: LeagueConfig,
    season: str,
    *,
    text_format: bool,
) -> int:
    source_parser = OpenFootballTextParser() if text_format else OpenFootballJSONParser()
    parsed = source_parser.parse(content, league=league, season=season)
    now = datetime.now(UTC)
    return sum(
        row.kickoff_utc is not None
        and row.kickoff_utc > now
        and row.fields["full_time_home_goals"].state is not OBSERVED
        and row.fields["full_time_away_goals"].state is not OBSERVED
        for row in parsed.rows
    )


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="allow live HTTPS requests")
    parser.add_argument("--season", required=True, help="season in YYYY-YY form")
    args = parser.parse_args(arguments)
    if not args.live:
        parser.error("--live is required; this smoke test is never run implicitly")
    season_code(args.season)

    failed = False
    for league in TARGET_LEAGUES:
        if not league.openfootball_supported:
            continue
        outcomes: dict[str, tuple[int | None, int, str | None]] = {}
        for label, url, text_format in (
            ("json", openfootball_url(league, args.season), False),
            ("footballtxt", openfootball_text_url(league, args.season), True),
        ):
            request = Request(
                url,
                headers={
                    "User-Agent": "MatchVet-F02-Live-Smoke/1.0",
                    "Accept": "application/json,text/plain;q=0.9",
                },
                method="GET",
            )
            try:
                with urlopen(request, timeout=30) as response:
                    content = response.read(MAX_FEED_BYTES + 1)
                    status = int(response.status)
                if len(content) > MAX_FEED_BYTES:
                    raise ValueError(f"feed exceeded {MAX_FEED_BYTES} bytes")
                future_rows = _future_unscored_rows(
                    content, league, args.season, text_format=text_format
                )
                outcomes[label] = (status, future_rows, None)
            except (HTTPError, URLError, OSError, SourceParseError, ValueError) as error:
                outcomes[label] = (None, 0, str(error))

        json_status, json_rows, json_error = outcomes["json"]
        text_status, text_rows, text_error = outcomes["footballtxt"]
        print(
            f"{league.key}: json_http={json_status or 'UNAVAILABLE'} "
            f"json_future_unscored_rows={json_rows} "
            f"footballtxt_http={text_status or 'UNAVAILABLE'} "
            f"footballtxt_future_unscored_rows={text_rows} coverage=UNKNOWN"
        )
        if json_error:
            print(f"  json diagnostic: {json_error}")
        if text_error:
            print(f"  footballtxt diagnostic: {text_error}")
        failed = failed or max(json_rows, text_rows) == 0

    print("Belgian Pro League: coverage=UNKNOWN (no approved schedule source configured)")
    if failed:
        return 1
    print("Smoke passed; feed availability and rows do not establish fixture completeness.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
