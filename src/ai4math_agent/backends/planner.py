"""Planner-only backends. No automatic live-to-mock fallback."""
from __future__ import annotations
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from ai4math_agent.storage import read_json, write_json


class BackendError(RuntimeError):
    pass


def subprocess_environment():
    """Reuse the user's configured Windows proxy for this child only."""
    environment = os.environ.copy()
    source = "environment" if environment.get("HTTPS_PROXY") else "direct"
    if os.name == "nt" and not any(environment.get(k) for k in ["HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY"]):
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Internet Settings") as key:
                enabled = winreg.QueryValueEx(key, "ProxyEnable")[0]
                proxy = winreg.QueryValueEx(key, "ProxyServer")[0] if enabled else ""
            if proxy:
                if "=" in proxy:
                    entries = dict(part.split("=", 1) for part in proxy.split(";") if "=" in part)
                    proxy = entries.get("https", entries.get("http", ""))
                if proxy:
                    value = proxy if "://" in proxy else "http://" + proxy
                    environment.update(HTTPS_PROXY=value, HTTP_PROXY=value)
                    source = "Windows user system proxy"
        except (OSError, ValueError):
            pass
    return environment, source


def public_events(stdout):
    result = []
    for line in stdout.splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        typ = event.get("type")
        if typ in {"thread.started", "turn.started", "turn.completed", "turn.failed", "error"}:
            result.append({k: v for k, v in event.items() if k in {"type", "usage", "error", "message"}})
        elif typ in {"item.started", "item.updated", "item.completed"}:
            item = event.get("item", {})
            if item.get("type") == "agent_message":
                result.append({"type": typ, "item": {"type": "agent_message", "text": item.get("text", "")}})
            elif item.get("type") == "reasoning":
                # Do not publish hidden reasoning; it has no executable effect.
                continue
            elif item.get("type") == "error":
                result.append({"type": typ, "item": {"type": "error", "message": item.get("message", "public CLI error")}})
            else:
                raise BackendError(f"planner attempted forbidden item: {item.get('type')}")
        else:
            raise BackendError(f"unknown planner event: {typ}")
    return result


class CodexBackend:
    mode = "live"
    name = "codex_cli"

    def __init__(self, model=None, timeout=180):
        self.executable = shutil.which("codex")
        if not self.executable:
            raise BackendError("codex CLI is not installed or not on PATH")
        self.model = model
        self.timeout = timeout

    def decide(self, context, output_schema, call_dir):
        directory = Path(call_dir).resolve()
        directory.mkdir(parents=True, exist_ok=True)
        workspace = directory / "planner_workspace"
        workspace.mkdir(exist_ok=True)
        prompt = ("You are a mathematical experiment planner. Use ONLY the supplied context. "
                  "Do not use any tool, command, MCP, browser, file inspection or calculation subprocess. "
                  "The host performs ALL mathematical experiments and charges their cost. "
                  "Return only the schema JSON, with a concise public decision summary, no hidden reasoning.\n\n" +
                  json.dumps(context, ensure_ascii=False))
        write_json(directory / "schema.json", output_schema)
        (directory / "prompt.txt").write_text(prompt, encoding="utf-8")
        answer_path = directory / "answer.json"
        args = [self.executable, "exec", "--json", "--sandbox", "read-only", "--ignore-user-config",
                "--ignore-rules", "--ephemeral", "--skip-git-repo-check", "--color", "never",
                "-C", str(workspace), "--output-schema", str(directory / "schema.json"), "-o", str(answer_path)]
        if self.model:
            args.extend(["--model", self.model])
        args.append("-")
        started = time.monotonic()
        metadata = {"backend": self.name, "mode": self.mode, "requested_model": self.model,
                    "effective_model": None, "provider_request_count": "unknown", "actual_cost": "unknown"}
        try:
            environment, proxy_source = subprocess_environment()
            metadata["proxy_source"] = proxy_source
            process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       text=True, encoding="utf-8", errors="replace", shell=False, env=environment)
            try:
                stdout, stderr = process.communicate(prompt, timeout=self.timeout)
            except subprocess.TimeoutExpired:
                # CLI is its own process; terminate children as well on Windows.
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
                else:
                    process.kill()
                stdout, stderr = process.communicate()
                raise BackendError("backend timeout")
            metadata["exit_code"] = process.returncode
            stderr = re.sub(r"(?i)(bearer\s+|sk-[A-Za-z0-9_-]+)[A-Za-z0-9._-]*", "[REDACTED]", stderr)
            (directory / "stderr.txt").write_text(stderr[-12000:], encoding="utf-8")
            events = public_events(stdout)
            (directory / "events.jsonl").write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in events), encoding="utf-8")
            metadata["usage"] = next((e.get("usage") for e in reversed(events) if e.get("usage")), None)
            if process.returncode or not answer_path.exists():
                raise BackendError(f"codex failed with exit {process.returncode}; inspect sanitized stderr")
            answer = read_json(answer_path)
            metadata["accepted"] = True
            return answer, metadata
        except Exception as exc:
            metadata["accepted"] = False
            metadata["error"] = str(exc)
            # A rejected action is not compliant research evidence.
            if answer_path.exists():
                answer_path.unlink()
            raise
        finally:
            metadata["elapsed"] = time.monotonic() - started
            write_json(directory / "metadata.json", metadata)


class ReplayBackend:
    mode = "replay"
    name = "replay"

    def __init__(self, source):
        self.answers = sorted(Path(source).glob("calls/*/answer.json"))
        self.index = 0

    def decide(self, context, output_schema, call_dir):
        if self.index >= len(self.answers):
            raise BackendError("replay exhausted")
        answer = read_json(self.answers[self.index])
        self.index += 1
        directory = Path(call_dir)
        write_json(directory / "context.json", context)
        write_json(directory / "answer.json", answer)
        metadata = {"mode": "replay", "backend": "replay", "source": str(self.answers[self.index-1]), "accepted": True}
        write_json(directory / "metadata.json", metadata)
        return answer, metadata


class DryBackend:
    mode = "dry_run"
    name = "dry_run"

    def decide(self, context, output_schema, call_dir):
        if context.get("role") == "skeptic":
            answer = {"summary": "Dry-run wiring check only.", "evidence_strength": "insufficient",
                      "limitation": "No live model decision was made.", "next_question": "Configure a live backend to research."}
        else:
            answer = {"action_type": "lower_bound", "claim_id": None, "hypothesis": None, "evidence_ids": [],
                      "tool_arguments": {"n": 6, "b": 4}, "decision_summary": "Dry-run certificate wiring check.",
                      "expected_information": "Validate deterministic tool and verifier wiring.", "requested_evaluations": 0, "policy": None}
        write_json(Path(call_dir) / "answer.json", answer)
        metadata = {"mode": self.mode, "backend": self.name, "accepted": True}
        write_json(Path(call_dir) / "metadata.json", metadata)
        return answer, metadata


class APIBackend:
    mode = "live"
    name = "api"

    def __init__(self, model=None, timeout=180):
        self.model = model or os.environ.get("AI4MATH_API_MODEL")
        self.key = os.environ.get("OPENAI_API_KEY")
        self.timeout = timeout
        if not self.key or not self.model:
            raise BackendError("api requires OPENAI_API_KEY and an explicitly configured model")

    def decide(self, context, output_schema, call_dir):
        import urllib.request
        directory = Path(call_dir)
        write_json(directory / "context.json", context)
        body = {"model": self.model, "input": [{"role": "user", "content": json.dumps(context, ensure_ascii=False)}],
                "text": {"format": {"type": "json_schema", "name": "research_decision", "schema": output_schema, "strict": True}}}
        request = urllib.request.Request("https://api.openai.com/v1/responses", data=json.dumps(body).encode(),
                    headers={"Authorization": "Bearer " + self.key, "Content-Type": "application/json"})
        started = time.monotonic()
        metadata = {"backend": "api", "mode": "live", "requested_model": self.model, "provider_request_count": 1,
                    "implicit_retries": 0, "actual_cost": "unknown"}
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.load(response)
            text = "".join(part.get("text", "") for item in data.get("output", []) if item.get("type") == "message"
                           for part in item.get("content", []) if part.get("type") == "output_text")
            answer = json.loads(text)
            write_json(directory / "answer.json", answer)
            metadata.update(effective_model=data.get("model"), usage=data.get("usage"), accepted=True)
            return answer, metadata
        finally:
            metadata["elapsed"] = time.monotonic() - started
            write_json(directory / "metadata.json", metadata)


def make_backend(name, model=None, timeout=180, replay_source=None):
    if name == "codex_cli":
        return CodexBackend(model, timeout)
    if name == "api":
        return APIBackend(model, timeout)
    if name == "dry_run":
        return DryBackend()
    if name == "replay":
        if not replay_source:
            raise BackendError("replay requires --replay-source")
        return ReplayBackend(replay_source)
    raise BackendError(f"unsupported backend: {name}")
