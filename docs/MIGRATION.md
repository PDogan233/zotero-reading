# 使用与迁移指南

## 程序、阅读成果和授权分别处理

- 程序与skill可复制到不同电脑、账户或支持本地工具的Agent。
- Zotero内的文献、PDF和笔记由Zotero迁移或同步。
- sessions保存未写入Zotero的讨论、草稿、回执及更新前备份；需要保留这些内容时，单独复制整个sessions目录。
- `.local/zotero-auth.json`属于当前电脑的授权缓存，迁移与公开分享时不复制。首次实际写入时在新Zotero中重新授权。

## 新电脑首次使用

推荐仅发送独立`zotero-reading-0.3.0-skill.zip`。接收方在自己的本地Agent中说“请读取这个ZIP中的zotero-reading/INSTALL.md，按说明为当前Agent安装zotero-reading并完成初始化检查”，Agent负责解压、核实技能目录与安装。支持Codex、Claude Code、DeepSeek Harness及明确自定义目录的其他本地Agent；目录不明时确认，不默认装进Codex。专用.cmd仅作可选手动入口。不要只复制SKILL.md，完整指引随包附带。

打开本地Agent的新会话，说“根据zotero-reading帮我看《论文标题》并生成阅读报告”。Agent运行setup，寻找已有Python 3.10+、复用或隔离安装PDF依赖，检查Zotero 10+。只有缺Python、Zotero未打开/未启用本机通信、权限或选文有歧义时才需要用户操作。笔记写入授权留到实际保存时，不提前申请。

需要源码开发时仍可运行`python -m pip install '.[pdf]'`或`python scripts/zotero_notes.py`。Windows源码入口zotero-report.ps1也使用相同bootstrap；paths不要求Zotero或依赖就绪。发布包中的run.ps1为相同入口，不依赖本项目路径。CLI脚本本身不解析自然语言，报告由当前Agent完成。

如需把运行数据放到源码之外，使用`--data-dir`（置于子命令之前），或设置环境变量：

```powershell
$env:ZOTERO_READING_HOME = 'D:\ZoteroReadingData'
zotero-reading paths
```

```sh
export ZOTERO_READING_HOME="$HOME/ZoteroReadingData"
zotero-reading paths
```

多个Agent接续同一文库时指向同一数据目录。多个不同账户使用不同数据目录，避免旧会话与新文库混淆。

## 程序更新与数据目录

0.3.0新增run.ps1 skill-update check/apply，分别查询和显式升级；正常阅读不自动联网更新。默认公开仓库PDogan233/zotero-reading，查询最新正式Release及其完整Skill附件。0.2.1需要先用完整新包升级一次，然后才能用该入口。更新保留ZOTERO_READING_HOME与已有本地数据，不自动更新阅读报告；修改过的技能文件先停下来确认。发布流程见公共源码包docs/RELEASING.md。

各电脑的数据目录可以不同。例如另一电脑已改到Documents/Codex/ZoteroReading，就继续沿用，不因更新改回LocalAppData。数据目录无法创建/重命名时应先核对实际Agent权限，并确认可写位置；设置环境变量不会自动搬迁已有记录或扩大沙箱权限。

## 同一Zotero账户换电脑

优先使用Zotero自身同步迁移文库，并等待附件下载。Zotero官方建议使用同步，或关闭Zotero后复制完整数据目录；不建议用导出/再导入替代完整迁移。[官方迁移说明](https://www.zotero.org/support/kb/transferring_a_library)

如果只需要已保存的阅读成果，在新电脑start相应文献即可：程序取回已有的专用笔记，Agent以它为基础复盘。程序不会从HTML无损还原所有原JSON字段，Agent须结合原文整理新的草稿。

如果需要保留完整本地讨论：

1. 复制旧数据目录中的sessions到新数据目录；不复制授权缓存。
2. 旧文件夹命名不统一时先`zotero-reading normalize-sessions --dry-run`检查，再运行normalize-sessions。它按主文献key重命名，保留内容，遇到同文献多个目录则停止。
3. 对每个需要接续的会话先运行`zotero-reading rebind ABCDEFGH --dry-run`，再运行`zotero-reading rebind ABCDEFGH`。
4. rebind检查原条目/PDF key、标题/DOI、所有PDF指纹以及已有报告正文；只刷新本地服务ID、文件路径与回执，不写入Zotero。内容或身份不符时停止，不自动猜测。
5. resume继续讨论；用户明确保存时覆盖原专用阅读笔记，其他笔记保持原样。

## 不同账户

程序和skill本身可以直接使用；历史会话不能保证直接迁移。新账户中的条目、PDF及笔记key可能不同，复制文件后强改server_id不能解决关联问题。

目前自动rebind只支持key和PDF指纹一致的情况。key变化时，在目标账户重新按DOI/标题找到文献并start；Agent可读取旧会话作为历史资料，但须逐项匹配新PDF、改正每条引用坐标并核实内容。已导入的旧AI笔记key变化时也不能仅凭标题认领，应先人工确认维护对象；当前没有自动跨账户认领接口。

## 不同Agent

- 有文件与命令能力的Agent可直接读取本项目AGENTS及prompts/reading-workflow.md，无需改模型接口。
- 支持Agent Skills的客户端可将独立skill包内的zotero-reading文件夹放到该客户端指定的技能目录；也可明确要求Agent读取SKILL.md并执行流程。
- skill源文件在源码项目中使用项目scripts；独立skill包包含自己的scripts和references，数据位置由paths或ZOTERO_READING_HOME指定。
- 仅聊天、无法访问本地文件与Zotero接口的Agent，不能独立完成本机写入，需要连接本地执行环境。

## 公开分享

只分享build_release.py产生的公共源码包/独立skill包或Python安装包。sessions、research、.local授权缓存和PDF都不进入ZIP；私人阅读成果另行迁移。当前许可证为MIT，公开源码与发行附件应保留LICENSE。
