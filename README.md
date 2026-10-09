# AI4Math 数学研究智能体

可输入新的数学问题或研究主题。真实模型制定计划、检索背景、提出猜想、编写并运行实验程序、寻找反例、提交证明草稿或证书；宿主核验后把证据与审查意见送回模型，由模型决定下一轮。LABS 作为专用工具模块保留。

## 输入新问题与在线展示

```powershell
.\.venv\Scripts\python.exe -m ai4math_agent solve --problem "研究前 n 个正整数的五次方和，设计实验、提出公式并尝试证明" --max-rounds 12
.\.venv\Scripts\python.exe -m ai4math_agent solve --problem-file examples/polynomial_primes.yaml --max-rounds 12
.\.venv\Scripts\python.exe -m ai4math_agent serve
```

本地展示界面为 `http://127.0.0.1:8765`，可输入问题并启动真实运行，查看行动、工具结果、反例、审查和修订。`results/general/` 每次产生新目录，包含真实模型调用、生成的实验代码、数学证据、资源账本、修订关系及独立的 HTML/Markdown 报告。报告会明确区分保存记录和新运行。

通用实验器执行模型新写的算法；有限检查器接受新的精确有理数/模运算命题；符号核验和归纳核验接受新的表达式和求和公式。它们有超时、操作与输出限制。实验器是受限制的 Python 执行器，**不是操作系统安全沙箱**，不要向它提供不受信任来源的代码。命题不局限于旧 LABS 的五种预设。

模型能研究新问题，不意味着能保证解决任意数学问题。机器证书只认证其显式形式化范围；有限测试不证明无限域命题，自然语言证明保留为待审查草稿，模型对原问题与形式化的对应判断也不算形式证明。背景工具读取 arXiv/Crossref 元数据与摘要，不能冒充读完整篇论文或证明原创性。详见 [通用智能体说明](docs/general-agent.md)。

```powershell
.\.venv\Scripts\python.exe -m ai4math_agent verify --run-dir results/general/<实际运行目录>
.\.venv\Scripts\python.exe -m ai4math_agent general-report --run-dir results/general/<实际运行目录>
```

## 安装

需要 Python 3.11+，默认仅使用 CPU。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m pytest -q
```

本机已配置 `.venv`，可直接使用 `.\.venv\Scripts\python.exe`。`requirements.lock` 记录本次实际依赖版本；字体使用 Windows 的 `simhei.ttf`，字体文件不进入仓库。

## LABS 专题工具与既有真实研究

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
.\.venv\Scripts\python.exe scripts/show_process.py --interactive
.\.venv\Scripts\python.exe scripts/reproduce.py
```

`scripts/reproduce.py` 自动找到已完成的真实研究和与其策略对应的正式对照，重新核验并重建中文 PDF。它默认不调用模型。加 `--live` 才会开启新的真实研究；所有预算沿配置执行。

课堂展示可运行 `scripts/show_process.py --interactive`，逐轮显示公开决策、工具结果、独立核验、模型审查与预算。`--round 10` 可直接展示被反驳命题和真实见证。展示已保存的 live 日志，不伪装成新的在线研究。

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

本次实际完成：

- `n=2..18` 完整条件谱，共 262,142 个取反轨道代表，并另做同规模独立枚举核验。
- 12 轮真实研究，27 次后端启动尝试（3 次探测、24 次研究 proposer/skeptic）；搜索合计 600,000 候选。
- 在 `n=18` 验证“存在平衡最优序列”，反驳“所有最优序列都平衡”：最优能量 25、最优不平衡程度集合 `{0,2,6}`。这属于有限域复现与结构检验。
- `n=6,b=4` 的见证能量与有效下界均为 7，认证该条件类最优。
- 留出对照 60 次、每次 50,000 候选，总计 3,000,000 候选；冻结策略相对 fixed_tabu 配对 14 胜、1 负。相对 static_mix 为 6 胜、7 平、2 负，少量种子不足以声称一般优势。

正式数据目录为 `results/evaluation/2026-10-09T150913.293456_0000`，中文报告为 `reports/AI4Math_LABS_Report.pdf`。对应原始日志与报告可离线重建。

开发版本的 `diagnostics.effective_skew_fraction` 曾把默认参数误作实际比例。原始数据保留；第 12 轮模型读到澄清后重新冻结策略：fixed_tabu 实际全程 unrestricted，skew 实际全程受限。数值见证和计费均正确。对照开始前仅修正此诊断元数据，没有改变搜索逻辑；报告器的完整 witness/checkpoint 区分也单独修正。初次 65% 混合配置在开发阶段未测试，其结果来自后续留出评价。

数学定义、基础证明与文献来源见 `docs/problem.md`、`docs/methodology.md` 和 `docs/references.bib`。本项目没有解决整个 LABS 渐近开放问题，也不声称世界纪录或算法原创。
