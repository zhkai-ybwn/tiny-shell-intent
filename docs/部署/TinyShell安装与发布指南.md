# TinyShell 安装与发布指南

## 环境与交付物

使用环境为 Windows、PowerShell 7.4+（`pwsh`）；交互菜单需要已加载的 PSReadLine 和可读键的终端。Windows PowerShell 5.1 不满足模块清单要求。

开发构建还需要能够编译 `net8.0` 的 .NET SDK。首次构建可能需要访问 NuGet；开发依赖还原与用户侧离线使用是不同阶段。完整模块依靠 PowerShell 宿主运行，无需额外启动服务或安装 Python。

当前实现没有本次 ARM64、跨平台或各 PowerShell 版本的兼容性实测记录。

## 从源码构建

在仓库根目录的 PowerShell 7 中执行：

```powershell
pwsh -File scripts/publish_module.ps1
```

脚本依次尝试用户 `.dotnet`、PATH 及 Program Files 中的 dotnet，执行 Release 构建，再复制 DLL、知识库、模型权重和分词器到 `modules/TinyShell`。构建后人工核对输出和下列文件是否完整；目录存在本身不代表构建成功。

脚本检查构建退出码，非零时立即中止，不进入资源复制阶段；已有旧 DLL 不会被当作本次成功构建继续发布。

```text
modules/TinyShell/
├── TinyShell.psd1
├── TinyShell.psm1
├── TinyShell.Core.dll
├── TinyShell.PowerShell.dll
├── data/knowledge_base.json
└── models/potion-base-2M/
    ├── model.safetensors
    └── tokenizer.json
```

DLL 和模块内的数据／模型副本没有纳入 Git，源码克隆后必须先构建。发布脚本组装的是目录，不生成 ZIP，也不发布到 PowerShell Gallery。

可先在独立终端中导入仓库内模块进行检查：

```powershell
Import-Module ./modules/TinyShell/TinyShell.psd1
Get-TinyIntent 'll'
```

## 安装与启用

```powershell
pwsh -File Install-TinyShell.ps1
Import-Module TinyShell
Register-TinyIntentKeyHandler -Chord 'Alt+s'
```

根脚本转调 `scripts/Install-TinyShell.ps1`。后者仅支持 `CurrentUser`，优先使用系统解析的 MyDocuments 路径，未取得时回退到用户 Documents；目标为其下的 `PowerShell/Modules/TinyShell`。

安装脚本复制现有模块，不自动构建、下载资源或修改 `$PROFILE`，也不会全面校验包内容。已有完整模块可直接复制整个 `TinyShell` 目录到目标机器的用户模块目录。安装和覆盖更新均可能覆盖同名文件，先保留需要恢复的旧版本副本。

需要每次启动自动启用时，由用户将以下内容加入实际使用的 `$PROFILE`：

```powershell
Import-Module TinyShell
Register-TinyIntentKeyHandler -Chord 'Alt+s'
```

## 配置

```powershell
# 指定其他快捷键和检索模式
Register-TinyIntentKeyHandler -Chord 'Alt+j' -Mode hybrid

# 预加载模型
Initialize-TinyIntent -PreloadModel

# 单次调用选项
Get-TinyIntent 'find process using port 8080' -Top 3 -Mode hybrid -OodThreshold 0.42
```

快捷键已占用时默认警告并保留原绑定；显式 `-Force` 会覆盖。注销不会恢复旧绑定。单次检索还支持 `-KnowledgeBasePath` 和 `-ModelPath`，初始化后会话复用引擎，详见[技术设计](../设计/TinyShell技术设计.md)。

## 更新与恢复

1. 保留旧模块完整目录及对应版本／commit 信息。
2. 在开发端重新构建，核对生成文件后安装或复制完整模块。
3. 关闭已加载旧 DLL 的 PowerShell 窗口，在新会话导入并验收；`Import-Module -Force` 不应作为替换已加载程序集的可靠手段。
4. 恢复时关闭使用该模块的会话，把保留的旧目录恢复到模块位置，在新会话验证。

停用当前快捷键可执行 `Unregister-TinyIntentKeyHandler`。永久停用时由用户移除 `$PROFILE` 中加入的启用语句；卸载时仅处理已确认的 TinyShell 模块目录。

## 常见问题

| 现象 | 核对项 |
|---|---|
| 找不到 DLL／导入失败 | 是否先构建，模块目录是否完整，是否使用 PowerShell 7.4+ |
| 无法识别模块 | 安装目标是否位于当前会话 `$env:PSModulePath`；文档目录是否被系统重定向 |
| 找不到模型或知识库 | 源资源是否齐全、发布复制是否成功、实际加载的模块路径是否正确 |
| 快捷键没有菜单 | PSReadLine 是否加载、键位是否冲突、输入是否被重定向、终端是否截获快捷键 |
| 新模型／命令未生效 | 是否重新发布并更新了模块副本，是否开启了新 PowerShell 会话 |

交付前按[测试与验收指南](../测试验证/TinyShell测试与验收指南.md)核对，不把复制成功作为验收通过。
