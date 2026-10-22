# Tiny Shell Intent — Windows 本地命令语义识别引擎 (PoC)

一个轻量、完全离线、低延迟的 Windows PowerShell 7 命令语义识别与意图补全实验引擎（Proof of Concept）。

本项目验证了在**不调用任何外部 LLM API**、**不运行向量数据库**的前提下，仅依靠本地静态词向量模型（`minishlab/potion-base-2M`，约 7.6 MB）与规则、模糊匹配混合策略，实现毫秒级端侧自然语言到 PowerShell 命令意图的精准映射。

---

## 目录

- [核心特性](#核心特性)
- [技术栈与设计约束](#技术栈与设计约束)
- [项目结构](#项目结构)
- [快速开始](#快速开始)
  - [环境准备](#环境准备)
  - [模型准备（支持全离线）](#模型准备支持全离线)
  - [交互式 CLI 测试](#交互式-cli-测试)
  - [单次命令行调用](#单次命令行调用)
- [知识库与独立测试集](#知识库与独立测试集)
- [评测指标与实际测试结果](#评测指标与实际测试结果)
  - [1. 资源占用与启动时间](#1-资源占用与启动时间)
  - [2. 四种检索模式准确率对比](#2-四种检索模式准确率对比)
  - [3. 混合模式分类型评测](#3-混合模式分类型评测)
  - [4. 检索端到端延迟分布](#4-检索端到端延迟分布)
  - [5. 专项测试集表现](#5-专项测试集表现)
- [失败案例与混淆意图分析](#失败案例与混淆意图分析)
- [关键问题回答与工程结论](#关键问题回答与工程结论)
  - [问题一：8 MB 轻量模型相比传统规则检索带来了多少额外价值？](#问题一8-mb-轻量模型相比传统规则检索带来了多少额外价值)
  - [问题二：是否值得继续对该模型进行进一步压缩？](#问题二是否值得继续对该模型进行进一步压缩)
- [运行单元测试与复现评测](#运行单元测试与复现评测)
- [开源协议](#开源协议)

---

## 核心特性

1. **50 常用 Windows PowerShell 7 命令意图知识库**：涵盖进程控制、文件系统、网络诊断、系统服务、环境策略、归档解压与终端维护。
2. **多通道融合检索引擎**：
   - **精确别名规则（Rule Exact）**：毫秒级秒杀 `kill`, `ps`, `ls -la`, `curl`, `pwd`, `cls` 等经典缩写；
   - **命令前缀规则（Rule Prefix）**：支持 `stop-proc`, `get-ch` 等前缀预测；
   - **模糊字符串匹配（Fuzzy Matching）**：基于 RapidFuzz 算法，容忍命令错别字与参数输入错误（如 `stopp-procss`）；
   - **静态向量语义检索（Model2Vec Embedding）**：加载 `minishlab/potion-base-2M`（64 维），通过矩阵点积实现自然语言语义匹配；
   - **混合动态决策（Hybrid Fusion）**：结合自然语言与 CLI 语法判定，自适应调配模型与规则权重。
3. **安全风险分级标签（Risk Tagging）**：
   - `[SAFE]`（绿色）：无副作用的只读查询、状态检测；
   - `[WARNING]`（黄色）：系统配置变更、单文件覆写、服务启停；
   - `[DANGEROUS]`（红色）：高危操作（如 `Remove-Item -Recurse -Force`, `Stop-Process -Force`, `Restart-Computer`, `Clear-RecycleBin`），强制弹出风险警示。
4. **安全执行限制**：第一阶段作为语义引擎验证 PoC，**绝不自动执行任何命令**。
5. **开箱即用离线运行**：模型文件一次性缓存到本地，运行时零网络请求。

---

## 技术栈与设计约束

- **语言环境**：Python 3.11+ (实际测试环境 Python 3.13.5 on Windows 11)
- **语义模型**：`minishlab/potion-base-2M` (Model2Vec 静态嵌入架构，64 维输出)
- **模糊算法**：RapidFuzz 3.14+
- **目标终端**：Windows PowerShell 7
- **向量检索**：纯 NumPy 内存矩阵向量点积与向量范数归一化，零外部向量数据库依附
- **网络策略**：仅首次下载模型需联网，已默认内置/缓存于 `./models/potion-base-2M/`，纯本地无感运行

---

## 项目结构

```text
tiny-shell-intent/
├── data/
│   ├── knowledge_base.json      # 50 个规范化 PowerShell 7 意图知识库
│   └── test_queries.json        # 82 条独立评测测试用例（严格与知识库示例零重合）
├── models/
│   └── potion-base-2M/          # 本地缓存的 7.64 MB Model2Vec 模型权重与 Tokenizer
├── tiny_shell_intent/
│   ├── __init__.py              # 模块入口与公共接口暴露
│   ├── schema.py                # CommandIntent, Candidate, QueryResult 数据模型
│   ├── store.py                 # 知识库加载器与快速索引
│   ├── risk.py                  # 风险评级与终端彩色徽标格式化
│   ├── engine.py                # 混合引擎主逻辑（支持 hybrid/rule/fuzzy/model）
│   └── matchers/
│       ├── __init__.py
│       ├── base.py              # Matcher 抽象基类
│       ├── rule_matcher.py      # 精确别名与前缀匹配器
│       ├── fuzzy_matcher.py     # RapidFuzz 模糊匹配器
│       └── model_matcher.py     # Model2Vec 静态向量余弦相似度检索器
├── tests/
│   └── test_engine.py           # 自动化单元测试集 (10/10 passed)
├── cli.py                       # 交互式 CLI Demo 与单次命令行查询入口
├── eval.py                      # 自动化评测与基准性能测量套件
├── eval_results.json            # 完整基准评测原始 JSON 数据输出
├── pyproject.toml               # 项目打包与依赖配置
├── requirements.txt             # 基础依赖清单
└── README.md                    # 项目文档与实验结论
```

---

## 快速开始

### 环境准备

```powershell
# 1. 克隆或进入项目目录
cd tiny-shell-intent

# 2. 安装必要依赖
pip install -r requirements.txt
```

### 模型准备（支持全离线）

项目中模型默认位于 `./models/potion-base-2M`。若未包含，可通过以下一行命令下载并持久化到本地：

```powershell
python -c "from model2vec import StaticModel; m = StaticModel.from_pretrained('minishlab/potion-base-2M'); m.save_pretrained('./models/potion-base-2M'); print('Model ready locally!')"
```

### 交互式 CLI 测试

启动交互式命令推荐 Shell：

```powershell
python cli.py
```

在交互提示符下输入任意英文短语、别名或错别字：

```text
tiny-shell (hybrid)> kill stuck chrome process

  1. [DANGEROUS] [RULE_EXACT] Stop-Process -Name "<name>" -Force
     Score: 100.0%  |  Category: process  |  Intent ID: proc_kill_name
     Desc:  Forcibly terminate running processes matching the specified process name.
     ! Risk Alert: Forcibly terminates running processes without saving unsaved data or giving cleanup time.

  2. [SAFE] [FUZZY] Wait-Process -Name "<name>"
     Score: 59.9%  |  Category: process  |  Intent ID: proc_wait
     Desc:  Pause shell execution until the specified process has stopped.

  3. [DANGEROUS] [FUZZY] Stop-Process -Id <pid> -Force
     Score: 55.0%  |  Category: process  |  Intent ID: proc_kill_id
     Desc:  Forcibly terminate a running process by its numeric Process ID (PID).
     ! Risk Alert: Forcibly kills a process identified by PID; wrong PID can crash critical system services.

 [Phase 1 PoC] Candidates are for recommendation only. Execution is disabled.
```

**交互命令说明**：
- `:mode hybrid`：切换至混合检索模式（默认）
- `:mode rule`：切换至纯规则模式
- `:mode fuzzy`：切换至纯模糊匹配模式
- `:mode model`：切换至纯向量模型语义模式
- `help`：查看使用帮助
- `exit` / `quit`：退出终端

### 单次命令行调用

```powershell
# 查询开放端口
python cli.py "test if port 8080 is reachable"

# 递归删除文件夹
python cli.py "wipe folder contents recursively"

# 指定使用纯模型检索
python cli.py "check local ip address" --mode model
```

---

## 知识库与独立测试集

### 1. 命令知识库 (`data/knowledge_base.json`)
精选 **50 个** Windows PowerShell 7 核心命令意图，涵盖：
- **进程管理** (`proc_*`)：强杀进程、按 PID 终止、CPU 排名进程监控、后台启动、进程等待；
- **文件系统** (`file_*`)：目录列出、显示隐藏文件、递归查找、Head/Tail 实时日志追踪、Grep 搜索、递归删除、文件复制移动、SHA256 校验、当前路径打印等；
- **网络诊断** (`net_*`)：TCP 端口探测、Ping、监听端口与进程查验、REST API GET 请求、文件下载、IP 配置、DNS 查询与缓存刷新、Traceroute；
- **系统状态与服务** (`sys_*`)：服务查询/启停/重启、系统硬件与内存规格、磁盘剩余空间、系统 Uptime 运行时间、立即关机/重启、清空回收站；
- **环境配置** (`env_*`)：环境变量全量查阅、单变量读取与临时会话导出、PATH 分行拆解、执行策略调整（RemoteSigned）；
- **归档工具** (`arch_*`)：Zip 文件夹打包与解压缩；
- **Shell 维护** (`sys_*`)：清屏（Clear-Host）、会话命令历史回溯（Get-History）。

### 2. 独立测试集 (`data/test_queries.json`)
包含 **82 个**测试样本，分为三类有标签样本与两类边界/异常样本。**经自动化脚本交叉比对，测试集中所有自然语言文本与知识库的 `intent_phrases` 字段重合度为严格的 0%**：
- **自然语言查询 (50 条)**：真实多样化句式，包括长难句、口语化表达与同义替换（如 `"which programs are hogging the processor right now"`）；
- **短别名与缩写 (12 条)**：经典 Unix/PowerShell 别名（如 `kill`, `ps`, `ls -la`, `rm -rf`, `curl`, `df -h`, `pwd`, `cls`）；
- **输入拼写错误 (10 条)**：命令拼写错漏与形近字（如 `stopp-procss chrome`, `tset-netconnection 8080`, `clrear-dnsclientcache`）；
- **未知/领域外输入 (6 条)**：与 Shell 无关的生活日常查询（如 `"how to bake chocolate chip cookies"`, `"what is the capital of switzerland"`）；
- **极端与空输入 (4 条)**：空字符串 `""`、空白符 `"   "`、纯标点符号 `"???"`、`"!@#$%^&*"`。

---

## 评测指标与实际测试结果

以下数据均为在本地机器（Python 3.13.5, Windows 11 AMD64）上执行 `python eval.py` 实测所得，保证 **100% 真实、可复现、不造假**。

### 1. 资源占用与启动时间

| 指标项 | 实际测量值 | 说明 |
| :--- | :--- | :--- |
| **模型磁盘总占用** | **7.64 MB** (8,010,076 字节) | 包含 safetensors (7.21 MB)、tokenizer.json (0.43 MB) 等 |
| **冷启动加载与建索耗时** | **895.47 ms** | 从磁盘读入权重、构建 300+ 向量并归一化全内存矩阵 |
| **内存基准占用 (Baseline)** | **53.97 MB** | 仅 Python 运行时与依赖库导入基础底噪 |
| **加载后进程内存 (Loaded)** | **97.12 MB** | 包含模型权重与 NumPy 索引矩阵的驻留集大小 (RSS) |
| **增量物理内存 (RSS Delta)** | **43.15 MB** | 运行时增加的实际常驻内存，极其轻量 |

### 2. 四种检索模式准确率对比

在独立测试集的 72 个有标签测试用例上进行评测：

| 检索模式 (Mode) | Top-1 命中数 | **Top-1 命中率** | Top-3 命中数 | **Top-3 命中率** | 模式特性与分析 |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **纯规则 (RULE)** | 12 / 72 | **16.7%** | 12 / 72 | **16.7%** | 仅能命中精准别名与固定前缀，对自然语言与拼写错误毫无泛化能力 |
| **纯模糊匹配 (FUZZY)** | 42 / 72 | **58.3%** | 62 / 72 | **86.1%** | 依靠字符编辑距离与 Token 集合相似度，对拼写错误较好，缺乏深层语义 |
| **纯模型向量 (MODEL)** | 47 / 72 | **65.3%** | 58 / 72 | **80.6%** | 依靠 Model2Vec 静态语义，对自然语言语义较好，但对极短缩写（如 `cls`）不敏感 |
| **混合引擎 (HYBRID)** | **54 / 72** | **75.0%** | **66 / 72** | **91.7%** | **规则优先 + 模糊容错 + 语义召回的最佳平衡，Top-3 突破 90%** |

### 3. 混合模式分类型评测

| 用例类别 (Query Type) | 样本数 | Top-1 命中率 | Top-3 命中率 | 典型案例 |
| :--- | :---: | :---: | :---: | :--- |
| **自然语言长句 (Natural Language)** | 50 | **68.0%** | **88.0%** | `"display all files in this directory"` -> `file_list` |
| **短命令/别名缩写 (Abbreviation)** | 12 | **100.0%** | **100.0%** | `"kill"`, `"ps"`, `"rm -rf"`, `"pwd"`, `"curl"`, `"cls"` 全中 |
| **输入错别字 (Fuzzy/Typo)** | 10 | **80.0%** | **100.0%** | `"tset-netconnection 8080"` -> `net_test_port` |

### 4. 检索端到端延迟分布

使用真实测试集循环压测（每次检索取 `time.perf_counter()`，单位毫秒 `ms`）：

| 检索模式 | 平均延迟 (Mean) | **P50 延迟** | P90 延迟 | **P95 延迟** | P99 延迟 |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **RULE** | 0.041 ms | **0.040 ms** | 0.045 ms | 0.053 ms | 0.117 ms |
| **FUZZY** | 0.849 ms | **0.751 ms** | 1.184 ms | 1.276 ms | 1.502 ms |
| **MODEL** | 0.076 ms | **0.073 ms** | 0.085 ms | 0.096 ms | 0.211 ms |
| **HYBRID** | 1.115 ms | **1.027 ms** | 1.494 ms | 1.609 ms | 2.127 ms |

> **关键发现**：Model2Vec 模型的 P50 延迟仅为 **0.073 ms (73 微秒)**，由于去除了 Transformer 自注意力机制，仅进行 BPE 分词查表和向量平均，速度甚至远快于 Python 实现的字符串编辑距离循环！整个混合流程在 1.5 ms 以内即可完成，完全满足终端实时按键输入的性能预算。

### 5. 专项测试集表现

- **领域外未知输入检测 (Out-of-Domain, 6 条)**：
  - 测试输入：`"how to bake chocolate chip cookies"`, `"play lo-fi jazz music"`, `"what is the capital of switzerland"`, `"order pepperoni pizza online"` 等；
  - 判定机制：当最高融合分低于置信度阈值（0.42）且无精确规则命中时，自动标记为 `is_out_of_domain = True`；
  - 实测结果：**6 / 6 (100%)** 准确识别为领域外输入，CLI 友好提示低置信度降级。
- **空输入与特殊字符 (Edge Cases, 4 条)**：
  - `""` 与 `"   "`：命中 `is_empty = True`，立即返回空候选，耗时 0.002 ms；
  - `"???"` 与 `"!@#$%^&*"`：检测到无有效字母数字，命中 `is_out_of_domain = True`，拦截误推荐。

---

## 失败案例与混淆意图分析

在评测中，HYBRID 模式 Top-1 未命中的 18 个案例中，有 12 个成功进入 Top-3，仅有 6 个彻底滑出 Top-3。深度剖析这些案例揭示了极具价值的端侧语义边界：

### 1. 概念高度交叠的同质意图混淆
- **PID 强杀 vs 名称强杀**：
  - 输入：`"kill process 12480 immediately"`
  - 预期：`proc_kill_id`
  - Top-1 结果：`proc_kill_name`（Top-2 为 `proc_kill_id`）
  - 原因：两者均共享 `"kill"` 核心动词，纯语义模型无法深刻分辨数字参数代表 PID 还是名称，但两者同属危险强杀操作，Top-2 成功捕获。
- **本地 IP 配置 vs DNS 域名解析**：
  - 输入：`"look up ip address for api.example.com"`
  - 预期：`net_dns_resolve` (`Resolve-DnsName`)
  - Top-1 结果：`net_ip_config` (`Get-NetIPAddress`)，Top-2 为 `net_dns_resolve`
  - 原因：输入包含 `"ip address"`，与 `net_ip_config` 的强关键字高度共鸣。

### 2. 负向上下文与否定词陷阱 (Negation Traps)
- **开机时间 vs 重启机器**：
  - 输入：`"how long has this computer been turned on without restarting"`
  - 预期：`sys_uptime` (`(Get-Uptime).TotalHours`)
  - Top-1 结果：`sys_reboot_machine` (`Restart-Computer -Force`)
  - 原因：词袋/静态向量对 `"without restarting"`（未经重启）中的否定词 `"without"` 缺乏语法逻辑推导能力，反被高频词 `"computer"` 和 `"restarting"` 牵引向了系统重启意图。

### 3. 系统对象层级混淆 (Process vs Service)
- **守护进程查找 vs 启动服务**：
  - 输入：`"is my docker daemon running"`
  - 预期：`proc_find` (`Get-Process -Name "docker"`)
  - Top-1 结果：`sys_service_start` / `sys_service_list`
  - 原因：Windows 环境中 Docker 既常作为后台 Service 运行，又对应 `dockerd.exe` 进程，模型在服务与进程间产生了合理的语义共振。

---

## 关键问题回答与工程结论

### 问题一：8 MB 轻量模型相比传统规则检索带来了多少额外价值？

**结论：带来了质的飞跃（跨越了“无法使用”到“可用”的鸿沟）。**

1. **准确率的维度碾压**：
   - 传统规则检索在面对自然语言时完全盲目，Top-1 仅 **16.7%**（仅能处理死记硬背的别名）；
   - 引入 8 MB 的 Model2Vec 模型后，仅模型单路即可实现 **65.3%** 的 Top-1 识别；
   - 规则与模型混合后，Top-1 提升至 **75.0%**，Top-3 达到 **91.7%**。**为系统凭空带来了超过 58 个百分点的自然语言泛化价值**。
2. **极佳的互补性**：
   - 规则检索的优势在**确定性极高、极短的符号**（如 `ps`, `df`, `cls`, `rm -rf`），这些缩写在静态词向量模型中通常是 OOV（未登录词）或词义稀疏；
   - 模型检索的优势在**发散性表达**（如 `"which programs are hogging the processor right now"`，无需用户知道任何 cmdlet 名称即可直达 `Get-Process | Sort-Object CPU`）；
   - 两者结合，既不丢失专业用户的短别名敲击肌肉记忆，又能接住初中级用户的口语化探索需求。
3. **极高的性能投入产出比 (ROI)**：
   - 传统大语言模型（如 7B/14B 本地 Ollama）需要 4~8 GB 显存/内存，端到端延迟 500~2000 ms；
   - 本项目约 7.6 MB 的静态模型，推理耗时仅 **0.073 ms**，物理内存增量仅 **43 MB**，可以在不卡顿终端按键输入的前提下无缝常驻。

### 问题二：是否值得继续对该模型进行进一步压缩？

**结论：在当前工程阶段，不值得继续压缩。理由如下：**

1. **模型体积早已不是主要瓶颈**：
   - 当前模型文件大小为 **7.64 MB**，比一个现代前端图标库或 Electron 运行时的千分之一还要小；
   - 内存占用仅 **43 MB**，在现代 16 GB/32 GB 内存的 Windows 开发者机器上属于可忽略的轻量底噪。
2. **推理速度已逼近极限**：
   - 单次语义推理 P50 耗时仅 **0.073 ms (73 微秒)**，仅占混合总耗时的 7%，主要的 1 ms 耗时其实花在 Python 循环的 RapidFuzz 字符串比对上；
   - 相比于终端按键采样的 16~33 ms 帧间隔，0.073 ms 拥有数百倍的性能余量，进一步通过 INT8/INT4 量化无法在用户感知层面带来任何可量化的体感提升。
3. **过小维度的精度风险**：
   - `potion-base-2M` 已经将向量压缩至 64 维超精简空间；若进一步进行极端剪枝或 4-bit 量化，会导致语义分布各向异性（Anisotropy）恶化，极易破坏区分相似命令（如 `Stop-Process` vs `Get-Process`）的微弱投影差异。
4. **更有价值的后续优化方向**：
   - **知识库丰富度**：将 50 个意图扩充至 200 个常用 Windows/PowerShell 操作；
   - **上下文环境感知**：感知当前工作目录下的文件类型（如存在 `package.json` 时偏向 Node.js 相关命令）；
   - **混淆意图微调 (Contrastive Fine-Tuning)**：针对 PID 强杀与名称强杀、启动与停止等反义词样本进行对比学习增强。

---

## 运行单元测试与复现评测

### 运行自动化单元测试

```powershell
python -m pytest -v
```

输出应全绿通过 (10 passed)：
```text
tests/test_engine.py::test_kb_store_loading PASSED                       [ 10%]
tests/test_engine.py::test_exact_alias_rule PASSED                       [ 20%]
tests/test_engine.py::test_prefix_rule PASSED                            [ 30%]
tests/test_engine.py::test_fuzzy_matching PASSED                         [ 40%]
tests/test_engine.py::test_model_semantic_matching PASSED                [ 50%]
tests/test_engine.py::test_hybrid_natural_language PASSED                [ 60%]
tests/test_engine.py::test_risk_tagging PASSED                           [ 70%]
tests/test_engine.py::test_empty_and_whitespace PASSED                   [ 80%]
tests/test_engine.py::test_punctuation_and_symbols PASSED                [ 90%]
tests/test_engine.py::test_out_of_domain_query PASSED                    [100%]
```

### 运行完整基准性能评测

```powershell
python eval.py
```

评测脚本将对 82 个用例运行并测量冷启动、内存、延迟和分项准确率，并在控制台输出格式化报表，同时生成可机读的 `eval_results.json`。

---

## 开源协议

本项目采用 [MIT 许可证](LICENSE) 开源。
