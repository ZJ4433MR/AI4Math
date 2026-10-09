"""Build a Chinese course report from sealed, independently checked evidence.

The caller performs the PDF skill's artifact-operation marker before invoking
build_report. Integrity validation precedes every output mutation.
"""
from __future__ import annotations

import csv
import io
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from xml.sax.saxutils import escape

from ai4math_agent.storage import file_hash, read_json, validate_manifest, write_json
from ai4math_agent.verification.reference import (
    check_bound, profile_digest, verify_exact_profile, verify_sequence,
)


METHODS = ("random", "fixed_tabu", "static_mix", "agent_policy")
STATUS_CN = {
    "proposed": "已提出", "refuted": "严格反例", "finite_domain_verified": "有限域验证",
    "empirical_supported": "经验支持", "certified_stratum_optimum": "条件最优认证",
    "certified_global_optimum": "全局最优认证", "proof_candidate": "证明候选",
    "unresolved": "未解决",
}


def _assert(condition, message):
    if not condition:
        raise ValueError(f"report evidence invalid: {message}")


def _read_sealed(directory, manifest, relative):
    _assert(relative in manifest["artifacts"], f"{relative} not sealed in manifest")
    return read_json(Path(directory) / relative)


def _walk_records(value):
    if isinstance(value, dict):
        if "sequence" in value and "C" in value and "E" in value:
            yield value
        for v in value.values():
            yield from _walk_records(v)
    elif isinstance(value, list):
        for v in value:
            yield from _walk_records(v)


def _walk_bounds(value):
    if isinstance(value, dict):
        if all(k in value for k in ("n", "b", "A", "c", "L")):
            yield value
        for v in value.values():
            yield from _walk_bounds(v)
    elif isinstance(value, list):
        for v in value:
            yield from _walk_bounds(v)


def _verify_nested(value, source, checks):
    for record in _walk_records(value):
        result = verify_sequence(record)
        _assert(result["valid"], f"{source}: witness mismatch {result['errors']}")
        checks.append({"source": source, "kind": "witness", "hash": record["hash"]})
    for cert in _walk_bounds(value):
        result = check_bound(cert)
        _assert(result["valid"], f"{source}: lower-bound certificate mismatch {result['errors']}")
        checks.append({"source": source, "kind": "bound", "n": cert["n"], "b": cert["b"], "L": cert["L"]})


def load_report_evidence(research_dir, evaluation_dir, exact_dir):
    """Validate all consumed JSON and return data without creating artifacts.

    Existing exact-completeness annotations must be bound to the profile hash,
    use the independent implementation, and cover all states. Without one,
    the independent enumeration is rerun; witness checks alone never certify
    an exact profile.
    """
    directories = {"research": Path(research_dir), "evaluation": Path(evaluation_dir), "exact": Path(exact_dir)}
    manifests = {kind: validate_manifest(path) for kind, path in directories.items()}
    _assert(manifests["research"]["mode"] in {"live", "dry_run", "replay"}, "research mode mismatch")
    _assert(manifests["evaluation"]["mode"] == "evaluation", "evaluation mode mismatch")
    _assert(manifests["exact"]["mode"] == "exact", "exact mode mismatch")
    research = _read_sealed(directories["research"], manifests["research"], "state.json")
    policy = _read_sealed(directories["research"], manifests["research"], "frozen_policy.json")
    runs = _read_sealed(directories["evaluation"], manifests["evaluation"], "runs.json")
    _assert(isinstance(research.get("rounds"), list), "research rounds missing")
    _assert(isinstance(research.get("evidence"), list), "research evidence missing")
    _assert(isinstance(research.get("hypotheses"), dict), "research hypotheses missing")
    if "mode" in research:
        _assert(research["mode"] == manifests["research"]["mode"], "state mode mismatch")
    _assert(isinstance(runs, list) and runs, "no evaluation runs")
    checks, profiles, bounds, ids = [], [], {}, set()
    for evidence in research["evidence"]:
        eid = evidence.get("id")
        _assert(isinstance(eid, str) and eid not in ids, "invalid/duplicate evidence ID")
        ids.add(eid)
        _assert(isinstance(evidence.get("result"), dict), f"{eid}: no tool result")
        _assert(isinstance(evidence.get("verification"), dict), f"{eid}: missing verification")
        _assert(evidence["verification"].get("valid") is True, f"{eid}: verification failed")
        _verify_nested(evidence["result"], eid, checks)
        for cert in _walk_bounds(evidence["result"]):
            bounds[(cert["n"], cert["b"])] = {**cert, "evidence_id": eid}
    seen_rounds = set()
    for round_ in research["rounds"]:
        index = round_.get("round_index")
        _assert(isinstance(index, int) and index not in seen_rounds, "invalid/duplicate round index")
        seen_rounds.add(index)
        _assert(round_.get("evidence_id") is None or round_["evidence_id"] in ids, f"round {index}: unknown evidence ID")
        action = round_.get("action", round_.get("validated_action"))
        _assert(isinstance(action, dict), f"round {index}: action missing")
        _assert(all(e in ids for e in action.get("evidence_ids", [])), f"round {index}: unregistered evidence reference")
        matches = []
        for name in manifests["research"]["artifacts"]:
            if name.startswith("rounds/") and name.endswith(".json"):
                saved = read_json(directories["research"] / name)
                if saved.get("round_index") == index:
                    matches.append(saved)
        _assert(len(matches) == 1, f"round {index}: missing/duplicate immutable round file")
        for key in ("round_index", "evidence_id", "action", "budget_before", "budget_after"):
            if key in round_:
                _assert(matches[0].get(key) == round_[key], f"round {index}: state/round {key} mismatch")
    for name in sorted(manifests["exact"]["artifacts"]):
        if not name.endswith(".json"):
            continue
        data = read_json(directories["exact"] / name)
        _verify_nested(data, f"EXACT:{name}", checks)
        for cert in _walk_bounds(data):
            bounds[(cert["n"], cert["b"])] = {**cert, "evidence_id": f"EXACT:{name}:b{cert['b']}"}
        if not (isinstance(data, dict) and "strata" in data and "visited" in data):
            continue
        structural = verify_exact_profile(data, exhaustive=False)
        _assert(structural["valid"], f"{name}: invalid profile {structural['errors']}")
        if data.get("exact") is True:
            v = data.get("verification", {})
            saved_complete = (
                v.get("valid") is True and v.get("recomputed_complete") is True
                and v.get("profile_hash") == profile_digest(data)
                and v.get("checked_states") == data["total_states"]
                and v.get("implementation") == "independent Python integer Gray-code enumeration"
            )
            if not saved_complete:
                v = verify_exact_profile(data, exhaustive=True)
                _assert(v["valid"] and v["recomputed_complete"], f"{name}: exactness unverified {v['errors']}")
            checks.append({"source": f"EXACT:{name}", "kind": "complete enumeration", "checked_states": v["checked_states"], "profile_hash": v["profile_hash"]})
        profiles.append({**data, "evidence_id": f"EXACT:{name}"})
    _assert(profiles, "no exact-profile evidence")
    profiles.sort(key=lambda p: p["n"])
    _assert(len({p["n"] for p in profiles}) == len(profiles), "duplicate exact lengths")
    seen_runs = set()
    for run in runs:
        identity = (run.get("n"), run.get("seed"), run.get("method"))
        _assert(identity not in seen_runs and run.get("method") in METHODS, "invalid/duplicate evaluation row")
        seen_runs.add(identity)
        _assert(run.get("verification", {}).get("valid") is True, f"EVAL:{identity}: no independent verification")
        result = run.get("result", {})
        best = result.get("best")
        _assert(isinstance(best, dict), f"EVAL:{identity}: best witness missing")
        _verify_nested(result, f"EVAL:{identity}", checks)
        _assert(best.get("n") == run["n"], f"EVAL:{identity}: length mismatch")
        count = result.get("evaluations")
        _assert(isinstance(count, int) and count >= 1, f"EVAL:{identity}: cost missing")
        curve = result.get("curve")
        _assert(isinstance(curve, list) and curve, f"EVAL:{identity}: convergence trace missing")
        previous_count, previous_E = 0, math.inf
        for point in curve:
            evaluations, energy = point.get("evaluations"), point.get("E")
            _assert(isinstance(evaluations, int) and previous_count <= evaluations <= count, f"EVAL:{identity}: invalid curve cost")
            _assert(isinstance(energy, int) and best["E"] <= energy <= previous_E, f"EVAL:{identity}: invalid best-so-far curve")
            previous_count, previous_E = evaluations, energy
        _assert(previous_E == best["E"], f"EVAL:{identity}: curve/best mismatch")
        run["evidence_id"] = f"EVAL:{run['n']}:{run['seed']}:{run['method']}"
    if manifests["evaluation"].get("policy_hash"):
        _assert(manifests["evaluation"]["policy_hash"] == file_hash(directories["research"] / "frozen_policy.json"), "evaluation policy hash mismatch")
    return {"directories": directories, "manifests": manifests, "research": research,
            "policy": policy, "runs": runs, "profiles": profiles, "bounds": bounds,
            "checks": checks, "mode": manifests["research"]["mode"]}


def _text(value, limit=1400):
    if value is None:
        return "unknown"
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    value = str(value).replace("\u2011", "-").replace("\u2013", "-").replace("\u2014", "-")
    return value if len(value) <= limit else value[:limit] + "…（完整内容见原始证据）"


def _statistics(runs):
    groups = defaultdict(list)
    for run in runs:
        groups[(run["n"], run["method"])].append(run)
    rows = []
    for (n, method), members in sorted(groups.items()):
        energy = [r["result"]["best"]["E"] for r in members]
        seconds = [r["result"].get("elapsed", r["result"].get("wall_seconds", 0)) for r in members]
        rows.append({"n": n, "method": method, "count": len(members), "best_E": min(energy),
                     "median_E": statistics.median(energy), "median_F": statistics.median(r["result"]["best"]["F"] for r in members),
                     "median_seconds": statistics.median(seconds), "evaluations": sum(r["result"]["evaluations"] for r in members)})
    return rows


def _chart_profile(data, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    candidates = [p for p in data["profiles"] if p.get("exact")]
    preferred = [p for p in candidates if p["n"] in (4, 6, 13)]
    selected = preferred[:3] or candidates[-3:]
    fig, axes = plt.subplots(1, len(selected), figsize=(9.6, 3.0), squeeze=False)
    for ax, profile in zip(axes[0], selected):
        b, E = [r["b"] for r in profile["strata"]], [r["E"] for r in profile["strata"]]
        ax.plot(b, E, "o-", color="#176b87", label="exact g(n,b)", lw=1.7, ms=4)
        available = [(x, data["bounds"][(profile["n"], x)]["L"]) for x in b if (profile["n"], x) in data["bounds"]]
        if available:
            ax.plot([x[0] for x in available], [x[1] for x in available], "s--", color="#dc7b29", label="certified L(n,b)", lw=1.4, ms=3)
        ax.set(title=f"n={profile['n']}", xlabel="absolute imbalance b", ylabel="integer energy")
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(alpha=.18)
        ax.legend(fontsize=7, frameon=False)
    fig.tight_layout()
    fig.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def _chart_convergence(data, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    lengths = sorted({r["n"] for r in data["runs"]})
    fig, axes = plt.subplots(1, len(lengths), figsize=(9.6, 3.1), squeeze=False)
    colors = dict(zip(METHODS, ("#999999", "#176b87", "#dc7b29", "#5f4b8b")))
    for ax, n in zip(axes[0], lengths):
        for method in METHODS:
            runs = [r for r in data["runs"] if r["n"] == n and r["method"] == method]
            if not runs:
                continue
            start = max(r["result"]["curve"][0]["evaluations"] for r in runs)
            end = min(r["result"]["evaluations"] for r in runs)
            grid = np.unique(np.linspace(start, end, 90).astype(int))
            values = []
            for run in runs:
                curve = run["result"]["curve"]
                indexes = np.searchsorted([p["evaluations"] for p in curve], grid, side="right") - 1
                values.append([curve[max(0, int(i))]["E"] for i in indexes])
            median = np.median(values, axis=0)
            ax.step(grid, median, where="post", label=method, color=colors[method], lw=1.5)
        ax.set(title=f"n={n}", xlabel="candidate evaluations", ylabel="median best E")
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(alpha=.18)
        ax.ticklabel_format(axis="x", style="sci", scilimits=(3, 3))
    axes[0][-1].legend(fontsize=7, frameon=False)
    fig.tight_layout()
    fig.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def build_report(research_dir, evaluation_dir, exact_dir, output):
    """Write a ten-page Chinese PDF and adjacent audit/CSV after validation."""
    data = load_report_evidence(research_dir, evaluation_dir, exact_dir)
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Image
    from pypdf import PdfReader

    font_path = Path("C:/Windows/Fonts/simhei.ttf")
    if not font_path.exists():
        raise RuntimeError("Chinese report font missing: C:/Windows/Fonts/simhei.ttf")
    pdfmetrics.registerFont(TTFont("AI4MathChinese", str(font_path)))
    font = "AI4MathChinese"
    styles = getSampleStyleSheet()
    for style in styles.byName.values():
        style.fontName = font
    styles.add(ParagraphStyle(name="ChineseBody", fontName=font, fontSize=9.3, leading=15, spaceAfter=8, wordWrap="CJK", textColor=colors.HexColor("#263238")))
    styles.add(ParagraphStyle(name="ChineseSmall", fontName=font, fontSize=7.2, leading=11, spaceAfter=4, wordWrap="CJK"))
    styles.add(ParagraphStyle(name="ChineseTitle", fontName=font, fontSize=24, leading=35, spaceAfter=24, textColor=colors.HexColor("#164f66")))
    styles.add(ParagraphStyle(name="ChineseHeading", fontName=font, fontSize=16, leading=23, spaceAfter=16, textColor=colors.HexColor("#164f66")))
    styles.add(ParagraphStyle(name="ChineseSub", fontName=font, fontSize=11, leading=17, spaceBefore=9, spaceAfter=7, textColor=colors.HexColor("#176b87")))
    styles.add(ParagraphStyle(name="ChineseFormula", fontName=font, fontSize=11, leading=20, alignment=TA_CENTER, spaceAfter=10))

    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    figure_dir = output.parent / f"{output.stem}_figures"
    figure_dir.mkdir(parents=True, exist_ok=True)
    profile_chart, convergence_chart = figure_dir / "profile.png", figure_dir / "convergence.png"
    _chart_profile(data, profile_chart)
    _chart_convergence(data, convergence_chart)
    story = []
    def p(text, style="ChineseBody"):
        return Paragraph(escape(_text(text, 5000)).replace("\n", "<br/>"), styles[style])
    def add(text, style="ChineseBody"):
        story.append(p(text, style))
    def title(number, text):
        if story:
            story.append(PageBreak())
        add(f"{number:02d}  {text}", "ChineseHeading")
    def table(rows, widths=None, size=7.6):
        cells = [[p(_text(c, 250), "ChineseSmall") for c in row] for row in rows]
        t = Table(cells, colWidths=widths, repeatRows=1, hAlign="LEFT")
        t.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#e8f1f5")),
            ("VALIGN", (0,0), (-1,-1), "TOP"),
            ("LEFTPADDING", (0,0), (-1,-1), 5), ("RIGHTPADDING", (0,0), (-1,-1), 5),
            ("TOPPADDING", (0,0), (-1,-1), 4), ("BOTTOMPADDING", (0,0), (-1,-1), 4),
            ("LINEBELOW", (0,0), (-1,0), .7, colors.HexColor("#b0c8d3")),
            ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#f6f8f9")]),
        ]))
        story.append(t)
        story.append(Spacer(1, 9))

    manifests, research, runs = data["manifests"], data["research"], data["runs"]
    rounds = research["rounds"]
    complete = [x for x in data["profiles"] if x.get("exact")]
    statistics_rows = _statistics(runs)
    research_manifest = manifests["research"]
    title(1, "研究智能体与实际运行摘要")
    add("面向低自相关二值序列问题的研究智能体", "ChineseTitle")
    add("不平衡能量谱、反例检验与自适应搜索", "ChineseSub")
    add("课程项目 / 证据驱动报告 / 文献核查 2026-10-09（Asia/Shanghai）")
    add(f"研究运行模式：{data['mode']}。运行 ID：{research_manifest.get('run_id', 'unknown')}。")
    if data["mode"] != "live":
        add("本报告对应离线接线或重放，不能作为新的真实模型研究运行。图表仍来自此模式保存的实际工具产物。")
    table([["实际完成项", "数量与证据来源"],
           ["研究轮次", f"{len(rounds)}，research/state.json 与 rounds/*.json"],
           ["已保存命题", f"{len(research['hypotheses'])}，hypotheses"],
           ["工具证据", f"{len(research['evidence'])}，evidence"],
           ["完整精确长度", ", ".join(str(x['n']) for x in complete)],
           ["正式对照运行", f"{len(runs)}，evaluation/runs.json"],
           ["搜索候选总评价", str(sum(r['result']['evaluations'] for r in runs))]], [150, 345])
    add("结果定位", "ChineseSub")
    add("系统展示提出命题、真实工具执行、独立核验和反馈修订。小长度精确值是复现；较大长度结果是本次预算内可行上界。基础引理、有限验证、反例、上下界认证和经验结果分开呈现。")
    add("原始渐近 merit factor 问题仍未解决。本项目没有完成逐长度外部纪录与见证审计，不作算法原创、世界纪录或较大长度全局最优声明。")

    title(2, "数学问题与文献定位")
    add("设 s 为长度 n 的 ±1 序列。非周期自相关与能量定义如下。目标是在全体二值序列中降低能量；固定不平衡程度和 skew 都只是辅助条件类。")
    add("C_k = Σ_{i=0}^{n-k-1} s_i s_{i+k}    (k=1,…,n-1)", "ChineseFormula")
    add("E(s) = Σ_k C_k² ;    F(s) = n² / (2E(s))", "ChineseFormula")
    add("b = |Σ_i s_i| ;    g_n(b) = min_{|Σs_i|=b} E(s)", "ChineseFormula")
    add("E*_n = min_b g_n(b) ;    b ≡ n (mod 2), 0 ≤ b ≤ n", "ChineseFormula")
    add("课程流程来源", "ChineseSub")
    add("本地 Moonshine 课件第 5、9-11、31-33 页强调状态循环、猜想/证明/反例切换、假设与计算核验及可回溯产物。本项目采用轻量自建控制器；用户执行方案中的测试例和默认预算没有当成完成结果。")
    table([["文献 ID", "一手结论与本项目边界"],
           ["REF01 / Jedwab 作者页", "渐近问题背景及 Littlewood 关联。"],
           ["REF02 / Packebusch-Mertens 2016 v2", "论文报告 n≤66 全局、n≤119 skew 精确结果；重算小长度是复现。"],
           ["REF03 / Jedwab-Katz-Schmidt 2013 v2", "大于 6.34 的渐近构造已有严格结果；超过 6 不是新目标。"],
           ["REF04 / Zhang 等 2025 v2", "GPU memetic tabu 和非受限优于部分 skew 最优已有先例。"],
           ["REF05 / Pšeničnik 等 2026 v1", "分区资源调度与 skew 后解除限制已有先例。"]], [170,325])
    add("所有来源于 2026-10-09 访问；精确 URL、版本及页面日期异常见 docs/references.bib 与 docs/provenance.md。检索不声称穷尽最新文献。")

    title(3, "基础恒等式与松弛证明")
    add("Littlewood 恒等式", "ChineseSub")
    add("令 P(z)=Σ_i s_i z^i。在单位圆上，|P(z)|²=n+Σ_k C_k(z^k+z^-k)。将其平方后积分，非零幂项消失，常数项为 n²+2Σ_kC_k²，因此：")
    add("∫_0^1 |P(exp(2πit))|⁴ dt = n² + 2E(s)", "ChineseFormula")
    add("由 (Σs_i)²=n+2Σ_kC_k 得 Σ_kC_k=(b²-n)/2。每个 C_k 与 n-k 同奇偶且 |C_k|≤n-k，故 E≥floor(n/2)，E≡floor(n/2) (mod 4)。Cauchy-Schwarz 还给出 E≥(b²-n)²/[4(n-1)]；整数下界用精确有理数向上取整。")
    add("整数松弛", "ChineseSub")
    add("令 ℓ_k=n-k，A=(b²-n)/2。L_n(b) 是在 Σc_k=A、c_k∈{-ℓ_k,-ℓ_k+2,…,ℓ_k} 下最小化 Σc_k² 的值。真实相关向量可行，因此 L≤g；同类真实序列给出 U，故 L≤g≤U。松弛向量 c 未必能由序列实现。")
    add("从 c_k=-ℓ_k 起，需要 T=(A+Σℓ_k)/2 次增加 2。边际代价 (c+2)²-c²=4c+4，同一坐标的后续代价增加 8。heap 每次选最小可用代价。")
    add("交换论证", "ChineseSub")
    add("每个坐标必须选择递增边际代价列表的一个前缀。全体 T 个最小代价天然满足前缀条件。若另一可行分配选了较大代价并遗漏较小代价，交换一个末尾已选与另一个首个未选操作不会增大目标；反复交换得到 heap 分配。这证明松弛最优，属于基础工具引理。")
    add("独立证书检查：最大已选边际代价 max 4(c_k-1) 不大于最小未选代价 min 4(c_k+1)，同时检查整数、总和、奇偶、范围与平方和。E=L 仅认证同类；全局认证还需全局有效下界。")

    title(4, "运行架构与后端证据")
    table([["阶段", "职责与保存产物"],
           ["proposer", "读取问题、预算及历史反馈，输出受 schema 约束的数学行动。"],
           ["controller / ToolRouter", "校验量词、参数、约束与硬预算；调用注册数学工具。"],
           ["独立 verifier", "Python 整数复算见证、检查证书及完整枚举；不调用搜索评价器。"],
           ["skeptic", "读取实际证据审查范围；公开摘要写入下一轮反馈。"],
           ["持久状态与报告", "state、rounds、manifest、frozen_policy；报告只读实际 JSON。"]], [125,370])
    backend = research_manifest.get("backend", research_manifest.get("backend_metadata", {}))
    add(f"实际后端：{_text(backend, 1800)}", "ChineseSmall")
    metadata_fields = ("auth_method", "cli_version", "requested_model", "effective_model", "provider_request_count", "backend_call_attempts", "termination_reason", "start", "end")
    table([["manifest 字段", "实际记录"]] + [[k, _text(research_manifest.get(k), 330)] for k in metadata_fields], [165,330])
    add("CLI 进程启动次数与 provider 内部请求数分别记录；不可观测项显示 unknown。dry_run/replay 不升级为 live；skeptic 审查不等于数学证明。全部公开决策摘要和可获得 usage 见原始日志。")
    add(f"实际研究账本：{_text(research_manifest.get('budget', research.get('budget')), 1600)}", "ChineseSmall")
    add(f"源码树 SHA-256：{research_manifest.get('source_tree_hash', 'unknown')}\n独立核验代码 SHA-256：{research_manifest.get('verification_code_hash', 'unknown')}", "ChineseSmall")

    title(5, "实际研究轨迹与反馈修订")
    add("下表只包含已保存轮次。每条完整行动、工具输入/输出、核验、审查与预算前后状态可由轮次文件恢复。预核对教学实例的重新计算属于复现。")
    trajectory = [["轮次", "行动 / 命题", "证据", "公开决策依据（摘要）"]]
    for r in rounds:
        action = r.get("action", r.get("validated_action", {}))
        trajectory.append([r["round_index"], f"{action.get('action_type')} / {action.get('claim_id') or '-'}", r.get("evidence_id") or "-", _text(action.get("decision_summary"), 150)])
    table(trajectory, [35,125,58,277])
    if rounds:
        selected = next((r for r in rounds if r.get("action", {}).get("action_type") == "revise"), rounds[-1])
        action = selected.get("action", selected.get("validated_action", {}))
        add(f"轮次 {selected['round_index']} 的实际反馈", "ChineseSub")
        add(_text(selected.get("feedback", selected.get("skeptic")), 950), "ChineseSmall")
        add(f"下一行动预期信息：{_text(action.get('expected_information'), 500)}", "ChineseSmall")
    add("反馈驱动变化是否达到课程目标，以原始决策理由和前轮证据为准；未发生的反例、模型调用或研究修订没有补入时间线。")

    title(6, "小长度精确能量谱")
    add("完整结果使用全局取反约简，首符号固定 +1，遍历 2^(n-1) 个代表；绝对 b 保留。交替变号不用于条件类合并。报告复算见证，并检查绑定到 profile hash 的独立完整枚举证据。")
    story.append(Image(str(profile_chart), width=495, height=165))
    add("图：实际 profile JSON 的 g_n(b)；虚线仅在存在已保存有效证书时绘制 L_n(b)。此处 n=4、6、13 若存在均为已知教学数据的复现。", "ChineseSmall")
    profile_rows = [["n", "全局 E*", "最优 b", "代表遍历数", "状态 / evidence ID"]]
    for prof in data["profiles"]:
        profile_rows.append([prof["n"], prof.get("optimum_E") if prof.get("exact") else "未认证", ",".join(map(str, prof.get("optimal_b", []))), f"{prof['visited']}/{prof['total_states']}", f"{'exact' if prof.get('exact') else 'incomplete'} / {prof['evidence_id']}"])
    table(profile_rows, [27,53,65,95,255])

    title(7, "命题状态、见证与上下界认证")
    claim_rows = [["命题", "量词 / 域 / 内容", "当前状态"]]
    for cid, h in research["hypotheses"].items():
        hypothesis = h.get("hypothesis", {})
        claim_rows.append([cid, f"{hypothesis.get('quantifier')} / {_text(hypothesis.get('domain'), 90)}\n{_text(hypothesis.get('text'), 250)}", STATUS_CN.get(h.get("status"), h.get("status", "unknown"))])
    table(claim_rows, [50,350,95])
    certifications = []
    for prof in complete:
        for row in prof["strata"]:
            bound = data["bounds"].get((prof["n"], row["b"]))
            if bound and bound["L"] == row["E"]:
                certifications.append((prof, row, bound))
    add("实际上下界匹配实例", "ChineseSub")
    table([["n,b", "L = U = E", "证据 ID"]] + [[f"{prof['n']},{row['b']}", row["E"], f"{prof['evidence_id']}; {bound['evidence_id']}"] for prof,row,bound in certifications[:10]], [70,100,325])
    chosen = next((c for c in certifications if c[0]["n"] == 6 and c[1]["b"] == 4), certifications[0] if certifications else None)
    if chosen:
        prof, row, bound = chosen
        witness = row["witness"]
        add(f"认证见证 n={prof['n']}, b={row['b']}：s={_text(witness['sequence'],500)}；C={_text(witness['C'],500)}；E={witness['E']}；F={witness['F_numerator']}/{witness['F_denominator']}。证书 c={_text(bound['c'],500)}。", "ChineseSmall")
    else:
        add("当前输入没有上下界匹配证据，不能补写条件最优认证。")
    add("反例必须满足命题前提；有关所有最优序列的命题还须最优性认证和正确的对称轨道覆盖。搜索没有找到反例只提供经验信息。每类一个最优见证不足以描述整个最优集合。")

    title(8, "冻结策略与同预算收敛")
    add(f"冻结策略：{_text(data['policy'], 1600)}", "ChineseSmall")
    evaluation_manifest = manifests["evaluation"]
    add(f"正式配置：{_text(evaluation_manifest.get('config'), 1600)}", "ChineseSmall")
    add("random 为独立随机采样；fixed_tabu 为 unrestricted 多起点强基线；static_mix 固定比例 skew 后解除限制；agent_policy 执行研究产生的冻结策略。正式策略运行不增加在线模型研究轮数。共同评价核心和候选扣费规则控制计算资源。")
    story.append(Image(str(convergence_chart), width=495, height=170))
    add("图：全部已保存种子的中位 best-so-far E，按实际曲线阶梯保持；各组共同可用预算范围内比较，不延伸中断运行的未知结果。", "ChineseSmall")
    table([["n", "方法", "次数", "best E", "median E", "median F", "median 秒"]] + [[r["n"],r["method"],r["count"],r["best_E"],r["median_E"],f"{r['median_F']:.4f}",f"{r['median_seconds']:.2f}"] for r in statistics_rows], [28,105,32,58,70,83,119])
    add("本表为本次矩阵的描述性结果；少量种子不支持普遍优势。负结果和较差策略保留。", "ChineseSmall")

    title(9, "完整逐种子结果与配对比较")
    by_pair = defaultdict(dict)
    for run in runs:
        by_pair[(run["n"],run["seed"])][run["method"]] = run
    seed_rows = [["n / seed"] + [f"{m}\nE / F" for m in METHODS]]
    for (n, seed), members in sorted(by_pair.items()):
        seed_rows.append([f"{n} / {seed}"] + [f"{members[m]['result']['best']['E']} / {members[m]['result']['best']['F']:.4f}" if m in members else "缺少运行" for m in METHODS])
    table(seed_rows, [65,107,107,107,109])
    add("每个单元格的 evidence ID 为 EVAL:n:seed:method，对应 runs.json 同一行。全部 60 行或实际输入行的 n、seed、method、E、精确 F 分子/分母、b、候选评价数、时间和见证 hash 同时导出为相邻 CSV。", "ChineseSmall")
    comparisons = [["n", "配对样本", "agent 比 fixed 胜 / 平 / 负", "median(E_agent-E_fixed)"]]
    for n in sorted({r["n"] for r in runs}):
        diffs = [members["agent_policy"]["result"]["best"]["E"]-members["fixed_tabu"]["result"]["best"]["E"] for (length,seed),members in by_pair.items() if length==n and "agent_policy" in members and "fixed_tabu" in members]
        comparisons.append([n,len(diffs),f"{sum(x<0 for x in diffs)} / {sum(x==0 for x in diffs)} / {sum(x>0 for x in diffs)}",statistics.median(diffs) if diffs else "缺少配对"])
    table(comparisons, [45,75,220,155])
    costs = [r["result"]["evaluations"] for r in runs]
    add(f"已保存正式搜索成本为 {sum(costs)} 次候选评价，单 run 范围 {min(costs)}-{max(costs)}。完整矩阵是否完成及停止原因以 evaluation manifest 为准：{_text(evaluation_manifest.get('termination_reason'),250)}。")
    add("初始化、presearch、扰动、重复和已评分 tabu 邻居均属于候选成本；完整 n 邻域扫描计 n 次。核验复算、精确枚举、下界和模型等待单列，不能借核验免费探索候选。")

    title(10, "局限、复现与证据索引")
    add("本项目完成范围", "ChineseSub")
    add(f"该报告从 {len(rounds)} 个保存轮次、{len(research['evidence'])} 个研究证据、{len(complete)} 个完整长度和 {len(runs)} 个正式 run 重建。数值均可追溯；未完成模式、缺少配对与未认证结论明确标注。没有解决原始无限长度开放问题。")
    add("结构松弛可能很弱，松弛 c 不一定可实现；skew 或固定 b 的最优不等于全局最优；本次预算与少量种子限制外推；策略来源和评价数据必须保持分离。若看过留出数据再改策略，原矩阵属于开发/复评，新的泛化结论需要新长度与种子。")
    add("复现", "ChineseSub")
    add(f"已保存研究目录：{directories_text(data['directories']['research'])}\n正式对照目录：{directories_text(data['directories']['evaluation'])}\n精确结果目录：{directories_text(data['directories']['exact'])}", "ChineseSmall")
    add("重建报告：ai4math report --research <research目录> --evaluation <evaluation目录> --exact <exact目录> --output <PDF路径>。命令无需新模型调用；重新 live 研究须配置实际后端并重新执行研究命令。具体安装及 CLI 参数以仓库 README 和 --help 为准。", "ChineseSmall")
    add("哈希与核验", "ChineseSub")
    add("相邻 audit.json 保存输入 manifest 的 SHA-256、全部核验条目、字体路径、PDF 页数和 PDF hash。完整产物索引为三个 manifest.artifacts；原始 JSON 给出完整见证与曲线。报告验证失败时不生成 PDF。", "ChineseSmall")
    for kind,path in data["directories"].items():
        add(f"{kind} manifest SHA-256：{file_hash(path / 'manifest.json')}", "ChineseSmall")
    add("一手文献（完整 BibTeX 见 docs/references.bib）", "ChineseSub")
    for ref in [
        "REF01 Jonathan Jedwab. The Merit Factor Problem. https://www.sfu.ca/~jed/Research/merit.html",
        "REF02 Packebusch T, Mertens S. Low Autocorrelation Binary Sequences. J Phys A 49, 165001 (2016). arXiv:1512.02475v2.",
        "REF03 Jedwab J, Katz DJ, Schmidt KU. Advances in the merit factor problem for binary sequences. JCTA 120, 882-906 (2013). arXiv:1205.0626v2.",
        "REF04 Zhang Z et al. New Improvements in Solving Large LABS Instances Using Massively Parallelizable Memetic Tabu Search (2025). arXiv:2504.00987v2.",
        "REF05 Pšeničnik B et al. Prioritizing Search Space Regions in the Low Autocorrelation Binary Sequences Problem (2026). arXiv:2607.09688v1.",
    ]:
        add(ref, "ChineseSmall")
    add("源码仓库：https://github.com/ZJ4433MR/AI4Math。报告不据仓库 URL 推断上传成功；实际 commit 与提交状态见最终交付记录。", "ChineseSmall")

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#b0c8d3"))
        canvas.line(50, 48, A4[0]-50, 48)
        canvas.setFont(font, 7)
        canvas.setFillColor(colors.HexColor("#58707b"))
        canvas.drawString(50, 34, f"AI4Math LABS / {data['mode']} / 证据驱动报告")
        canvas.drawRightString(A4[0]-50, 34, str(doc.page))
        canvas.restoreState()
    doc = SimpleDocTemplate(str(output), pagesize=A4, rightMargin=50, leftMargin=50, topMargin=48, bottomMargin=61,
                            title="面向低自相关二值序列问题的研究智能体", author="AI4Math course project")
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    reader = PdfReader(str(output))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    _assert(8 <= len(reader.pages) <= 12, f"PDF page count {len(reader.pages)} outside 8-12")
    _assert("研究智能体" in text and data["mode"] in text, "PDF text extraction missing Chinese or mode")
    csv_path = output.with_suffix(".runs.csv")
    with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["evidence_id","n","seed","method","E","F_numerator","F_denominator","F","b","evaluations","elapsed_seconds","witness_hash"])
        for run in sorted(runs,key=lambda r:(r["n"],r["seed"],r["method"])):
            r,b = run["result"],run["result"]["best"]
            writer.writerow([run["evidence_id"],run["n"],run["seed"],run["method"],b["E"],b["F_numerator"],b["F_denominator"],b["F"],b["b"],r["evaluations"],r.get("elapsed",r.get("wall_seconds")),b["hash"]])
    audit = {"mode":data["mode"],"input_manifests":{kind:{"path":str(path / "manifest.json"),"sha256":file_hash(path / "manifest.json")} for kind,path in data["directories"].items()},
             "checks":data["checks"],"rounds":len(rounds),"evaluation_rows":len(runs),"font_path":str(font_path),"page_count":len(reader.pages),
             "pdf_sha256":file_hash(output),"csv_sha256":file_hash(csv_path),"limitations":["No asymptotic problem solution", "No world-record claim", "Visual QA must inspect rendered pages"]}
    write_json(output.with_suffix(".audit.json"),audit)
    return output


def directories_text(path):
    """Use compact relative directory names in the page, full paths in audit."""
    parts = Path(path).parts
    return "/".join(parts[-3:])
