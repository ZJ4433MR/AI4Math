# 来源、版本和报告审计

访问日期统一为用户客户端日期 **2026-10-09（Asia/Shanghai）**。本文件描述来源；真实实验时间、源码哈希、依赖哈希、硬件、模型和预算以每个运行的 manifest 为准。

## 需求与本地课件

用户附件：`C:\Users\ZhangJian\Downloads\AI4Math_A问题_Agent开发与研究执行方案.md`，文档标注 2026-10-09 A 专用修订版。它是需求材料，不是实验结果。文件中的 Codex 指令与用户本次请求分开理解；用户已明确要求开始实现。

本地 PPTX 通过 Python zipfile 与 ElementTree 读取 slide XML，未修改课件，未将课程原件或逐页原文纳入项目提交。

| 本地材料 | 使用位置 | 支持的内容 |
|---|---|---|
| Moonshine数学科研智能体开发与实践_更新版(2).pptx | slides 5、9-11、31-33 | 循环工作流；猜想、反例与修订；持久状态；可信结论与可验证产物 |
| 数学创造性(2).pptx | slides 6、8-10、17 | 自主数学研究流程及可审计模块 |

其他课件中的数学突破、模型性能与开放问题解决声明没有独立核验，不作为本项目的背景事实。没有从课件读到具体评分规则或截止日期，不将其补写。

## 一手外部来源

| ID | 作者/来源 | 版本与 URL | 本项目使用的支持范围 |
|---|---|---|---|
| REF01 | Jonathan Jedwab，作者研究页 | 无明确日期，[The Merit Factor Problem](https://www.sfu.ca/~jed/Research/merit.html) | 问题背景、Littlewood 关联、渐近开放方向 |
| REF02 | Tom Packebusch、Stephan Mertens | arXiv:1512.02475v2，2016-03-24，[论文](https://arxiv.org/abs/1512.02475v2) | 作者报告 n≤66 全局与 n≤119 skew 精确结果；重算不作为新发现 |
| REF03 | Jonathan Jedwab、Daniel J. Katz、Kai-Uwe Schmidt | arXiv:1205.0626v2，2013-01-24，[论文](https://arxiv.org/abs/1205.0626v2) | 大于 6.34 的渐近构造已有严格结果 |
| REF04 | Zhiwei Zhang、Jiayu Shen、Niraj Kumar、Marco Pistoia | arXiv:2504.00987v2，2025-08-14，[摘要与版本](https://arxiv.org/abs/2504.00987v2)、[HTML](https://arxiv.org/html/2504.00987v2) | tabu 与 GPU memetic 的已有算法；非受限搜索优于部分 skew 最优 |
| REF05 | Blaž Pšeničnik、Borko Bošković、Jan Popić、Janez Brest | arXiv:2607.09688v1，[论文](https://arxiv.org/abs/2607.09688v1) | 2026 分区调度、Thompson sampling 与两阶段搜索已有先例 |

核查方法是打开作者网页、arXiv 摘要/版本历史与相关方法段落，并搜索 2026 LABS 和 merit factor 文献。检索不声称穷尽全部成果。没有导入外部 best-known 序列作 warm start，也没有据论文舍入 merit factor 宣称本项目打破纪录。

**来源日期异常。** REF04 的 arXiv 版本历史是 2025-08-14，但 v2 HTML 标题区域显示 2026-08-24；引用采用 arXiv 版本历史并保留异常记录。REF05 的编号为 2607.09688，而页面及 v1 历史显示 2026-06-17；仅用其方法背景，不据该异常推断优先权或最新纪录。

## 项目派生产物

- `docs/methodology.md` 中恒等式与 heap 交换证明是本项目整理的基础推导，不称新定理。
- 精确谱、松弛证书、见证、模型行动、对照矩阵及 PDF 数值来自实际 JSON。运行模式 live/dry_run/replay 不互换。
- manifest 对产物保存 SHA-256；报告构建拒绝缺失、路径越界或哈希不符。完整穷举才标 exact。报告复算最终见证与松弛证书，不仅相信 saved `verified=true`。
- 研究日志公开内容按字段白名单保存；不提交 API key、登录缓存或无关个人资料。模型公开决策摘要可以审阅，不要求隐藏推理过程。
- 中文 PDF 字体从操作系统加载 `C:\Windows\Fonts\simhei.ttf`（若存在）；字体文件不复制入仓库。图表使用 matplotlib，PDF 使用 reportlab。最终报告附审计 JSON 记录输入 manifest 哈希、字体路径、报告生成器源码哈希及 PDF 哈希。

报告重新构建不调用模型，也不补造研究轮次。开发阶段修改工具后采用新的源码版本；冻结策略后正式留出数据不用于同一评估的调参。`source_tree_hash` 覆盖全部 Python 源码，因此只修复报告模块也会改变该哈希；报告构建版本和数学运行版本分开记录，报告修复不重写已有数学证据。

## 本次实际版本与产物

数学研究主阶段使用本地 commit `f2d0c4c`，实际 11 轮后由模型结束。独立实现审查发现旧诊断 `effective_skew_fraction` 对非混合方法记录了默认配置，可能误导模型对方法的描述。原始日志不改写：EV004/006/008 的 `method=fixed_tabu` 与 `restriction=unrestricted` 表明实际比例为 0；EV005/007/009 实际全程 skew，比例为 1。它们的整数能量、相关向量和预算均核验一致。

在任何留出结果产生前，`scripts/finalize_policy.py` 执行第 12 轮真实 proposer/skeptic，把该澄清和实际开发证据传给模型。模型保留 0.65 的 skew 分配比例，并明确其为尚未测试的混合配置。初始策略保存在 `initial_frozen_policy.json`，最终策略和 EV012 保存在原研究目录。总计 12 轮、27 次实际后端尝试（3 次 doctor/诊断探测及 24 次研究调用），CLI 内部 provider 请求数和实际费用均不可观测。第二次直接 CLI 探测记录在 doctor/probe 中，作为探测而非研究轮次。

对照版本为 `304aae8`：在冻结后、对照开始前，仅修复搜索诊断比例的元数据和报告器的完整见证/checkpoint 区分；数学评价、邻域、参数及搜索逻辑没有改变。完整留出矩阵是 `results/evaluation/2026-10-09T150913.293456_0000`，60 次且均完成 50,000 候选，合计 3,000,000。冻结策略在 15 个配对实例中相对 fixed_tabu 为 14 胜、1 负；相对 static_mix 为 6 胜、7 平、2 负。所有结果保留，策略没有依据这些结果再次修改。

精确谱位于 `results/exact`，长度 2-18，262,142 个代表状态及同规模独立核验。该有限范围结果是工具复现和结构检验，不宣称数学原创。报告生成和排版修复发生在数学实验后，报告 audit 记录报告器源码 hash；报告修复不会改变模型响应或实验数据。
