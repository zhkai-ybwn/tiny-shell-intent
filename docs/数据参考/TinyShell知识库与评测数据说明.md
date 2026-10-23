# TinyShell 知识库与评测数据说明

> 核对日期：2026-10-22。路径相对于仓库根目录。

## 文件职责

| 文件 | 用途 |
|---|---|
| `data/knowledge_base.json` | 运行时知识库唯一维护源，当前为 51 个意图 |
| `data/test_queries.json` | 固定检索与拒绝评测集，当前为 92 条 |
| `data/cross_language_test_cases.json` | Python／C# 的 Tokenizer、向量和检索对照 fixture |
| `models/potion-base-2M/model.safetensors` | 静态词向量权重 |
| `models/potion-base-2M/tokenizer.json` | 分词词表与配置 |
| `models/potion-base-2M/README.md` | 模型随附资料，保留原位 |
| `eval_results.json` | Python `eval.py` 生成的评测产物，不是 C# 报告 |

`modules/TinyShell/data/` 和 `modules/TinyShell/models/` 是发布脚本生成的副本，已被 Git 忽略。不要在副本中直接维护业务数据；源文件修改后重新发布。

## 意图字段

知识库为 JSON 数组，各项对应 `CommandIntent`。

| 字段 | 说明 |
|---|---|
| `id` | 稳定意图标识，应保持唯一；评测通过该字段关联 |
| `category` | 分类，当前为 process、filesystem、network、system、environment、archive、vcs |
| `command` | PowerShell 命令模板，必要参数通过 `<pid>` 等占位符表达 |
| `aliases` | 精确或规则匹配入口；支持同一别名关联多个意图，不能假定始终唯一 |
| `description` | 意图说明 |
| `keywords` | 关键词，参与检索 |
| `intent_phrases` | 自然语言表达，参与检索 |
| `risk_level` | safe、warning 或 dangerous |
| `risk_reason` | 修改或危险行为的原因说明 |
| `parameter_slots` | 参数槽位数组 |

槽位包含 `name`、`type`、`required`、`placeholder`、`description`。新增槽位时必须检查参数提取器是否支持，不应只添加 JSON 字段就宣称具备抽取能力。模板仍有未解析占位符时，候选必须保持不完整状态。

## 查询集口径

| 类型 | 数量 | 归属 |
|---|---|---|
| natural_language | 50 | 域内 |
| abbreviation | 12 | 域内 |
| fuzzy_typo | 10 | 域内 |
| parameterized | 3 | 域内 |
| out_of_domain | 13 | 负样本 |
| edge_case | 4 | 空值／符号等边界样本 |
| 合计 | 92 | 75 条域内，17 条负样本／边界 |

`query` 是输入，`expected_intent_id` 是预期意图；负样本可能为空。C# 全量评测将空预期、out_of_domain 或 edge_case 归入负样本统计。Top-1／Top-3 的分母是域内样本，不是全部 92 条。

## 数据变更流程

1. 修改源知识库，确认 ID、别名冲突、命令模板、参数槽位和风险标记。
2. 增加正确意图、相近错误意图、缺参及拒绝样本，避免只增加容易通过的问法。
3. 如改变分词、向量或跨语言行为，核对并更新对照 fixture 的生成来源；不能单纯按当前失败输出来修改预期。
4. 按[测试指南](../测试验证/TinyShell测试与验收指南.md)运行相关验证，重新发布模块。

模型资源与发布目录体积按实际字节测量；脚本使用的 `1MB` 为 1,048,576 字节，对应 MiB。
