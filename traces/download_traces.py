"""Download all runs from a LangSmith project, with their feedback, and save
them to a JSON file.

Run from the traces folder with:

    uv run python3 download_traces.py
    uv run python3 download_traces.py --project my-project --output traces.json
"""

import argparse
import json
import os
import re
import uuid
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from langsmith import Client

# Project name comes from .env (LANGSMITH_PROJECT); override with --project.
DEFAULT_PROJECT = os.getenv("LANGSMITH_PROJECT")

# Runtime tracebacks (captured in run.error and sometimes inputs/outputs) bake in
# the absolute path of the local install, e.g.
#   /Users/<you>/.../engine-workshop/.venv/lib/python3.13/site-packages/...
# That leaks the author's home directory into the committed traces. Rewrite any
# such local project path to a neutral "/app" so the file is portable and clean.
# Derived from this file's location (repo root is the parent of traces/) so it
# keeps working if the checkout is renamed. Two alternatives, longest first:
# the actual repo root path, then any POSIX home-style prefix ending in the
# project dir name (covers traces captured from a different checkout location).
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_LOCAL_PATH_RE = re.compile(
    re.escape(str(_PROJECT_ROOT))
    + r"|/(?:Users|home)/[^\s\"'\\]*?/"
    + re.escape(_PROJECT_ROOT.name)
)


def scrub(text):
    """Replace local absolute project paths with a neutral '/app' prefix."""
    return _LOCAL_PATH_RE.sub("/app", text)


# extra.runtime records the box the trace was captured on. The library and SDK
# versions in there are worth keeping -- they explain the shape of the runs --
# but the OS build string and Python patch level identify one laptop and say
# nothing about the agent, so drop just those two.
_RUNTIME_FINGERPRINT_KEYS = ("platform", "runtime_version")


# The tracing SDK copies the LANGSMITH_* environment into every run's metadata,
# which pins the capture to one workspace/project/endpoint. Those values are
# meaningless (and wrong) once the traces are replayed somewhere else, so drop
# the whole family rather than carrying a stale workspace id around.
def scrub_metadata(extra):
    """Drop capture-environment identifiers from a run's extra.metadata/runtime."""
    if not extra:
        return extra
    scrubbed = dict(extra)

    metadata = extra.get("metadata")
    if metadata:
        cleaned = {k: v for k, v in metadata.items() if not k.startswith("LANGSMITH_")}
        # revision_id is the capture machine's git describe, so it picks up a
        # "-dirty" suffix whenever the checkout had uncommitted edits. Keep the
        # commit, drop the local working-tree state.
        revision_id = cleaned.get("revision_id")
        if isinstance(revision_id, str) and revision_id.endswith("-dirty"):
            cleaned["revision_id"] = revision_id[: -len("-dirty")]
        scrubbed["metadata"] = cleaned

    runtime = extra.get("runtime")
    if runtime:
        scrubbed["runtime"] = {
            k: v for k, v in runtime.items() if k not in _RUNTIME_FINGERPRINT_KEYS
        }

    return scrubbed


# Feedback is a separate resource from runs -- list_runs never returns it -- so it
# has to be fetched by run id and stitched back on. The ids travel as repeated
# query params, so ask for a batch at a time rather than the whole project at once.
FEEDBACK_BATCH = 50

# Issue ids are assigned by LangSmith's own review of the source project. They
# belong to that project's issues, not to these runs, so replaying them would
# staple someone else's triage onto a fresh upload.
SKIP_FEEDBACK_KEYS = {"langsmith_issue_id"}


def fetch_feedback(client, run_ids):
    """Map run id -> its feedback records, fetched in batches."""
    by_run = defaultdict(list)
    for i in range(0, len(run_ids), FEEDBACK_BATCH):
        for feedback in client.list_feedback(run_ids=run_ids[i:i + FEEDBACK_BATCH]):
            if feedback.key in SKIP_FEEDBACK_KEYS:
                continue
            by_run[str(feedback.run_id)].append(
                {
                    "key": feedback.key,
                    "score": feedback.score,
                    "value": feedback.value,
                    "comment": feedback.comment,
                }
            )
    return by_run


def serialize(obj):
    """JSON serializer for objects not serializable by default (datetime, UUID)."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, uuid.UUID):
        return str(obj)
    raise TypeError(f"Type {type(obj)} not serializable")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default=DEFAULT_PROJECT, help="Source project name")
    parser.add_argument("--output", default="traces.json", help="Output file path")
    args = parser.parse_args()

    if not args.project:
        parser.error("No project name found. Set LANGSMITH_PROJECT in .env or pass --project.")

    client = Client()
    print(f"Fetching runs from project '{args.project}'...")

    runs = []
    for run in client.list_runs(project_name=args.project):
        runs.append(
            {
                "id": str(run.id),
                "trace_id": str(run.trace_id),
                "parent_run_id": str(run.parent_run_id) if run.parent_run_id else None,
                "name": run.name,
                "run_type": run.run_type,
                "inputs": run.inputs,
                "outputs": run.outputs,
                "error": run.error,
                "extra": scrub_metadata(run.extra),
                "tags": run.tags,
                "start_time": run.start_time.isoformat() if run.start_time else None,
                "end_time": run.end_time.isoformat() if run.end_time else None,
            }
        )

    feedback_by_run = fetch_feedback(client, [r["id"] for r in runs])
    for run in runs:
        run["feedback"] = feedback_by_run.get(run["id"], [])

    # Sort for stable output: by trace, then root-first, then start_time.
    runs.sort(key=lambda r: (r["trace_id"], r["parent_run_id"] is not None, r["start_time"] or ""))

    # Serialize first, then scrub any local absolute paths out of the whole
    # payload (error tracebacks, inputs, outputs, extra) in one pass.
    payload = scrub(json.dumps(runs, indent=2, default=serialize))
    with open(args.output, "w") as f:
        f.write(payload)

    n_traces = len({r["trace_id"] for r in runs})
    n_feedback = sum(len(r["feedback"]) for r in runs)
    print(
        f"Saved {len(runs)} runs across {n_traces} traces "
        f"({n_feedback} feedback records) to {args.output}"
    )


if __name__ == "__main__":
    main()
