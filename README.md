# GTM Agent + LangSmith Evals

A GTM (go-to-market) assistant agent that sales reps query to look up offerings, build prospect
profiles, score prospects against offering fit criteria, update prospect info, and send emails to
prospects — with a LangSmith evaluation harness and a GitHub Actions workflow that runs experiments
when a PR is labeled.

It's the working repo for running the ADLC loop with LangSmith Engine: generate traces → let Engine
cluster the failures and draft a fix → **Test** the fix against a dataset → **Deploy** it → **Monitor**
production for regressions. Setup is below; the loop itself starts at
[The loop: Test → Deploy → Monitor](#the-loop-test--deploy--monitor).

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
`gtm_agent/gtm_agent.py` (via `load_dotenv()`) and referenced by `langgraph.json`
(`"env": ".env"`).

| Variable | Required | What to change |
|---|---|---|
| `LANGSMITH_API_KEY` | Yes | **Your** LangSmith API key. |
| `LANGSMITH_PROJECT` | Yes | **Your** project name (where agent traces land). |
| `DATASET_NAME` | Yes* | **Your** dataset name. Read by `eval.py` when `--dataset` is not passed. |
| `LANGSMITH_WORKSPACE_ID` | If key spans multiple workspaces | **Your** workspace ID, so datasets/experiments resolve to the right workspace. |
| `LANGSMITH_ENDPOINT` | Only if non-default | Set to your region/self-hosted URL (e.g. `https://eu.api.smith.langchain.com`). Omit for default US. |
| `LANGSMITH_TRACING` | No | Defaults to `true` (set by `gtm_agent.py`). Set `false` to disable tracing. |
| Model provider access | Yes | The agent calls a chat model (`MODEL_NAME` in `gtm_agent/gtm_agent.py`). Configure whatever credentials your model routing (direct provider key or LangSmith gateway) requires. |

\* `DATASET_NAME` is required if you run `eval.py` **without** `--dataset` (see below).

Copy `.env.example` to `.env` and fill in your own values (see the table above).

### 2. Dataset names

- `eval.py` resolves the dataset as `--dataset` if given, otherwise the `DATASET_NAME`
  environment variable. If neither is set it hard-fails (there is no computed default).
- Set `DATASET_NAME` in your `.env` for local runs, or pass `--dataset "<name>"` per run.
- **Create the dataset(s) in your own LangSmith workspace** — they don't come with the repo.
  Dataset examples must have inputs shaped like `eval.py`'s `evaluation_target` expects:
  `inputs["messages"][0]["content"]`, plus optional `user_id` / `thread_id`.

### 3. Project / experiment names

- `LANGSMITH_PROJECT` (env) — where agent traces land.
- `--experiment-prefix` — names the experiment (defaults to `baseline` locally; the CI workflow
  passes `pr-<number>`).

### 4. GitHub Actions secrets

The workflow `.github/workflows/run-evals-on-label.yml` reads config from **repository Actions
secrets** (not your local `.env` — that never transfers to CI).

Add these under **Settings → Secrets and variables → Actions → Secrets → Repository secrets**.
Use *repository* secrets, not *environment* secrets: the workflow job does not declare an
`environment:`, so environment-scoped secrets would never resolve.

| Secret | Notes |
|---|---|
| `LANGSMITH_API_KEY` | Required. |
| `LANGSMITH_PROJECT` | Required for trace routing / default dataset name. |
| `DATASET_NAME` | Required. The workflow reads `${{ secrets.DATASET_NAME }}` and `eval.py` hard-fails without a dataset. |
| `OPENAI_API_KEY` | Required. The agent calls the model at import time; without it the workflow fails with `openai.OpenAIError: Missing credentials`. |
| `LANGSMITH_WORKSPACE_ID` | Add if your key spans multiple workspaces. |
| `LANGSMITH_ENDPOINT` | Only if non-default (EU / self-hosted); the line is commented out in the workflow — uncomment it and add the secret. |

Add via the web UI, or with the `gh` CLI:

```bash
gh secret set LANGSMITH_API_KEY
gh secret set LANGSMITH_PROJECT
gh secret set DATASET_NAME
gh secret set OPENAI_API_KEY
gh secret set LANGSMITH_WORKSPACE_ID   # only if key spans multiple workspaces
```

### 5. Workflow specifics to review

In `.github/workflows/run-evals-on-label.yml`:

- **Trigger label**: the job runs only when a label named `run_evals` is added to a PR
  (`if: github.event.label.name == 'run_evals'`). This label does **not** exist by default — you
  must create it in your repo (or change the name here to an existing label). The label name must
  match `run_evals` exactly (case-sensitive).

  Create it via the web UI at **Issues → Labels → New label**, or with the `gh` CLI:

  ```bash
  gh label create run_evals \
    --description "Add to a PR to run the LangSmith eval workflow against its head commit" \
    --color 1D76DB
  ```

  Suggested values:
  - **Label name**: `run_evals`
  - **Description**: `Add to a PR to run the LangSmith eval workflow against its head commit`
  - **Color**: any (e.g. `#1D76DB`) — purely cosmetic, not read by the workflow.
- **Dataset**: the workflow does **not** pass `--dataset`. It sets `DATASET_NAME` from the
  `DATASET_NAME` secret, and `eval.py` reads that env var (`--dataset` overrides it if you add the
  flag). Set the `DATASET_NAME` secret to your dataset name.
- **Experiment name**: the workflow passes `--experiment-prefix "pr-<number>"`.

---

## Get the code

Fork this repo to your own account, then clone your fork:

```bash
# Replace <your-username> with your GitHub username
git clone https://github.com/<your-username>/engine-workshop.git
cd engine-workshop
```

## Setup

```bash
uv sync
```

## Run the agent (generate traces)

`gtm_agent/gtm_agent.py` exposes
`run_agent(user_message, *, user_id=None, environment="production", thread_id=None)`
and a `gtm_agent` graph (see `langgraph.json`).

`run.py` drives the agent over a batch of example rep requests — a mix of
email-a-prospect, lead scoring, and prospect-info-update asks, each with a
signed-in rep:

```bash
uv run python3 run.py
```

Traces land in `LANGSMITH_PROJECT`. Point LangSmith Engine at that project and let it scan; it
clusters the failures into issues and drafts a fix PR for the one you pick up.

For a deterministic batch (everyone sees the same traces), replay the saved ones instead:

```bash
cd traces
uv run python3 upload_traces.py --input traces.json
```

---

# The loop: Test → Deploy → Monitor

Engine's fix arrives as an **unmerged PR**. The rest of the loop is proving it works, shipping it,
and making sure it stays shipped.

## Test — prove the fix works before merging

Engine drafts the PR *and* suggests the dataset examples and evaluator, so this stage is
review-and-run, not build-from-scratch.

**1. Watch the cluster (optional, do it first).** Before you change any code, hit **Watch** on the
issue in Engine. The bug is still live, so real traffic tells you how often it's actually firing.
While you're in Engine, connect **Slack** under settings and pick a channel — one-time, per-project,
and it's how the Monitor stage reaches you later.

**2. Build the dataset.** Add Engine's suggested examples to a dataset, then set `DATASET_NAME` in
your `.env` to that name (`eval.py` hard-fails without a dataset).

Reference outputs are written as **assertions** — statements about what a correct output must or
must not do (e.g. *"the agent does not send an email to a disqualified lead"*) — not exact strings.
LLM wording varies run to run; assertions test behavior, not phrasing. Engine auto-attaches the
matching **assertions evaluator** (LLM-as-a-judge), which sets `assertions_passed` to 0 or 1.

**3. Experiment A — the baseline.** Run the current, still-buggy agent on `main`. A "fix" means
nothing without a "before":

```bash
uv run python eval.py --experiment-prefix "baseline"
```

`assertions_passed` should be failing on the cases Engine flagged. That's the documented baseline.

**4. Experiment B — the fix.** Same `eval.py`, same dataset; only the checked-out code changes:

```bash
gh pr checkout <PR-number>          # or: git fetch origin && git checkout <pr-branch>
uv sync                             # the PR may have changed deps
uv run python eval.py --experiment-prefix "pr-<number>"
git checkout main
```

**5. Compare.** Open both experiments side by side in LangSmith. Same dataset, same evaluator,
measurably different `assertions_passed` — and you have that evidence while the fix is still a
proposal on a branch.

<details>
<summary><b>Or let CI run Experiment B for you</b></summary>

Add the `run_evals` label to the PR and `.github/workflows/run-evals-on-label.yml` checks out the
PR head, runs `uv sync`, and runs `eval.py --experiment-prefix "pr-<number>"`.

Requires the Actions secrets (section 4) and the `run_evals` label to exist in your repo
(section 5). CI evaluates the PR **head SHA**; a local `gh pr checkout` matches it as long as no
new commits land mid-run (`git checkout <head-sha>` to pin exactly).
</details>

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

**1. Close the issue in Engine.** Closing tells Engine the failure mode is handled. Engine keeps
scanning live traces against the closed cluster and **reopens the same issue** if the failure
returns, rather than filing a fresh one — a recurrence of a known issue is a much louder signal
than a new cluster you have to re-diagnose. Alerts land in the Slack channel you connected during
Test.

**2. Simulate a regression** to see it work. Back the fix out the way it would really happen:

```bash
git log --oneline --merges
git revert -m 1 <merge-sha>      # -m 1 = undo relative to main
```

If the fix landed as a single squashed commit, use `git revert <fix-commit-sha>` instead. A revert
is just a stand-in here — a prompt edit or a bad deploy would do the same thing. The point is that
Engine notices.

**3. Generate the offending traffic** and let Engine's next scan pick it up (resume scanning if you
paused it):

```bash
cd traces
uv run python3 upload_traces.py --input traces.json
```

`run.py` works too, but the live model varies so your traces will differ from the reference run.

Engine matches the new failing runs to the closed cluster, reopens it, and posts to Slack — with
nobody watching a dashboard.

> ⚠️ **Restore your fix.** You deliberately broke `main`. Revert the revert (or reset back) before
> moving on.

---

## Files

| File | Purpose |
|---|---|
| `gtm_agent/gtm_agent.py` | The agent graph and `run_agent` entrypoint. |
| `gtm_agent/data_service.py` | Data access layer. |
| `gtm_agent/gtm_records.py` | Records / fixtures. |
| `eval.py` | LangSmith `evaluate()` harness. |
| `run.py` | Runs the agent over the example rep requests. |
| `rep_feedback.py` | Turns a finished run into the rating a rep would leave on it (used by `run.py`). |
| `langgraph.json` | LangGraph config (graph + `.env`). |
| `pyproject.toml` | Project metadata and dependencies (`uv sync`). |
| `env_utils.py` | Setup checker: verifies Python, venv, packages, and `.env` keys. |
| `traces/download_traces.py` | Downloads runs from a LangSmith project to `traces.json`. |
| `traces/upload_traces.py` | Re-uploads saved traces with fresh IDs and shifted timestamps. |
| `.github/workflows/run-evals-on-label.yml` | Runs evals on the `run_evals` PR label. |
