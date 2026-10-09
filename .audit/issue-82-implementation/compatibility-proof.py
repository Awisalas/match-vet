"""Compare complete historical canonical artifacts with the exact pre-#82 source."""

import json
import os
import shutil
import subprocess
import tarfile
import tempfile
from dataclasses import asdict
from pathlib import Path

from test_issue76 import candidate

repo = Path.cwd()
audit = repo / ".audit/issue-82-implementation"


class TemporaryFixtures:
    def __init__(self, root):
        self.root = root

    def mktemp(self, name):
        return Path(tempfile.mkdtemp(prefix=name, dir=self.root))


with tempfile.TemporaryDirectory(prefix="issue82-compatibility-") as temporary:
    root = Path(temporary)
    case = candidate.__wrapped__(TemporaryFixtures(root))
    values = asdict(case.request)
    values.pop("candidate_contract_digest", None)
    values["policy"] = case.request.policy.to_dict()
    request_path = root / "request.json"
    request_path.write_text(json.dumps(values))
    archive = root / "baseline.tar"
    with archive.open("wb") as stream:
        subprocess.run(
            ["git", "archive", "a65c033160dd1b6e50a5bf69e9c7e0aecb4e8bf0", "src"],
            stdout=stream,
            check=True,
        )
    baseline = root / "baseline"
    baseline.mkdir()
    with tarfile.open(archive) as stream:
        stream.extractall(baseline, filter="data")
    outputs = []
    for label, source in (("baseline", baseline / "src"), ("current", repo / "src")):
        destination = root / label / "store"
        destination.mkdir(parents=True)
        shutil.copytree(case.root / "objects", destination / "objects")
        shutil.copyfile(case.root / "store.sqlite3", destination / "store.sqlite3")
        result = root / (label + ".json")
        environment = dict(os.environ)
        environment["PYTHONPATH"] = f"{repo / 'tests/no_network'}:{source}:{repo / 'tests'}"
        subprocess.run(
            [
                str(repo / ".venv/bin/python"),
                str(audit / "compatibility-worker.py"),
                str(destination),
                str(request_path),
                str(result),
            ],
            env=environment,
            check=True,
        )
        outputs.append(json.loads(result.read_text()))
        print(label + " complete", flush=True)
    assert outputs[0] == outputs[1], (
        "Historical canonical bytes or software/engine identities changed"
    )
    media = sorted({value["media_type"] for value in outputs[0]["artifacts"].values()})
    print(
        json.dumps(
            {
                "result": "PASS",
                "base": "a65c033160dd1b6e50a5bf69e9c7e0aecb4e8bf0",
                "artifacts": len(outputs[0]["artifacts"]),
                "media_types": media,
                "manifest": outputs[0]["manifest"],
                "input_digest": outputs[0]["input_digest"],
                "engine_version": outputs[0]["engine_version"],
            },
            indent=2,
        ),
        flush=True,
    )
