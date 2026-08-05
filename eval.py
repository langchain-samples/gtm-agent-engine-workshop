import argparse
import os

from langsmith import evaluate

from gtm_agent.gtm_agent import run_agent


def evaluation_target(inputs: dict) -> dict:
    user_message = inputs["messages"][0]["content"]

    result = run_agent(
        user_message,
        user_id=inputs.get("user_id"),
        thread_id=inputs.get("thread_id"),
    )
    return {"output": result["reply"], "run_id": result["run_id"]}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a LangSmith experiment.")
    parser.add_argument(
        "--dataset",
        default=None,
        help="Name of the LangSmith dataset to evaluate against. "
        "Defaults to the DATASET_NAME environment variable.",
    )
    parser.add_argument(
        "--experiment-prefix",
        default="baseline",
        help="Prefix for the experiment name in LangSmith.",
    )
    args = parser.parse_args()

    # --dataset overrides; otherwise fall back to DATASET_NAME.
    # Hard-fails if neither is set.
    dataset = args.dataset or os.environ["DATASET_NAME"]

    evaluate(
        evaluation_target,
        data=dataset,
        experiment_prefix=args.experiment_prefix,
    )


if __name__ == "__main__":
    main()
