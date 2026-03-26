#!/usr/bin/env python
import json
import os
import sys
import warnings

from code_crew.crew import CodeCrew

warnings.filterwarnings("ignore", category=SyntaxWarning, module="pysbd")


def _request_from_argv(default: str) -> str:
    if len(sys.argv) > 1:
        return " ".join(sys.argv[1:]).strip()
    return default


def run() -> None:
    """Run the crew with a natural-language request."""
    inputs = {
        "user_request": _request_from_argv("请为当前代码库实现一个最小可行的功能改动并完成验证。"),
        "repo_path": ".",
    }
    os.environ["TARGET_REPO_PATH"] = inputs["repo_path"]

    try:
        CodeCrew().crew().kickoff(inputs=inputs)
    except Exception as e:
        raise Exception(f"An error occurred while running the crew: {e}")


def train() -> None:
    """Train the crew for a given number of iterations."""
    if len(sys.argv) < 3:
        raise Exception("Usage: train <n_iterations> <filename> [natural language request]")

    inputs = {
        "user_request": " ".join(sys.argv[3:]).strip() or "Train coding-collaboration behavior.",
        "repo_path": ".",
    }
    os.environ["TARGET_REPO_PATH"] = inputs["repo_path"]
    try:
        CodeCrew().crew().train(
            n_iterations=int(sys.argv[1]),
            filename=sys.argv[2],
            inputs=inputs,
        )
    except Exception as e:
        raise Exception(f"An error occurred while training the crew: {e}")


def replay() -> None:
    """Replay the crew execution from a specific task."""
    if len(sys.argv) < 2:
        raise Exception("Usage: replay <task_id>")
    try:
        CodeCrew().crew().replay(task_id=sys.argv[1])
    except Exception as e:
        raise Exception(f"An error occurred while replaying the crew: {e}")


def test() -> None:
    """Test the crew execution and return results."""
    if len(sys.argv) < 3:
        raise Exception("Usage: test <n_iterations> <eval_llm> [natural language request]")

    inputs = {
        "user_request": " ".join(sys.argv[3:]).strip() or "Test coding-collaboration behavior.",
        "repo_path": ".",
    }
    os.environ["TARGET_REPO_PATH"] = inputs["repo_path"]
    try:
        CodeCrew().crew().test(
            n_iterations=int(sys.argv[1]),
            eval_llm=sys.argv[2],
            inputs=inputs,
        )
    except Exception as e:
        raise Exception(f"An error occurred while testing the crew: {e}")


def run_with_trigger():
    """Run the crew with trigger payload."""
    if len(sys.argv) < 2:
        raise Exception("No trigger payload provided. Please provide JSON payload as argument.")

    try:
        trigger_payload = json.loads(sys.argv[1])
    except json.JSONDecodeError:
        raise Exception("Invalid JSON payload provided as argument")

    inputs = {
        "crewai_trigger_payload": trigger_payload,
        "user_request": trigger_payload.get("user_request", ""),
        "repo_path": trigger_payload.get("repo_path", "."),
    }
    os.environ["TARGET_REPO_PATH"] = inputs["repo_path"]

    try:
        result = CodeCrew().crew().kickoff(inputs=inputs)
        return result
    except Exception as e:
        raise Exception(f"An error occurred while running the crew with trigger: {e}")


if __name__ == "__main__":
    run()
