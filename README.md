# Tiny Shell Intent

Tiny Shell Intent 是面向 Windows PowerShell 7.4+ 的本地命令建议插件。用户输入英文短语、命令别名或带有拼写错误的命令后，通过 `Alt+s` 获取候选，选择后填入当前命令行，由用户检查并回车执行。

插件使用 .NET 8、Model2Vec 静态词向量和规则／模糊／语义混合检索，在 PowerShell 进程内运行。发布包包含模型和知识库，使用时无需 Python、GPU、网络或独立后台服务。仓库保留 Python 原型用于评测和对照。

## 当前能力

- 51 个命令意图，覆盖进程、文件、网络、系统、环境变量、压缩和 Git 状态查询。
- 支持 `hybrid`、`rule`、`fuzzy`、`model` 四种检索模式，默认返回最多 3 个候选。
- 支持参数抽取、占位符完整性检查和 `safe / warning / dangerous` 风险标记。
- 拒绝低置信度、代码及部分域外输入；不支持任意外部工具子命令或通用命令生成。
- PSReadLine 菜单提示当前会话已有命令，检测快捷键冲突，支持取消和注销。

当前实现、后续核对项和交接入口见[项目现状与路线图](docs/需求/TinyShell项目现状与路线图.md)。中文输入不作为已支持的通用自然语言能力。

## 快速开始

在 Windows 的 PowerShell 7.4+ 中操作。**从源码克隆后先构建发布包**，开发机需安装 .NET 8 SDK 或兼容 SDK，并具备首次 NuGet 还原所需的访问条件：

```powershell
pwsh -File scripts/publish_module.ps1
pwsh -File Install-TinyShell.ps1
Import-Module TinyShell
Register-TinyIntentKeyHandler -Chord 'Alt+s'
```

已有完整发布包时可跳过构建。安装脚本复制 `modules/TinyShell` 到当前用户文档目录下的 `PowerShell/Modules/TinyShell`，不会自动修改 `$PROFILE`。离线部署应提前准备好完整发布目录。

```powershell
Get-TinyIntent 'll'
Get-TinyIntent 'find process using port 8080'
(Get-TinyIntent 'git s').Candidates |
    Format-Table IntentId, Command, RiskLevel, Score, IsComplete

# 关闭当前会话的快捷键
Unregister-TinyIntentKeyHandler
```

交互使用：输入短语后按 `Alt+s`，按 `1`—`3` 将候选填入命令行；按 `Esc` 或 `Enter` 保留原输入。候选中的 `[NEEDS PARAMS]` 表示仍需补全参数。插件不会自动执行所选命令。

安装、配置、升级和恢复方式见[安装与发布指南](docs/部署/TinyShell安装与发布指南.md)。

## 技术结构

```text
PSReadLine 快捷键 / Get-TinyIntent
              │
       TinyShell.PowerShell
              │
       TinyShell.Core.IntentEngine
              ├─ 输入门控与唯一规则短路
              ├─ 规则、模糊、静态向量检索与融合
              ├─ 参数抽取、风险评估与候选门控
              └─ QueryResult → 菜单 → 替换缓冲行
```

源码分为 `src/TinyShell.Core`（核心引擎）、`src/TinyShell.PowerShell`（Cmdlet）、`modules/TinyShell`（交互模块）和 `tiny_shell_intent`（Python 原型）。架构及接口以[技术设计](docs/设计/TinyShell技术设计.md)为当前说明。

## 开发验证

在仓库根目录执行：

```powershell
dotnet test tests/dotnet/TinyShell.Tests/TinyShell.Tests.csproj

# Python 原型验证；需另行安装 Python 3.11+ 和开发依赖
python -m pip install -r requirements.txt
python -m pip install pytest
python -m pytest
```

性能目标、历史数据来源、场景脚本及真实终端手动验收见[测试与验收指南](docs/测试验证/TinyShell测试与验收指南.md)。2026-10-22 审查修复后 C# 36 项、Python 41 项回归通过，发布失败拦截与命令语法检查通过；真实终端按键与显示仍待手动验收。原 README 的具体性能数字保留为历史记录。

## 文档

- [文档索引](docs/文档索引.md)
- [项目现状与路线图／新对话交接](docs/需求/TinyShell项目现状与路线图.md)
- [需求与验收标准](docs/需求/TinyShell需求与验收标准.md)
- [技术设计与命令接口](docs/设计/TinyShell技术设计.md)
- [知识库与评测数据说明](docs/数据参考/TinyShell知识库与评测数据说明.md)
- [测试与验收指南](docs/测试验证/TinyShell测试与验收指南.md)
- [安装与发布指南](docs/部署/TinyShell安装与发布指南.md)
- [架构决策](docs/架构决策/0001-采用进程内静态向量检索并仅替换命令缓冲区.md)

本项目采用 [MIT License](LICENSE)。模型资料见[模型自带说明](models/potion-base-2M/README.md)。
