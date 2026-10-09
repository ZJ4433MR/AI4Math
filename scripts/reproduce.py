"""Rebuild only from sealed real evidence by default; --live starts new research."""
from pathlib import Path
import argparse
import subprocess
import sys
import yaml
from ai4math_agent.storage import read_json, validate_manifest, digest, source_metadata


ROOT = Path(__file__).resolve().parents[1]


def run(*args):
    subprocess.run([sys.executable, "-m", "ai4math_agent", *map(str, args)], cwd=ROOT, check=True)


def newest(kind, predicate):
    candidates = []
    for path in (ROOT/"results"/kind).glob("*/manifest.json"):
        try:
            manifest = validate_manifest(path.parent)
            if predicate(path.parent, manifest):
                candidates.append(path.parent)
        except ValueError:
            continue
    if not candidates:
        raise SystemExit(f"No complete, sealed {kind} run found. Inspect actual run manifests.")
    return sorted(candidates)[-1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="start a NEW model-backed session")
    args = parser.parse_args()
    if args.live:
        exact_path = ROOT/"results"/"exact_versions"/source_metadata()["source_tree_hash"][:12]
        run("exact", "--n-max", 18, "--output", exact_path)
        config = yaml.safe_load((ROOT/"configs/research.yaml").read_text(encoding="utf-8"))
        config["exact_dir"] = str(exact_path)
        config_path = ROOT/"results"/"research_fresh.yaml"
        config_path.write_text(yaml.safe_dump(config),encoding="utf-8")
        run("research", "--config", config_path, "--backend", "codex_cli")
    research_path = newest("research", lambda p,m:m["mode"]=="live" and (p/"frozen_policy.json").exists() and m.get("termination_reason")!="running")
    policy_hash = digest(read_json(research_path/"frozen_policy.json"))
    if args.live:
        evaluation_config = yaml.safe_load((ROOT/"configs/evaluation.yaml").read_text(encoding="utf-8"))
        evaluation_config["policy_path"] = str(research_path/"frozen_policy.json")
        config_path = ROOT/"results"/"evaluation_fresh.yaml"
        config_path.write_text(yaml.safe_dump(evaluation_config),encoding="utf-8")
        run("evaluate", "--config", config_path)
    evaluation_path = newest("evaluation", lambda p,m:m.get("policy_hash")==policy_hash and m.get("termination_reason")=="complete")
    exact_path = read_json(research_path/"manifest.json")["config"]["exact_dir"]
    run("verify", "--run-dir", research_path)
    run("verify", "--run-dir", evaluation_path)
    run("report", "--research-dir", research_path, "--evaluation-dir", evaluation_path, "--exact-dir", exact_path, "--output", ROOT/"reports/AI4Math_LABS_Report.pdf")


if __name__ == "__main__":
    main()
