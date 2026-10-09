# 输入问题并运行通用数学研究智能体

LABS 专用案例保留原命令和证据。通用工作流接收自然语言主题或完整问题，保存模型行动、工具产物、审查、命题修订、成本和停止原因；它不再把课件展示等同于读取旧日志。

## 命令行

在项目目录并使用已安装的 Python 环境运行：

```powershell
ai4math solve --problem "研究 Pell 方程 x^2 - 2y^2 = 1 的整数解结构。提出明确猜想，尝试证明并检验。" --backend codex_cli --model gpt-6.1-sol --max-rounds 20
ai4math solve --problem-file problem.txt --backend codex_cli --max-rounds 12
ai4math solve --resume results/general/实际运行目录 --backend codex_cli --max-rounds 20
```

`--backend api` 使用已经配置的环境凭证与相应模型；`dry_run` 只用于离线接线检查。后端失败会记录为失败，不能自动换成 mock 后声称真实运行。模式以每个 manifest 为准，续跑保持原模式和累积账本。

续跑必须使用原模型、资源限制和相同源码。上面的 20 轮续跑对应第一条同样为 20 轮的运行；不能在续跑时从 12 增加为 20 来重置或扩大原账本。页面续跑自动沿用原 manifest 配置。

## 本地过程页面

```powershell
ai4math serve --host 127.0.0.1 --port 8765
```

访问 [本地过程页面](http://127.0.0.1:8765)。输入数学主题、选择真实后端、模型和轮数，点击“启动实际研究”。服务会启动真正的 `ai4math solve` Python 子进程；页面每 1.5 秒读取实际写入的状态，显示行动、证据、模型审查、修订关系和预算。

本地页面不收集或显示 API key；凭证沿用登录或进程环境。服务器只绑定 loopback，启动/续跑/中断使用本地页面 token，不允许跨域执行操作。问题文本通过参数数组传给 Python，不经过 shell 拼接。Windows 子进程不弹出额外终端窗口。

UI 启动的研究使用独立目录 `results/general/ui-任务ID/时间戳/`，便于可靠关联后台进程；普通 CLI 仍可使用 `results/general/时间戳/`。启动日志在 `tmp/general_ui_logs/`，页面不公开原始环境。已有通用会话可以读取、生成报告或续跑；已有 `results/research/` LABS 会话只读，并保留原 mode 与工作流。

“中断当前进程”终止本页面启动的进程树，确认进程退出后记录 `host_process_interrupted` 并封存为 interrupted，保留 pending_tool 和所有已预留预算。累计时间至少包含本次后台进程经过的时间；这不是完成状态。有剩余轮次、调用、时间和 operations 预算的中断或后端失败会话可以续跑，已完成或预算耗尽会话不能重置预算。关闭页面不会自动取消模型调用；关闭服务也不会伪造完成状态。模型和工具等待须结合后台进程状态、预算与停止原因阅读。

## 结论与报告

`build_general_report(run_dir)` 从封存日志离线生成同目录的 `report.md`、自包含 `report.html` 和 `report_audit.json`，并把报告纳入 manifest 哈希。原始每轮行动、证明草稿、工具错误与负结果保留；文献工具保存的原始链接列入报告。报告生成不调用模型，也不补写轮次。

证明草稿、经验样本、有限域穷举、声明假设内的符号核验和形式证明分别标注。原自然语言命题只记为“形式证书可用”或“形式反例可用”，而实际工具状态保存在 `formal_status`、明确的对象和前提保存在 `verification_scope`。模型对语义对应的审查即使为 true，也不是对应关系的独立证明；false 会突出警告“不能据此认证原命题”。来源链接也不能代替原文核查。operations 是具体工具记录的测量单位，不自动等于序列候选数、CPU 指令或统一时间成本。一般数学问题可能超出当前注册工具的能力，系统应记录 unsupported、失败或 unresolved，而不是承诺解决任意开放问题。
