# GitHub发布指南

公开仓库：PDogan233/zotero-reading。本指南说明从干净公共源码到正式Release的操作，适用于首次发布及后续维护；执行发布需要仓库维护者的明确授权。

## 第一次建立公开仓库

1. 使用PDogan233账号创建名为zotero-reading的公开仓库。保留当前MIT许可证，除非发布者另行决定。
2. 从build_release.py生成的公共source.zip解压到一个独立、干净的发布工作目录，再将其初始化为Git仓库并关联上述远端。不要在私人阅读项目中直接git add .后推送；公共包已按白名单排除PDF、sessions、research、.local和授权缓存，并包含.gitignore防止后续生成的私有目录误提交。忽略规则不会移除已经被Git跟踪的文件，首次仍需核对待提交列表。
3. 源码和文档中可以保留公开账号/仓库名，但不得带入用户电脑路径、真实文库快照或密钥。核对待提交列表后再提交推送。接收方运行数据始终留在各电脑。

## 发布一个版本

1. 修改源码中的提示词、脚本或规则。阅读规则原文件为prompts/reading-workflow.md；构建会将其放入Skill的references，不手工只改ZIP中的一份。
2. 同时更新pyproject.toml版本、scripts/bootstrap.py的VERSION和scripts/zotero_notes.py的--version，并同步当前分享包版本介绍；首次实际发布时更新文档中“尚未发布”的状态，历史迁移示例可保留。使用major.minor.patch，新功能用次版本、修复用补丁版本；Release标签与包内版本必须一致，例如v0.3.0。不要用已发布的同一版本号替换不同内容，更新器不会重装同版。
3. 在Windows Python 3.10+环境中运行测试和构建（下方python替换为实际可用解释器）：

   ```powershell
   python -X utf8 -m unittest discover -s tests -v
   python -X utf8 scripts/build_release.py --output dist
   ```

   PDF抽取/渲染相关测试需要对应开发依赖；普通测试不操作真实Zotero。需要Skill官方校验时，在开发环境中使用skill-creator的quick_validate.py；它不是接收方运行依赖。当前默认更新仓库为PDogan233/zotero-reading；fork发布时用--repository明确指定自己的公开仓库。
4. 核对dist/zotero-reading-0.3.0-skill.zip、source.zip（文件名依实际版本），确认版本、文件清单和数据排除。GitHub对新上传的附件计算SHA256 digest，更新器要求此字段；ZIP内另有逐文件manifest。不要上传私人项目文件夹或Python运行环境。
5. 推送源码和与该提交对应的v0.3.0标签。GitHub的Releases页面创建对应标签的正式发行版，更新说明写清行为变化、是否涉及接收方操作和兼容性。不要勾选预发布；如有多个版本，明确将目标正式版设为Latest。
6. 上传精确命名的zotero-reading-0.3.0-skill.zip作为Release附件，另可上传source.zip供开发者使用。GitHub自动生成的Source code ZIP不能代替独立Skill ZIP。首次上传、附件完成前可先保存为草稿，附件齐全后再发布。
7. 发布后先在临时安装目录验收skill-update check/apply，核对从旧版升级、入口版本、备份、自定义数据目录和本地修改阻止行为。实际GitHub下载验收通过后，才告诉接收方已可在线更新。

## 已安装电脑的操作

- 当前另一台电脑若为0.2.1，先把完整0.3.0 Skill ZIP交给它的Agent，按INSTALL.md升级一次。保留它已设置的ZOTERO_READING_HOME；有本地修改时先确认。
- 之后说“检查zotero-reading有没有新版本”只查询；说“把zotero-reading更新到最新正式版”才执行升级。
- 所有电脑在各自执行更新后跟上新版本。本版没有自动更新、后台任务或远程推送机制；无须接收方安装Git。

## 故障与版本恢复

404可能表示仓库或正式Release尚未发布；403/429需核对访问或API额度，不连续自动重试。GitHub给出的附件digest缺失时先重新上传合格附件，不能关闭校验。新版下载/校验失败不动旧版；复制/入口检查失败自动恢复，失败信息及备份位置必须保留。若一个已发布版本本身有问题，发布更高版本的修复；不要让电脑自动降级或改用未测试的main分支。

普通失败回退只恢复Skill文件，不回滚或改写论文笔记。当前更新不迁移阅读会话格式，后续若有不兼容数据结构变化，应单独设计迁移、备份与提示，不能仅替换代码后声称兼容。

当前没有配置GitHub Actions。未来如需自动构建，可在用户确认后增加Windows测试/打包及发布工作流；仓库令牌存GitHub Secrets或受限GITHUB_TOKEN，不能写入源码或分享包。

官方参考：[Releases](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases)、[创建发行版](https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository)、[附件API](https://docs.github.com/en/rest/releases/assets#get-a-release-asset)。
