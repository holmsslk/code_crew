import os
import json
import re
import subprocess
from pathlib import Path
from typing import Literal

from crewai import Agent, Crew, Process, Task
from crewai.agents.agent_builder.base_agent import BaseAgent
from crewai.project import CrewBase, agent, crew, task
from crewai_tools import DirectoryReadTool, FileReadTool
from pydantic import BaseModel, Field
from code_crew.tools import (
    ControlledCommandTool,
    ControlledGitDiffTool,
    ControlledWriteFileTool,
)


class ProductOutput(BaseModel):
    role: Literal["product"]
    task_id: str
    summary: str
    requirements: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    boundary_conditions: list[str] = Field(default_factory=list)
    priority: Literal["P0", "P1", "P2"]
    subtasks: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    next_recommended_role: Literal["developer"]


class LeadGateOutput(BaseModel):
    role: Literal["lead"]
    task_id: str
    stage: Literal["scope_gate", "implementation_gate"]
    status: Literal["approved", "needs_rework"]
    reason: str
    required_fixes: list[str] = Field(default_factory=list)
    next_recommended_role: Literal["product", "developer", "qa"]


class DeveloperOutput(BaseModel):
    role: Literal["developer"]
    task_id: str
    implementation_plan: list[str] = Field(default_factory=list)
    files_to_change: list[str] = Field(default_factory=list)
    commands_executed: list[str] = Field(default_factory=list)
    patch_summary: str
    technical_notes: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    next_recommended_role: Literal["qa"]


class QAOutput(BaseModel):
    role: Literal["qa"]
    task_id: str
    test_points: list[str] = Field(default_factory=list)
    executed_checks: list[str] = Field(default_factory=list)
    defects: list[str] = Field(default_factory=list)
    regression_risks: list[str] = Field(default_factory=list)
    verdict: Literal["pass", "fail"]
    evidence: list[str] = Field(default_factory=list)
    next_recommended_role: Literal["lead", "developer"]


class BlackboardSummary(BaseModel):
    requirement_summary: str
    implementation_summary: str
    qa_summary: str
    decision_log: list[str] = Field(default_factory=list)


class LeadFinalOutput(BaseModel):
    role: Literal["lead"]
    task_id: str
    stage: Literal["final_gate"]
    final_status: Literal["done", "needs_followup"]
    decision_summary: str
    release_recommendation: Literal["ship", "hold"]
    followup_actions: list[str] = Field(default_factory=list)
    blackboard: BlackboardSummary


def _repo_path_for_guardrails() -> Path:
    repo_path = os.getenv("TARGET_REPO_PATH", ".")
    return Path(repo_path).expanduser().resolve()


def _git_diff_name_only(repo: Path) -> list[str]:
    if not repo.exists() or not repo.is_dir():
        return []
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), "diff", "--name-only"],
            capture_output=True,
            text=True,
            timeout=20,
            shell=False,
        )
        if proc.returncode != 0:
            return []
        return [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    except Exception:
        return []


def _normalize_guardrail_raw(result) -> str:
    if isinstance(result, str):
        return result
    if isinstance(result, BaseModel):
        return result.model_dump_json()

    raw = getattr(result, "raw", None)
    if isinstance(raw, str):
        return raw
    if isinstance(raw, BaseModel):
        return raw.model_dump_json()

    pydantic_obj = getattr(result, "pydantic", None)
    if isinstance(pydantic_obj, BaseModel):
        return pydantic_obj.model_dump_json()

    if isinstance(result, dict):
        return json.dumps(result, ensure_ascii=False)

    if raw is not None and isinstance(raw, dict):
        return json.dumps(raw, ensure_ascii=False)

    return str(result)


def _extract_json_from_text(text: str) -> dict | None:
    text = text.strip()
    if not text:
        return None

    # 1) direct JSON
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass

    # 2) fenced json/code block
    fence_matches = re.findall(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text, flags=re.IGNORECASE)
    for candidate in fence_matches:
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict):
                return obj
        except Exception:
            continue

    # 3) first json-like object
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = text[start : end + 1]
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict):
                return obj
        except Exception:
            return None
    return None


def _extract_json_from_unknown(result) -> dict | None:
    required_hints = {"role", "task_id"}

    def _looks_like_payload(data: dict) -> bool:
        return required_hints.issubset(set(data.keys()))

    if isinstance(result, dict):
        # Only trust dict directly when it already looks like target payload.
        if _looks_like_payload(result):
            return result
        # Otherwise keep searching nested content.
        for key in ("raw", "output", "result", "response", "content", "text", "message"):
            value = result.get(key)
            if isinstance(value, dict):
                if _looks_like_payload(value):
                    return value
                nested = _extract_json_from_unknown(value)
                if nested:
                    return nested
            if isinstance(value, str):
                found = _extract_json_from_text(value)
                if found:
                    return found
        for value in result.values():
            if isinstance(value, str):
                found = _extract_json_from_text(value)
                if found:
                    return found
            elif isinstance(value, dict):
                nested = _extract_json_from_unknown(value)
                if nested:
                    return nested
        return None
    if isinstance(result, BaseModel):
        dumped = result.model_dump()
        if isinstance(dumped, dict) and _looks_like_payload(dumped):
            return dumped
        return _extract_json_from_unknown(dumped)

    raw = getattr(result, "raw", None)
    if isinstance(raw, dict):
        if _looks_like_payload(raw):
            return raw
        return _extract_json_from_unknown(raw)
    if isinstance(raw, BaseModel):
        return raw.model_dump()
    if isinstance(raw, str):
        found = _extract_json_from_text(raw)
        if found:
            return found

    pydantic_obj = getattr(result, "pydantic", None)
    if isinstance(pydantic_obj, BaseModel):
        return pydantic_obj.model_dump()

    if isinstance(result, str):
        return _extract_json_from_text(result)

    return None


def _parse_guardrail_payload(result, model_cls):
    if isinstance(result, model_cls):
        parsed = result
        return parsed, parsed.model_dump_json()

    extracted = _extract_json_from_unknown(result)
    if extracted is not None:
        parsed = model_cls.model_validate(extracted)
        return parsed, json.dumps(extracted, ensure_ascii=False)

    raw = _normalize_guardrail_raw(result)
    try:
        parsed = model_cls.model_validate_json(raw)
        return parsed, raw
    except Exception:
        try:
            data = json.loads(raw)
            parsed = model_cls.model_validate(data)
            return parsed, json.dumps(data, ensure_ascii=False)
        except Exception as inner:
            raise ValueError(
                "unable to extract valid JSON payload from model output; "
                "ensure output is a plain JSON object without markdown wrappers"
            ) from inner


def _developer_guardrail(result) -> tuple[bool, str]:
    try:
        parsed, raw = _parse_guardrail_payload(result, DeveloperOutput)
    except Exception as e:
        return (False, f"developer guardrail: invalid developer JSON output ({e})")

    if not parsed.files_to_change:
        return (False, "developer guardrail: files_to_change must be non-empty")
    if not parsed.commands_executed:
        return (False, "developer guardrail: commands_executed must be non-empty")

    repo = _repo_path_for_guardrails()
    changed_files = _git_diff_name_only(repo)
    if not changed_files:
        return (False, f"developer guardrail: git diff is empty in {repo}")

    changed_set = set(changed_files)
    declared = set(parsed.files_to_change)
    if not (changed_set & declared):
        return (
            False,
            "developer guardrail: declared files_to_change do not match repository git diff",
        )
    return (True, raw)


def _qa_guardrail(result) -> tuple[bool, str]:
    try:
        parsed, raw = _parse_guardrail_payload(result, QAOutput)
    except Exception as e:
        return (False, f"qa guardrail: invalid QA JSON output ({e})")

    if not parsed.executed_checks:
        return (False, "qa guardrail: executed_checks must be non-empty")
    if not parsed.evidence:
        return (False, "qa guardrail: evidence must be non-empty")

    repo = _repo_path_for_guardrails()
    if not _git_diff_name_only(repo):
        return (False, f"qa guardrail: git diff is empty in {repo}")

    if parsed.verdict == "pass" and not any("pytest" in c.lower() for c in parsed.executed_checks):
        return (False, "qa guardrail: PASS verdict requires at least one pytest-related check")

    return (True, raw)


def _lead_final_guardrail(result) -> tuple[bool, str]:
    try:
        parsed, raw = _parse_guardrail_payload(result, LeadFinalOutput)
    except Exception as e:
        return (False, f"final guardrail: invalid lead JSON output ({e})")

    repo = _repo_path_for_guardrails()
    changed_files = _git_diff_name_only(repo)
    if parsed.release_recommendation == "ship" and not changed_files:
        return (False, f"final guardrail: cannot ship when git diff is empty in {repo}")
    return (True, raw)


@CrewBase
class CodeCrew:
    """Single-task coding collaboration crew on an existing repository."""

    agents: list[BaseAgent]
    tasks: list[Task]

    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

    def _ensure_storage_dir(self) -> None:
        storage_dir = Path(os.getenv("CREWAI_STORAGE_DIR", ".crewai_storage"))
        storage_dir.mkdir(parents=True, exist_ok=True)
        os.environ["CREWAI_STORAGE_DIR"] = str(storage_dir.resolve())

    @agent
    def product_agent(self) -> Agent:
        return Agent(
            config=self.agents_config["product_agent"],  # type: ignore[index]
            llm="anthropic/claude-sonnet-4-6",
            verbose=True,
            inject_date=True,
            reasoning=True,
            respect_context_window=True,
            allow_delegation=False,
            tools=[DirectoryReadTool(), FileReadTool()],
        )

    @agent
    def developer_agent(self) -> Agent:
        return Agent(
            config=self.agents_config["developer_agent"],  # type: ignore[index]
            llm="anthropic/claude-sonnet-4-6",
            verbose=True,
            inject_date=True,
            reasoning=True,
            respect_context_window=True,
            allow_delegation=False,
            tools=[
                DirectoryReadTool(),
                FileReadTool(),
                ControlledWriteFileTool(),
                ControlledCommandTool(),
                ControlledGitDiffTool(),
            ],
        )

    @agent
    def qa_agent(self) -> Agent:
        return Agent(
            config=self.agents_config["qa_agent"],  # type: ignore[index]
            llm="anthropic/claude-sonnet-4-6",
            verbose=True,
            inject_date=True,
            reasoning=True,
            respect_context_window=True,
            allow_delegation=False,
            tools=[
                DirectoryReadTool(),
                FileReadTool(),
                ControlledCommandTool(),
                ControlledGitDiffTool(),
            ],
        )

    @agent
    def lead_agent(self) -> Agent:
        return Agent(
            config=self.agents_config["lead_agent"],  # type: ignore[index]
            llm="anthropic/claude-sonnet-4-6",
            verbose=True,
            inject_date=True,
            reasoning=True,
            respect_context_window=True,
            allow_delegation=False,
            tools=[DirectoryReadTool(), FileReadTool()],
        )

    @task
    def product_spec_task(self) -> Task:
        return Task(
            config=self.tasks_config["product_spec_task"],  # type: ignore[index]
            output_pydantic=ProductOutput,
        )

    @task
    def lead_scope_gate_task(self) -> Task:
        return Task(
            config=self.tasks_config["lead_scope_gate_task"],  # type: ignore[index]
            output_pydantic=LeadGateOutput,
            context=[self.product_spec_task()],
        )

    @task
    def developer_implementation_task(self) -> Task:
        return Task(
            config=self.tasks_config["developer_implementation_task"],  # type: ignore[index]
            context=[self.product_spec_task(), self.lead_scope_gate_task()],
            guardrail=_developer_guardrail,
        )

    @task
    def lead_quality_gate_task(self) -> Task:
        return Task(
            config=self.tasks_config["lead_quality_gate_task"],  # type: ignore[index]
            output_pydantic=LeadGateOutput,
            context=[self.product_spec_task(), self.developer_implementation_task()],
        )

    @task
    def qa_validation_task(self) -> Task:
        return Task(
            config=self.tasks_config["qa_validation_task"],  # type: ignore[index]
            context=[
                self.product_spec_task(),
                self.developer_implementation_task(),
                self.lead_quality_gate_task(),
            ],
            guardrail=_qa_guardrail,
        )

    @task
    def lead_final_decision_task(self) -> Task:
        return Task(
            config=self.tasks_config["lead_final_decision_task"],  # type: ignore[index]
            context=[
                self.product_spec_task(),
                self.lead_scope_gate_task(),
                self.developer_implementation_task(),
                self.lead_quality_gate_task(),
                self.qa_validation_task(),
            ],
            guardrail=_lead_final_guardrail,
        )

    @crew
    def crew(self) -> Crew:
        """Creates the coding collaboration crew."""
        self._ensure_storage_dir()
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=True,
            memory=False,
            cache=True,
            respect_context_window=True,
        )
