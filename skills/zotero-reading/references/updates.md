# 按指令更新zotero-reading

本功能更新Skill的提示词、Python脚本及配套规则；不更新论文阅读笔记。仅用户明确要求检查/更新本技能时执行，常规阅读、setup和安装介绍不主动联网检查版本。

## 用户怎么说

> 从GitHub仓库PDogan233/zotero-reading更新已安装的zotero-reading到最新正式版，保留原数据目录；遇到本地修改先向我确认。

这也是明确的更新指令，Agent应使用下述skill-update apply获取完整Release，不把git pull、只复制仓库中的SKILL.md或技能源目录当作完整升级。用户仅说“检查”时仍只check。安装0.3.0及以上版本后可直接使用，0.2.1需先按最新完整包INSTALL.md升级一次。

> 检查zotero-reading有没有新版本，先告诉我结果。

Agent运行已安装Skill入口：

```powershell
& '已安装Skill目录\run.ps1' skill-update check
```

这一步只读安装文件和GitHub版本信息，不下载或覆盖技能，不写本地数据、不连接Zotero。返回当前/最新版本、正式Release链接，以及已有发行文件的修改/缺失清单。清单基于文件摘要，不代表已完成逐行内容比较。

> 把zotero-reading更新到最新正式版。

这句话已授权更新，无需再重复问是否开始。运行：

```powershell
& '已安装Skill目录\run.ps1' skill-update apply
```

先核实当前是完整的已安装Skill目录及日常使用的数据目录。保持ZOTERO_READING_HOME，或在skill-update前传--data-dir；不要把数据写进技能目录。源码开发目录不能被覆盖，源码入口可加--skill-dir指向已确认的安装目录。

用户实际使用源码项目时，先核对该项目pyproject.toml和入口--version，而不是只查全局安装目录。源码可直接阅读；已是目标版本则重读项目SKILL.md/阅读规则/格式说明并继续，不因没有全局安装而阻塞阅读或擅自另装。源码需要升级时在独立目录获取完整公共源码并核对改动和原数据，不能让安装版更新器覆盖私人项目；当前不提供源码目录的一键原地升级。

## 来源与版本

- 0.3.0发行manifest预设公开仓库PDogan233/zotero-reading。404可能表示仓库或正式Release不可用；请核对[正式发行版](https://github.com/PDogan233/zotero-reading/releases/latest)，不能把请求失败说成更新成功。
- 默认从安装的package-manifest.json读取update_repository。接收方明确选择其他公开仓库时，可加--repo账号/仓库名（或完整GitHub HTTPS仓库地址），只对本次调用生效；不要自行更换来源。
- 只接受major.minor.patch正式版和精确命名zotero-reading-<版本>-skill.zip；不安装源码ZIP、草稿、预发布版、同版或更旧版。
- 公开GitHub接口不需要新的API密钥。当前版本未实现私有仓库认证或GitHub Enterprise。

## 本地修改、备份与失败

- 返回local_changes时，列出路径及modified/missing/unmanaged_collision状态并停止。用户修改的发行文件以及与新版重名的额外文件均不能直接覆盖。
- 接收方明确同意覆盖这些差异后，才可重试skill-update apply --overwrite-local。重试仍先备份。对安装器的对应参数是-OverwriteLocal，两者不能混用。
- 不重名的额外文件保留；旧版manifest登记但新版已移除的文件在成功更新中删除，相关Python生成的字节码缓存会清除后重建以免继续运行旧代码。旧版和本地修改会完整保存在当前数据目录.local/skill-updates/backup-<旧版本>-<编号>，不放入技能发现目录。
- 先在临时目录下载并核对GitHub给出的ZIP大小、SHA256，再检查包内文件清单/摘要、路径、版本、仓库、Python语法及入口版本。SHA256用于完整性检查，不是独立发布者签名；信任来源是用户选择的GitHub仓库及HTTPS。
- 更新期间再次检查本地文件，发现变化就停止。更新锁阻止同目录两个更新器同时替换。请在当前阅读/保存任务结束后运行，不在另一Agent正在读取同一安装目录时升级。
- 普通复制或新版入口检查失败返回rolled_back，自动恢复旧文件，备份保留。若连恢复也失败，会明确给出备份位置并要求停止使用；不要声称已恢复。进程被强制结束/断电不能保证自动恢复，遗留锁及备份需先核对，不能反复重试或直接删锁。
- 不能联网、缺正式附件或目录权限不足时保留旧版，按action说明原因。目录不可写时先与用户核对当前--data-dir/ZOTERO_READING_HOME，不擅改用户环境变量，不关闭完整性或备份检查。

## 更新后

updated表示已安装文件通过检查；不等于当前会话已读到新提示词。可以先留在原对话中说：

> 请重新读取已安装的zotero-reading/SKILL.md、references/reading-workflow.md和报告格式说明，确认版本后按当前保存方式继续；保留之前的讨论。如果我说只讨论或暂停，继续尊重该选择。

Agent实际读取这些文件并结合context.md、report.json和讨论记录后，可在原对话继续使用新要求；不必一概要求关闭窗口或重启客户端。不要只口头说“已更新”而继续沿用旧规则。若客户端未发现更新、无法读取新技能或规则仍未生效，再刷新技能列表、新开会话或按客户端要求重启。

Codex官方说明会自动发现Skill变化；这是技能发现机制，不能据此保证所有Agent已自动重读旧对话中加载过的正文。[官方说明](https://learn.chatgpt.com/docs/build-skills)。下一次阅读先setup检查实际依赖和Zotero连接。检查/更新本身不安装PDF依赖、不申请笔记写入授权、不修改数据目录设置或已有阅读报告。0.5.0采用可独立理解论文的开篇，支持多段正文/短摘录，明确首次完整阅读与复盘按需回查；旧单段及快照兼容。默认按轮保存仍尊重manual/暂停，不因升级批量改笔记，后续实际讨论时按需更新。

同一电脑多个Agent各自安装一份时，分别对对应目录执行；当前不自动发现并批量修改其他Agent的安装。0.2.1不带更新器，需先让Agent按完整0.3.0包的INSTALL.md升级一次。已有本地讨论及授权继续留在原数据目录。

发布者流程见公共源码包docs/RELEASING.md。GitHub接口依据：[最新正式Release](https://docs.github.com/en/rest/releases/releases#get-the-latest-release)、[发行附件与SHA256](https://docs.github.com/en/rest/releases/assets#get-a-release-asset)。
