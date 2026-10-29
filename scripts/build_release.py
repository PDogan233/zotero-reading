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
        archive.writestr(prefix + "/AGENTS.md", "论文阅读任务先读prompts/reading-workflow.md和skills/zotero-reading/SKILL.md。首轮分析及报告覆盖总结与动机、挑战与解决方法、优点与缺点；动机交代前人工作、已有不足及本文解决内容。中文平实、完整，不堆术语或过度凝练，保留原文证据与限定。用户明确保存后才写Zotero；每篇文献维护一份专用笔记，保留其他笔记。\n")
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
