# LABS Research Agent

面向课程作业的数学研究智能体：模型提出命题、选择实验，宿主执行 LABS 数学工具，独立核验器复算，模型读取实际反馈后决定下一步。研究对象是低自相关二值序列，以及条件能量谱 `g_n(b)`。

## 安装

需要 Python 3.11+，默认仅使用 CPU。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m pytest -q
```

本机已配置 `.venv`，可直接使用 `.\.venv\Scripts\python.exe`。`requirements.lock` 记录本次实际依赖版本；字体使用 Windows 的 `simhei.ttf`，字体文件不进入仓库。

## 数学工具与真实研究

```powershell
.\.venv\Scripts\python.exe -m ai4math_agent doctor
.\.venv\Scripts\python.exe -m ai4math_agent exact --n-max 18 --output results/exact_fresh
.\.venv\Scripts\python.exe -m ai4math_agent doctor --live-probe --model gpt-6.1-sol
.\.venv\Scripts\python.exe -m ai4math_agent research --config configs/research.yaml --backend codex_cli
```

`configs/research.yaml` 默认加载已提交的 `results/exact`。如需使用新生成的精确谱，把 `exact_dir` 指向对应目录。首次真实运行需要 `codex` 在 PATH 中、已有有效登录且配置模型可用；程序不会读取或复制登录凭证。Windows 下若环境中没有代理变量，会仅为 CLI 子进程复用用户已配置的系统代理。

CLI planner 只接收宿主提供的数学上下文，输出严格 JSON 行动。宿主拒绝任意 shell/Python/MCP 工具事件。proposer 与 skeptic 每次启动分别计入后端账本，失败与重试也计数；CLI 内部 provider 请求数、实际费用不可观测时明确记录 `unknown`。

`dry_run` 是确定性接线测试，`replay` 只重放已保存响应，两者都有独立模式标记，不能作为新发生的真实研究。真实后端失败后不会自动退回模拟动作。

```powershell
.\.venv\Scripts\python.exe -m ai4math_agent research --backend dry_run
.\.venv\Scripts\python.exe -m ai4math_agent research --backend replay --replay-source results/research/2026-10-09T145817.516168_0000
```

## 过程展示与复现

完整公开过程位于 `results/research/2026-10-09T145817.516168_0000`：

- `calls/`：模型请求、结构化响应、公开事件、用量与耗时。
- `rounds/`：每轮行动、证据 ID、核验后的反馈与预算变化。
- `state.json`：命题及修订历史、实际数学产物、搜索 checkpoint。
- `manifest.json`：运行模式、源码版本、资源账本和产物 SHA-256。
- `frozen_policy.json`：模型依据开发证据给出的冻结策略（仅在实际生成后存在）。

```powershell
.\.venv\Scripts\python.exe -m ai4math_agent verify --run-dir results/research/2026-10-09T145817.516168_0000
.\.venv\Scripts\python.exe scripts/reproduce.py
```

`scripts/reproduce.py` 自动找到已完成的真实研究和与其策略对应的正式对照，重新核验并重建中文 PDF。它默认不调用模型。加 `--live` 才会开启新的真实研究；所有预算沿配置执行。

支持 `research --resume 实际目录` 与 `evaluate --resume 实际目录`。恢复要求配置、模式和源码版本匹配；已消费预算不会清零。搜索前先保存并封存预算预留，进程意外退出时保留已预留成本。

## 对照实验

正式方法为独立 random、多起点 fixed_tabu、固定比例 static_mix，以及真实研究产出的 agent_policy。四者使用相同数学评价核心和候选计量规则；初始化、所有已评分邻居（含 tabu 禁止移动）、重复状态、扰动、重启均计费。最终见证复核单列成本。

研究策略必须在留出结果产生前冻结。默认留出矩阵为长度 89/107/127、种子 1001–1005、四种方法、每次 50,000 候选，共 60 次。设置 `configs/evaluation.yaml` 的 `policy_path` 后运行：

```powershell
.\.venv\Scripts\python.exe -m ai4math_agent evaluate --config configs/evaluation.yaml
```

搜索结果均为本次预算内最佳候选。小长度完整穷举与下界/见证相等的实例可认证最优；有限验证不推广到一般长度，skew 子空间最优不等同于原问题全局最优。

## 交付范围

已有独立整数核验、增量搜索、精确谱、heap 下界证书、受控命题 DSL、真实/模拟/重放后端、硬预算与可审核报告。课程资料原件保留在本机，但不纳入 Git。Moonshine 适配、GPU 搜索和模型训练属于后续扩展。

数学定义、基础证明与文献来源见 `docs/problem.md`、`docs/methodology.md` 和 `docs/references.bib`。本项目没有解决整个 LABS 渐近开放问题，也不声称世界纪录或算法原创。
