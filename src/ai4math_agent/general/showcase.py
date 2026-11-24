"""View of the archived LABS classroom case, without starting a new model run."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from ai4math_agent.storage import read_json


_RUN = "2026-10-09T145817.516168_0000"

# Chinese editorial captions for this specific archived session. Numeric results
# and witness sequences below come from the independently checked artifacts.
_CAPTIONS = {
    "EV001": ("提出平衡猜想", "先问长度 18 时，能否找到一个正负号一样多的全局最优序列。",
              "本轮登记了猜想。还需要在完整枚举结果中寻找平衡的最优序列。"),
    "EV002": ("核验存在性", "读取已独立核验的长度 18 条件能量表，检查失衡量为零的那一组。",
              "确实存在平衡的最优序列。最优值也出现在其他失衡组，值得检验更强的猜想。"),
    "EV003": ("提出更强的猜想", "把命题改成“长度 18 的每个最优序列都平衡”，并登记反驳它所需的证据。",
              "失衡量为 2 或 6 的最优解已给出反例线索。下一步可以提取具体序列。"),
    "EV004": ("建立搜索基线", "放开平衡限制，在长度 31 的序列中运行禁忌搜索。",
              "得到一个能独立复算的候选序列。它的能量给出了全局最小值的上界。"),
    "EV005": ("比较斜对称搜索", "在长度 31 上固定随机种子和评价次数，把搜索限制在斜对称序列中。",
              "本次无约束搜索找到了更低的能量。每种方法只运行了一个随机种子。"),
    "EV006": ("改变实验长度", "在长度 47 上建立新的无约束基线，给配对实验保留相同预算。",
              "记录本次候选能量，等待同预算的斜对称实验。"),
    "EV007": ("观察方法排名反转", "在长度 47 上运行配对的斜对称搜索，比较两种方法找到的最低能量。",
              "这次斜对称搜索表现更好，方法的排序与长度 31 的实验相反。"),
    "EV008": ("检验更长序列", "前两组实验的排名不同。继续在长度 67 上建立无约束基线。",
              "候选序列已核验，可以用相同种子和预算比较另一种方法。"),
    "EV009": ("完成第三组比较", "将剩余搜索预算用于长度 67 的斜对称搜索。",
              "本次斜对称搜索得到更低的能量，却有更大的失衡量。"),
    "EV010": ("核验具体反例", "回到长度 18 的强猜想，从完整枚举结果中提取一个失衡的全局最优序列。",
              "一个失衡的最优序列就足以推翻“每个最优序列都平衡”。平衡最优序列同样存在。"),
    "EV011": ("冻结混合策略", "综合三个开发长度的配对结果，为下一阶段选定两种搜索的预算比例。",
              "这一比例来自开发实验。还需在新的长度和随机种子上检验效果。"),
    "EV012": ("依据审计修正解释", "核对每次搜索实际执行的限制，纠正先前对参数默认值的解读。",
              "基线全程无约束，斜对称方法全程受限。候选能量有效，各方法按评价次数配对。"),
}


def _artifact(path: Path, directory: Path, manifest: dict) -> dict:
    """Accept only bytes bound by this manifest, and only inside its directory."""
    if not path.resolve().is_relative_to(directory.resolve()):
        return {}
    data = path.read_bytes()
    if sha256(data).hexdigest() != manifest["artifacts"].get(path.relative_to(directory).as_posix()):
        return {}
    return json.loads(data)


def _profile(path: Path, root: Path, manifest: dict) -> dict | None:
    profile = _artifact(path, path.parent, manifest)
    if not (profile.get("complete") and profile.get("exact")
            and profile.get("verification", {}).get("recomputed_complete")
            and profile["verification"]["valid"]):
        return None
    bounds = {row["b"]: row["L"] for row in profile["bounds"] if row["verification"]["valid"]}
    points = [{"b": row["b"], "energy": row["E"], "lower_bound": bounds.get(row["b"]),
               "sequence": row["sequence"]} for row in profile["strata"]]
    return {"n": profile["n"], "min_energy": profile["optimum_E"], "optimal_b": profile["optimal_b"],
            "points": sorted(points, key=lambda point: point["b"]), "source": path.relative_to(root).as_posix()}


def _result_text(evidence: dict) -> str:
    tool, result = evidence["tool"], evidence["result"]
    if tool == "propose":
        return "已登记猜想及反驳条件，等待核验。"
    if tool == "check_small_claim":
        check = result["checks"][0]
        if result["status"] == "refuted":
            sample = check["counterexample"]
            return f"反例的失衡量为 {sample['b']}，能量为 {sample['E']}，达到该长度的全局最优。"
        values = "、".join(map(str, check["evidence"]["optimal_b"]))
        return f"全局最小能量为 {check['evidence']['optimum_E']}，在失衡量 {values} 处均达到。"
    if tool == "run_search":
        best = result["best"]
        return f"评价 {result['evaluations']:,} 次，找到能量 {best['E']}、失衡量 {best['b']} 的候选序列。"
    if tool == "finish":
        skew = result["policy"]["skew_fraction"]
        return f"冻结搜索预算分配，斜对称搜索占 {skew:.0%}，无约束搜索占 {1 - skew:.0%}。"
    raise ValueError(f"unexpected archive tool {tool!r}")


def _replay(root: Path) -> list[dict]:
    directory = root / "results" / "research" / _RUN
    manifest = read_json(directory / "manifest.json")
    if manifest.get("mode") != "live" or manifest.get("run_id") != _RUN:
        return []
    state = _artifact(directory / "state.json", directory, manifest)
    items = {item["id"]: item for item in state.get("evidence", [])}
    rounds = []
    for path in sorted((directory / "rounds").glob("[0-9][0-9][0-9].json")):
        row = _artifact(path, directory, manifest)
        key = row.get("evidence_id")
        if key not in _CAPTIONS or key not in items or not items[key]["verification"]["valid"]:
            continue
        title, decision, review = _CAPTIONS[key]
        rounds.append({"number": row["round_index"], "title": title, "decision": decision,
                       "result": _result_text(items[key]), "review": review, "evidence_ids": [key],
                       "original_decision": row["action"]["decision_summary"],
                       "original_review": row["skeptic"]["summary"],
                       "source": path.relative_to(root).as_posix()})
    return rounds


def load_showcase(root: Path) -> dict:
    """Load the exact table and teaching replay independently for partial checkouts."""
    root = Path(root)
    directory = root / "results" / "exact"
    profiles = []
    try:
        manifest = read_json(directory / "manifest.json")
        for path in sorted(directory.glob("profile_*.json")):
            profile = _profile(path, root, manifest)
            if profile:
                profiles.append(profile)
    except (OSError, ValueError, TypeError, KeyError):
        pass
    try:
        rounds = _replay(root)
    except (OSError, ValueError, TypeError, KeyError):
        rounds = []
    return {"profiles": profiles, "rounds": rounds, "session_id": f"research/{_RUN}" if rounds else None}
