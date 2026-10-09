"""Canonical JSON, immutable artifact hashes, and reproducibility metadata."""
from __future__ import annotations
import hashlib
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def source_metadata():
    root = Path(__file__).resolve().parents[2]
    files = sorted((root / "src").rglob("*.py"))
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, stderr=subprocess.DEVNULL, text=True).strip()
    except (OSError, subprocess.SubprocessError):
        commit = None
    return {"git_commit": commit, "source_tree_hash": digest({str(p.relative_to(root)): file_hash(p) for p in files}),
            "verification_code_hash": digest({str(p.relative_to(root)): file_hash(p) for p in files if "verification" in p.parts}),
            "dependency_lock_hash": file_hash(root / "requirements.lock") if (root / "requirements.lock").exists() else None,
            "python": sys.version, "platform": platform.platform(),
            "hardware": {"cpu": platform.processor(), "logical_cpus": os.cpu_count()}}


def seal_manifest(directory, manifest):
    directory = Path(directory)
    manifest["artifacts"] = {str(p.relative_to(directory)).replace("\\", "/"): file_hash(p)
                             for p in sorted(directory.rglob("*"))
                             if p.is_file() and p.name != "manifest.json" and "planner_workspace" not in p.parts and p.suffix != ".tmp"}
    write_json(directory / "manifest.json", manifest)


def validate_manifest(directory):
    directory = Path(directory).resolve()
    manifest = read_json(directory / "manifest.json")
    if manifest.get("mode") not in {"live", "dry_run", "replay", "evaluation", "exact"}:
        raise ValueError("invalid run mode")
    if not manifest.get("artifacts"):
        raise ValueError("missing artifact hashes")
    for relative, expected in manifest["artifacts"].items():
        path = (directory / relative).resolve()
        if not path.is_relative_to(directory) or not path.is_file() or file_hash(path) != expected:
            raise ValueError(f"missing or changed evidence: {relative}")
    return manifest
