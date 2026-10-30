# 给接收方Agent的安装入口

仅当用户明确要求按本文件安装zotero-reading时执行。目标是让用户说一句“根据这个安装说明安装zotero-reading，并完成初始化检查”，由当前Agent完成文件安装和验证。无需让用户自己选择或双击客户端专用脚本。

## 确认安装对象与执行位置

1. 以本INSTALL.md所在目录为包根，应有SKILL.md、package-manifest.json、install.ps1、run.ps1和scripts。若用户只给ZIP，先使用当前环境的安全解压能力解到可写位置，再读取本文件；不要只提取SKILL.md。
2. 确认工具运行在用户的Windows电脑上，能读取本地PDF并连接本机Zotero。远程服务器/容器内的localhost不等于用户电脑；不满足时说明缺少的本机执行能力，不能报告已经安装可用。
3. 确认当前使用的是哪一个Agent/harness及其原生技能目录。依据当前客户端提供的信息、实际配置或官方文档，而不是根据模型名称或电脑上存在某个目录推断；DeepSeek模型可以运行在不同harness中。

## 安装到当前Agent

以下为已核实的Windows用户级目录。配置自定义目录时，以实际配置为准：

| 当前Agent | 默认技能位置 | 安装器参数 |
|---|---|---|
| Codex | 用户目录/.agents/skills/zotero-reading | -Client Codex |
| Claude Code | 用户目录/.claude/skills/zotero-reading | -Client ClaudeCode |
| DeepSeek Harness（DSH） | DSH_HOME/skills/zotero-reading；未设置时用户目录/.dsh/skills/zotero-reading | -Client DeepSeekHarness |
| 其他本地Agent | 已核实的技能根目录/zotero-reading | -Client Custom -Destination '完整目标路径' |

DSH需要已启用本地文件系统技能provider；本包是目录型Skill，不是DSH代码插件，不运行dsh plugin add来安装它。DSH_HOME可改变其配置根；若当前部署使用其他provider或自定义扫描目录，先核对实际设置。

以本包的绝对路径执行，下面的路径和参数必须替换为实际值：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File '包根绝对路径\install.ps1' -Client DeepSeekHarness
```

对于其他Agent，在已核实目录后执行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File '包根绝对路径\install.ps1' -Client Custom -Destination '已核实技能根目录\zotero-reading'
```

- 当前Agent或目录不确定时，先向用户确认客户端/技能目录，不默认安装到Codex，不把同一技能散装到所有可能位置。安装器无目标参数时会返回needs_install_target，不写文件。
- 若客户端没有原生Skill机制，向用户说明“无法注册成自动发现的技能”，可在用户确认的稳定目录放置完整包，之后通过SKILL.md绝对路径使用。不得将这种直接使用冒充成原生安装成功，或擅改该Agent全局提示词。
- 安装器会核对文件摘要，安装同内容可跳过；更新托管旧版本先备份。已安装发行文件有修改/缺失或新版文件与额外文件重名时，返回local_changes并停止；说明文件名和状态，接收方明确同意后才能加-OverwriteLocal重试。非托管同名技能停止并请用户确认处理方式。不得手动删除旧目录绕过保护。

## 初始化与验收

1. 解析安装器JSON的path。检查该目录中SKILL.md、scripts/bootstrap.py和references/report-format.md均存在。
2. 用安装后的入口运行初始化：

   ```powershell
   powershell.exe -NoProfile -ExecutionPolicy Bypass -File '已安装目录\run.ps1' setup
   ```

   ready表示本机运行时和Zotero已就绪。缺Python、未打开Zotero、未启用本机通信、依赖安装失败或权限被拒时，按返回action向用户说明；可继续完成不依赖该问题的安装步骤，但不把部分就绪说成全部完成。不擅自系统安装Python、改Zotero数据库/设置或申请笔记写入授权。
3. 若客户端有技能列表/加载工具，用其核对zotero-reading是否被发现；DSH的文件provider支持目录发现，具体能否实时更新由当前部署决定。必要时刷新列表或请用户开新会话。仅文件复制成功时，报告“文件已安装；当前会话技能发现尚未验证”。
4. 向用户返回：实际安装位置、原生技能是否发现、初始化状态及仍需操作的最少步骤。安装任务不新建或修改Zotero笔记。

0.3.0起提供[按指令更新](references/updates.md)。旧0.2.1需先用完整0.3.0包及本安装器升级一次，保留已有ZOTERO_READING_HOME；不要改回默认数据目录。公开更新来源为PDogan233/zotero-reading，读取其最新正式Release；没有可用正式版时明确报告，不冒充更新成功。

完成后，用户即可说：

> 根据zotero-reading帮我看《论文标题》并生成阅读报告。

若对方同一句已经要求安装后阅读某篇论文，环境就绪后读取[SKILL.md](SKILL.md)完成阅读，不重复询问是否开始。0.5.0默认每轮重要讨论后保存，首次使用说明该行为并尊重只讨论/暂停的选择；已有明确长期授权不逐轮询问。安装、介绍或Skill升级本身不写论文笔记，不将原开发者的授权套用给接收方。

目录机制依据：[DeepSeek Harness本地技能provider](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/skill/skill-filesystem/README.md)、[Codex](https://learn.chatgpt.com/docs/build-skills)、[Claude Code](https://code.claude.com/docs/en/skills)。更详细的用户说明见[安装使用指南](references/installation.md)。
