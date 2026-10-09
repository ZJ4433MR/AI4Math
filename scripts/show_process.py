"""Display the saved real research trajectory for a classroom demonstration."""
from pathlib import Path
import argparse
import sys
from ai4math_agent.storage import read_json, validate_manifest


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Show saved research evidence; no new model calls")
    parser.add_argument("--run-dir", default="results/research/2026-10-09T145817.516168_0000")
    parser.add_argument("--round", type=int)
    parser.add_argument("--interactive", action="store_true", help="press Enter between rounds")
    args = parser.parse_args()
    directory = Path(args.run_dir)
    manifest = validate_manifest(directory)
    state = read_json(directory/"state.json")
    by_id = {e["id"]:e for e in state["evidence"]}
    print(f"展示已有日志；原运行模式={manifest['mode']}；本次不发生模型调用或数学实验。")
    for row in state["rounds"]:
        if args.round is not None and row["round_index"] != args.round:
            continue
        action = row["action"]
        evidence = by_id[row["evidence_id"]]
        result = evidence["result"]
        print(f"\n第 {row['round_index']} 轮 / {evidence['id']} / {action['action_type']}")
        if action.get("hypothesis"):
            print("命题：",action["hypothesis"]["text"])
        print("决策：",action["decision_summary"])
        print("预期信息：",action["expected_information"])
        if result.get("best"):
            best = result["best"]
            print(f"工具：n={best['n']}, E={best['E']}, b={best['b']}, F={best['F_numerator']}/{best['F_denominator']}")
        if result.get("status"):
            print("结论状态：",result["status"])
        counter = result.get("counterexample")
        if counter:
            witness = counter.get("counterexample",counter)
            if "sequence" in witness:
                print(f"反例见证：n={witness['n']}, b={witness['b']}, E={witness['E']}, sequence={witness['sequence']}")
        print("核验：",evidence["verification"].get("valid"),evidence["verification"].get("scope", "独立数学核验"))
        print("审查：",row["skeptic"]["summary"])
        print("局限：",row["skeptic"]["limitation"])
        print("下一问题：",row["skeptic"]["next_question"])
        print("累计候选：",row["budget_after"]["evaluations"])
        if args.interactive:
            input("按 Enter 展示下一轮…")


if __name__ == "__main__":
    main()
