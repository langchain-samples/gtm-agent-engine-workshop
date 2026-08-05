"""Load downloaded traces, spread timestamps over a recent window, regenerate IDs, and upload.

Run from the traces folder with:

    uv run python3 upload_traces.py
    uv run python3 upload_traces.py --project my-project --input traces.json
    uv run python3 upload_traces.py --days 0.5 --seed 42
"""

import argparse
import json
import os
import random
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

load_dotenv()

from langsmith import Client, uuid7

# Project name comes from .env (LANGSMITH_PROJECT); override with --project.
DEFAULT_PROJECT = os.getenv("LANGSMITH_PROJECT")

# Ingest rejects any run whose start_time is more than 24 hours from now, on both
# the multipart and batch endpoints, with a 422. That caps how far back traces can
# be dated: ask for more and the runs are silently dropped. Stay under the limit
# so the last trace in the spread still clears it once the upload has run a while.
MAX_BACKDATE_DAYS = 0.95

# Ingested runs take a moment to become queryable, so the landing check retries
# rather than failing on the first empty read.
WAIT_ATTEMPTS = 10
WAIT_SECONDS = 3


def parse_dt(s):
    """Parse an ISO timestamp string into a naive (tz-stripped) datetime."""
    if s is None:
        return None
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is not None:
        dt = dt.replace(tzinfo=None)
    return dt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default=DEFAULT_PROJECT, help="Target project name")
    parser.add_argument("--input", default="traces.json", help="Input file path")
    parser.add_argument(
        "--days",
        type=float,
        default=MAX_BACKDATE_DAYS,
        help=f"Spread traces randomly over this many days ending now "
        f"(default: {MAX_BACKDATE_DAYS}; the ingest API rejects anything older than 24h)",
    )
    parser.add_argument("--seed", type=int, help="Seed for reproducible timestamp spreading")
    args = parser.parse_args()

    if args.days > MAX_BACKDATE_DAYS:
        parser.error(
            f"--days {args.days} exceeds the ingest API's 24-hour backdating limit; "
            f"runs older than that are rejected with a 422 and never land. "
            f"Use --days {MAX_BACKDATE_DAYS} or less."
        )

    if args.seed is not None:
        random.seed(args.seed)

    if not args.project:
        parser.error("No project name found. Set LANGSMITH_PROJECT in .env or pass --project.")

    with open(args.input) as f:
        runs = json.load(f)

    print(f"Loaded {len(runs)} runs from {args.input}")
    if not runs:
        print("Nothing to upload.")
        return

    start_times = [parse_dt(r["start_time"]) for r in runs if r.get("start_time")]
    if not start_times:
        raise ValueError("No runs have a start_time; cannot compute time shift.")

    # Build a map from old IDs to fresh uuid7s (uuid7 is time-ordered).
    # For root runs, trace_id must equal id, so map both to the same new uuid7.
    id_map = {}
    for run in runs:
        if run.get("parent_run_id") is None:
            root_new_id = str(uuid7())
            id_map[run["id"]] = root_new_id
            id_map[run["trace_id"]] = root_new_id
    for run in runs:
        for field in ("id", "parent_run_id"):
            old_id = run.get(field)
            if old_id and old_id not in id_map:
                id_map[old_id] = str(uuid7())

    # Group runs by (new) trace id, keeping original times for now.
    traces = defaultdict(list)
    for run in runs:
        trace_id = id_map[run["trace_id"]]
        traces[trace_id].append(
            {
                "id": id_map[run["id"]],
                "trace_id": trace_id,
                "dotted_order": None,  # populated below
                "parent_run_id": id_map.get(run.get("parent_run_id")),
                "name": run["name"],
                "run_type": run["run_type"],
                "inputs": run.get("inputs") or {},
                "outputs": run.get("outputs"),
                "error": run.get("error"),
                "extra": run.get("extra") or {},
                "tags": run.get("tags"),
                "start_time": parse_dt(run["start_time"]),
                "end_time": parse_dt(run["end_time"]) if run.get("end_time") else None,
                # Carried through the id remap and replayed once the runs exist.
                # Absent from traces captured before feedback was collected.
                "feedback": run.get("feedback") or [],
            }
        )

    # Scatter each trace to a random point in the last `--days` days, shifting all of
    # its runs by the same delta so the internal spacing/nesting of a trace is intact.
    # Traces land independently of one another, so the batch looks like organic
    # day-to-day usage rather than one replayed burst.
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    window = timedelta(days=args.days)
    for trace_runs in traces.values():
        trace_start = min(r["start_time"] for r in trace_runs)
        trace_end = max(
            [r["end_time"] for r in trace_runs if r["end_time"]] or [trace_start]
        )
        duration = trace_end - trace_start
        # Keep the whole trace inside the window (nothing ends in the future).
        latest_start = max(window - duration, timedelta(0))
        offset = timedelta(seconds=random.uniform(0, latest_start.total_seconds()))
        delta = (now - window + offset) - trace_start
        for run in trace_runs:
            run["start_time"] += delta
            if run["end_time"]:
                run["end_time"] += delta

    all_starts = [r["start_time"] for trace_runs in traces.values() for r in trace_runs]
    print(
        f"Spread {len(traces)} traces over {args.days} days: "
        f"{min(all_starts):%Y-%m-%d %H:%M} to {max(all_starts):%Y-%m-%d %H:%M}"
    )

    client = Client()
    print(f"Uploading {len(traces)} traces to project '{args.project}'...")

    for i, (trace_id, trace_runs) in enumerate(traces.items()):
        # Sort: root first, then children by start_time.
        trace_runs.sort(key=lambda r: (r["parent_run_id"] is not None, r["start_time"]))

        # Build dotted_order by walking the parent chain, so nesting is correct
        # regardless of run order or start_time skew.
        runs_by_id = {run["id"]: run for run in trace_runs}
        dotted_orders = {}

        def build_dotted_order(run):
            rid = run["id"]
            if rid in dotted_orders:
                return dotted_orders[rid]
            ts = run["start_time"].strftime("%Y%m%dT%H%M%S%f") + "Z"
            segment = f"{ts}{rid}"
            parent = runs_by_id.get(run["parent_run_id"])
            order = segment if parent is None else f"{build_dotted_order(parent)}.{segment}"
            dotted_orders[rid] = order
            run["dotted_order"] = order
            return order

        for run in trace_runs:
            build_dotted_order(run)

        for run in trace_runs:
            client.create_run(
                id=run["id"],
                trace_id=run["trace_id"],
                dotted_order=run["dotted_order"],
                parent_run_id=run["parent_run_id"],
                name=run["name"],
                run_type=run["run_type"],
                inputs=run["inputs"],
                outputs=run.get("outputs"),
                error=run.get("error"),
                extra=run.get("extra"),
                tags=run.get("tags"),
                start_time=run["start_time"],
                end_time=run["end_time"],
                project_name=args.project,
            )

        if (i + 1) % 10 == 0:
            print(f"  Uploaded {i + 1}/{len(traces)} traces")

    # Wait for all background operations to complete.
    print("Flushing...")
    client.flush()

    # create_run() only enqueues; the HTTP POST happens on a background thread and
    # a rejected batch is logged there, not raised here. Count what actually landed
    # before claiming success, so a server-side rejection cannot pass for an upload.
    expected_ids = {run["id"] for trace_runs in traces.values() for run in trace_runs}
    landed_ids = set()
    for attempt in range(WAIT_ATTEMPTS):
        landed_ids = {
            str(r.id) for r in client.list_runs(project_name=args.project)
        } & expected_ids
        if len(landed_ids) == len(expected_ids):
            break
        time.sleep(WAIT_SECONDS)

    missing = len(expected_ids) - len(landed_ids)
    if missing:
        print(
            f"ERROR: only {len(landed_ids)}/{len(expected_ids)} runs landed in "
            f"'{args.project}' ({missing} missing). Check the ingest warnings above.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    print(f"Verified {len(landed_ids)}/{len(expected_ids)} runs landed.")

    # Feedback is keyed by run id, so it can only be attached once the runs it
    # points at have been created -- hence after the verification above, and against
    # the regenerated ids rather than the ones in the input file.
    n_feedback = 0
    for trace_runs in traces.values():
        for run in trace_runs:
            for feedback in run["feedback"]:
                client.create_feedback(
                    run_id=run["id"],
                    key=feedback["key"],
                    score=feedback.get("score"),
                    value=feedback.get("value"),
                    comment=feedback.get("comment"),
                )
                n_feedback += 1
    if n_feedback:
        print(f"Attaching {n_feedback} feedback records...")
        client.flush()

    print(
        f"Done! Uploaded {len(traces)} traces "
        f"({n_feedback} feedback records) to '{args.project}'."
    )


if __name__ == "__main__":
    main()
