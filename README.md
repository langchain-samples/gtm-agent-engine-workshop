# Using LangSmith Engine with a GTM Agent

A GTM (go-to-market) assistant agent that sales reps query to look up offerings, build prospect
profiles, score prospects against offering fit criteria, update prospect info, and send emails to
prospects. It ships with a LangSmith evaluation harness.

It's the working repo for running the ADLC loop with LangSmith Engine: generate traces → let Engine
cluster the failures → **Build** the fix as a PR → **Test** it against a dataset → **Deploy** it →
**Monitor** production for regressions. Setup is below; the loop itself starts at
[The loop: Build → Test → Deploy → Monitor](#the-loop-build--test--deploy--monitor).

## Files

```
.
├── .github/
│   └── workflows/
│       └── eval.yml           # PR eval: runs eval.py on main vs. the PR branch and comments the results
├── gtm_agent/
│   ├── gtm_agent.py           # The agent graph and run_agent entrypoint
│   ├── data_service.py        # Data access layer
│   └── gtm_records.py         # Records / fixtures
├── traces/
│   ├── download_traces.py     # Downloads runs from a LangSmith project to traces.json
│   ├── upload_traces.py       # Re-uploads saved traces with fresh IDs, shifted timestamps, and rep ratings
│   └── traces.json            # Saved reference traces for a deterministic batch
├── run.py                     # Runs the agent over the example rep requests
├── eval.py                    # LangSmith evaluate() harness
├── env_utils.py               # Setup checker: verifies Python, venv, packages, and .env keys
├── pyproject.toml             # Project metadata and dependencies (uv sync)
├── .env.example               # Template for your local .env
└── README.md
```

## Stack

- Python `>=3.11`, managed with [uv](https://docs.astral.sh/uv/)
- LangChain / LangGraph deep agent (`gtm_agent/` package)
- LangSmith for tracing + evals (`eval.py`)

---

## If you forked and cloned this repo — what you need to change

Everything below is wired to a specific LangSmith workspace/project/dataset. Swap these for your
own before running.

### 1. Local environment variables (`.env`)

Create a `.env` file in the project root. It is gitignored and loaded automatically by
`gtm_agent/gtm_agent.py` (via `load_dotenv()`).

| Variable | Required | What to change |
|---|---|---|
| `LANGSMITH_API_KEY` | Yes | **Your** LangSmith API key. |
| `LANGSMITH_PROJECT` | Yes | **Your** project name (where agent traces land). |
| `DATASET_NAME` | Yes* | **Your** dataset name. Read by `eval.py`. |
| `LANGSMITH_WORKSPACE_ID` | If key spans multiple workspaces | **Your** workspace ID, so datasets/experiments resolve to the right workspace. |
| `LANGSMITH_ENDPOINT` | Only if non-default | Set to your region/self-hosted URL (e.g. `https://eu.api.smith.langchain.com`). Omit for default US. |
| `LANGSMITH_TRACING` | No | Defaults to `true` (set by `gtm_agent.py`). Set `false` to disable tracing. |
| Model provider access | Only to run the agent locally | Needed by `run.py` / `eval.py`, which call a chat model (`MODEL_NAME` in `gtm_agent/gtm_agent.py`). Configure whatever credentials your model routing (direct provider key or LangSmith gateway) requires. **Not needed if you generate traces with `upload_traces.py`.** |

\* `DATASET_NAME` is required to run `eval.py` (see below).

**On the model key:** the recommended way to generate traces is to replay saved traces with
`traces/upload_traces.py`, which never calls a model locally, so you don't need a provider key in
`.env` to get through setup and Engine's scan. You only need one locally if you run the live agent
(`run.py`) or `eval.py`. Separately, the **assertions evaluator** (LLM-as-a-judge) during the Test
stage needs a model key too, but you enter that one directly in LangSmith rather than in this `.env`.

Copy `.env.example` to `.env` and fill in your own values (see the table above).

### 2. Dataset names

- `eval.py` reads the dataset from the `DATASET_NAME` environment variable. If it isn't set,
  the run hard-fails (there is no computed default).
- Set `DATASET_NAME` in your `.env` for local runs.
- **Create the dataset(s) in your own LangSmith workspace.** They don't come with the repo.
  Dataset examples must have inputs shaped like `eval.py`'s `evaluation_target` expects:
  `inputs["messages"][0]["content"]`, plus optional `user_id` / `thread_id`.

### 3. Project / experiment names

- `LANGSMITH_PROJECT` (env) — where agent traces land.
- `experiment_prefix` in `eval.py` — names the experiment (set to `baseline`).

---

## Get the code

Fork this repo to your own account, then clone your fork:

```bash
# Replace <your-username> with your GitHub username
git clone https://github.com/<your-username>/gtm-agent-engine-workshop.git
cd gtm-agent-engine-workshop
```

## Setup

```bash
uv sync
```

## Generate traces

### Recommended: replay the saved traces (`upload_traces.py`)

**This is the preferred way to generate traces for this workshop.** It replays the reference traces
in `traces/traces.json` with fresh IDs, shifted timestamps, and rep ratings, so everyone sees the
same batch and the same failure clusters:

```bash
cd traces
uv run python3 upload_traces.py
```

Traces land in `LANGSMITH_PROJECT`. Point LangSmith Engine at that project and let it scan; it
clusters the failures into issues and drafts a fix PR for the one you pick up.

### Alternative: run the live agent (`run.py`) — results will vary

`run.py` drives the agent over a batch of example rep requests that mixes email-a-prospect, lead
scoring, and prospect-info-update asks, each with a signed-in rep:

```bash
uv run python3 run.py
```

⚠️ This calls the live model, so **your traces will differ from the reference run**. The wording
changes, and the buggy behaviors may not fire on every request. Engine may cluster them differently
or surface fewer issues, so the rest of this walkthrough won't line up exactly. Use `run.py` when
you want to see the agent actually execute; use `upload_traces.py` when you want the workshop to
behave as written.

(`gtm_agent/gtm_agent.py` exposes
`run_agent(user_message, *, user_id=None, environment="production", thread_id=None)`
and a `gtm_agent` graph, if you'd rather drive it yourself.)

---

# The loop: Build → Test → Deploy → Monitor

Engine turns a cluster of failing traces into a fix. **Build** is getting that fix onto a branch as
an unmerged PR; the rest of the loop is proving it works, shipping it, and making sure it stays
shipped.

## Build — open Engine's PR

Engine has already scanned your project and clustered the failures into issues. You don't write the
fix; you pick the issue and let Engine draft it.

**1. Pick an issue.** Open your project in Engine and read the clustered issues. Each one bundles
the failing traces, a description of the failure mode, and a suggested fix. Pick the one you want to
work on (e.g. *the agent sends email to leads it never checked for disqualification*).

**2. Review the diagnosis before the code.** Skim the traces in the cluster and confirm the failure
mode is what Engine says it is. A fix built on a misread cluster passes its own tests and solves
nothing.

**3. Have Engine open the PR.** Kick off the fix from the issue. Engine writes the patch and opens an
unmerged **PR on your fork**, on its own branch. Nothing has touched `main`, and the bug is still
live in production, which is exactly what makes the Test stage's before/after possible.

**4. Read the diff.** Review the PR the way you'd review a teammate's: does the guard sit on the
path that actually sends, or just on the happy-path branch? Does it hold when the rep asks directly?
Note the PR number, since you'll check it out in Test.

Engine also suggests dataset examples for this issue. Leave them in the issue for now; you'll pull
them into a dataset in the next stage.

## Test — prove the fix works before merging

Because Engine drafted the PR *and* suggested the dataset examples, this stage is review-and-run,
not build-from-scratch.

**1. Add your model provider key to your workspace.** The evaluator runs in LangSmith, not on your
machine, so it needs its own key. In LangSmith, go to workspace settings → **Model providers** (or
**Secrets**) and add your provider key there. Do this before you attach the evaluator, because
without it the judge can't run and every example comes back unscored.

**2. Assemble the dataset.** Add Engine's suggested examples to a dataset, then set `DATASET_NAME`
in your `.env` to that name (`eval.py` hard-fails without a dataset).

Reference outputs are written as **assertions**, not exact strings. An assertion states what a
correct output must or must not do (e.g. *"the agent does not send an email to a disqualified
lead"*). LLM wording varies run to run; assertions test behavior, not phrasing.

To score them, attach an evaluator to the dataset: in LangSmith, add an evaluator and pick
**Assertions** from the evaluator templates. It's an LLM-as-a-judge that checks the output against
each assertion and sets `assertions_passed` to 0 or 1. It runs on the workspace key from step 1, not
anything in your local `.env`.

**3. Experiment A — the baseline.** Run the current, still-buggy agent on `main`. A "fix" means
nothing without a "before":

```bash
uv run python eval.py
```

`assertions_passed` should be failing on the cases Engine flagged. That's the documented baseline.

**4. Experiment B — the fix.** Same `eval.py`, same dataset; only the checked-out code changes:

```bash
gh pr checkout <PR-number>          # or: git fetch origin && git checkout <pr-branch>
uv sync                             # the PR may have changed deps
uv run python eval.py
git checkout main
```

**5. Compare.** Open both experiments side by side in LangSmith. Same dataset, same evaluator,
measurably different `assertions_passed`, and you have that evidence while the fix is still a
proposal on a branch.

**6. Or let CI do steps 3–5 for you.** `.github/workflows/eval.yml` runs the same before/after
automatically on every PR that touches `gtm_agent/**`: it checks out the PR's base commit and its
head commit, runs `eval.py` on each (as `pr-<number>-main` and `pr-<number>-fix`, via
`EXPERIMENT_PREFIX`), and posts a comment on the PR with both experiment names to open in the
Compare view.

It runs on **your fork's** secrets in GitHub, not the upstream repo's, so add these under
**Settings → Secrets and variables → Actions**: `LANGSMITH_API_KEY` and `DATASET_NAME`, plus
`LANGSMITH_WORKSPACE_ID`, `LANGSMITH_ENDPOINT`, and `LANGSMITH_PROJECT` if your setup needs them. If
either required secret is missing, the workflow comments which one and fails fast, so you can add it
and hit **Re-run failed jobs**.

`OPENAI_API_KEY` is optional. If you add it, the agent calls OpenAI directly with it. If you leave it
out, the agent's model calls go through the [LangSmith LLM Gateway](https://docs.langchain.com/langsmith/llm-gateway),
authenticated by `LANGSMITH_API_KEY`, and the gateway uses the OpenAI key stored in your workspace
(step 1). A workshop host can then add one key to every attendee's workspace without anyone handling
the key itself. The LangSmith API key needs the `gateway:invoke` and `workspaces:read` permissions;
on Enterprise plans the built-in Workspace Editor and Viewer roles have neither
([admin setup](https://docs.langchain.com/langsmith/llm-gateway-admin-setup)). Outside the US region,
set the repository variable `LANGSMITH_GATEWAY_URL` to your region's gateway URL.

A pull request is the only trigger — there's no "Run workflow" button. If opening the PR produces no
run at all, check, in order:

1. **Actions enabled on your fork?** GitHub disables them on new forks. Open the **Actions** tab and
   click *"I understand my workflows, go ahead and enable them"*, then reopen the PR.
2. **Is the PR against your fork?** `gh pr create` defaults to upstream, whose runs can't see your
   fork's secrets. Base and head must both be your fork.
3. **Does the diff touch `gtm_agent/**`?** The `paths:` filter skips everything else silently.

## Deploy — ship it

All the risk was retired in Test, so this is short:

1. **Merge the PR** into `main`.
2. **Confirm the fix landed** — read the send path on `main` and check the guard is there: the
   agent looks up the lead's disqualified status before sending, and refuses even when the rep
   asks directly.
3. **Pull it down** so your working copy isn't stale (you need it for Monitor):

```bash
git checkout main
git pull
```

## Monitor — make sure it stays fixed

Test and Deploy proved the fix against examples *you* chose. Production runs on traffic nobody
wrote a test for.

**1. Connect Slack.** In Engine, open settings, connect **Slack**, and pick a channel. This is a
one-time setup per project, and it's how Engine reaches you when the failure comes back.

**2. Close the issue in Engine.** Closing tells Engine the failure mode is handled. Engine keeps
scanning live traces against the closed cluster and **reopens the same issue** if the failure
returns, rather than filing a fresh one. A recurrence of a known issue is a much louder signal than
a new cluster you have to re-diagnose. Alerts land in the Slack channel you just connected.

**3. Simulate a regression** to see it work. Back the fix out the way it would really happen:

```bash
git log --oneline --merges
git revert -m 1 <merge-sha>      # -m 1 = undo relative to main
```

If the fix landed as a single squashed commit, use `git revert <fix-commit-sha>` instead. A revert
is just a stand-in here, since a prompt edit or a bad deploy would do the same thing. The point is that
Engine notices.

**4. Generate the offending traffic** and let Engine's next scan pick it up (resume scanning if you
paused it):

```bash
cd traces
uv run python3 upload_traces.py
```

Use `upload_traces.py` here too. `run.py` works, but the live model varies, so your traces will
differ from the reference run and Engine may not match them to the closed cluster.

Engine matches the new failing runs to the closed cluster, reopens it, and posts to Slack, all with
nobody watching a dashboard.

> ⚠️ **Restore your fix.** You deliberately broke `main`. Revert the revert (or reset back) before
> moving on.
