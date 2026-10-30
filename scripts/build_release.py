"""Build allow-listed public ZIPs without copying local reading data."""

from pathlib import Path
import hashlib
import json
import re
import zipfile


ROOT = Path(__file__).resolve().parents[1]
VERSION = re.search(r'^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text(encoding="utf-8"), re.M)[1]
UPDATE_REPOSITORY = "PDogan233/zotero-reading"


def build(output, repository=UPDATE_REPOSITORY):
    from skill_updates import repository_name
    repository = repository_name(repository)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    source = output / f"zotero-reading-{VERSION}-source.zip"
    skill = output / f"zotero-reading-{VERSION}-skill.zip"
    files = [ROOT / name for name in (".gitignore", "pyproject.toml", "LICENSE", "zotero-report.ps1",
                                      "docs/PUBLIC_README.md", "docs/MIGRATION.md", "docs/RELEASING.md", "prompts/reading-workflow.md")]
    files += [ROOT / "scripts" / name for name in ("zotero_notes.py", "reading_sessions.py", "bootstrap.py", "paper_materials.py", "skill_updates.py", "build_release.py")]
    files += sorted((ROOT / "tests").glob("test_*.py"))
    skill_root = ROOT / "skills/zotero-reading"
    files += [skill_root / "SKILL.md", skill_root / "agents/openai.yaml"]
    files += [skill_root / name for name in ("INSTALL.md", "install.ps1", "Install-Codex.cmd", "Install-Claude-Code.cmd")]
    files += sorted((skill_root / "references").glob("*.md"))
    with zipfile.ZipFile(source, "w", zipfile.ZIP_DEFLATED) as archive:
        prefix = f"zotero-reading-{VERSION}"
        for path in files:
            archive.write(path, prefix + "/" + path.relative_to(ROOT).as_posix())
        public_readme = (ROOT / "docs/PUBLIC_README.md").read_text(encoding="utf-8")
        archive.writestr(prefix + "/README.md", public_readme.replace("](MIGRATION.md)", "](docs/MIGRATION.md)").replace("](RELEASING.md)", "](docs/RELEASING.md)").replace("](../prompts/", "](prompts/"))
        archive.writestr(prefix + "/AGENTS.md", "论文阅读先读prompts/reading-workflow.md和skills/zotero-reading/SKILL.md。默认对接受该流程的用户每轮重要讨论后autosave，尊重仅讨论/暂停，安装更新不写文献笔记。阅读日期下面的核心贡献或理念应可独立讲清论文主要工作、设计依据和关键取舍，保留必要技术细节与短摘录，按需联系问题、已有方案、改动和结果，不固定顺序或段数；多段用core_idea.paragraphs，旧text兼容。后文总结与动机、挑战与解决方法、优点与缺点三模块继续展开证据，避免逐句重复。首次完整阅读，复盘先读旧报告并按需回查，不自动重做全文或虚标已读。源码可直接用，不依赖全局安装，更新器不覆盖私人源码。中文平实完整，保留证据限定，不显示全局阶段标签。未读来源、草稿、所有权、并发和备份检查继续生效；每篇只维护一份专用笔记，保留其他笔记及旧保存快照。\n")
    payload = {"SKILL.md": (skill_root / "SKILL.md").read_text(encoding="utf-8").replace(
        "](../../prompts/reading-workflow.md)", "](references/reading-workflow.md)").replace(
        "](../../docs/MIGRATION.md)", "](references/MIGRATION.md)").encode("utf-8"),
        "agents/openai.yaml": (skill_root / "agents/openai.yaml").read_bytes(),
        "LICENSE": (ROOT / "LICENSE").read_bytes(),
        "run.ps1": (ROOT / "zotero-report.ps1").read_bytes(),
        "README.md": (skill_root / "references/installation.md").read_text(encoding="utf-8").replace("](updates.md)", "](references/updates.md)").encode("utf-8"),
        "references/reading-workflow.md": (ROOT / "prompts/reading-workflow.md").read_bytes(),
        "references/MIGRATION.md": (ROOT / "docs/MIGRATION.md").read_bytes()}
    for name in ("INSTALL.md", "install.ps1", "Install-Codex.cmd", "Install-Claude-Code.cmd"):
        payload[name] = (skill_root / name).read_bytes()
    for path in (skill_root / "references").glob("*.md"):
        payload["references/" + path.name] = path.read_bytes()
    for name in ("zotero_notes.py", "reading_sessions.py", "bootstrap.py", "paper_materials.py", "skill_updates.py"):
        payload["scripts/" + name] = (ROOT / "scripts" / name).read_bytes()
    manifest = {"name": "zotero-reading", "version": VERSION, "update_repository": repository,
                "files": {name: hashlib.sha256(data).hexdigest() for name, data in sorted(payload.items())}}
    payload["package-manifest.json"] = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    with zipfile.ZipFile(skill, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(payload.items()):
            archive.writestr("zotero-reading/" + name, data)
    return {"source": str(source.resolve()), "skill": str(skill.resolve())}


if __name__ == "__main__":
    import argparse
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / ".local/releases")
    parser.add_argument("--repository", default=UPDATE_REPOSITORY, help="随包记录的公开GitHub更新仓库")
    options = parser.parse_args()
    print(json.dumps(build(options.output, options.repository), ensure_ascii=False))
