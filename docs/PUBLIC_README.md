# Zotero Reading

与本地阅读Agent讨论论文，在明确保存指令后将中文阅读报告写入Zotero原生子笔记。每篇文献维护一份专用报告，保留其他笔记。程序不自行调用模型API。

首轮分析和最终报告包含总结与动机、挑战与解决方法、优点与缺点三个模块。可联合阅读同文献下正文与补充PDF，证据链接分别指向各文件的页码。

## 安装与运行

推荐独立zotero-reading-0.3.0-skill.zip：把实际文件路径交给本地Agent，说“根据这个ZIP中的zotero-reading/INSTALL.md，为当前Agent安装zotero-reading并完成初始化检查”。Agent解压、确认原生技能目录并安装；支持Windows上的Codex、Claude Code、DeepSeek Harness及已明确技能目录的其他本地Agent。专用.cmd只是可选入口。安装后说“根据zotero-reading帮我看《论文标题》并生成阅读报告”。缺Python、Zotero设置或目录不明时Agent确认所需操作。详见随包INSTALL.md和README.md。

在[正式发行版](https://github.com/PDogan233/zotero-reading/releases/latest)下载完整skill.zip。仓库中的skills/zotero-reading是供构建的技能源目录，直接复制该子目录不包含完整运行时；安装使用Release附件。

需要Python 3.10+、Zotero 10+及一个能执行本地命令、读取PDF的Agent。打开Zotero并启用本机通信。

当前使用本机个人文库，默认中文及UTC+8日期筛选；群组文库尚未实现。

```sh
python -m pip install '.[pdf]'
zotero-reading paths
zotero-reading probe
zotero-reading find '论文标题'
zotero-reading start ABCDEFGH
```

也可不安装，直接在源码目录运行`python scripts/zotero_notes.py`，传相同参数；Windows提供`zotero-report.ps1`。

标题分析指令由Agent转换为find/start，再读PDF与规则；脚本本身不解析自然语言。讨论不会自动写入Zotero，用户明确保存后Agent准备报告并调用save。

新建会话放在数据目录的`sessions/<主文献key>/`。`--data-dir`或环境变量`ZOTERO_READING_HOME`可指定数据目录；paths显示实际位置。pip安装版默认使用系统用户数据目录，源码版默认使用项目目录。

## 按指令更新

0.3.0起，说“检查zotero-reading有没有新版本”只查询；“把zotero-reading更新到最新正式版”才下载和替换。入口为run.ps1 skill-update check/apply，保持原ZOTERO_READING_HOME；发行文件有本地修改时先停止并确认，更新前备份、普通失败尝试恢复旧版，已有阅读成果不改写。

默认公开来源为PDogan233/zotero-reading，更新器查询其最新正式Release；没有正式附件时会说明原因并保留旧版。旧0.2.1先用完整0.3.0包升级一次。发布者见[GitHub发布指南](RELEASING.md)。本版不做后台或自动更新。

## 接续与迁移

start会取回已有程序报告到existing-note.html，供Agent复盘；同时保留本地未保存草稿。只靠Zotero笔记可恢复已保存的阅读成果，完整未保存讨论需要迁移本地sessions。

同一文库在另一电脑且条目key、PDF指纹一致时，可用`rebind <会话> --dry-run`核对，再显式rebind刷新本地服务和文件路径。不同账户的历史key映射目前需要人工或Agent核对，不能原样重用旧标识。

详见[迁移指南](MIGRATION.md)，阅读规则见[prompts/reading-workflow.md](../prompts/reading-workflow.md)。技能源文件位于skills/zotero-reading；独立skill发布包会包含程序脚本和规则。

## 验证与许可

`python -m unittest discover -s tests -v`运行隔离测试，不访问真实Zotero服务。许可证为MIT；发行包仅包含程序、技能、测试与公共文档，不包含PDF、阅读记录或授权缓存。
