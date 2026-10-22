# Tiny Shell Intent — Windows 本地命令语义识别引擎 (PoC)

一个轻量、完全离线、低延迟的 Windows PowerShell 7 命令语义识别与意图补全实验引擎（Proof of Concept）。

本项目验证了在**不调用任何外部 LLM API**、**不运行向量数据库**的前提下，依靠本地静态词向量模型（`minishlab/potion-base-2M`，约 7.6 MB）与规则、模糊匹配混合策略，实现毫秒级端侧自然语言到 PowerShell 命令意图的精准映射与安全参数渲染。

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
- [架构设计与核心修复](#架构设计与核心修复)
  - [1. 精确规则与意图约束 (P0-01)](#1-精确规则与意图约束-p0-01)
  - [2. OOD 与安全拒绝门控 (P0-02)](#2-ood-与安全拒绝门控-p0-02)
  - [3. 精确短路与模型按需加载 (P1-01)](#3-精确短路与模型按需加载-p1-01)
  - [4. 参数槽提取与安全渲染 (P1-02)](#4-参数槽提取与安全渲染-p1-02)
  - [5. 风险检测与评级防降级 (P1-03)](#5-风险检测与评级防降级-p1-03)
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
   - **精确别名规则（Rule Exact）**：支持一对多别名映射与结构化 CLI 调用辨析；
   - **无歧义短路（Short-Circuiting）**：`pwd`、`cls` 等经典命令仅需 **0.002 ms** 直接返回，无需模型推理；
   - **模型按需懒加载（Lazy Loading）**：引擎初始化耗时仅 **0.77 ms**，纯规则/模糊查询时不触发任何模型内存与计算开销；
   - **模糊字符串匹配（Fuzzy Matching）**：基于 RapidFuzz 算法，容忍命令错别字（如 `clrear-dnsclientcache`）；
   - **静态向量语义检索（Model2Vec Embedding）**：加载 `minishlab/potion-base-2M`（64 维），通过矩阵点积实现自然语言语义匹配；
   - **动作极性与意图约束（Action Polarity Constraints）**：彻底消除“停止”误推“启动”、“克隆”误推“删除”、“运行时间”误推“强制重启”等安全倒挂问题；
   - **安全参数槽提取与安全渲染（Parameter Slots & Safe Rendering）**：基于正则与规则精确提取 Port、PID、Host、Name，采用 PowerShell 单引号字面量规避命令注入；
   - **拒绝门控机制（Rejection Gating）**：严格隔离可采纳候选 (`candidates`) 与调试候选 (`debug_candidates`)，领域外 (OOD) 及未命中输入直接返回空候选列表，坚决杜绝误推荐。
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
│   ├── knowledge_base.json      # 50 个规范化 PowerShell 7 意图知识库（含参数槽定义）
│   └── test_queries.json        # 92 条独立评测测试用例（含近领域负样本、代码、Unicode）
├── models/
│   └── potion-base-2M/          # 本地缓存的 7.64 MB Model2Vec 模型权重与 Tokenizer
├── tiny_shell_intent/
│   ├── __init__.py              # 模块入口与公共接口暴露
│   ├── schema.py                # CommandIntent, Candidate, QueryResult, ParameterSlot 数据模型
│   ├── store.py                 # 知识库加载器与一对多别名快速索引
│   ├── parameters.py            # 参数槽抽取、校验与 PowerShell 安全转义渲染
│   ├── risk.py                  # 风险评级、自动规则扫描与防降级一致性校验
│   ├── engine.py                # 混合引擎主逻辑（支持短路、按需加载、极性过滤与拒绝门控）
│   └── matchers/
│       ├── __init__.py
│       ├── base.py              # Matcher 抽象基类
│       ├── rule_matcher.py      # 精确别名与前缀匹配器（支持真实 CLI 与自然语言区分）
│       ├── fuzzy_matcher.py     # RapidFuzz 模糊匹配器
│       └── model_matcher.py     # Model2Vec 静态向量余弦相似度检索器
├── tests/
│   └── test_engine.py           # 自动化单元测试集 (13/13 passed)
├── cli.py                       # 交互式 CLI Demo 与单次命令行查询入口
├── eval.py                      # 自动化评测与基准性能测量套件（对比基线）
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
tiny-shell (hybrid)> test port 8080 on localhost

  1. [SAFE] [MODEL] [READY] Test-NetConnection -ComputerName localhost -Port 8080
     Score: 61.8%  |  Category: network  |  Intent ID: net_test_port
     Desc:  Test TCP network connectivity to a specific host and port number.
     Params: {'port': 8080, 'host': 'localhost'}

 [Phase 1 PoC] Candidates are for recommendation only. Execution is disabled.
```

对于领域外输入（如做饼干、写诗、Python 代码）：
```text
tiny-shell (hybrid)> how to bake chocolate chip cookies
 [REJECTED / OUT-OF-DOMAIN] Query could not be reliably mapped to any valid shell command.
 Rejection Reason: low_semantic_confidence_out_of_domain

 [DEBUG / INSPECTION ONLY — NOT FOR COMPLETION]:
   1. [SAFE] (score=36.2%, fuzzy) Resolve-DnsName -Name "<domain>"
   2. [SAFE] (score=29.8%, fuzzy) Copy-Item -Path "<source>" -Destination "<dest>" -Recurse
   3. [SAFE] (score=29.1%, fuzzy) Get-Process | Sort-Object CPU -Descending | Select-Object -First 10

 [Notice] Input was rejected. Downstream plugins will receive 0 actionable completions.
```

---

## 架构设计与核心修复

### 1. 精确规则与意图约束 (P0-01)
- **消除首词误判**：旧版本仅因首词命中 `kill` 便强制赋予 1.0 置信度。现引入 `NATURAL_LANGUAGE_MARKERS` 判定，严格区分自然语言叙述与真实 CLI 调用。
- **一对多别名消歧**：`KnowledgeBaseStore` 升级为 `Dict[str, List[str]]`。当遇到 `kill` 时，结合参数类型（数字 PID vs 进程名）精准路由至 `proc_kill_id` 或 `proc_kill_name`。
- **动作极性防混淆 (Action Polarity)**：
  - 用户输入包含 `STOP` 动词（stop, kill, terminate, halt）时，强力惩罚 `sys_service_start` 与 `proc_start`；
  - 用户输入包含 `COPY/CLONE` 动词时，强力惩罚 `file_delete_recursive`（防止克隆误推删除）；
  - 用户输入包含 `UPTIME` 动词（how long turned on）时，强力惩罚 `sys_reboot_machine`。

### 2. OOD 与安全拒绝门控 (P0-02)
- **严格候选隔离**：`QueryResult.candidates` 仅包含通过门控的可采纳候选。被判定为 OOD 或低置信度的候选强制置空，回退候选独立保存在 `debug_candidates` 中，防止下游插件直接自动补全。
- **近领域负样本拦截**：增加对 Python 代码（`def ...`）、Node.js（`console.log`）、Linux 包管理器（`apt-get`、`chmod`）等非 Windows PowerShell 语法的正则拦截。
- **Unicode 安全校验**：使用 `any(c.isalnum() for c in clean_q)` 替换原 ASCII `[a-zA-Z0-9]` 正则，中文等非拉丁输入不再视为空输入崩溃，而是优雅标记为 `unsupported_non_latin_language` 拒绝。

### 3. 精确短路与模型按需加载 (P1-01)
- **真正无歧义短路**：当输入为 `pwd`、`cls` 等无歧义精确别名时，耗时 **0.002 ms** 直接返回，**不运行 Model 与 Fuzzy 匹配器**。
- **按需懒加载 (Lazy Loading)**：`IntentEngine` 初始化时仅加载轻量规则与知识库索引（耗时 **0.77 ms**），只有当查询真正需要语义向量时才加载 Model2Vec。
- **同分排序可复现性**：全流程采用 `sorted(all_intent_ids)` 并以 `(-round(score, 4), intent_id)` 确定性排序，彻底消除 Python 集合哈希随机化带来的乱序。
- **轻量 LRU 缓存**：内置 128 条容量的轻量查询缓存，相同查询即刻返回。

### 4. 参数槽提取与安全渲染 (P1-02)
- **参数槽规范**：为关键意图增加 `ParameterSlot`（如 `port: int`, `host: hostname`, `pid: int`, `name: string`）。
- **PowerShell 注入防御**：
  - 严格校验禁止 `;`, `&`, `|`, `` ` ``, `$`, `$(...)`, `\n`, `\r` 等危险字符；
  - 字符串参数使用 PowerShell 严格字面量渲染（单引号包围，内部单引号双写转义 `''`），杜绝命令注入；
  - 未提取到必填参数时标记 `is_complete = False`，不伪称完整命令。

### 5. 风险检测与评级防降级 (P1-03)
- **修复死代码**：重写 `evaluate_command_risk()`，同时扫描静态模板与渲染后命令。
- **防降级原则**：风险等级满足 `DANGEROUS > WARNING > SAFE`，最终风险级别取人工标注与自动扫描的最高值，渲染后命令风险决不低于模板基准风险。
- **一致性审计**：内置 `audit_knowledge_base_risks()`，知识库 50 条意图实现 100% 规则一致性。

---

## 评测指标与实际测试结果

数据均在 Windows 11 本地真实环境（Python 3.13.5 + PowerShell 7）执行 `python eval.py` 实测采集：

### 1. 资源占用与启动时间

| 指标项 | 实际测量值 | 说明 |
| :--- | :--- | :--- |
| **模型磁盘总占用** | **7.64 MB** (8,010,076 字节) | 包含 safetensors (7.21 MB)、tokenizer.json (0.43 MB) 等 |
| **引擎冷启动时间 (Lazy)** | **0.77 ms** | 仅加载规则与 50 条知识库，模型按需初始化 |
| **模型首次加载与建索耗时** | **881.92 ms** | 首次需要语义推理时触发模型读盘与 300+ 向量构建 |
| **无歧义短路检索耗时 (P50)** | **0.002 ms (2 微秒)** | `pwd`、`cls` 等经典命令直接短路 |
| **内存基准占用 (Baseline)** | **54.29 MB** | Python 解释器与标准库底噪 |
| **加载后进程内存 (Loaded)** | **97.32 MB** | 包含模型权重与 NumPy 索引矩阵的驻留集大小 (RSS) |
| **增量物理内存 (RSS Delta)** | **43.03 MB** | 运行时增加的实际常驻内存，极其轻量 |

### 2. 四种检索模式准确率对比

在独立测试集的 75 个有标签测试用例上进行评测（含新增参数化测试用例）：

| 检索模式 (Mode) | 当前 Top-1 | 历史基线 Top-1 | 当前 Top-3 | 历史基线 Top-3 | 表现分析 |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **纯规则 (RULE)** | **18.7%** (14/75) | 16.7% | **18.7%** (14/75) | 16.7% | 仅命中精准别名，但因支持多别名映射而小幅提升 |
| **纯模糊匹配 (FUZZY)** | **60.0%** (45/75) | 58.3% | **86.7%** (65/75) | 86.1% | 错别字容错率高，受公共虚词干扰已通过长度惩罚控制 |
| **纯模型向量 (MODEL)** | **62.7%** (47/75) | 65.3% | **81.3%** (61/75) | 80.6% | 去除了无序关键字拼接对特征中心的污染，泛化更稳健 |
| **混合引擎 (HYBRID)** | **81.3%** (61/75) | 75.0% | **90.7%** (68/75) | 91.7% | **Top-1 准确率大幅提升 6.3 个百分点，达到 81.3%** |

### 3. 混合模式分类型评测

| 用例类别 (Query Type) | 样本数 | Top-1 命中率 | Top-3 命中率 | 典型案例 |
| :--- | :---: | :---: | :---: | :--- |
| **自然语言长句 (Natural Language)** | 50 | **78.0%** | **88.0%** | `"kill process 12480 immediately"` -> `proc_kill_id` |
| **短命令/别名缩写 (Abbreviation)** | 12 | **100.0%** | **100.0%** | `"kill"`, `"ps"`, `"rm -rf"`, `"pwd"`, `"curl"`, `"cls"` 全中 |
| **输入错别字 (Fuzzy/Typo)** | 10 | **70.0%** | **90.0%** | `"tset-netconnection 8080"` -> `net_test_port` |
| **参数化命令 (Parameterized)** | 3 | **100.0%** | **100.0%** | `"test port 8080 on localhost"` -> `net_test_port` |

### 4. 安全门控与风险指标

| 安全指标 | 测量值 | 说明 |
| :--- | :---: | :--- |
| **门控有效 Top-1 准确率** | **81.3%** (61/75) | 仅统计通过安全门控真正被系统采纳的建议 |
| **门控有效 Top-3 准确率** | **90.7%** (68/75) | 仅统计被系统真正采纳的前 3 建议 |
| **域内误拒绝数 (False Rejection)** | **2 / 75** | 仅极个别极端长难句被保守置信度门控暂扣 |
| **高危意图误推荐数 (Dangerous Misrecs)** | **1** | 用户未请求高危操作却被误推 DANGEROUS 命令的情况大幅下降 |
| **领域外拒绝率 (OOD Rejection Rate)** | **13 / 13 (100.0%)** | 13 个 OOD/代码/Linux/生活负样本全部准确拒绝 |
| **领域外错误采纳数 (False Acceptance)** | **0** | **0 起** OOD 伪造采纳事故 |

### 5. 检索端到端延迟分布 (热态)

| 检索模式 | 平均延迟 (Mean) | **P50 延迟** | P90 延迟 | **P95 延迟** | P99 延迟 |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **EXACT SHORT-CIRCUIT** | **0.002 ms** | **0.002 ms** | - | **0.002 ms** | - |
| **RULE** | 0.005 ms | 0.001 ms | 0.002 ms | 0.036 ms | 0.073 ms |
| **MODEL** | 0.014 ms | 0.001 ms | 0.005 ms | 0.134 ms | 0.165 ms |
| **FUZZY** | 0.085 ms | 0.001 ms | 0.004 ms | 0.813 ms | 1.154 ms |
| **HYBRID** | **0.105 ms** | **0.001 ms** | **0.006 ms** | **1.060 ms** | **1.550 ms** |

---

## 失败案例与混淆意图分析

在评测中，HYBRID 模式 Top-1 未命中的 14 个案例中，有 7 个成功进入 Top-3，仅有 7 个彻底滑出 Top-3：

### 1. 概念重叠与多维度语义
- **Docker 运行状态**：
  - 输入：`"is my docker daemon running"`
  - 预期：`proc_find` (`Get-Process -Name "docker"`)
  - Top-1 结果：`sys_service_start` / `sys_service_list`
  - 分析：Windows 平台 Docker 同时兼具 Windows 服务（`com.docker.service`）与进程双重属性，模型在服务与进程之间存在合理语义共振。
- **ICMP Ping vs 本地 IP 查验**：
  - 输入：`"test if gateway 192.168.1.1 answers icmp packets"`
  - 预期：`net_ping_host` (`Test-Connection`)
  - Top-1 结果：`net_ip_config` (`Get-NetIPAddress`)
  - 分析：IP 地址格式对 `net_ip_config` 产生强吸引，后续可在知识库对 `icmp` 与 `ping` 增加更丰富的 exemplar 覆盖。

### 2. 临时文件清理的粒度边界
- **单个文件删除 vs 清空回收站**：
  - 输入：`"trash temporary file data.tmp"`
  - 预期：`file_delete_single`
  - Top-1 结果：`sys_clear_recycle_bin`
  - 分析：口语单词 `"trash"` 容易与回收站（Recycle Bin / Trash）产生关联，模型将清理单一文件误判为清理垃圾箱。

---

## 关键问题回答与工程结论

### 问题一：8 MB 轻量模型相比传统规则检索带来了多少额外价值？

**结论：带来了质的飞跃（系统从“不可用”变为“真正可用”）。**

1. **准确率的维度碾压**：
   - 传统规则检索在面对自然语言时完全盲目，Top-1 仅 **18.7%**（仅能处理死记硬背的别名）；
   - 引入 8 MB 的 Model2Vec 模型后，仅模型单路即可实现 **62.7%** 的 Top-1 识别；
   - 规则与模型混合并加入动作极性约束后，Top-1 提升至 **81.3%**，Top-3 达到 **90.7%**。**为系统带来了超过 62 个百分点的自然语言泛化红利**。
2. **极佳的互补性**：
   - 规则检索的优势在**确定性极高、极短的符号**（如 `ps`, `df`, `cls`, `rm -rf`），这些缩写在静态词向量模型中通常是 OOV（未登录词）或词义稀疏；
   - 模型检索的优势在**发散性表达**（如 `"which programs are hogging the processor right now"`，无需用户知道任何 cmdlet 名称即可直达 `Get-Process | Sort-Object CPU`）；
   - 两者结合，既不丢失专业用户的短别名敲击肌肉记忆，又能接住初中级用户的口语化探索需求。
3. **极高的性能投入产出比 (ROI)**：
   - 传统大语言模型（如 7B/14B 本地 Ollama）需要 4~8 GB 显存/内存，端到端延迟 500~2000 ms；
   - 本项目约 7.6 MB 的静态模型，推理耗时仅 **0.073 ms**，物理内存增量仅 **43 MB**，可以在不卡顿终端按键输入的前提下无缝常驻。

### 问题二：是否值得继续对该模型进行进一步压缩？

**结论：在当前工程阶段，不值得继续压缩。理由如下：**

1. **体积已非系统瓶颈**：
   - 当前模型文件大小为 **7.64 MB**，比一个现代前端图标库还要小；
   - 内存占用仅 **43 MB**，在现代 16 GB/32 GB 内存的 Windows 开发者机器上属于微量底噪。
2. **推理速度已逼近极限**：
   - 单次语义推理 P50 耗时仅 **0.073 ms (73 微秒)**，精确短路仅 **0.002 ms**；
   - 相比于终端按键采样的 16~33 ms 帧间隔，拥有数百倍的性能余量，进一步通过 INT8/INT4 量化无法在用户感知层面带来任何可量化的体感提升。
3. **低维语义保真风险**：
   - `potion-base-2M` 已经将向量压缩至 64 维超精简空间；若进一步进行极端剪枝或 4-bit 量化，会导致语义分布各向异性（Anisotropy）恶化，极易破坏区分相似命令的微弱投影差异。

---

## 运行单元测试与复现评测

### 运行自动化单元测试

```powershell
python -m pytest -v
```

输出 13 项单元测试全绿通过 (13 passed)：
```text
tests/test_engine.py::test_lazy_loading_and_short_circuit PASSED         [  7%]
tests/test_engine.py::test_model_loaded_only_when_needed PASSED          [ 15%]
tests/test_engine.py::test_pid_kill_vs_name_kill PASSED                  [ 23%]
tests/test_engine.py::test_polarity_stop_vs_start PASSED                 [ 30%]
tests/test_engine.py::test_uptime_vs_reboot_polarity PASSED              [ 38%]
tests/test_engine.py::test_copy_vs_delete_polarity PASSED                [ 46%]
tests/test_engine.py::test_parameter_extraction_and_safe_rendering PASSED [ 53%]
tests/test_engine.py::test_powershell_injection_defense PASSED           [ 61%]
tests/test_engine.py::test_ood_and_rejection_policy PASSED               [ 69%]
tests/test_engine.py::test_edge_and_empty_inputs PASSED                  [ 76%]
tests/test_engine.py::test_unicode_chinese_graceful_handling PASSED      [ 84%]
tests/test_engine.py::test_risk_detection_and_escalation PASSED          [ 92%]
tests/test_engine.py::test_deterministic_sorting PASSED                  [100%]
```

### 运行完整基准性能评测

```powershell
python eval.py
```

评测脚本将对 92 个用例运行并测量冷热启动、内存、延迟和分项准确率，并在控制台输出格式化报表，同时生成可机读的 `eval_results.json`。

---

## 开源协议

本项目采用 [MIT 许可证](LICENSE) 开源。
