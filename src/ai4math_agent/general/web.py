"""Local process UI: starts real solve processes and reads actual run state."""
from __future__ import annotations

import ipaddress
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from ai4math_agent.storage import now, read_json, seal_manifest, validate_manifest, write_json
from .report import alignment_notice, build_general_report, proof_level


def _public(value):
    """Do not put authentication values or provider/private fields in the UI."""
    if isinstance(value, dict):
        hidden = {"api_key", "authorization", "access_token", "refresh_token", "password", "secret", "environment", "env", "reasoning", "hidden_reasoning"}
        return {str(k): _public(v) for k,v in value.items() if str(k).lower() not in hidden}
    if isinstance(value, list):
        return [_public(v) for v in value]
    if isinstance(value, str):
        value = re.sub(r"(?i)bearer\s+[A-Za-z0-9._-]+", "Bearer [REDACTED]", value)
        return re.sub(r"sk-[A-Za-z0-9_-]{20,}", "[REDACTED]", value)
    return value


class _App:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.token = secrets.token_urlsafe(32)
        self.jobs, self.lock = {}, threading.RLock()

    def sessions(self):
        result = []
        for kind in ("general", "research"):
            base = self.root / "results" / kind
            if not base.exists():
                continue
            for state_path in base.rglob("state.json"):
                directory = state_path.parent.resolve()
                if not directory.is_relative_to(base.resolve()) or not (directory / "manifest.json").is_file():
                    continue
                try:
                    manifest, state = read_json(directory / "manifest.json"), read_json(state_path)
                    problem = state.get("problem", {})
                    identifier = kind + "/" + directory.relative_to(base.resolve()).as_posix()
                    result.append({"id":identifier, "mode":manifest.get("mode", "unknown"), "workflow":manifest.get("workflow", "labs" if kind=="research" else "general-v1"),
                                   "title":problem.get("title", "LABS 研究（历史工作流）" if kind=="research" else "数学研究"),
                                   "termination_reason":state.get("termination_reason",manifest.get("termination_reason", "running")),
                                   "start":manifest.get("start"), "rounds":len(state.get("rounds",[])), "modified":state_path.stat().st_mtime})
                except (OSError, ValueError, TypeError):
                    continue
        return sorted(result,key=lambda x:x["modified"],reverse=True)

    def resolve(self, identifier):
        if not isinstance(identifier,str) or "\\" in identifier:
            raise ValueError("invalid session ID")
        parts = identifier.split("/")
        if len(parts)<2 or parts[0] not in {"general","research"} or any(p in {"", ".", ".."} for p in parts):
            raise ValueError("invalid session ID")
        base = (self.root / "results" / parts[0]).resolve()
        path = base.joinpath(*parts[1:]).resolve()
        if not path.is_relative_to(base) or not (path/"manifest.json").is_file() or not (path/"state.json").is_file():
            raise ValueError("session not found within results")
        return path

    def session(self, identifier):
        directory = self.resolve(identifier)
        manifest, state = read_json(directory/"manifest.json"), read_json(directory/"state.json")
        reason = state.get("termination_reason",manifest.get("termination_reason","running"))
        integrity = {"valid":None,"note":"进行中的写入快照；最终报告会校验文件哈希。"}
        if reason != "running":
            try:
                validate_manifest(directory)
                integrity = {"valid":True,"note":"产物与 manifest 哈希一致；哈希核验不等于数学证明。"}
            except (OSError, ValueError) as exc:
                integrity = {"valid":False,"note":str(exc)}
        hypotheses = state.get("hypotheses", [])
        if isinstance(hypotheses,dict):
            hypotheses = [{"id":k,**v} for k,v in hypotheses.items()]
        for h in hypotheses:
            h["proof_level_label"] = proof_level(h.get("status"))
            h["formal_status_label"] = proof_level(h.get("formal_status"))
            h["alignment_notice"] = alignment_notice(h)
        for item in state.get("evidence",[]):
            item["proof_level_label"] = proof_level(item.get("result",{}).get("status")) if isinstance(item.get("result"),dict) else "工具状态未记录"
        config, budget = manifest.get("config",{}), state.get("budget",manifest.get("budget",{}))
        remaining = (len(state.get("rounds",[])) < config.get("max_rounds",0)
                     and budget.get("backend_attempts",0) < config.get("max_backend_attempts",0)
                     and budget.get("elapsed_seconds",0) < config.get("session_seconds",0)
                     and budget.get("operations",0) < config.get("max_operations",0))
        can_resume = identifier.startswith("general/") and reason in {"interrupted","backend_failed"} and remaining and integrity["valid"] is True
        resume_note = "保留原配置和累计账本，可以续跑。" if can_resume else ("资源预算已用尽，不能增加原预算续跑。" if not remaining else "仅中断或后端失败的通用会话可以续跑；完成会话保留原结论。")
        public = {"id":identifier,"mode":manifest.get("mode","unknown"), "workflow":manifest.get("workflow","labs" if identifier.startswith("research/") else "general-v1"),
                  "backend":manifest.get("backend",manifest.get("config",{}).get("backend")), "requested_model":manifest.get("requested_model",manifest.get("config",{}).get("model")),
                  "limits":manifest.get("config",{}),
                  "problem":state.get("problem",{"title":"LABS 研究（历史工作流）","statement":"这是已有的 LABS 专用研究记录；通用问题工作流不改写它。","assumptions":[],"goal":manifest.get("config",{}).get("problem_revision")}),
                  "hypotheses":hypotheses, "rounds":state.get("rounds",[]), "evidence":state.get("evidence",[]),
                  "budget":state.get("budget",manifest.get("budget",{})),"termination_reason":reason,"errors":state.get("errors",[]),
                  "integrity":integrity,"can_resume":can_resume,"resume_note":resume_note,
                  "has_report":(directory/"report.html").is_file()}
        return _public(public)

    @staticmethod
    def parameters(body):
        backend = body.get("backend","codex_cli")
        if backend not in {"codex_cli","api","dry_run"}:
            raise ValueError("unsupported backend")
        rounds = body.get("max_rounds",12)
        if isinstance(rounds,bool) or not isinstance(rounds,int) or not 1<=rounds<=40:
            raise ValueError("max_rounds must be an integer from 1 to 40")
        model = str(body.get("model") or "").strip()
        if len(model)>100 or (model and (model.startswith("-") or not re.fullmatch(r"[A-Za-z0-9._:/-]+",model))):
            raise ValueError("invalid model name")
        return backend,rounds,model

    def launch(self, body, resume=False):
        with self.lock:
            if any(job["process"].poll() is None for job in self.jobs.values()):
                raise RuntimeError("本页面已有后台研究运行；先读取它的状态或中断后再启动。")
            backend,rounds,model = self.parameters(body)
            job_id = uuid.uuid4().hex
            args = [sys.executable,"-m","ai4math_agent","solve","--backend",backend,"--max-rounds",str(rounds)]
            if model:
                args += ["--model",model]
            if resume:
                identifier = body.get("id")
                directory = self.resolve(identifier)
                if not identifier.startswith("general/"):
                    raise ValueError("LABS 历史会话只读；请使用原 research 命令续跑。")
                manifest = validate_manifest(directory)
                if not self.session(identifier)["can_resume"]:
                    raise ValueError(self.session(identifier)["resume_note"])
                config = manifest.get("config",{})
                original = manifest.get("backend",config.get("backend",backend))
                backend,rounds,model = original,config.get("max_rounds",rounds),config.get("model",model)
                args = [sys.executable,"-m","ai4math_agent","solve","--backend",backend,"--max-rounds",str(rounds),"--resume",str(directory)]
                if model:
                    args += ["--model",str(model)]
                for flag,key in (("--max-operations","max_operations"),("--session-seconds","session_seconds"),("--backend-timeout","backend_timeout")):
                    if key in config:
                        args += [flag,str(config[key])]
                output_root = directory.parent
                session_id = identifier
                previous_elapsed = read_json(directory/"state.json").get("budget",{}).get("elapsed_seconds",0)
            else:
                problem = body.get("problem")
                if not isinstance(problem,str) or not 5<=len(problem.strip())<=12000:
                    raise ValueError("请输入 5-12000 字符的数学主题或完整问题。")
                output_root = self.root/"results"/"general"/("ui-"+job_id)
                args += ["--problem",problem.strip()]
                session_id = None
                previous_elapsed = 0
            args += ["--output-root",str(output_root)]
            log_dir = self.root/"tmp"/"general_ui_logs"
            log_dir.mkdir(parents=True,exist_ok=True)
            log_path = log_dir/(job_id+".log")
            environment = os.environ.copy()
            environment["PYTHONIOENCODING"]="utf-8"
            environment["PYTHONUNBUFFERED"]="1"
            creationflags = getattr(subprocess,"CREATE_NO_WINDOW",0) if os.name=="nt" else 0
            with log_path.open("wb") as stream:
                process = subprocess.Popen(args,cwd=self.root,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,
                                           shell=False,env=environment,creationflags=creationflags,start_new_session=os.name!="nt")
            self.jobs[job_id] = {"process":process,"output_root":output_root,"session_id":session_id,"start":time.monotonic(),"previous_elapsed":previous_elapsed,
                                 "interrupted":False,"log_path":log_path,"backend":backend}
            return self.job(job_id)

    def job(self, job_id):
        with self.lock:
            if job_id not in self.jobs:
                raise ValueError("job not found")
            job = self.jobs[job_id]
            if not job["session_id"] and job["output_root"].exists():
                candidates = sorted(job["output_root"].rglob("state.json"))
                for path in candidates:
                    if (path.parent/"manifest.json").is_file():
                        job["session_id"] = "general/"+path.parent.relative_to(self.root/"results"/"general").as_posix()
                        break
            code = job["process"].poll()
            message = "实际后台进程运行中" if code is None else ("后台进程已中断；最后写入的状态仍保留，可审查后续跑。" if job["interrupted"] else "后台进程已结束")
            if code not in (None,0) and not job["interrupted"]:
                message = "后台进程失败；原始状态不升级为完成。请查看保存的错误或本地启动日志。"
            return {"job_id":job_id,"session_id":job["session_id"],"running":code is None,"exit_code":code,"interrupted":job["interrupted"],"message":message,
                    "elapsed_seconds":round(time.monotonic()-job["start"],1),"backend":job["backend"]}

    def stop(self, job_id):
        with self.lock:
            if job_id not in self.jobs:
                raise ValueError("job not found")
            job = self.jobs[job_id]
            if job["process"].poll() is None:
                if os.name=="nt":
                    killed = subprocess.run(["taskkill","/PID",str(job["process"].pid),"/T","/F"],capture_output=True,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0),timeout=20)
                    if killed.returncode and job["process"].poll() is None:
                        raise RuntimeError("未确认进程树停止，不能封存中断状态。")
                else:
                    import signal
                    os.killpg(job["process"].pid,signal.SIGTERM)
                job["process"].wait(timeout=5)
                self.job(job_id)  # Resolve the directory only after the writer exited.
                if job["session_id"]:
                    directory = self.resolve(job["session_id"])
                    manifest = read_json(directory/"manifest.json")
                    try:
                        validate_manifest(directory)
                        prior_integrity = "sealed snapshot matched"
                    except ValueError as exc:
                        prior_integrity = "Writer stopped between atomic state write and manifest sealing: "+str(exc)
                    state = read_json(directory/"state.json")
                    if state.get("termination_reason")=="running":
                        state["termination_reason"] = "interrupted"
                        elapsed = job["previous_elapsed"] + time.monotonic() - job["start"]
                        state["budget"]["elapsed_seconds"] = max(state["budget"].get("elapsed_seconds",0),elapsed)
                        state.setdefault("errors",[]).append({"time":now(),"event":"host_process_interrupted","error":"Local UI confirmed its process exited after explicit stop. Pending tools and all reserved budgets remain charged.","prior_snapshot_integrity":prior_integrity,"exit_code":job["process"].returncode,"process_elapsed_seconds":elapsed-job["previous_elapsed"]})
                        write_json(directory/"state.json",state)
                        manifest.update(termination_reason="interrupted",budget=state["budget"],end=now())
                        seal_manifest(directory,manifest)
                job["interrupted"] = True
            return self.job(job_id)


PAGE = r"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>AI4Math · 数学研究智能体</title><style>
:root{--ink:#20313a;--teal:#176b87;--line:#d5e1e7}*{box-sizing:border-box}body{margin:0;background:#f3f6f8;color:var(--ink);font:15px/1.6 'Microsoft YaHei',system-ui,sans-serif}header{background:#164f66;color:white;padding:28px max(24px,calc((100vw - 1200px)/2))}header h1{margin:0;font-size:27px}header p{margin:7px 0 0;opacity:.85}.layout{max-width:1240px;margin:25px auto;padding:0 20px;display:grid;grid-template-columns:350px 1fr;gap:24px}.panel,.card{background:white;border:1px solid var(--line);border-radius:10px;padding:20px;margin-bottom:18px}h2{margin:0 0 15px;font-size:20px;color:#164f66}h3{font-size:16px;margin:0 0 8px}textarea,input,select,button{font:inherit}textarea,input,select{width:100%;border:1px solid #b6cbd5;border-radius:6px;padding:10px;background:white}textarea{min-height:190px;resize:vertical}label{display:block;margin:13px 0 5px;font-weight:600;font-size:13px}.twocol{display:grid;grid-template-columns:1fr 1fr;gap:12px}button{border:0;border-radius:6px;background:var(--teal);color:white;padding:10px 15px;cursor:pointer;margin-top:15px}button.secondary{background:#e8f1f5;color:var(--teal)}button.danger{background:#a23d35}button:disabled{opacity:.4;cursor:default}.muted{color:#657781;font-size:13px}.status{border-left:4px solid #176b87;background:#edf5f8;padding:12px;margin:0 0 18px;white-space:pre-wrap}.badge{display:inline-block;padding:3px 7px;border-radius:5px;background:#e8f1f5;color:#176b87;font-size:12px;margin-right:5px}.warning{background:#fff4df;color:#80591d}.error{background:#fff0ee;color:#a23d35}.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:0 0 18px}.metric{background:white;border:1px solid var(--line);border-radius:8px;padding:14px}.metric b{font-size:23px;color:var(--teal);display:block}.timeline article{border-left:3px solid #80afc0;margin:0 0 18px;padding:0 0 0 18px}pre{font:12px/1.65 Consolas,monospace;white-space:pre-wrap;overflow-wrap:anywhere;background:#f6f8fa;padding:12px;border-radius:6px}p{white-space:pre-wrap;overflow-wrap:anywhere}details{margin-top:10px}summary{cursor:pointer;color:#176b87}.empty{padding:45px;text-align:center;color:#657781}a{color:#176b87}.tabs{display:flex;gap:8px;margin-bottom:18px}.tabs button{margin:0}.view[hidden]{display:none}.sessionline{font-size:12px;overflow-wrap:anywhere}.progress{height:6px;background:#dbe7ed;border-radius:5px;margin-bottom:18px}.progress div{height:100%;background:#176b87;border-radius:5px;transition:width .4s}#errors{color:#a23d35}@media(max-width:900px){.layout{grid-template-columns:1fr}.metrics{grid-template-columns:repeat(2,1fr)}}
</style></head><body><header><h1>AI4Math · 数学研究智能体</h1><p>输入数学主题，让模型规划、调用工具、审查证据并修订方向。页面显示实际后台运行和已保存过程。</p></header><main class="layout"><aside><section class="panel"><h2>发起研究</h2><label for="problem">数学主题或完整问题</label><textarea id="problem" maxlength="12000" placeholder="例如：研究 Pell 方程 x^2 - 2y^2 = 1 的整数解结构。提出明确猜想，尝试证明，并检验有限范围或反例。"></textarea><label for="backend">模型后端</label><select id="backend"><option value="codex_cli">Codex CLI · live</option><option value="api">已配置 API · live</option><option value="dry_run">dry_run · 离线接线</option></select><div class="twocol"><div><label for="model">模型名称</label><input id="model" value="gpt-6.1-sol" maxlength="100"></div><div><label for="rounds">最多研究轮数</label><input id="rounds" type="number" min="1" max="40" value="12"></div></div><p class="muted">凭证沿用本地登录或进程环境；页面不收集 API key。API 模型名须符合你的后端配置。失败会明确记录，不会自动改成 dry_run。</p><button id="start">启动实际研究</button><button id="stop" class="danger" disabled>中断当前进程</button><p id="launch" class="muted"></p></section><section class="panel"><h2>已保存会话</h2><select id="sessions"><option value="">选择已有研究</option></select><button id="refresh" class="secondary">刷新列表</button><button id="resume" class="secondary" disabled>续跑所选通用会话</button><p class="muted">历史会话保持原 mode 与工作流。LABS 专用历史可读取，通用流程不改写它。</p></section><section class="panel"><h3>结论怎么读</h3><p class="muted">证明草稿 ≠ 数学证明。样本支持、有限域验证、符号核验和形式证明分别展示。文献链接也不能替代证据核验。</p></section></aside><section><div id="runtime" class="status">尚未选择会话。可以发起新的实际研究，或读取已有记录。</div><div class="progress"><div id="progress" style="width:0"></div></div><div class="metrics"><div class="metric"><b id="metricRounds">0</b>已保存轮次</div><div class="metric"><b id="metricCalls">0</b>后端尝试</div><div class="metric"><b id="metricTools">0</b>工具调用</div><div class="metric"><b id="metricOps">0</b>测量 operations</div></div><section class="panel"><div id="problemTitle"><h2>问题与声明前提</h2></div><p id="statement" class="muted">研究开始后显示原始问题、目标和声明的假设。</p><details><summary>目标与前提</summary><pre id="assumptions"></pre></details><p id="integrity" class="muted"></p><button id="report" class="secondary" disabled>查看完整报告</button></section><div class="tabs"><button data-view="timeline">行动与反馈</button><button data-view="claims" class="secondary">命题与修订</button><button data-view="evidence" class="secondary">工具证据</button></div><section id="timeline" class="view panel"><div class="empty">暂无已保存轮次。</div></section><section id="claims" class="view panel" hidden></section><section id="evidence" class="view panel" hidden></section><section id="errors" class="panel" hidden></section></section></main><script>
const TOKEN=__TOKEN__;let selected='',jobId='',jobSession='',autoSelected=false,jobRunning=false,selectedData=null;const $=id=>document.getElementById(id);const pretty=v=>typeof v==='string'?v:JSON.stringify(v,null,2);function node(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=String(text);if(cls)n.className=cls;return n}function details(title,value){const d=node('details');d.append(node('summary',title),node('pre',pretty(value)));return d}async function api(path,body){const r=await fetch(path,{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json','X-AI4Math-Token':TOKEN}:{},body:body?JSON.stringify(body):undefined});const v=await r.json();if(!r.ok)throw new Error(v.error||'请求失败');return v}function params(){return {problem:$('problem').value,backend:$('backend').value,model:$('model').value,max_rounds:Number($('rounds').value)}}async function refreshSessions(){const rows=await api('/api/runs');const old=selected;const select=$('sessions');select.replaceChildren(node('option','选择已有研究'));select.firstChild.value='';for(const r of rows){const o=node('option',`${r.title} · ${r.mode} · ${r.rounds}轮 · ${r.termination_reason}`);o.value=r.id;select.append(o)}if(old)select.value=old}function render(data){selectedData=data;const live=data.mode==='live';$('runtime').replaceChildren(node('span',data.mode,'badge'+(live?'':' warning')),node('span',data.workflow,'badge'),node('span',data.termination_reason,'badge'),node('p',`${jobRunning&&jobSession===data.id?'所选会话的实际后台进程正在运行。':'显示所选会话已经写入磁盘的研究状态。'} ${live?'live 表示配置的真实模型后端；请结合实际调用与停止状态阅读。':'这是离线或重放记录，不能当作新的 live 研究。'}`),node('div',data.id,'sessionline'));$('metricRounds').textContent=data.rounds.length;$('metricCalls').textContent=data.budget.backend_attempts??data.budget.backend_call_attempts??0;$('metricTools').textContent=data.budget.tool_calls??data.evidence.length;$('metricOps').textContent=data.budget.operations??'单列';$('progress').style.width=Math.min(100,100*data.rounds.length/Math.max(1,Number(data.limits?.max_rounds||$('rounds').value)))+'%';$('problemTitle').replaceChildren(node('h2',data.problem.title||'数学研究'));$('statement').textContent=data.problem.statement||'未记录';$('assumptions').textContent=pretty({goal:data.problem.goal,assumptions:data.problem.assumptions});$('integrity').textContent=data.integrity.note+' '+data.resume_note;$('resume').disabled=!data.can_resume||jobRunning;$('report').disabled=(jobRunning&&jobSession===data.id)||data.termination_reason==='running'||data.integrity.valid!==true||data.workflow==='labs';const t=$('timeline');t.replaceChildren();for(const r of data.rounds){const a=r.action||{};const card=node('article');card.append(node('h3',`第 ${r.index??r.round_index} 轮 · ${a.action_type||'行动'} · ${r.evidence_id||'无工具证据'}`),node('p',a.decision_summary||'未保存决策摘要'));card.append(details('审查与反馈（模型审查不是数学证明）',r.review??r.skeptic??{}));card.append(details('行动、参数与预算',{action:a,budget_after:r.budget_after}));t.append(card)}if(!data.rounds.length)t.append(node('div','尚未完成研究轮次；后台可能正在等待模型或工具。','empty'));const c=$('claims');c.replaceChildren();for(const h of data.hypotheses){const card=node('article',undefined,'card');card.append(node('h3',h.id),node('span',h.proof_level_label,'badge'),node('p',pretty(h.statement??h.hypothesis??'')),node('p',`父命题：${h.parent_id||'无'}；证据：${pretty(h.evidence_ids||[])}`,'muted'));card.append(node('p',h.alignment_notice,h.semantic_alignment?.model_review===false?'status error':'status warning'));if(h.formal_status)card.append(node('p','形式工具状态：'+h.formal_status_label));if(h.verification_scope)card.append(details('核验对象与前提（不自动认证原命题）',h.verification_scope));if(h.proof_drafts?.length)card.append(details('证明草稿（不自动认证）',h.proof_drafts));card.append(details('完整已保存命题',h));c.append(card)}if(!data.hypotheses.length)c.append(node('div','尚未提出明确命题。','empty'));const e=$('evidence');e.replaceChildren();for(const item of data.evidence){const card=node('article',undefined,'card');card.append(node('h3',`${item.id} · ${item.tool}`),node('span',item.proof_level_label,'badge'),details('工具输入、结果及错误',item));e.append(card)}if(!data.evidence.length)e.append(node('div','尚无工具产物。','empty'));$('errors').hidden=!data.errors?.length;$('errors').replaceChildren(node('h3','保存的错误'),node('pre',pretty(data.errors||[])))}async function loadSelected(){if(selected)render(await api('/api/session?id='+encodeURIComponent(selected)))}async function tick(){try{if(jobId){const j=await api('/api/job?id='+encodeURIComponent(jobId));jobRunning=j.running;$('launch').textContent=`${j.message} · ${j.elapsed_seconds}秒`;$('stop').disabled=!j.running;$('start').disabled=j.running;jobSession=j.session_id||jobSession;if(j.session_id&&!autoSelected){selected=j.session_id;autoSelected=true;await refreshSessions()}if(!j.running){jobId='';await refreshSessions()}}await loadSelected()}catch(e){$('launch').textContent=e.message}}$('start').onclick=async()=>{try{$('start').disabled=true;const j=await api('/api/start',params());jobId=j.job_id;jobSession=j.session_id||'';autoSelected=false;jobRunning=j.running;$('launch').textContent=j.message;await tick()}catch(e){$('launch').textContent=e.message;$('start').disabled=false}};$('resume').onclick=async()=>{try{const body={...params(),id:selected,backend:selectedData.backend||$('backend').value};const j=await api('/api/resume',body);jobId=j.job_id;jobSession=j.session_id||'';autoSelected=false;jobRunning=j.running;await tick()}catch(e){$('launch').textContent=e.message}};$('stop').onclick=async()=>{try{if(jobId)await api('/api/stop',{job_id:jobId});await tick()}catch(e){$('launch').textContent=e.message}};$('refresh').onclick=()=>refreshSessions().catch(e=>$('launch').textContent=e.message);$('sessions').onchange=async()=>{selected=$('sessions').value;try{await loadSelected()}catch(e){$('launch').textContent=e.message}};$('report').onclick=()=>window.open('/api/report?id='+encodeURIComponent(selected),'_blank','noopener');document.querySelectorAll('[data-view]').forEach(b=>b.onclick=()=>{document.querySelectorAll('.view').forEach(v=>v.hidden=v.id!==b.dataset.view)});refreshSessions().catch(e=>$('launch').textContent=e.message);setInterval(tick,1500);
</script></body></html>"""


def serve_general(host="127.0.0.1", port=8765):
    """Serve the local UI until interrupted; CLI solve processes run separately."""
    if host != "localhost":
        try:
            if not ipaddress.ip_address(host).is_loopback:
                raise ValueError("the process UI binds only to localhost")
        except ValueError:
            raise ValueError("host must be a loopback address or localhost") from None
    if isinstance(port,bool) or not isinstance(port,int) or not 1<=port<=65535:
        raise ValueError("invalid local server port")
    app = _App(Path.cwd())
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,format,*args):
            # Do not echo problem text, query strings, or tokens to a console.
            return

        def allowed_host(self):
            header = self.headers.get("Host","").lower()
            return header in {f"127.0.0.1:{port}",f"localhost:{port}",f"[::1]:{port}"}

        def send(self,code,value,kind="application/json; charset=utf-8"):
            raw = (json.dumps(value,ensure_ascii=False).encode("utf-8") if kind.startswith("application/json") else value.encode("utf-8"))
            self.send_response(code)
            self.send_header("Content-Type",kind)
            self.send_header("Content-Length",str(len(raw)))
            self.send_header("Cache-Control","no-store")
            self.send_header("X-Content-Type-Options","nosniff")
            self.send_header("Referrer-Policy","no-referrer")
            self.send_header("Content-Security-Policy","default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            if not self.allowed_host():
                return self.send(403,{"error":"unrecognized localhost Host"})
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            identifier = query.get("id",[""])[0]
            try:
                if parsed.path=="/":
                    return self.send(200,PAGE.replace("__TOKEN__",json.dumps(app.token)),"text/html; charset=utf-8")
                if parsed.path=="/api/runs":
                    return self.send(200,app.sessions())
                if parsed.path=="/api/session":
                    return self.send(200,app.session(identifier))
                if parsed.path=="/api/job":
                    return self.send(200,app.job(identifier))
                if parsed.path=="/api/report":
                    if not identifier.startswith("general/"):
                        raise ValueError("use the existing LABS report for this historical workflow")
                    data = app.session(identifier)
                    if data["termination_reason"]=="running" or any(j["session_id"]==identifier and j["process"].poll() is None for j in app.jobs.values()):
                        return self.send(409,{"error":"研究仍在运行；最终状态封存后生成报告。"})
                    path = build_general_report(app.resolve(identifier))
                    return self.send(200,path.read_text(encoding="utf-8"),"text/html; charset=utf-8")
                return self.send(404,{"error":"not found"})
            except (OSError,ValueError,TypeError,KeyError) as exc:
                return self.send(400,{"error":_public(str(exc))})

        def do_POST(self):
            if not self.allowed_host() or not secrets.compare_digest(self.headers.get("X-AI4Math-Token",""),app.token):
                return self.send(403,{"error":"local session token required"})
            origin=self.headers.get("Origin")
            if origin and origin not in {f"http://127.0.0.1:{port}",f"http://localhost:{port}",f"http://[::1]:{port}"}:
                return self.send(403,{"error":"cross-origin action rejected"})
            try:
                length=int(self.headers.get("Content-Length","0"))
                if not 0<length<=100000:
                    raise ValueError("invalid request length")
                body=json.loads(self.rfile.read(length))
                if not isinstance(body,dict):
                    raise ValueError("JSON object required")
                route=urlparse(self.path).path
                if route=="/api/start":
                    return self.send(202,app.launch(body))
                if route=="/api/resume":
                    return self.send(202,app.launch(body,resume=True))
                if route=="/api/stop":
                    return self.send(200,app.stop(body.get("job_id")))
                return self.send(404,{"error":"not found"})
            except RuntimeError as exc:
                return self.send(409,{"error":str(exc)})
            except (OSError,ValueError,TypeError,KeyError,subprocess.SubprocessError) as exc:
                return self.send(400,{"error":_public(str(exc))})
    class Server(ThreadingHTTPServer):
        daemon_threads=True
        address_family=socket.AF_INET6 if ":" in host else socket.AF_INET
    server=Server((host,port),Handler)
    print(f"AI4Math local process UI: http://{'['+host+']' if ':' in host else host}:{port}",flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
