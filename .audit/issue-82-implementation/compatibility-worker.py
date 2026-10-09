"""Execute historical writers under either checkout against identical offline inputs."""

import json
import sys
from pathlib import Path

from matchweek_research_support import Clock

from matchvet.artifacts import ArtifactStore
from matchvet.f13 import engine_version_identity
from matchvet.f15 import AnalyzeMatchweek, AnalyzeMatchweekRequest
from matchvet.f16 import F16MatchweekProcessor
from matchvet.runs import RunPhase, WorkContext
from matchvet.store import open_store
from matchvet.t15 import PolicyVersion

root = Path(sys.argv[1])
values = json.loads(Path(sys.argv[2]).read_text())
values["cutoff_ids"] = tuple(values["cutoff_ids"])
values["policy"] = PolicyVersion.from_mapping(values["policy"])
request = AnalyzeMatchweekRequest(**values)
with open_store(root / "store.sqlite3", private_root=root) as store:
    inputs, sources = AnalyzeMatchweek(store, clock=Clock())._inputs(request)
    context = WorkContext(
        "direct",
        "direct",
        request.matchweek,
        RunPhase.PREFERENCE_VETTING,
        1,
        "RESEARCH_ONLY",
        "0" * 64,
        "0" * 64,
        1,
    )
    result = F16MatchweekProcessor(store, clock=Clock()).process_phase(
        context,
        freeze_id=request.freeze_id,
        cutoff_policy_digest=request.cutoff_policy_digest,
        cutoff_ids=request.cutoff_ids,
        profile_digest=request.preference_profile_digest,
        policy=request.policy,
    )
    artifacts = ArtifactStore(store)
    output = {
        "engine_version": engine_version_identity(),
        "input_digest": inputs.aggregate_digest,
        "inputs": json.loads(inputs.to_json()),
        "sources": sources,
        "manifest": result.result_digest,
        "artifacts": {
            metadata.digest: {
                "media_type": metadata.media_type,
                "canonical_hex": artifacts.read_artifact(metadata.digest).hex(),
            }
            for metadata in store.artifact_catalog()
        },
    }
Path(sys.argv[3]).write_text(json.dumps(output, sort_keys=True))
