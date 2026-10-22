# Tiny Shell Intent — 轻量 Windows 本地命令语义识别插件

基于本地轻量静态嵌入模型与多通道混合检索的 Windows PowerShell 7.4+ 智能命令建议插件。

用户端**零 Python 依赖、零 GPU 需求、零网络或外部 LLM API、零常驻独立后台服务**。模型文件与 Tokenizer 仅约 **7.64 MB**，完整 PowerShell 插件发布包仅 **7.76 MB**，增量常驻内存仅 **15.5 MB**，无缓存热态检索 P95 延迟仅 **5.6 ms**（严格 $\le 10.0\text{ ms}$ 预算）。

---

## 目录

- [核心架构与演进](#核心架构与演进)
- [资源预算与实际达成指标](#资源预算与实际达成指标)
- [交互体验与安全设计原则](#交互体验与安全设计原则)
- [快速开始与安装使用](#快速开始与安装使用)
  - [1. 一键安装到用户模块目录](#1-一键安装到用户模块目录)
  - [2. 命令行单次检索（Get-TinyIntent）](#2-命令行单次检索get-tinyintent)
  - [3. 注册 PSReadLine 快捷键交互建议（Alt+s）](#3-注册-psreadline-快捷键交互建议alts)
- [八大真实 Shell 场景验证](#八大真实-shell-场景验证)
- [跨语言一致性与自动化测试](#跨语言一致性与自动化测试)
- [目录结构](#目录结构)
- [技术实现细节](#技术实现细节)
  - [1. 纯 C# Model2Vec 静态推理引擎](#1-纯-c-model2vec-静态推理引擎)
  - [2. 规则短路与多意图融合约束](#2-规则短路与多意图融合约束)
  - [3. 参数抽取、实体屏蔽与安全防注入](#3-参数抽取实体屏蔽与安全防注入)
  - [4. PSReadLine 缓冲行替换（永不自动执行）](#4-psreadline-缓冲行替换永不自动执行)
- [编译与打包发布](#编译与打包发布)
- [开源协议](#开源协议)

---

## 核心架构与演进

Tiny Shell Intent 从 Phase 1 的 Python 语义引擎验证原型（PoC），演进为 Phase 2 / 2.1 的 **.NET 8 原生 C# 类库与 PowerShell 7.4+ 交互式模块**：

```
 用户输入 (PowerShell 7.4+ 控制台)
            │
     [Alt+s] 快捷键触发 (避免 Ctrl+I 与 Tab 补全冲突)
            │
            ▼
┌─────────────────────────────────────────────────────────────┐
│ PSReadLine KeyHandler (TinyShell.psm1)                      │
│ - 读取控制台当前缓冲行与游标位置                            │
│ - 检测当前 Shell 环境已有合法命令/别名                      │
│ - 快捷键冲突探测与持久模式捕获                              │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│ C# 原生核心引擎 (TinyShell.Core.dll)                        │
│                                                             │
│ ┌─────────────────────────┐     ┌─────────────────────────┐ │
│ │  RuleMatcher            │     │  FuzzyMatcher           │ │
│ │  - 51 意图别名映射      │     │  - Indel / LCS 算法     │ │
│ │  - ll/pwd/cls/git s     │     │  - WRatio / 错别字容忍   │ │
│ │    0.03ms 极速短路      │     │  - 关键词覆盖度加权     │ │
│ └────────────┬────────────┘     └────────────┬────────────┘ │
│              │                               │              │
│              └───────────────┬───────────────┘              │
│                              ▼                              │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │  ModelMatcher (纯 C# Model2Vec 静态嵌入)                │ │
│ │  - 纯 C# SafetensorsDirectReader (直接读取 f32 权重)    │ │
│ │  - 纯 C# WordPieceTokenizer (完全等价 HuggingFace 分词) │ │
│ │  - 64 维静态词向量查表 + 算术平均池化 + L2 范数归一化   │ │
│ │  - 纯内存矩阵点积余弦相似度检索                         │ │
│ └────────────────────────────┬────────────────────────────┘ │
│                              │                              │
│                              ▼                              │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │  HybridFusion & Intent Constraints                      │ │
│ │  - 本地监听端口 (Get-NetTCPConnection) vs 远程连通测试   │ │
│ │  - 停止 vs 启动极性互斥约束                             │ │
│ │  - 复制 vs 删除互斥约束                                 │ │
│ │  - 运行时间 vs 重启/关机互斥约束                        │ │
│ │  - 单文件 vs 目录 vs 回收站操作范围约束                 │ │
│ │  - IPv4 实体屏蔽参数提取 & 占位符完整性检查             │ │
│ │  - 高危命令扫描与非降级风险评估                         │ │
│ └────────────────────────────┬────────────────────────────┘ │
│ └────────────────────────────┬────────────────────────────┘ │
│                              │                              │
│                              ▼                              │
┌─────────────────────────────────────────────────────────────┐
│ 交互式建议选择菜单                                          │
│ - 彩色安全风险徽标: [SAFE] (绿) / [WARN] (黄) / [DANGER] (红)│
│ - 状态徽标: [NEEDS PARAMS]                                  │
│ - 用户按 [1-3] 选择 -> 替换输入缓冲区 (等待用户审查后回车) │
│ - 用户按 [Esc/Enter] -> 保持原输入                          │
└─────────────────────────────────────────────────────────────┘
```

---

## 资源预算与实际达成指标

在开发与重构过程中，确立了严格的工业级资源与正确性目标。下表汇总了目标与最终实测数据：

| 指标维度 | 目标预算 | Python PoC 基线 (Phase 1) | **C# 原生插件实测 (Phase 2.1)** | 达成结论 |
|---|---|---|---|---|
| **Python 依赖** | **0** | Python 3.11+ / NumPy | **0 (纯 C# .NET 8 类库)** | **完全达标** |
| **GPU / 网络 / 外部后台** | **0** | 0 | **0** | **完全达标** |
| **模型与 Tokenizer 大小** | $\le 8\text{ MB}$ | 7.64 MB | **7.64 MB** | **完全达标** |
| **完整插件分发包体积** | 尽量 $\le 15\text{ MB}$ | ~50 MB (含环境) | **7.76 MB (含模型/字典/二进制)** | **超越预算 (52%)** |
| **PowerShell 常驻增量内存** | 尽量 $\le 30\text{ MB}$ | 43.16 MB (RSS) | **15.53 MB (WorkingSet64)** | **超越预算 (51%)** |
| **模型冷态初始化时间** | — | 790 ~ 1100 ms | **54.8 ms** | **提速 14 倍** |
| **无缓存热态检索 P95** | $\le 10.0\text{ ms}$ | 1.52 ms (PyPy/C) | **5.68 ms** | **严格满足 $\le 10.0\text{ ms}$** |
| **无歧义精确短路延迟** | $\le 1\text{ ms}$ | 0.04 ms | **0.03 ms** | **极速短路** |
| **核心别名 `ll`** | 精确映射 | 错误推荐 proc_kill | **`file_list` (`Get-ChildItem -Path .`)** | **0.03 ms 命中** |
| **开发者别名 `git s`** | 精确映射 | 被外部工具拦截 | **`git_status` (`git status`)** | **0.03 ms 命中** |
| **外部工具非法子命令** | 安全拦截 | 误推 | **`git commit` 拒绝 (`unsupported_external_tool`)**| **严格隔离** |
| **端口查询语义混淆** | 准确区分 | 推荐远端测试 | **`find process using port 8080` $\to$ 本地监听**| **语义精准** |
| **75 条域内测试集 Top-1** | $\ge 88.0\%$ | 88.0% | **90.7% (68/75)** | **超越基线** |
| **75 条域内测试集 Top-3** | $100\%$ | 100.0% | **100.0% (75/75)** | **完全对齐** |
| **负样本/代码/空输入拒绝率**| $100\%$ | 100.0% | **100.0%** | **完全对齐** |
| **高危命令误推数** | **0** | 0 | **0** | **零高危误推** |

---

## 交互体验与安全设计原则

1. **绝对不自动执行命令**：
   插件仅通过 PSReadLine 的 `[Microsoft.PowerShell.PSConsoleReadLine]::Replace()` 将用户选中的候选命令填入当前命令行。用户可以在终端中从容检查参数、修改路径，最后主动按下回车执行。
2. **三级风险警示标签**：
   - `[SAFE]`（绿色）：无副作用的只读信息获取、状态查询（如 `Get-Process`, `(Get-Location).Path`）。
   - `[WARNING]`（黄色）：存在轻度修改操作（如临时环境变量赋值、单文件删除、服务状态变更）。
   - `[DANGER]`（红色）：包含强力终止、递归强制删除或整机重启关机等破坏性指令（如 `Stop-Process -Force`, `Stop-Computer -Force`）。
3. **参数占位符完整性守卫**：
   若命令模板含有 `<...>` 且无法从输入中推断（如 `Compress-Archive -Path "<source>" ...`），系统强制标记 `is_complete=False`，界面提示 `[NEEDS PARAMS]`，绝不伪装为立即可执行命令。
4. **优先尊重原生环境**：
   若用户输入的命令已经是 PowerShell 7 内建的合法命令或别名（如 `Get-Process`），界面会提示 `Note: ... is an existing Cmdlet/Alias in this shell session`，不进行破坏性抢占。
5. **快捷键防冲突设计**：
   默认快捷键采用 **`Alt+s`**，彻底避开常见终端协议中 `Ctrl+i` 与系统 `Tab` 补全产生的 ASCII 0x09 键码冲突。注册时自动执行冲突探测（`Get-PSReadLineKeyHandler -Bound`），并支持通过 `-Chord` 自定义。

---

## 快速开始与安装使用

### 运行环境要求

- **操作系统**：Windows 10 / 11 (x64 / arm64) 或已安装 PowerShell 7 的 Windows Server
- **PowerShell 版本**：**PowerShell 7.4+** (`pwsh.exe`)
- **.NET 运行时**：PowerShell 7.4+ 内置的 .NET 8 宿主运行时即可直接加载

### 1. 一键安装到用户模块目录

克隆仓库后，在 PowerShell 7 终端中执行一键安装脚本：

```powershell
.\Install-TinyShell.ps1
```

该脚本会自动将发布包安装至当前用户的模块目录（`$HOME\Documents\PowerShell\Modules\TinyShell`）。安装完成后，任意新开的 PowerShell 窗口均可直接导入：

```powershell
Import-Module TinyShell
Register-TinyIntentKeyHandler -Chord 'Alt+s'
```

若希望每次启动终端自动启用，只需将上述两行加入您的 `$PROFILE` 即可。

### 2. 命令行单次检索（Get-TinyIntent）

```powershell
# 查询自然语言描述
Get-TinyIntent "find process using port 8080"

# 查询缩写或别名
Get-TinyIntent "ll"
Get-TinyIntent "git s"

# 查看详细候选属性
(Get-TinyIntent "kill process 12480 immediately").Candidates | Format-Table IntentId, Command, RiskLevel, Score
```

### 3. 注册 PSReadLine 快捷键交互建议（Alt+s）

```powershell
# 注册全局快捷键 (默认快捷键为 Alt+s，避免 Tab 冲突)
Register-TinyIntentKeyHandler -Chord 'Alt+s'
```

注册后，在终端中输入任意短语（例如输入 `find process using port 8080`），按下 <kbd>Alt</kbd> + <kbd>S</kbd>，即可在光标下方展开交互菜单：

```text
╭── TinyShell Suggestions (3 matches in 6.45 ms) ──────────────────────────
 │ [1] Get-NetTCPConnection -LocalPort 8080 -State Listen | Select-Object LocalAddress, LocalPort, OwningProcess [SAFE]
 │     List active TCP ports and listening sockets (model: 0.821)
 │ [2] Get-ChildItem -Recurse -Filter "*.<ext>" [SAFE] [NEEDS PARAMS]
 │     Recursively search for files matching extension (fuzzy: 0.541)
 │ [3] Get-Process | Sort-Object CPU -Descending | Select-Object -First 10 [SAFE]
 │     List top processes sorted by CPU usage (fuzzy: 0.490)
╰──────────────────────────────────────────────────────────────────────────
Select [1-3], or [Esc/Enter] keep original: 
```

此时：
- 按键盘数字键 <kbd>1</kbd>、<kbd>2</kbd> 或 <kbd>3</kbd>：立即将选中的命令替换到当前输入缓冲行；
- 按 <kbd>Esc</kbd> 或 <kbd>Enter</kbd>：取消并保留当前输入的文字。

---

## 八大真实 Shell 场景验证

项目中提供了全自动端到端验证脚本：

```powershell
pwsh -File scripts/test_interactive_scenarios.ps1
```

实测输出：

| # | 场景类型 | 用户输入 | 识别意图 / 行为 | 延迟 | 安全与完整性 |
|---|---|---|---|---|---|
| 1 | **核心别名解析** | `ll` | 极速映射为 `Get-ChildItem -Path .` | **0.03 ms** | `rule_exact`，安全只读 |
| 2 | **精确短路** | `pwd` | `(Get-Location).Path` | **0.03 ms** | `rule_exact`，安全只读 |
| 3 | **合法已有命令** | `Get-Process` | 保留原生，提示为已有 Cmdlet 并推荐进阶用法 | 10.3 ms | 尊重当前 Shell 环境 |
| 4 | **错别字容忍** | `get-childiitem` | 正确纠正并映射为 `Get-ChildItem` | 3.9 ms | 模糊容错匹配 |
| 5 | **本地端口语义与参数抽取** | `find process using port 8080` | 提取端口 `8080`，精准推荐本地监听端口查询 | 6.5 ms | 区分本地监听与远程连通 |
| 6 | **开发工具别名与边界隔离** | `git s` / `git commit` | `git s` $\to$ `git status`；`git commit` 明确拒绝 | **0.16 ms** | 兼顾高频别名与外部工具边界 |
| 7 | **高危操作防误推** | `kill process 12480 immediately` | 绑定 PID `12480`，输出 `Stop-Process -Id 12480 -Force` | 4.1 ms | 强制标记 `[DANGEROUS]` 风险 |
| 8 | **代码及域外输入** | `def fibonacci(n): return n` | 明确拒绝（`near_domain_code_or_unsupported_system`） | **0.01 ms** | 零污染静默拒绝 |

---

## 跨语言一致性与自动化测试

本项目在迁移至 C# 原生实现时，编写了严格的双语跨语言对齐校验测试集（`data/cross_language_test_cases.json`）：
- **词表与 Tokenizer 校验**：24 组包含标点、大小写、CJK、未知字符的样本，Assert C# Token IDs 与 HuggingFace Tokenizer 100.0% 严格一致；
- **向量浮点误差校验**：64 维嵌入向量与 Python Model2Vec 输出比对，最大分量浮点绝对误差 $< 10^{-4}$，余弦相似度 $> 0.9999$；
- **检索决策对齐**：覆盖域内、近领域负样本、代码、Unicode，确保 C# 版本的得分、排序、参数提取及门控决策与 Python 版本高度一致。

运行测试命令：

```powershell
# 1. 运行全部 16 个 C# 单元测试与评测套件
dotnet test tests/dotnet/TinyShell.Tests/TinyShell.Tests.csproj

# 2. 运行严格性能基准与常驻内存测试 (严格要求 P95 <= 10.0 ms)
dotnet test tests/dotnet/TinyShell.Tests/TinyShell.Tests.csproj --filter "BenchmarkTests"

# 3. 运行全部 21 个 Python 回归与边界测试
python -m pytest

# 4. 运行真实 PSReadLine 交互与缓冲替换自动化验证
pwsh -File scripts/test_psreadline_interactive.ps1
```

实测测试报告：
```text
已通过! - 失败: 0，通过: 16，已跳过: 0，总计: 16，持续时间: 531 ms
- Model initialization time: 54.79 ms
- Engine memory footprint: 11.40 MB
- Uncached P50: 3.329 ms, P95: 5.688 ms (Target <= 10.0 ms PASS)
- Hybrid Top-1: 68/75 (90.7%)
- Hybrid Top-3: 75/75 (100.0%)
- Negative Rejection: 17/17 (100.0%)
```

---

## 目录结构

```text
tiny-shell-intent/
├── TinyShell.sln                         # .NET 8 跨项目解决方案
├── Install-TinyShell.ps1                 # 根目录一键安装脚本
├── src/
│   ├── TinyShell.Core/                   # 纯 C# 核心类库 (net8.0, 零外部原生依赖)
│   │   ├── Models/                       # 数据模型 (CommandIntent, Candidate, QueryResult)
│   │   ├── Tokenizer/                    # 纯 C# WordPieceTokenizer 实现
│   │   ├── Storage/                      # SafetensorsReader, Model2VecModel, KnowledgeBaseStore
│   │   ├── Matchers/                     # RuleMatcher, FuzzyMatcher (LCS/WRatio), ModelMatcher
│   │   ├── Parameters/                   # 实体屏蔽、参数提取与安全字面量转义
│   │   ├── Risk/                         # 命令风险评级扫描与非降级守卫
│   │   └── IntentEngine.cs               # 统一检索调度引擎 (支持缓存与意图约束)
│   └── TinyShell.PowerShell/             # PowerShell 7 二进制 Cmdlet 模块
│       ├── TinyShellSession.cs           # 引擎单例生命周期与资源路径解析
│       ├── GetTinyIntentCmdlet.cs        # Get-TinyIntent Cmdlet
│       └── InitializeTinyIntentCmdlet.cs # Initialize-TinyIntent Cmdlet
├── modules/
│   └── TinyShell/                        # 编译打包发布的独立 PowerShell 模块目录
│       ├── TinyShell.psd1                # 模块清单 (PowerShellVersion = 7.4)
│       ├── TinyShell.psm1                # 模块逻辑与 PSReadLine 交互键位绑定 (默认 Alt+s)
│       ├── TinyShell.Core.dll            # 编译后的核心引擎 (约 62 KB)
│       ├── TinyShell.PowerShell.dll      # 编译后的 Cmdlet 扩展 (约 10 KB)
│       ├── data/knowledge_base.json      # 51 个标准化命令知识库 (约 44 KB)
│       └── models/potion-base-2M/        # 静态权重与分词配置 (约 7.6 MB)
├── data/
│   ├── knowledge_base.json               # 意图知识库主源 (51 个常用意图)
│   ├── test_queries.json                 # 92 条评测基准
│   └── cross_language_test_cases.json    # 跨语言双向对齐测试用例
├── tests/
│   ├── test_engine.py                    # Python 端 21 项回归与安全测试
│   └── dotnet/TinyShell.Tests/           # xUnit 跨语言与单元测试工程 (16 项测试)
├── scripts/
│   ├── publish_module.ps1                # 动态 SDK 探测与一键打包发布脚本
│   ├── Install-TinyShell.ps1             # 模块安装脚本
│   ├── test_psreadline_interactive.ps1   # PSReadLine 交互行为模拟与反注册自动化测试
│   ├── test_interactive_scenarios.ps1    # 8 大真实场景自动化评测脚本
│   └── measure_pwsh_memory.ps1           # 独立常驻内存实测脚本
└── tiny_shell_intent/                    # Phase 1 的 Python 验证源码 (已完整保留备查)
```

---

## 技术实现细节

### 1. 纯 C# Model2Vec 静态推理引擎

很多 NLP 插件往往引入数十至数百兆的 ONNX Runtime 或 LibTorch C++ 动态链接库，导致发布包庞大且存在平台依赖兼容难题。

`potion-base-2M` 本质是一个词表大小为 29,528、输出维度为 64 的静态词向量表（`float[29528, 64]`）。本项目在 C# 中纯手写了两个无外部依赖的核心组件：
1. **`SafetensorsReader`**：根据 HuggingFace Safetensors 开放规范，直接读取头部 JSON 元数据偏移量，并通过 `BinaryReader` 将 7.21 MB 连续字节块无额外转换地解析为托管单精度浮点数组；
2. **`WordPieceTokenizer`**：完整实现 BERT 规范的文本清理、CJK 字符切分与最长贪心子词匹配算法（Greedy WordPiece），完全兼容 `[UNK]` 处理逻辑；
3. **推理开销**：单次向量编码与余弦点积耗时仅约 **0.2 毫秒**，内存开销仅约 **11.4 MB**。

### 2. 规则短路与多意图融合约束

混合融合（Hybrid Fusion）并非简单的加权打分，而是深度融合了终端环境特性与操作语义约束：
- **精确短路**：当输入完全匹配唯一单无歧义别名（如 `pwd` $\to$ `Get-Location`，`cls` $\to$ `Clear-Host`，`ll` $\to$ `Get-ChildItem -Path .`，`git s` $\to$ `git status`）时，直接以置信度 1.0 短路返回，耗时 **0.03 ms**；
- **本地端口 vs 远程测试**：针对 `find process using port 8080`，增强本地监听端口语义，定向抑制远程连通测试 `Test-NetConnection`，生成带有端口过滤的 `Get-NetTCPConnection`；
- **极性排斥**：当输入中出现 `stop`, `kill` 等停止词时，自动大幅衰减启动相关意图得分（降低 80%），避免操作方向颠倒；
- **操作范围守卫**：识别操作对象是单一文件（如 `data.tmp`）还是目录结构或全局回收站，杜绝将删除单文件推荐为清空回收站；
- **外部工具隔离**：针对 `git`, `docker`, `npm` 等合法命令，规则明确隔离，非白名单子命令（如 `git commit`）直接拒绝为 `unsupported_external_tool`。

### 3. 参数抽取、实体屏蔽与安全防注入

为防止破坏性指令注入：
- **实体预屏蔽（Entity Masking）**：先识别 IPv4、URL 等复杂格式并替换为占位符掩码，后续再对独立端口或数值进行提取，彻底避免将 `192.168.1.1` 的网段误解析为端口 `192`；
- **单引号安全字面量转义**：渲染命令时严格调用 `EscapePowerShellLiteral()`，阻断 `$(...)`、`;`、`|` 等任意脚本块注入可能；
- **占位符残余检查**：只要输出命令中仍存在任何未替换的 `<...>`，该命令的 `is_complete` 属性强制为 `False`。

### 4. PSReadLine 缓冲行替换（永不自动执行）

在 `TinyShell.psm1` 中使用原生 PSReadLine 提供的安全 API：
```powershell
[Microsoft.PowerShell.PSConsoleReadLine]::Replace(0, $line.Length, $selectedCmd)
```
仅替换输入框内容，不调用 `[Microsoft.PowerShell.PSConsoleReadLine]::AcceptLine()`，彻底将执行确认权留给用户。

---

## 编译与打包发布

要自行重新生成独立分发包：

```powershell
# 运行发布脚本 (自动探测 .NET SDK，编译 Release 架构并组装 modules/TinyShell 目录)
pwsh -File scripts/publish_module.ps1
```

发布后，可以直接将 `modules/TinyShell` 整个目录复制到任意安装了 PowerShell 7.4+ 的电脑的模块目录（如 `~/.local/share/powershell/Modules` 或 `$env:USERPROFILE\Documents\PowerShell\Modules`）中使用，完全脱离开发环境。

---

## 开源协议

本项目采用 [MIT License](LICENSE) 授权许可。
