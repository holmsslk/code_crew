import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Literal, Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field


def _resolve_repo_path(repo_path: str) -> Path:
    repo = Path(repo_path).expanduser().resolve()
    if not repo.exists() or not repo.is_dir():
        raise ValueError(f"repo_path not found or not directory: {repo}")
    return repo


def _safe_target_path(repo: Path, relative_path: str) -> Path:
    target = (repo / relative_path).resolve()
    if repo != target and repo not in target.parents:
        raise ValueError("target path escapes repo_path")
    return target


class ControlledWriteFileInput(BaseModel):
    """Input schema for controlled write tool."""

    repo_path: str = Field(..., description="Absolute or relative path to target repository root")
    relative_path: str = Field(..., description="File path relative to repo_path")
    content: str = Field(..., description="File content to write")
    mode: Literal["overwrite", "append"] = Field(
        default="overwrite", description="Write mode"
    )


class ControlledWriteFileTool(BaseTool):
    name: str = "controlled_write_file"
    description: str = (
        "Safely writes text into a file under repo_path. "
        "Blocks path traversal outside repo_path."
    )
    args_schema: Type[BaseModel] = ControlledWriteFileInput

    def _run(
        self,
        repo_path: str,
        relative_path: str,
        content: str,
        mode: Literal["overwrite", "append"] = "overwrite",
    ) -> str:
        try:
            repo = _resolve_repo_path(repo_path)
            target = _safe_target_path(repo, relative_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            write_mode = "w" if mode == "overwrite" else "a"
            with target.open(write_mode, encoding="utf-8") as f:
                f.write(content)
            return (
                f"success: wrote file '{target}' with mode='{mode}', "
                f"chars={len(content)}"
            )
        except Exception as e:
            return f"error: {e}"


class ControlledCommandInput(BaseModel):
    """Input schema for controlled command tool."""

    repo_path: str = Field(..., description="Absolute or relative path to target repository root")
    command: str = Field(..., description="Single command string without shell operators")
    timeout_sec: int = Field(default=180, description="Command timeout in seconds")
    max_output_chars: int = Field(default=12000, description="Max returned output chars")


class ControlledCommandTool(BaseTool):
    name: str = "controlled_run_command"
    description: str = (
        "Runs a single repository command in repo_path using a whitelist. "
        "No shell chaining, no redirection, no subshell expansion."
    )
    args_schema: Type[BaseModel] = ControlledCommandInput

    _allowed_prefixes = {
        "python",
        "python3",
        "uv",
        "pytest",
        "ruff",
        "mypy",
        "npm",
        "pnpm",
        "yarn",
        "go",
        "cargo",
        "make",
        "cmake",
        "ctest",
        "gradle",
        "mvn",
        "dotnet",
        "git",
    }

    _blocked_tokens = {"&&", "||", ";", "|", ">", ">>", "<", "$()"}

    def _run(
        self,
        repo_path: str,
        command: str,
        timeout_sec: int = 180,
        max_output_chars: int = 12000,
    ) -> str:
        try:
            repo = _resolve_repo_path(repo_path)

            parts = shlex.split(command)
            if not parts:
                return "error: empty command"

            if any(token in self._blocked_tokens for token in parts):
                return "error: shell control operators are not allowed"

            if parts[0] not in self._allowed_prefixes:
                return (
                    f"error: command '{parts[0]}' not in whitelist: "
                    f"{sorted(self._allowed_prefixes)}"
                )

            if shutil.which(parts[0]) is None:
                return f"error: command '{parts[0]}' not found on system"

            proc = subprocess.run(
                parts,
                cwd=repo,
                capture_output=True,
                text=True,
                timeout=max(1, timeout_sec),
                shell=False,
            )
            raw = (
                f"exit_code={proc.returncode}\n"
                f"stdout:\n{proc.stdout}\n"
                f"stderr:\n{proc.stderr}"
            )
            if len(raw) > max_output_chars:
                raw = raw[:max_output_chars] + "\n...<truncated>"
            return raw
        except subprocess.TimeoutExpired:
            return f"error: command timed out after {timeout_sec}s"
        except Exception as e:
            return f"error: {e}"


class ControlledGitDiffInput(BaseModel):
    """Input schema for controlled git diff tool."""

    repo_path: str = Field(..., description="Absolute or relative path to target repository root")
    target: str = Field(default="", description="Optional file path to diff")
    staged: bool = Field(default=False, description="Use staged diff if true")
    max_output_chars: int = Field(default=30000, description="Max returned output chars")


class ControlledGitDiffTool(BaseTool):
    name: str = "controlled_git_diff"
    description: str = (
        "Returns git diff output for repo_path (optionally staged or file-scoped)."
    )
    args_schema: Type[BaseModel] = ControlledGitDiffInput

    def _run(
        self,
        repo_path: str,
        target: str = "",
        staged: bool = False,
        max_output_chars: int = 30000,
    ) -> str:
        try:
            repo = _resolve_repo_path(repo_path)
            if shutil.which("git") is None:
                return "error: git command not found on system"

            cmd = ["git", "-C", str(repo), "diff"]
            if staged:
                cmd.append("--cached")
            if target:
                cmd.extend(["--", target])

            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
                shell=False,
            )
            if proc.returncode not in (0, 1):
                return f"error: git diff failed with code {proc.returncode}\n{proc.stderr}"

            out = proc.stdout if proc.stdout.strip() else "(no diff)"
            if len(out) > max_output_chars:
                out = out[:max_output_chars] + "\n...<truncated>"
            return out
        except Exception as e:
            return f"error: {e}"
