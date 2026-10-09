"""Offline integrity/certificate verification and report regeneration; no model calls."""
import argparse
import json
import sys
from pathlib import Path
from ai4math_agent.general.controller import verify_general
from ai4math_agent.general.report import build_general_report
from ai4math_agent.storage import read_json


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", action="append")
    args = parser.parse_args()
    directories = [Path(p) for p in args.run_dir] if args.run_dir else sorted(p.parent for p in Path("results/general").rglob("manifest.json")
        if (p.parent / "state.json").is_file() and read_json(p).get("workflow") == "general-v1" and read_json(p).get("mode") == "live"
        and read_json(p.parent / "state.json")["termination_reason"] == "finished")
    if not directories:
        parser.error("no completed general live sessions found")
    for directory in directories:
        verification = verify_general(directory)
        report = build_general_report(directory)
        print(json.dumps({"run": str(directory), "verification": verification, "report": str(report)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
