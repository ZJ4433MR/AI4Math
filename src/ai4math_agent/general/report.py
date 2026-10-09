"""Honest, self-contained reports for the general mathematical workflow."""
from __future__ import annotations

import html
import json
from pathlib import Path
from urllib.parse import urlparse

from ai4math_agent.storage import file_hash, read_json, seal_manifest, validate_manifest, write_json


LEVELS = {
    "proposed": "已提出，尚未验证",
    "proof_candidate": "证明草稿，尚未认证",
    "proof_draft": "证明草稿，尚未认证",
    "finite_domain_verified": "声明的有限域内计算验证",
    "computationally_verified": "计算核验，范围以工具证据为准",
    "symbolically_verified": "声明假设内的符号核验",
    "symbolic_verified": "声明假设内的符号核验",
    "empirical_supported": "样本经验支持，不能作为一般证明",
    "refuted": "反例或完整有限域检查反驳；范围与前提见证据",
    "counterexample_found": "已记录反例，前提与复算见证见证据",
    "formal_verified": "已记录形式核验，须检查形式化与原命题的对应",
    "formally_verified": "已记录形式核验，须检查形式化与原命题的对应",
    "unresolved": "当前证据不足，未解决",
    "unsupported": "工具尚不支持此命题",
    "symbolic_identity_verified": "形式表达式的符号恒等核验；语义对应另行审查",
    "induction_verified": "形式归纳证书核验；语义对应另行审查",
    "bound_certificate": "下界证书核验；范围和前提见工具证据",
    "empirical_unverified": "未经独立核验的经验产物，不是证明",
    "empirical": "经验样本观察，不是一般证明",
    "invalid_certificate": "证书无效，未获认证",
    "invalid_input": "输入不合法，未执行有效核验",
    "tool_error": "工具失败，没有有效数学结论",
    "action_rejected": "行动被拒绝，没有执行有效实验",
    "formal_certificate_available": "形式化表述已有核验产物；原自然语言命题尚未认证",
    "formal_counterexample_available": "形式化表述已有反例或有限域反驳产物；原命题前提对应仍须审查",
    "formalization_mismatch": "形式化可能不对应原命题，不得据此认证原命题",
}


def proof_level(status):
    if isinstance(status, dict):
        status = status.get("status", status.get("kind", "unresolved"))
    status = str(status or "unresolved")
    return LEVELS.get(status, f"记录状态 {status}；核验强度尚需审查")


def _text(value):
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, indent=2)
    return "未记录" if value is None else str(value)


def _e(value):
    return html.escape(_text(value), quote=True)


def alignment_notice(claim):
    alignment = claim.get("semantic_alignment", {})
    opinion = alignment.get("model_review") if isinstance(alignment,dict) else alignment
    if opinion is False:
        return "模型审查认为形式化与原命题不对应；形式工具通过也不能认证原命题。此对应判断本身仅是模型意见。" + (" 原因："+str(alignment.get("flaw")) if isinstance(alignment,dict) and alignment.get("flaw") else "")
    if opinion is True:
        return "模型审查认为形式化与原命题对应；这只是模型意见，不是语义对应的独立证明。"
    return "原命题与形式化表述的语义对应尚未独立认证；工具核验只适用于其明确声明的形式对象和前提。"


def _sources(value, result=None):
    result = [] if result is None else result
    if isinstance(value, dict):
        url = value.get("url", value.get("source_url", value.get("link")))
        if isinstance(url, str) and urlparse(url).scheme in {"https", "http"}:
            title = str(value.get("title", value.get("name", url)))
            record = {"title": title, "url": url}
            if record not in result:
                result.append(record)
        for nested in value.values():
            _sources(nested, result)
    elif isinstance(value, list):
        for nested in value:
            _sources(nested, result)
    return result


def _hypotheses(state):
    values = state.get("hypotheses", [])
    return [{"id": key, **value} for key, value in values.items()] if isinstance(values, dict) else values


def build_general_report(run_dir):
    """Build report.md and report.html from a sealed run, return the HTML path.

    This function is offline. It does not call a model, reconstruct missing
    rounds, or certify a natural-language proof. Reports are added to the run
    manifest after generation; the input snapshot hash is recorded separately.
    """
    directory = Path(run_dir).resolve()
    manifest = validate_manifest(directory)
    if manifest.get("mode") not in {"live", "dry_run", "replay"}:
        raise ValueError("general report requires a research run mode")
    if "state.json" not in manifest["artifacts"]:
        raise ValueError("state.json is not sealed")
    state = read_json(directory / "state.json")
    if not isinstance(state.get("problem"), dict):
        raise ValueError("this is not a general mathematical research session")
    if state.get("termination_reason") == "running" or manifest.get("termination_reason") == "running":
        raise ValueError("run is still active; report only completed/interrupted evidence")
    problem = state["problem"]
    rounds, evidence = state.get("rounds", []), state.get("evidence", [])
    if not isinstance(rounds, list) or not isinstance(evidence, list):
        raise ValueError("invalid research history")
    evidence_ids = [e.get("id") for e in evidence]
    if len(set(evidence_ids)) != len(evidence_ids) or any(not isinstance(e, str) for e in evidence_ids):
        raise ValueError("invalid or duplicate evidence IDs")
    indexes = set()
    for round_ in rounds:
        index = round_.get("index", round_.get("round_index"))
        if not isinstance(index, int) or index in indexes:
            raise ValueError("invalid or duplicate research round")
        indexes.add(index)
        if round_.get("evidence_id") and round_["evidence_id"] not in evidence_ids:
            raise ValueError("research round references missing evidence")
        if any(e not in evidence_ids for e in round_.get("action", {}).get("evidence_ids", [])):
            raise ValueError("action references missing evidence")
    hypotheses = _hypotheses(state)
    audit_path = directory / "report_audit.json"
    if audit_path.is_file() and (directory/"report.html").is_file() and (directory/"report.md").is_file():
        old = read_json(audit_path)
        if old.get("state_sha256") == file_hash(directory/"state.json") and old.get("reporter_sha256") == file_hash(Path(__file__)) and old.get("mode") == manifest["mode"]:
            return directory / "report.html"
    mode, title = manifest["mode"], problem.get("title", "数学研究")
    source_manifest_hash = file_hash(directory / "manifest.json")
    md = [f"# {_text(title)}", "", f"运行模式：**{mode}**。工作流：{manifest.get('workflow', 'general-v1')}。", "",
          f"停止状态：{state.get('termination_reason', manifest.get('termination_reason', '未记录'))}。",
          f"实际保存 {len(rounds)} 轮、{len(evidence)} 条工具证据、{len(hypotheses)} 条命题。", ""]
    if mode != "live":
        md += ["本次是离线接线或重放，不是新的真实模型数学研究。", ""]
    md += ["## 问题、前提与目标", "", _text(problem.get("statement")), "",
           f"前提：{_text(problem.get('assumptions', []))}", "", f"目标：{_text(problem.get('goal'))}", "",
           "## 当前命题与证据强度", "",
           "自然语言证明草稿、计算样本、有限域穷举、符号核验与形式证明分开记录。模型审查不能代替数学证明。", ""]
    html_claims = []
    for claim in hypotheses:
        statement = claim.get("statement", claim.get("hypothesis", {}))
        level = proof_level(claim.get("status"))
        md += [f"### {claim.get('id', '未编号')}：{level}", "", _text(statement), "",
               f"父命题：{claim.get('parent_id') or '无'}；证据：{_text(claim.get('evidence_ids', []))}", "",
               f"形式产物状态：{proof_level(claim.get('formal_status'))}", "", f"核验范围：{_text(claim.get('verification_scope'))}", "",
               f"**语义对应提醒：{alignment_notice(claim)}**", ""]
        if claim.get("proof_drafts"):
            md += ["证明草稿（按保存原文列示，未自动升级为定理）：", "", "````json", _text(claim["proof_drafts"]), "````", ""]
        html_claims.append(f"<article><h3>{_e(claim.get('id'))} <span class='badge'>{_e(level)}</span></h3><p>{_e(statement)}</p><p class='notice'>{_e(alignment_notice(claim))}</p><p class='muted'>形式产物状态：{_e(proof_level(claim.get('formal_status')))}<br>父命题：{_e(claim.get('parent_id') or '无')} / 证据：{_e(claim.get('evidence_ids', []))}</p><details><summary>明确的核验范围</summary><pre>{_e(claim.get('verification_scope'))}</pre></details>" +
                           (f"<details><summary>保存的证明草稿（未自动认证）</summary><pre>{_e(claim['proof_drafts'])}</pre></details>" if claim.get("proof_drafts") else "") + "</article>")
    md += ["## 实际行动、核验反馈与修订", ""]
    html_rounds = []
    for round_ in rounds:
        action = round_.get("action", {})
        index = round_.get("index", round_.get("round_index"))
        review = round_.get("review", round_.get("skeptic"))
        md += [f"### 第 {index} 轮：{action.get('action_type', '未记录')}", "",
               f"行动依据：{_text(action.get('decision_summary'))}", "", f"预期信息：{_text(action.get('expected_information'))}", "",
               f"证据 ID：{round_.get('evidence_id') or '无'}", "", "审查与反馈（模型审查本身不是证明）：", "", "````json", _text(review), "````", "",
               "完整公开行动：", "", "````json", _text(action), "````", ""]
        html_rounds.append(f"<article><h3>第 {_e(index)} 轮 · {_e(action.get('action_type'))} <span class='badge'>{_e(round_.get('evidence_id') or '无工具证据')}</span></h3><p>{_e(action.get('decision_summary'))}</p><p class='muted'>预期信息：{_e(action.get('expected_information'))}</p><h4>模型审查与反馈（不是数学证明）</h4><pre>{_e(review)}</pre><details><summary>完整公开行动与预算</summary><pre>{_e({'action':action,'budget_after':round_.get('budget_after')})}</pre></details></article>")
    md += ["## 工具证据与来源", ""]
    html_evidence, sources = [], []
    for item in evidence:
        tool_level = proof_level(item.get("result",{}).get("status"))
        md += [f"### {item['id']} / {item.get('tool', '未记录')} / {tool_level}", "", "````json", _text(item), "````", ""]
        html_evidence.append(f"<details><summary>{_e(item['id'])} · {_e(item.get('tool'))} · {_e(tool_level)} · 命题 {_e(item.get('claim_id') or '无')}</summary><pre>{_e(item)}</pre></details>")
        _sources(item.get("result"), sources)
    if sources:
        md += ["原始来源链接（来自本次文献工具产物；链接存在本身不证明数学命题）：", ""]
        for source in sources:
            md.append(f"- [{source['title'].replace('[','').replace(']','')}]({source['url'].replace(')','%29')})")
        md.append("")
    budget = state.get("budget", manifest.get("budget", {}))
    md += ["## 资源、局限与复现", "", "````json", _text(budget), "````", "",
           "operations 是工具已记录的测量单位，不自动等于候选序列数或 CPU 指令；CAS 请求、枚举覆盖范围及中断分别解释。",
           "当前未解决命题、失败工具和负结果保留。没有发生的轮次没有补写；有限测试不能推广为一般定理。",
           "模型调用次数、可获得 usage、模型和源码版本以 manifest/calls 为准；未知 provider 请求数与费用不猜测。", "",
           f"运行目录：`{directory}`；状态：`state.json`；不可变轮次与调用：`rounds/`、`calls/`。",
           f"报告输入快照 manifest SHA-256：`{source_manifest_hash}`。", ""]
    if state.get("errors"):
        md += ["## 已保存错误", "", "````json", _text(state["errors"]), "````", ""]
    source_html = "".join(f"<li><a href='{html.escape(s['url'],quote=True)}' target='_blank' rel='noopener noreferrer'>{_e(s['title'])}</a></li>" for s in sources)
    css = """body{margin:0;background:#f3f6f8;color:#20313a;font:16px/1.65 'Microsoft YaHei',system-ui,sans-serif}main{max-width:980px;margin:40px auto;padding:0 24px 70px}h1{font-size:30px;color:#164f66}h2{margin-top:38px;border-bottom:1px solid #c7dbe4;padding-bottom:10px;color:#164f66}h3{font-size:18px}article,details{background:white;border:1px solid #d6e1e7;border-radius:9px;padding:18px;margin:14px 0}details article,article details{margin:10px 0}.badge{font-size:13px;padding:4px 8px;background:#e7f1f5;color:#176b87;border-radius:5px}.muted{color:#596e78;font-size:14px}p{white-space:pre-wrap;overflow-wrap:anywhere}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:13px/1.6 Consolas,monospace;background:#f6f8fa;padding:12px;border-radius:6px}a{color:#176b87}summary{cursor:pointer;font-weight:600}.notice{border-left:4px solid #dc7b29;background:#fff8ec;padding:14px}footer{font-size:13px;color:#596e78}li{overflow-wrap:anywhere}@media print{body{background:white}main{margin:0;max-width:none}details,article{break-inside:avoid}details>pre{display:block}}"""
    body = f"<header><p class='muted'>AI4Math · 通用数学研究工作流 · 模式 {_e(mode)}</p><h1>{_e(title)}</h1><p>停止状态：{_e(state.get('termination_reason',manifest.get('termination_reason')))}；实际 {_e(len(rounds))} 轮 / {_e(len(evidence))} 条工具证据。</p></header>"
    if mode != "live":
        body += "<p class='notice'>本次是离线接线或重放，不能当作新的真实模型研究。</p>"
    body += f"<h2>问题、前提与目标</h2><p>{_e(problem.get('statement'))}</p><h4>声明前提</h4><pre>{_e(problem.get('assumptions',[]))}</pre><h4>目标</h4><p>{_e(problem.get('goal'))}</p>"
    body += "<h2>当前命题与证据强度</h2><p class='notice'>自然语言证明草稿、经验样本、有限计算、符号核验与形式证明分开记录。模型审查不是独立数学证明。</p>" + ("".join(html_claims) or "<p>本次尚未保存明确命题。</p>")
    body += "<h2>实际行动、核验反馈与修订</h2>" + ("".join(html_rounds) or "<p>本次尚未完成研究轮次。</p>")
    body += "<h2>工具证据与来源</h2>" + ("".join(html_evidence) or "<p>尚无工具证据。</p>")
    if sources:
        body += "<h3>本次文献产物保存的原始链接</h3><p class='muted'>来源链接存在本身不证明命题；原文与适用条件仍须核查。</p><ul>" + source_html + "</ul>"
    body += f"<h2>资源与局限</h2><pre>{_e(budget)}</pre><p>operations 是工具已保存的测量单位；不是统一的序列候选数或 CPU 指令数。CAS 请求和枚举覆盖范围分别解释。负结果、失败与未解决命题保留；有限测试不能推广为一般定理。模型请求数与费用未知时不猜测。</p>"
    if state.get("errors"):
        body += f"<h3>保存的错误</h3><pre>{_e(state['errors'])}</pre>"
    body += f"<footer><p>运行目录：{_e(directory)}<br>状态与原始行动见 state.json、rounds/、calls/。此报告离线生成，不新增模型调用或研究轮次。<br>输入快照 manifest SHA-256：{_e(source_manifest_hash)}</p></footer>"
    md_path, html_path = directory / "report.md", directory / "report.html"
    md_path.write_text("\n".join(md), encoding="utf-8")
    html_path.write_text("<!doctype html><html lang='zh-CN'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>"+_e(title)+" · AI4Math</title><style>"+css+"</style><main>"+body+"</main></html>", encoding="utf-8")
    write_json(directory / "report_audit.json", {"mode":mode,"input_manifest_sha256":source_manifest_hash,"state_sha256":file_hash(directory/"state.json"),
        "reporter_sha256":file_hash(Path(__file__)),"markdown_sha256":file_hash(md_path),"html_sha256":file_hash(html_path),"rounds":len(rounds),"evidence":len(evidence),"proof_certification":"report does not upgrade tool or model conclusions"})
    manifest["reports"] = {"markdown":"report.md","html":"report.html","audit":"report_audit.json"}
    seal_manifest(directory, manifest)
    return html_path
