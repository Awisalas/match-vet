"""Explicit causal F15 CLI dispatch over an already retained candidate descriptor."""

from __future__ import annotations

import argparse
import json

from matchvet.causal_candidate import CAUSAL_CONTRACT, writer_contract
from matchvet.f15 import AnalyzeMatchweek
from matchvet.f15_inputs import request_from_candidate
from matchvet.store import default_database_path, open_store, termux_private_root


def handle_candidate_run(arguments: argparse.Namespace) -> int:
    from matchvet.cli import _print_error, _resume_command, _run_command

    try:
        contract = writer_contract(
            arguments.candidate_contract_digest, arguments.selection_contract
        )
        if contract != CAUSAL_CONTRACT:
            if arguments.command == "run":
                return _run_command(arguments.date, arguments.store, arguments.as_json)
            return _resume_command(arguments.run_id, arguments.store, arguments.as_json)
        digest = arguments.candidate_contract_digest
        assert isinstance(digest, str)
        with open_store(
            arguments.store or default_database_path(), private_root=termux_private_root()
        ) as store:
            request = request_from_candidate(store, digest)
            service = AnalyzeMatchweek(store, candidate_contract_digest=digest)
            if arguments.command == "run":
                if arguments.date is not None and arguments.date != request.matchweek:
                    raise ValueError("Matchweek differs from the explicit candidate descriptor.")
                result = service.start(request)
            else:
                if arguments.run_id is None:
                    raise ValueError("Causal resume requires the exact existing run ID.")
                result = service.resume(arguments.run_id, request)
            payload = {
                "run_id": result.run_id,
                "run_state": result.run_state,
                "phase": result.phase,
                "analysis_state": result.analysis_state,
                "candidate_contract_digest": digest,
                "matchweek_result_identity": result.matchweek_result_identity,
                "durable_result_identities": result.durable_result_identities,
                "analysis_complete": result.analysis_complete,
            }
    except (OSError, RuntimeError, ValueError, PermissionError) as error:
        return _print_error(
            {
                "status": "REFUSED",
                "code": "MV-CAUSAL-CANDIDATE-REFUSED",
                "explanation": str(error),
                "last_checkpoint": "none",
                "reuse_state": "NONE",
                "recovery_command": "matchvet status",
            },
            arguments.as_json,
        )
    if arguments.as_json:
        print(json.dumps(payload, sort_keys=True, indent=2))
    else:
        print(f"MatchVet causal candidate: {digest}")
        print(f"Run: {result.run_id}; {result.run_state}; {result.analysis_state}")
    return 0
