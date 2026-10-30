# 在Agent中安装与使用（Windows）

## 发给别人什么

只发送`zotero-reading-0.5.0-skill.zip`。它包含INSTALL.md、Skill说明、程序、PDF工具、Windows入口、通用安装器、按指令更新器和参考说明，无需再发源码包、Python wheel或本项目文件夹。

ZIP不含论文、私人会话、Zotero库、授权、Python或第三方依赖。接收方使用自己的本机Zotero文库和Agent；无需提供新的模型API Key。

## 接收方安装

把ZIP的实际本机路径交给当前Agent，例如直接说：

> 请读取 D:\Downloads\zotero-reading-0.5.0-skill.zip 中的 zotero-reading/INSTALL.md，按说明为当前Agent安装zotero-reading，并完成初始化检查；有不确定的地方先向我确认。

路径替换为对方电脑的实际位置；若Agent支持本地附件，也可附上ZIP并说“根据附件中的INSTALL.md安装zotero-reading”。Agent负责安全解压、确认自己的原生技能目录、运行安装器和setup。用户无需选择或双击专用脚本。

完整解压后也可说“请根据<解压目录>\zotero-reading\INSTALL.md安装zotero-reading”。首次阅读请求可与安装合并在一句话中。

默认目录：Codex为`%USERPROFILE%\.agents\skills\zotero-reading`，Claude Code为`%USERPROFILE%\.claude\skills\zotero-reading`；DeepSeek Harness为`%DSH_HOME%\skills\zotero-reading`，未设置DSH_HOME时为`%USERPROFILE%\.dsh\skills\zotero-reading`。其他本地Agent由它核实实际技能目录后指定-Destination；不能根据模型名猜客户端，也不能省略目标后默认装进Codex。

文件安装本身无需Python、管理员权限或网络；初始化依赖可能需要联网。安装与当前会话能否发现技能分开验收；未发现时刷新技能列表或开新会话。INSTALL.md要求Agent报告实际位置、技能发现情况、初始化状态及剩余操作。

Install-Codex.cmd和Install-Claude-Code.cmd仍作为可选手动入口；它们不是使用本包的前提。

通用安装器复制同一套技能。重装相同内容会跳过；更新已由本安装器管理的旧版本时，先检查发行文件是否被修改/删除或新版是否与额外文件重名，有差异就停止并由接收方决定。明确同意后才用-OverwriteLocal；先备份再覆盖。备份在`ZOTERO_READING_HOME\skill-backups`，未设置时用`%LOCALAPPDATA%\ZoteroReading\skill-backups`，也可明确指定-BackupRoot。不重名的额外文件保留。遇到非托管同名技能或链接目录则停止，先确认，不直接覆盖。

DeepSeek Harness需启用本地技能provider；本包是Skill而非DSH代码插件。其他Agent若不支持原生技能，可在确认的稳定目录保留完整包并按SKILL.md路径直接使用，但必须说明没有注册为自动发现的技能。仅网页聊天或远程容器通常无法直连这台电脑的Zotero。

## 第一次说什么

> 根据zotero-reading这个skill，帮我看《论文标题》并生成阅读报告。

Codex还可明确写`$zotero-reading`；Claude Code可用`/zotero-reading`加论文标题。上述中文完整指令可说明阅读和输出目标。

Agent先运行setup并继续选文，用户不必手写部署命令：

- 自动寻找Python 3.10+，优先复用已有Python/常见Agent配套运行时。若没有可用Python，Agent会确认使用已有解释器还是协助安装一次；不擅自更改系统软件。
- 已有pypdf则复用。缺少时只在数据目录`.local/runtime`的独立环境从PyPI安装；图表渲染工具按需安装pypdfium2和Pillow，不做系统pip安装。正常重复使用不重复下载。
- 检查本机Zotero连接；无需配置Zotero数据库路径或Python模型服务。首次下载依赖需要网络与Agent执行权限；已有依赖后可离线读取本地文库（Agent模型自身是否联网由客户端决定）。
- 用户需打开Zotero 10+，在设置→高级中启用“允许此计算机上的其他应用程序与Zotero通信”，并确保PDF已下载。若这些尚未完成，Agent指出缺少哪一步。
- Agent沙箱可能单独要求允许localhost访问；这不是Zotero的笔记写入授权。

报告默认中文，含总结与动机、挑战与解决方法、优缺点。总结与动机讲清前人已经做了什么、已有不足、本文解决了什么及证据支持的范围。语言平实、直接、完整，必要时展开解释，不把报告压成术语和口号；重要引用仍附原文关键摘录和PDF页码链接。标题有多个匹配、PDF缺失或正文版本不清楚时，Agent向用户确认。

## 讨论与保存

0.5.0默认在首次完整分析后创建笔记，此后每轮重要解释、修正或问答后更新同一份；没有实质变化不写。用户采用这个流程后，不必每次另说保存。Agent首次使用时说明默认行为，尊重用户只讨论/暂停的选择；安装和Skill更新本身不创建论文笔记。

0.5.0报告在阅读日期下面先给可独立阅读的“核心贡献或理念”：只读这一节即可理解论文主要工作、设计理由和关键取舍，后文三模块展开细节和证据。可联系问题、已有方案、本文改动、依据与结果，保留必要技术细节，按论文自然组织，不硬套顺序或段数。多段正文与关键短摘录分别定位；用户重点可调整侧重，但不能遮蔽全貌。不显示全局阶段标签，必要的科学不确定性保留。

已有报告优先接续旧笔记、草稿和讨论，再按需回查原文，未变化且已核实的部分复用。首次阅读或资料变化/证据不足时扩大核对，不为更新开篇自动通读或重写整篇。源码版可直接用项目入口；若已是所需版本，重读规则即可，不需要先安装一份全局Skill。

首次真实保存仍需在Zotero对话框授权；按用户意愿选择“始终允许”可供后续复用。未读材料/尚未核对的草稿不会因为自动模式而跳过检查，失败时保留本地讨论并告知原因，不误报保存成功。

可以说“这篇先不保存，只讨论”“恢复这篇自动保存”“以后都改成手动保存”。单篇选择优先于默认，manual下明确说“保存这一轮”仍可只保存本次。同一文献维护一份专用笔记，覆盖前备份，其他笔记保留。已有旧报告不会因升级被批量改写，后续实际讨论更新时再补新开篇。

## 更新Skill

0.3.0起可以说“检查zotero-reading有没有新版本”或“把zotero-reading更新到最新正式版”，分别只查询和实际升级。详细规则见[更新说明](updates.md)。默认公开来源为[PDogan233/zotero-reading正式发行版](https://github.com/PDogan233/zotero-reading/releases/latest)，没有可用正式附件时会说明原因并保留旧版。旧0.2.1需先按完整0.3.0包的INSTALL.md升级一次。正常阅读不自动检查或安装新版。

更新保留原数据目录、讨论及Zotero笔记；本地修改先停，未获明确同意不覆盖。可以直接说“从GitHub更新zotero-reading到最新正式版”。更新完成后，让Agent在当前对话重新读取新SKILL.md和阅读规则再继续；客户端未发现或无法刷新时再新开会话。各Agent的独立安装分别更新，不自动扫描其他客户端。

## 数据在哪里

安装版默认`%LOCALAPPDATA%\ZoteroReading`，多个Agent可共用：

- `sessions/<文献主条目key>`：讨论、草稿、预览、保存快照和旧笔记备份。
- `.local/papers/<文献主条目key>`：派生文本与页图，按PDF附件key命名，不复制原PDF。
- `.local/runtime`：仅在确实缺依赖时创建的独立环境。
- `.local/setup.json`：初始化状态；`.local/zotero-auth.json`：本机写入授权，不能分享。
- `.local/reading-preferences.json`：本人选择的全局保存方式；单篇选择保存在session.json。偏好不随公共Skill包分发。

需要改变位置时，让Agent先确认新位置，并统一使用`--data-dir`或`ZOTERO_READING_HOME`。旧会话不会自动搬迁。不同Zotero文库使用不同数据目录；程序会拒绝把旧会话直接绑定到其他文库。

源码直接运行仍默认项目目录。分享技能与迁移私人阅读成果是两件事：同账户换机另外迁移Zotero数据和所需sessions，详见MIGRATION.md。

安装路径与调用方式依据：[Codex技能说明](https://learn.chatgpt.com/docs/build-skills)、[Claude Code技能说明](https://code.claude.com/docs/en/skills)、[DeepSeek Harness技能provider](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/skill/skill-filesystem/README.md)。Zotero设置与授权依据：[官方Local API](https://www.zotero.org/support/dev/web_api/v3/local_api)。
