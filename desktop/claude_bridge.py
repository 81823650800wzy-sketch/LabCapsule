"""Bounded, non-interactive bridge to a locally installed Claude Code CLI."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time


MAX_PROMPT_CHARS = 12_000
MAX_RESULT_CHARS = 2_400
COMPLEX_TERMS = (
    "复杂任务", "深入分析", "全面分析", "完整方案", "详细方案", "系统排查",
    "分析文件", "分析代码", "阅读项目", "制定计划", "比较多个", "生成报告",
    "根因分析", "优化方案", "数据建模", "统计检验",
)
_SECRET_PATTERN = re.compile(
    r"(?i)(api[_ -]?key|token|secret|password|密码|密钥)\s*[:=：]?\s*([^\s,;，；]{4,})"
)
_TOOL_MARKER_PATTERN = re.compile(
    r"(?is)<\s*/?\s*(?:tool_calls?|invoke|parameter)\b|"
    r"\b(?:request_user_input|bash|write|edit|apply_patch)\b\s*(?:\(|\{|>)"
)


@dataclass(frozen=True)
class ClaudeResult:
    text: str = ""
    elapsed_s: float = 0.0
    error: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.text and not self.error)


def _redact(value: str) -> str:
    return _SECRET_PATTERN.sub(lambda match: f"{match.group(1)}：[已隐藏]", value)


class ClaudeBridge:
    def __init__(self, model: str = "sonnet", executable: str | Path | None = None,
                 timeout_seconds: int = 180):
        self.model = model.strip() or "sonnet"
        self.executable = Path(executable).resolve() if executable else self.find_executable()
        self.timeout_seconds = max(15, min(300, int(timeout_seconds)))

    @staticmethod
    def find_executable() -> Path | None:
        direct = shutil.which("claude.exe")
        if direct:
            return Path(direct).resolve()
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            candidate = (Path(appdata) / "npm" / "node_modules" / "@anthropic-ai" /
                         "claude-code" / "bin" / "claude.exe")
            if candidate.is_file():
                return candidate.resolve()
        return None

    @property
    def available(self) -> bool:
        return bool(self.executable and self.executable.is_file())

    @staticmethod
    def should_delegate(text: str, model_requested: bool = False) -> bool:
        clean = text.strip()
        if model_requested:
            return True
        if any(term in clean for term in COMPLEX_TERMS):
            return True
        multi_step = len(re.findall(r"[；;。\n]|然后|并且|同时|最后", clean)) >= 3
        technical = any(term in clean.lower() for term in
                        ("代码", "文件", "csv", "fft", "统计", "回归", "报告", "方案"))
        return len(clean) >= 140 and multi_step and technical

    @staticmethod
    def parse_output(output: str) -> str:
        root = json.loads(output)
        result = root.get("result", "") if isinstance(root, dict) else ""
        if not isinstance(result, str) or not result.strip():
            raise ValueError("Claude 没有返回可显示文本")
        if _TOOL_MARKER_PATTERN.search(result):
            raise ValueError("Claude 返回了交互或工具调用，已安全拦截")
        return _redact(result.strip())[:MAX_RESULT_CHARS]

    def _command(self, system_prompt: str, prompt: str) -> list[str]:
        return [
            str(self.executable), "--print", "--output-format", "json",
            "--permission-mode", "dontAsk", "--tools", "", "--max-turns", "1",
            "--max-budget-usd", "0.20", "--no-session-persistence", "--safe-mode",
            "--disable-slash-commands", "--no-chrome", "--strict-mcp-config",
            "--mcp-config", '{"mcpServers":{}}', "--system-prompt", system_prompt,
            "--effort", "low", "--model", self.model, prompt,
        ]

    def _run_once(self, system_prompt: str, prompt: str) -> tuple[str, float]:
        command = self._command(system_prompt, prompt)
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        started = time.monotonic()
        completed = subprocess.run(
            command, cwd=str(Path.home()), stdin=subprocess.DEVNULL,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=self.timeout_seconds, creationflags=flags, check=False,
        )
        elapsed = time.monotonic() - started
        if completed.returncode != 0:
            detail = _redact((completed.stderr or completed.stdout).strip())[:300]
            raise RuntimeError(f"Claude 退出码 {completed.returncode}：{detail}")
        return self.parse_output(completed.stdout), elapsed

    def process(self, user_text: str, context: dict, initial_reply: str = "") -> ClaudeResult:
        if not self.available:
            return ClaudeResult(error="未找到本机 Claude Code")
        safe_context = json.dumps(context, ensure_ascii=False, separators=(",", ":"), default=str)
        system_prompt = (
            "你是 LabCapsule 桌宠的只读复杂任务分析器。只用简体中文输出给用户看的最终答案。"
            "禁止使用或请求任何工具，禁止输出工具调用、XML、JSON、内部标记，禁止反问。"
            "信息不足时明确列出合理假设并继续作答。不得声称执行了设备操作，不得索取或输出"
            "密码或 API Key。给出可验证的结论、必要计算和下一步，不要使用 Markdown 表格。"
        )
        prompt = _redact(
            f"用户请求：{user_text}\n"
            f"当前上下文：{safe_context}\n"
            f"前级助手初步回答：{initial_reply or '无'}"
        )[:MAX_PROMPT_CHARS]
        started = time.monotonic()
        try:
            try:
                text, _ = self._run_once(system_prompt, prompt)
            except ValueError as first_error:
                if "工具调用" not in str(first_error):
                    raise
                retry_prompt = (
                    prompt + "\n上一次回答包含交互或工具调用，已被拦截。现在不要提问、不要调用工具；"
                    "请基于已有信息和明确假设，直接给出完整最终答案。"
                )[:MAX_PROMPT_CHARS]
                text, _ = self._run_once(system_prompt, retry_prompt)
            return ClaudeResult(text, time.monotonic() - started)
        except subprocess.TimeoutExpired:
            return ClaudeResult(elapsed_s=time.monotonic() - started,
                                error=f"Claude 超过 {self.timeout_seconds} 秒未完成")
        except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
            return ClaudeResult(elapsed_s=time.monotonic() - started,
                                error=_redact(str(error))[:300])
