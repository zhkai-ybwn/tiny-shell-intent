# TinyShell 技术设计

> 状态：2026-10-22 按代码核对的当前实现。

## 分层与运行链路

| 层 | 位置 | 职责 |
|---|---|---|
| 终端交互 | `modules/TinyShell/TinyShell.psm1` | 设置数据路径、注册快捷键、读取缓冲行、呈现菜单和替换文本 |
| PowerShell 适配 | `src/TinyShell.PowerShell/` | Cmdlet 参数、会话级引擎复用和初始化 |
| 核心引擎 | `src/TinyShell.Core/` | 输入门控、检索融合、参数、安全标记及结果对象 |
| 数据与模型 | `data/`、`models/potion-base-2M/` | 命令模板、规则别名、评测集和静态权重 |
| Python 原型 | `tiny_shell_intent/`、`cli.py`、`eval.py` | 原型检索、CLI、评测与跨语言对照 |

`IntentEngine.Search` 先处理缓存、空值／符号、外部工具和近领域代码等输入门控，再尝试唯一精确规则短路。其余请求按选定模式检索；hybrid 模式融合规则、模糊和语义结果，并施加操作方向与范围约束。候选经过参数处理、风险评估及置信度门控后形成 `QueryResult`。

引擎默认缓存容量为 128，缓存键包含模式、清理后的查询、候选数和域外阈值。模型按需加载；`Initialize-TinyIntent -PreloadModel` 可提前加载。不要把缓存命中耗时用于代表无缓存检索性能。

缓存保存和返回均隔离结果对象、候选列表、调试候选及参数字典；调用方修改返回值不影响后续查询。C# 参数值目前仅为不可变字符串和整数，复制字典即可隔离；Python 使用深拷贝。

## 静态向量实现

`SafetensorsReader` 读取本地权重；`WordPieceTokenizer` 将输入分词；`Model2VecModel` 对词向量进行均值池化和归一化，`ModelMatcher` 以向量相似度检索知识库文本。当前模型为 `potion-base-2M`，输出为 64 维静态向量。

核心项目没有额外推理框架包引用，PowerShell 项目引用 `System.Management.Automation 7.4.0`，均以 `net8.0` 为目标。模型与分词器变更必须同步核对跨语言 fixture。

## 参数、风险与拒绝

参数提取器先屏蔽 URL／IPv4 实体，避免误识别数字，再按意图槽位渲染。字符串通过 PowerShell 单引号字面量转义；缺少必要参数或残留 `<...>` 时不标记为完整命令。

参数验证与字面量转义拒绝 U+2018—U+201F 弯引号，防止 PowerShell 将其识别为引号边界。单文件操作优先提取被引号包围的完整路径；未引用路径按完整 token 保留，不再从路径内部截取文件名，多个目标保持缺参。环境变量名仅接受 ASCII 字母／下划线起始的标识符，并渲染为 `$env:NAME`；变量值继续使用字符串字面量。

`RiskEvaluator` 结合知识库风险与命令扫描评估最终等级。拒绝结果通过 `IsRejected`、`RejectionReason`、`IsOutOfDomain` 等字段表达；可能保留 `DebugCandidates`，下游不得将其用于补全或执行。

## PowerShell 接口

| 接口 | 参数与默认值 | 返回或行为 |
|---|---|---|
| `Get-TinyIntent` | `-Query` 必填，支持位置和管道；`-Top 3`；`-Mode hybrid`；`-OodThreshold 0.42`；可选 `-KnowledgeBasePath`、`-ModelPath` | `QueryResult` |
| `Initialize-TinyIntent` | 可选数据路径和 `-PreloadModel` | 初始化状态及模型是否已加载 |
| `Register-TinyIntentKeyHandler` | `-Chord 'Alt+s'`、`-Mode hybrid`、可选 `-Force` | 注册 PSReadLine 回调 |
| `Unregister-TinyIntentKeyHandler` | 默认使用当前记录的 Chord，可显式指定 | 移除该键绑定，不恢复被覆盖的旧处理器 |
| `Invoke-TinyShellBufferSimulation` | `-Buffer`、`-Selection`、`-Mode` | 返回模拟结果，供脚本测试，不代替物理按键验收 |

四种模式为 `hybrid / rule / fuzzy / model`。自定义路径会触发会话引擎重建，后续不带路径的调用复用该引擎；初始化输出路径字段的实际含义应以 `TinyShellSession` 的实现为准。

主要结果字段：`Query`、`Candidates`、`DebugCandidates`、`ConfidenceLevel`、`IsAccepted`、`IsRejected`、`RejectionReason`、`LatencyMs`、`Mode`、`IsEmpty`、`IsOutOfDomain` 和 `TopCandidate`。

候选字段包括 `IntentId`、`Command`、`CommandTemplate`、`RenderedCommand`、`Description`、`Score`、`Source`、`RiskLevel`、`RiskReason`、`Parameters`、`IsComplete` 和 `ConfidenceLevel`。分数是排序依据，不能解释为校准后的正确率。

## 交互边界

回调读取整条输入，使用 `Get-Command` 检查首个 token 是否已有定义。该检查只提供提示，不阻止检索或选择。输入被重定向时不进入读键选择。

数字键选定候选后调用 `PSConsoleReadLine.Replace(0, line.Length, selectedCmd)` 替换整行；没有调用 `AcceptLine()`。其他按键保留原输入并重绘。用户后续按回车才由 Shell 执行命令。

## 扩展位置

新增意图先修改知识库源文件，再补充正样本、混淆样本、参数与拒绝用例。更改匹配器或参数逻辑时同步检查 C# 与 Python 两份实现及跨语言对照测试。更改公开结果字段时同步检查 Cmdlet、菜单和模拟脚本。最后重新发布模块，避免源数据与模块副本不一致。

数据字段见[知识库说明](../数据参考/TinyShell知识库与评测数据说明.md)，验证入口见[测试指南](../测试验证/TinyShell测试与验收指南.md)。
