# TinyShell 测试与验收指南

> 状态：验证入口、手动清单及证据整理。2026-10-22 审查修复后已运行下文列明的回归与脚本；历史评测数据未重新生成，真实终端验收仍待执行。

## 本次审查修复验证（2026-10-22）

- 用户目录 `.dotnet/dotnet.exe` 执行 C# 全量测试：36 项通过，包含原有性能预算测试及新增 20 条审查回归。PATH 中的 dotnet 无 SDK，不能直接用其替代本次执行路径。
- `python -m pytest -q`：41 项通过，包含新增 20 条审查回归；未运行 `eval.py`。
- `scripts/test_review_regressions.ps1`：命令语法解析、弯引号拦截、失败构建不覆盖旧模块三组检查通过，不执行生成的命令。
- `scripts/publish_module.ps1`：Release 构建成功，0 警告、0 错误，完整模块目录已重新组装；未运行用户安装脚本。
- `scripts/test_interactive_scenarios.ps1`：场景展示脚本执行成功，仅作输出检查，不据其打印内容扩大断言范围。
- `scripts/test_psreadline_interactive.ps1`：首次在 NoProfile 非交互会话中因 PSReadLine 未加载而停止；显式 `Import-Module PSReadLine` 后注册／注销与缓冲模拟检查通过。真实按键、菜单重绘仍需用户手动验收。

新增用例与阶段记录见[审查修复记录](../plans/2026-10-22-代码审查问题修复.md)。

## 自动化入口

以下命令从仓库根目录执行，使用对应开发环境。

```powershell
# C# 全量回归（包含准确率、跨语言和性能断言）
dotnet test tests/dotnet/TinyShell.Tests/TinyShell.Tests.csproj

# 需要详细指标时可单独执行；不必在全量通过后无理由重复
dotnet test tests/dotnet/TinyShell.Tests/TinyShell.Tests.csproj --filter BenchmarkTests --logger 'console;verbosity=detailed'

# 先构建模块后，运行非物理按键验证
pwsh -File scripts/publish_module.ps1
pwsh -File scripts/test_interactive_scenarios.ps1
pwsh -File scripts/test_psreadline_interactive.ps1

# 审查问题的语法树及隔离发布检查；需先构建 Debug 核心 DLL
pwsh -NoProfile -File scripts/test_review_regressions.ps1

# 独立 PowerShell 进程工作集测量
pwsh -File scripts/measure_pwsh_memory.ps1
```

`test_interactive_scenarios.ps1` 核对查询场景；`test_psreadline_interactive.ps1` 检查注册／注销等行为，并通过 `Invoke-TinyShellBufferSimulation` 模拟选择。它们没有发送真实键盘输入，不能证明菜单重绘、焦点、物理快捷键及实际缓冲替换已经通过终端验收。应检查脚本中的实际断言及输出，不能仅据打印的 PASS 文本认定所有分支有效。

Python 原型验证：

```powershell
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements.txt
./.venv/Scripts/python.exe -m pip install pytest
./.venv/Scripts/python.exe -m pytest
./.venv/Scripts/python.exe cli.py 'find process using port 8080'
./.venv/Scripts/python.exe eval.py
```

`eval.py` 会覆盖根目录 `eval_results.json`，运行前保留需要比较的旧结果。C# 与 Python 测试不是两个可相加的产品验收总数。

## 自动化覆盖与口径

| 套件 | 覆盖重点 |
|---|---|
| RuleMatcherTests | 精确别名、规则短路及歧义 |
| TokenizerTests / VectorConsistencyTests | Token ID 与向量对照；只证明 fixture 覆盖范围 |
| RetrievalConsistencyTests | 跨语言检索和门控 |
| RiskAndParameterTests | 参数、风险、注入输入及缺参 |
| FullDatasetEvaluationTests | 75 条域内样本准确率与 17 条负样本拒绝 |
| BenchmarkTests | 托管堆增量和无缓存热态 P95 |
| `tests/test_engine.py` | Python 原型的检索、安全和边界回归 |
| ReviewRegressionTests / `tests/test_review_regressions.py` | 弯引号、完整路径、歧义路径、变量标识符及缓存隔离 |

C# 全量评测的现有门槛为 Top-1 ≥ 88%、Top-3 ≥ 99%、负样本全部拒绝；产品目标 Top-3 为 100%。基准用 `GC.GetTotalMemory` 测托管堆增量，预热后对 100 条附加计数后缀的查询计时以规避缓存，断言 P95 ≤ 10 ms。该指标不等同于真实菜单响应时间或进程工作集。

## 真实终端手动验收

在独立 PowerShell 7.4+ 终端导入模块、注册快捷键后逐项验证。涉及危险命令时只检查候选或缓冲内容，不执行候选。以下均为待执行清单，未勾选不表示已通过。

| 检查 | 输入／操作 | 预期 |
|---|---|---|
| [ ] 别名 | `ll`、`pwd`、`git s` | 分别对应文件列表、当前位置、Git 状态 |
| [ ] 拼写容错 | `get-childiitem` | 推荐 Get-ChildItem 对应意图 |
| [ ] 本地端口 | `find process using port 8080` | 本地监听查询，绑定 8080，不误推远程连通测试 |
| [ ] 既有命令 | `Get-Process` 后按 Alt+s | 提示当前会话已有命令，保留用户选择权 |
| [ ] 选择 | 查询后按 Alt+s，再按 1 | 仅填入整行，无自动执行；检查后清空输入 |
| [ ] 取消 | 分别使用 Esc 与 Enter 取消菜单 | 保留原输入，不执行原短语 |
| [ ] 缺参 | `compress files` 等缺少路径的模板问法 | 若返回未补全模板则显示 NEEDS PARAMS，不标记为完整 |
| [ ] 高危标签 | `kill process 12480 immediately` | PID 绑定、dangerous 标记；仅查看，不执行 |
| [ ] 域外 | `git commit`、`def fibonacci(n): return n` | 拒绝，不把调试候选作为补全 |
| [ ] 快捷键 | 已绑定快捷键上重新注册、不带 Force | 警告并保留原处理器 |
| [ ] 注销 | 注销后再次触发 | TinyShell 菜单不再出现 |
| [ ] 显示 | 窄窗口、长路径、重复触发 | 菜单与输入重绘可读；记录实际终端及异常 |

页面与 UI 默认由用户手动验证。需要浏览器或自动化视觉验证时，按用户提供的 AGENTS.md 先说明原因、页面／交互范围和预期，再等待明确同意。

## 历史结果与证据边界

以下为文档整理前已有记录，保留用于比较，不能当作本轮测试输出。

| 来源 | 历史数据 | 边界 |
|---|---|---|
| 原 README 的 C# 测试摘录 | 16 项通过；Top-1 68/75（90.7%）；Top-3 75/75（100%） | 只有文档摘录，缺少完整机器环境与原始日志 |
| 原 README 的 C# 性能摘录 | 初始化 54.79 ms；托管堆约 11.40 MiB；无缓存 P50 3.329 ms、P95 5.688 ms | 不承诺跨机器复现；配置与机器信息未随摘录完整保留 |
| 原 README 的发布／进程测量 | 模块约 7.76 MiB；PowerShell 工作集增量约 15.53 MiB | 与托管堆测量口径不同；本轮未重新构建或测量 |
| 原 README 的 Python 回归说明 | 21 项通过 | 历史文字说明，本轮仅核对到 21 个测试函数 |
| `eval_results.json`（时间字段 2026-10-22 18:53:42） | Python hybrid Top-1 88%、Top-3 100%；模型目录 8,010,076 字节；冷启动 1109.98 ms；RSS 增量 43.51 MiB | 文件时间未声明时区；属于 Python 原型，不代表 C# 插件 |

原 README 将部分指标写成“严格达标”或通用性能结论；现统一保留为具有来源限制的历史测量。JSON 不是本次新生成的结果。

后续执行时至少记录：日期、commit、操作系统、CPU／架构、PowerShell／SDK／Python 版本、构建配置、样本版本、模型、缓存状态、测量口径、完整命令、退出码、原始输出及失败项。真实终端验收另记终端程序、按键与现象。
