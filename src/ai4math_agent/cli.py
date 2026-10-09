from __future__ import annotations
import argparse
import importlib.metadata
import platform
import shutil
import subprocess
import time
from pathlib import Path
import yaml
from .storage import digest, file_hash, now, read_json, write_json, seal_manifest, validate_manifest, source_metadata


def doctor(live_probe=False, model=None):
    output = Path("results/doctor")
    output.mkdir(parents=True, exist_ok=True)
    previous = read_json(output / "doctor.json") if (output / "doctor.json").exists() else {}
    result = {"time": now(), "python": platform.python_version(), "backend_call_attempts": previous.get("backend_call_attempts",0),
              "dependencies": {}, "codex": shutil.which("codex"), "font": str(Path("C:/Windows/Fonts/simhei.ttf"))}
    for package in ["numpy", "pydantic", "matplotlib", "PyYAML", "reportlab", "pypdf", "numba", "pytest"]:
        try:
            result["dependencies"][package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            result["dependencies"][package] = None
    if result["codex"]:
        for field, args in [("cli_version", ["--version"]), ("exec_help", ["exec", "--help"]), ("login_status", ["login", "status"])]:
            command = subprocess.run([result["codex"], *args], capture_output=True, text=True, encoding="utf-8", timeout=30)
            result[field] = command.stdout.strip() or command.stderr.strip()
        result["auth_method"] = "ChatGPT" if "ChatGPT" in result["login_status"] else "unknown"
        result["structured_output_supported"] = "--output-schema" in result["exec_help"]
    if live_probe:
        from .agent.schema import Review, output_schema
        from .backends import make_backend
        result["backend_call_attempts"] += 1
        write_json(output / "doctor.json", result)
        try:
            answer, metadata = make_backend("codex_cli", model, 120).decide(
                {"role": "skeptic", "task": "This is a real structured-output connectivity probe, not research. Return a concise acknowledgement; evidence_strength insufficient, limitation no experiment run, next_question validate tools."},
                output_schema(Review), output / f"probe_{result['backend_call_attempts']:03d}")
            Review.model_validate(answer)
            result["live_probe"] = {"valid": True, "metadata": metadata}
        except Exception as exc:
            result["live_probe"] = {"valid": False, "error": str(exc)}
    write_json(output / "doctor.json", result)
    print({k:v for k,v in result.items() if k != "exec_help"}, flush=True)


def exact(n_max, output, wall_seconds=600):
    from .math.exact import exact_profile
    from .math.bounds import lower_bound
    from .verification.reference import verify_exact_profile, check_bound
    directory = Path(output)
    directory.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    manifest = {"run_id": "exact", "mode": "exact", "start": now(), "n_max": n_max, **source_metadata()}
    if (directory / "manifest.json").exists():
        previous = validate_manifest(directory)
        if previous["source_tree_hash"] != manifest["source_tree_hash"]:
            raise ValueError("exact source changed; use a fresh output directory")
        elapsed_prior = previous.get("enumeration_seconds", 0)
    else:
        elapsed_prior = 0
    enumeration_seconds = elapsed_prior
    verification_seconds = 0
    for n in range(2, n_max+1):
        path = directory / f"profile_{n:03d}.json"
        if path.exists() and read_json(path).get("complete"):
            continue
        remaining = wall_seconds - enumeration_seconds
        if remaining <= 0:
            break
        tick = time.monotonic()
        profile = exact_profile(n, wall_seconds=remaining)
        enumeration_seconds += time.monotonic() - tick
        profile["bounds"] = []
        for stratum in profile["strata"]:
            certificate = lower_bound(n, stratum["b"])
            verification = check_bound(certificate)
            if not verification.get("valid"):
                raise ValueError("invalid bound certificate")
            profile["bounds"].append({**certificate, "verification": verification})
        verify_tick = time.monotonic()
        profile["verification"] = verify_exact_profile(profile, exhaustive=True)
        verification_seconds += time.monotonic() - verify_tick
        if not profile["verification"].get("valid"):
            raise ValueError(f"profile n={n} failed independent verification")
        write_json(path, profile)
        print(f"n={n}: exact={profile['complete']}, visited={profile['visited']}, E*={profile.get('optimum_E')}", flush=True)
        manifest.update(enumeration_seconds=enumeration_seconds, verification_seconds=verification_seconds, end=now())
        seal_manifest(directory, manifest)
        if not profile["complete"]:
            break
    manifest.update(enumeration_seconds=enumeration_seconds, verification_seconds=verification_seconds,
                    total_wall_seconds=time.monotonic()-start, end=now(), termination_reason="complete_or_time_limit")
    seal_manifest(directory, manifest)


def evaluation(config, resume=None):
    from .agent.schema import FrozenPolicy
    from .search.engine import run_search
    from .verification.reference import verify_sequence
    import statistics
    policy_path = Path(config["policy_path"])
    policy = FrozenPolicy.model_validate(read_json(policy_path)).model_dump()
    research_manifest = validate_manifest(policy_path.parent)
    if research_manifest["mode"] != "live":
        raise ValueError("formal agent_policy requires a live research policy")
    if research_manifest.get("policy_hash") != digest(policy):
        raise ValueError("policy differs from the research-frozen version")
    if resume:
        directory = Path(resume)
        manifest = validate_manifest(directory)
        if manifest["config_hash"] != digest(config) or manifest["policy_hash"] != digest(policy) or manifest["source_tree_hash"] != source_metadata()["source_tree_hash"]:
            raise ValueError("resume config/policy/source mismatch")
        runs = read_json(directory / "runs.json")
    else:
        run_id = now().replace(":", "").replace("+", "_")
        directory = Path(config["output_root"]) / run_id
        directory.mkdir(parents=True)
        runs = []
        manifest = {"run_id": run_id, "mode": "evaluation", "start": now(), "config": config,
                    "config_hash": digest(config), "policy_hash": digest(policy), "policy_file_hash": file_hash(policy_path),
                    "frozen_before_results": True, "policy_origin": str(policy_path), "policy": policy,
                    "pre_registration_time": now(), **source_metadata()}
        write_json(directory / "runs.json", runs)
        seal_manifest(directory, manifest)
    done = {(r["n"],r["seed"],r["method"]) for r in runs}
    for n in config["lengths"]:
        for seed in config["seeds"]:
            for method in config["methods"]:
                if (n,seed,method) in done:
                    continue
                result = run_search(n=n, method=method, evaluations=config["evaluations_per_run"], seed=seed,
                                    policy=policy if method=="agent_policy" else None, wall_seconds=config["run_wall_seconds"])
                verification = verify_sequence(result["best"])
                if not verification.get("valid"):
                    raise ValueError("invalid evaluation witness")
                runs.append({"n":n, "seed":seed, "method":method, "result":result, "verification":verification})
                write_json(directory / "runs.json", runs)
                manifest.update(completed_runs=len(runs), end=now(), termination_reason="running")
                seal_manifest(directory, manifest)
                print(f"evaluation {len(runs)}: n={n} seed={seed} {method} E={result['best']['E']} evaluations={result['evaluations']}", flush=True)
    summary = []
    for n in config["lengths"]:
        for method in config["methods"]:
            records = [r for r in runs if r["n"]==n and r["method"]==method]
            values = [r["result"]["best"]["E"] for r in records]
            differences = [r["result"]["best"]["E"] - next(b["result"]["best"]["E"] for b in runs if b["n"]==n and b["seed"]==r["seed"] and b["method"]=="fixed_tabu") for r in records]
            summary.append({"n":n,"method":method,"best_E":min(values),"median_E":statistics.median(values),
                            "paired_difference_vs_tabu":differences,"wins":sum(d<0 for d in differences),
                            "ties":sum(d==0 for d in differences),"losses":sum(d>0 for d in differences)})
    write_json(directory / "summary.json", summary)
    manifest.update(end=now(), termination_reason="complete", total_evaluations=sum(r["result"]["evaluations"] for r in runs))
    seal_manifest(directory, manifest)
    return directory


def verify_run(directory):
    from .verification.reference import verify_sequence, check_bound
    manifest = validate_manifest(directory)
    if manifest["mode"] in {"live", "dry_run", "replay"}:
        state = read_json(Path(directory)/"state.json")
        records = []
        for evidence in state["evidence"]:
            result = evidence["result"]
            if "best" in result:
                records.append(verify_sequence(result["best"]))
            elif "sequence" in result and "E" in result:
                records.append(verify_sequence(result))
            elif "c" in result and "L" in result:
                records.append(check_bound(result))
            elif "witness" in result:
                records.append(verify_sequence(result["witness"]))
        if any(not r.get("valid") for r in records):
            raise ValueError("independent evidence verification failed")
        print({"valid": True, "mode": manifest["mode"], "verified_records": len(records), "rounds": len(state["rounds"]), "budget": state["budget"]})
    elif manifest["mode"] == "evaluation":
        runs = read_json(Path(directory)/"runs.json")
        if any(not verify_sequence(r["result"]["best"]).get("valid") for r in runs):
            raise ValueError("invalid evaluation witness")
        print({"valid":True,"mode":"evaluation","verified_witnesses":len(runs)})
    else:
        from .verification.reference import verify_exact_profile
        profiles = [read_json(p) for p in Path(directory).glob("profile_*.json")]
        if any(not verify_exact_profile(p,exhaustive=True).get("valid") for p in profiles):
            raise ValueError("invalid exact profile")
        print({"valid":True,"mode":"exact","verified_profiles":len(profiles)})


def main():
    parser = argparse.ArgumentParser(description="Evidence-grounded LABS research agent")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("doctor"); p.add_argument("--live-probe", action="store_true"); p.add_argument("--model")
    p = sub.add_parser("exact"); p.add_argument("--n-max", type=int, default=18); p.add_argument("--output", default="results/exact"); p.add_argument("--wall-seconds", type=float, default=600)
    p = sub.add_parser("research"); p.add_argument("--config", default="configs/research.yaml"); p.add_argument("--backend", choices=["codex_cli","api","dry_run","replay"], default="codex_cli"); p.add_argument("--resume"); p.add_argument("--replay-source")
    p = sub.add_parser("evaluate"); p.add_argument("--config", default="configs/evaluation.yaml"); p.add_argument("--resume")
    p = sub.add_parser("verify"); p.add_argument("--run-dir", required=True)
    p = sub.add_parser("report"); p.add_argument("--research-dir", required=True); p.add_argument("--evaluation-dir"); p.add_argument("--exact-dir", default="results/exact"); p.add_argument("--output", default="reports/AI4Math_LABS_Report.pdf")
    p = sub.add_parser("benchmark"); p.add_argument("--evaluations", type=int, default=5000)
    args = parser.parse_args()
    if args.command == "doctor":
        doctor(args.live_probe, args.model)
    elif args.command == "exact":
        exact(args.n_max, args.output, args.wall_seconds)
    elif args.command == "research":
        from .agent.controller import research
        print(research(yaml.safe_load(Path(args.config).read_text(encoding="utf-8")), args.backend, args.resume, args.replay_source))
    elif args.command == "evaluate":
        print(evaluation(yaml.safe_load(Path(args.config).read_text(encoding="utf-8")), args.resume))
    elif args.command == "verify":
        verify_run(args.run_dir)
    elif args.command == "report":
        from .reporting.report import build_report
        print(build_report(args.research_dir, args.evaluation_dir, args.exact_dir, args.output))
    elif args.command == "benchmark":
        from .search.engine import run_search
        from .verification.reference import verify_sequence
        records = []
        for method in ["random","fixed_tabu","static_mix"]:
            run_search(31,method,100,0)  # initialization/JIT warmup reported separately
            result = run_search(127,method,args.evaluations,17,wall_seconds=10)
            records.append({"method":method,"n":127,"evaluations":result["evaluations"],"elapsed":result["elapsed"],"rate":result["evaluations"]/result["elapsed"],"verification":verify_sequence(result["best"])})
        write_json("results/benchmark.json", {"records":records, "warmup_evaluations":300, **source_metadata()})
        print(records)


if __name__ == "__main__":
    main()
