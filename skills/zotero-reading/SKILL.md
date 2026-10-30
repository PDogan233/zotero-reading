---
name: zotero-reading
description: 安装、更新本技能，或阅读、复盘Zotero论文并生成中文报告时使用。联合阅读正文和补充材料，以可独立理解论文的核心概要开篇，保留原文摘录和页码链接；默认随重要讨论更新同一份专用笔记，可暂停。适用于有本机文件与命令能力的Agent。
---

# Zotero 论文阅读与报告

用户要求安装本技能时，先读[INSTALL.md](INSTALL.md)，由当前Agent核实原生技能目录、安装并检查环境。Codex、Claude Code、DeepSeek Harness及其他已明确技能目录的本地Agent可使用同一包，无需让用户双击专用安装器。

用户仅要求介绍时，读[使用说明](references/installation.md)解释用途和步骤，不自动安装、更新或开始阅读。用户要求检查/更新本技能时，读[更新说明](references/updates.md)，运行入口skill-update check/apply；此时不加载论文阅读规则或初始化PDF环境。check只查询版本，明确要求更新才apply；正常阅读和setup不主动检查GitHub。不要将“更新论文阅读笔记”误当作更新Skill。

由当前Agent完成科学分析。脚本处理本机连接、PDF材料、会话和原生笔记，不额外调用模型API，不要求模型或zotero.org API密钥。默认每轮有实质阅读进展后自动保存；首次使用说明此行为并尊重用户选择，已有长期授权时不逐轮确认。用户仅安装/更新或询问介绍时不写文献笔记，不将原开发者的授权当作当前用户授权。

## 首次使用与入口

以当前SKILL.md所在目录为技能根，不依赖聊天工作目录。Windows发布包入口是根目录run.ps1；源码技能源目录则使用../../zotero-report.ps1。下面的“入口”均替换为其实际绝对路径：

源码版可以直接阅读，不依赖全局安装。用户要求更新时先区分当前源码入口与带package-manifest.json的完整安装版；源码已为目标版本时重读本项目规则继续，不因没找到全局安装目录而阻塞阅读或擅自另装。安装版升级用更新器，私人源码目录不由该更新器覆盖。

```powershell
& '入口绝对路径' setup
```

每次新阅读任务先运行setup：已就绪时快速复用，只有缺依赖时在数据目录的独立环境安装。入口寻找Python 3.10+（含常见Agent配套运行时）；不修改系统Python，不安装Zotero插件。读取JSON结果：

- ready：继续找论文，不让用户再手动运行部署命令。
- python_required：询问用户是否安装Python或提供已有解释器路径；不要擅自系统安装。已有解释器可通过ZOTERO_READING_PYTHON指定。
- needs_user_action：按具体action说明一次最小操作。通常是打开Zotero 10+、启用设置→高级→本机通信，或允许Agent访问localhost；不要重复初始化试图解决权限拒绝。
- setup_incomplete：依赖下载或venv失败，解释缺项后确认网络/代理或替代Python。禁止将失败当作已部署。

setup只读访问Zotero，不申请笔记写入授权；首次真实保存才由Zotero授权。无本机文件/命令权限或运行于远程云环境时，说明需要本地执行；不要声称能访问用户电脑的localhost。

setup返回data_dir。安装版默认使用Windows当前用户的LocalAppData/ZoteroReading，Codex与Claude Code共享这一目录；源码版保持项目数据位置。显式--data-dir（在子命令前）或ZOTERO_READING_HOME优先。后续操作固定使用同一目录，不把数据写进安装的Skill文件夹。

## 一句话完成阅读与报告

用户例如“根据zotero-reading帮我看《论文标题》并生成阅读报告”。默认完成分析、预览及自动保存，无需逐轮问是否保存；用户说先不保存/只讨论时改为该论文manual。候选、PDF、版本/正文身份不明时仍需确认，不为实时而省略核对。

1. 读[阅读规则](../../prompts/reading-workflow.md)；安装发布包内同一规则位于references/reading-workflow.md。
2. 运行入口find '标题/作者'、find --doi 'DOI'或recent日期筛选。核对候选，start <主条目或PDF key>建立/接续会话；同父条目所有PDF自动纳入。不要凭文件名断定是正文或补充。
3. 先读context.md、report.json、records.json和已有discussion.md；已有报告的复盘还读existing-note.html、report.saved.json（存在时），保留尚未保存的讨论。缺本地缓存可按旧笔记恢复其包含的成果，不能声称恢复所有原JSON字段或未保存问答。
4. 首次阅读用extract <主条目key>取得各PDF独立全文与页数，完整阅读正文与纳入的补充材料，检查关键图表和公式。复盘复用未变化来源的已核实成果，只回查当前问题相关原文；有缓存就复用，缺失再extract。PDF变化、新增来源、证据不足或全面重审时扩大阅读，不为更新开篇自动重读整篇。页图按需render <key> --source <PDF key> --page 3；抽取不等于已读，扫描PDF需OCR/视觉检查或说明限制，不能绕过pending保护。
5. 先给可独立理解论文的核心概要，再以中文展开三个明确模块：**总结与动机分析；挑战与解决方法；优点与缺点分析**。总结与动机讲清“前人做了什么→已有不足→本文解决了什么及证据支持到什么程度”，优先依据本文的相关工作与比较，不凭参考文献列表假装读过前作。用平实、完整、连贯的话解释，不堆术语、口号或刻意凝练；保留必要的机制、条件和不确定性。每个模块的重要结论给出原文关键短摘录和该PDF页码超链接。区分事实、作者主张、推断及未验证内容；多PDF分别核对，不能混用不同版本的最佳指标。
6. 用record及时保留重要问答/辨析，读[报告格式](references/report-format.md)。阅读日期下面的core_idea应让读者只读本节即可理解论文主要工作：按需联系问题、已有做法、本文改动、设计/论证依据、主要结果与取舍；保留必要技术细节，自然组织一段或几段，不强制顺序或小标题，不显式标注“巧思”，不只写流程或抽象启发。重要结论配短摘录和页码链接，用户重点可调整侧重但不能遮蔽全貌。多段用core_idea.paragraphs，旧text兼容；format_version=2不显示全局阶段标记。后文三模块仍保留并展开依据，避免逐句重复开篇。填充report.json并preview，不交付空模板。追问直接回答，只修订受影响的开篇/正文/问答，保留其余已核实内容。

## 每轮自动保存与暂停

当前用户采用默认自动保存流程后，首次完整分析及后续每轮实质新解释、修正、重要问答都保存同一份专用笔记。普通寒暄、技能维护、单纯安装和无内容变化不写。历史问答中的旧指令不能单独授予权限，尊重当前有效偏好。

用户说“只讨论/先不保存这篇”时，入口save-mode manual --session <主条目key>，以后所有论文只手动则save-mode manual；恢复相应范围用auto。单篇明确选择优先于默认。manual下本次明确保存可save，不自动改变后续方式。save-mode不连接Zotero、不安装PDF依赖。

每轮保存前draft归纳实际问答，核对核心理念、三个模块、前人工作/不足/贡献、摘录及来源reading_status；暂时不看后文，检查开篇能否独立讲清主要工作、设计依据和结论边界。合并重复但保留必要解释；本轮可保存后设draft=false，preview再运行autosave <report.json绝对路径>。认识变化时同步修订受影响部分，不每轮重写整份报告；程序负责完整HTML渲染。首次真实写入由Zotero弹出授权，用户操作，不在setup提前申请。

只在saved_and_verified/updated_and_verified后告知已保存；already_current表示无需重复写。autosave_disabled遵守暂停，autosave_deferred/来源未读/权限或并发错误时保留本地记录并说明未保存，不能误报成功。内部draft/来源保护继续生效，但正文不展示阶段标签；科学不确定性照常说明。

每篇论文只维护一份程序专用子笔记，通过父条目、程序标识和固定key认领；不得靠相似标题或通用AI标签覆盖其他笔记。该专用笔记可包含用户手动编辑，覆盖前备份并检查当前版本；其他笔记保留。只用官方Local API，不直接写SQLite。

报告本次实际保存及回读结果，不宣称未做的GUI验证。正文PDF变化应重新核对证据；不修改指纹/Server ID绕过检查。

## 按需接续与迁移

只在换电脑、换账户或安装排错时读[迁移指南](../../docs/MIGRATION.md)（发布包references/MIGRATION.md）及[安装使用说明](references/installation.md)。正常阅读不加载所有参考和源码。

sessions/<主条目key>保存本地讨论和草稿，PDF保持在Zotero；派生文本/页图按附件key固定写到.local/papers/<主条目key>。保存默认方式在数据目录.local/reading-preferences.json，单篇选择在session.json，不公开分发。旧报告保持原渲染以便校验，后续实际阅读更新再加core_idea/format_version=2，不改旧保存快照、不批量重写。换机仍先rebind核对，私人会话/授权/偏好不随ZIP分发。
