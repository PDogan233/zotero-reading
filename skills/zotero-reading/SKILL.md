---
name: zotero-reading
description: 用户要求安装、检查或更新zotero-reading技能，或要求阅读、复盘Zotero论文并生成报告时使用。首次按需初始化环境，联合阅读正文及补充材料，产出含原文摘录及页码链接的中文报告；明确保存后维护唯一的Zotero子笔记。适用于能执行本机命令的Agent。
---

# Zotero 论文阅读与报告

用户要求安装本技能时，先读[INSTALL.md](INSTALL.md)，由当前Agent核实原生技能目录、安装并检查环境。Codex、Claude Code、DeepSeek Harness及其他已明确技能目录的本地Agent可使用同一包，无需让用户双击专用安装器。

用户仅要求介绍时，读[使用说明](references/installation.md)解释用途和步骤，不自动安装、更新或开始阅读。用户要求检查/更新本技能时，读[更新说明](references/updates.md)，运行入口skill-update check/apply；此时不加载论文阅读规则或初始化PDF环境。check只查询版本，明确要求更新才apply；正常阅读和setup不主动检查GitHub。不要将“更新论文阅读笔记”误当作更新Skill。

由当前Agent完成科学分析。脚本处理本机连接、PDF材料、会话和原生笔记，不额外调用模型API，不要求模型或zotero.org API密钥。首次使用、生成预览和保存是不同操作。

## 首次使用与入口

以当前SKILL.md所在目录为技能根，不依赖聊天工作目录。Windows发布包入口是根目录run.ps1；源码技能源目录则使用../../zotero-report.ps1。下面的“入口”均替换为其实际绝对路径：

```powershell
& '入口绝对路径' setup
```

每次新阅读任务先运行setup：已就绪时快速复用，只有缺依赖时在数据目录的独立环境安装。入口寻找Python 3.10+（含常见Agent配套运行时）；不修改系统Python，不安装Zotero插件。读取JSON结果：

- ready：继续找论文，不让用户再手动运行部署命令。
- python_required：询问用户是否安装Python或提供已有解释器路径；不要擅自系统安装。已有解释器可通过ZOTERO_READING_PYTHON指定。
- needs_user_action：按具体action说明一次最小操作。通常是打开Zotero 10+、启用设置→高级→本机通信，或允许Agent访问localhost；不要重复初始化试图解决权限拒绝。
- setup_incomplete：依赖下载或venv失败，解释缺项后确认网络/代理或替代Python。禁止将失败当作已部署。

setup只读访问Zotero，不申请笔记写入授权。无本机文件/命令权限或运行于远程云环境时，说明需要本地执行；不要声称能访问用户电脑的localhost。

setup返回data_dir。安装版默认使用Windows当前用户的LocalAppData/ZoteroReading，Codex与Claude Code共享这一目录；源码版保持项目数据位置。显式--data-dir（在子命令前）或ZOTERO_READING_HOME优先。后续操作固定使用同一目录，不把数据写进安装的Skill文件夹。

## 一句话完成阅读与报告

用户例如“根据zotero-reading帮我看《论文标题》并生成阅读报告”。执行至预览完成，无需再询问是否开始；有多个候选、缺PDF、版本/正文身份不明时才向用户确认。

1. 读[阅读规则](../../prompts/reading-workflow.md)；安装发布包内同一规则位于references/reading-workflow.md。
2. 运行入口find '标题/作者'、find --doi 'DOI'或recent日期筛选。核对候选，start <主条目或PDF key>建立/接续会话；同父条目所有PDF自动纳入。不要凭文件名断定是正文或补充。
3. 运行入口extract <主条目key>，它返回每个PDF的独立全文文件与页数。读取全文，检查图表、公式和引用关键页；需要页图时运行入口render <key> --source <PDF key> --page 3。渲染依赖首次按需安装。抽取不改变已读状态，扫描PDF仍需适当OCR或向用户说明材料限制。
4. 先读context.md、report.json、records.json和已有discussion.md；复盘还读existing-note.html、report.saved.json（存在时），保留尚未保存的讨论。缺本地缓存仅可恢复旧笔记包含的成果。
5. 以中文完成三个明确模块：**总结与动机分析；挑战与解决方法；优点与缺点分析**。总结与动机讲清“前人做了什么→已有不足→本文解决了什么及证据支持到什么程度”，优先依据本文的相关工作与比较，不凭参考文献列表假装读过前作。用平实、完整、连贯的话解释，不堆术语、口号或刻意凝练；保留必要的机制、条件和不确定性。每个模块的重要结论给出原文关键短摘录和该PDF页码超链接。区分事实、作者主张、推断及未验证内容；多PDF分别核对，不能混用不同版本的最佳指标。
6. 用record及时保留重要问答/辨析。需要输出报告时读[报告格式](references/report-format.md)，填充start生成的report.json，运行入口preview <report.json绝对路径>，交付可查看的报告与关键结论。不要只给一个空草稿、计划或口头摘要。追问只回答当前问题，并按需修订本地草稿。

## 明确保存后写入Zotero

“生成报告”“分析”“复盘”只授权生成本地报告；用户明确说“保存/更新到Zotero”才写。若同一句已明确要求保存，完成阅读与预览后继续保存，不重复询问。历史指令或已有笔记不授予本轮权限。

保存前draft归纳实际问答，核对三个模块、前人工作/已有不足/本文贡献、摘录及所有附件的reading_status，去掉重复内容但保留必要解释，设draft=false并preview，再save；已有笔记也可update --dry-run后update。首次真实写入会由Zotero弹出本地授权，用户操作；不提前在setup申请。

每篇论文只维护一份程序专用子笔记，通过父条目、程序标识和固定key认领；不得靠相似标题或通用AI标签覆盖其他笔记。该专用笔记可包含用户手动编辑，覆盖前备份并检查当前版本；其他笔记保留。只用官方Local API，不直接写SQLite。

报告本次实际保存及回读结果，不宣称未做的GUI验证。正文PDF变化应重新核对证据；不修改指纹/Server ID绕过检查。

## 按需接续与迁移

只在换电脑、换账户或安装排错时读[迁移指南](../../docs/MIGRATION.md)（发布包references/MIGRATION.md）及[安装使用说明](references/installation.md)。正常阅读不加载所有参考和源码。

sessions/<主条目key>保存本地讨论和草稿，PDF保持在Zotero；派生文本/页图按附件key固定写到.local/papers/<主条目key>。同key/同PDF换机先rebind --dry-run核对后rebind；不同账户key变化需重新匹配。只分享发行ZIP，私人会话和授权缓存不随Skill分发。
