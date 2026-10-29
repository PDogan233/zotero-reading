"""Read-only recovery, safe local migration, and public package boundaries."""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from build_release import build
from reading_sessions import normalize_sessions, read_json, session_path, start_session, write_json
from zotero_notes import ZoteroError, default_data_root, publish_report, rebind_session, store_receipt
from test_multi_pdf import BundleClient, MAIN, PARENT, SUPPLEMENT
from test_reading_workflow import temporary_workspace
from test_zotero_notes import report


class PortabilityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = temporary_workspace()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.client = BundleClient()
        for namespace in ("reading_sessions", "zotero_notes"):
            source_patch = patch(namespace + ".pdf_snapshot", side_effect=lambda client, key: deepcopy(client.snapshots[key]))
            source_patch.start()
            self.addCleanup(source_patch.stop)

    def saved_session(self):
        directory = Path(start_session(self.client, self.root / "sessions", PARENT)["session"])
        prepared = read_json(directory / "report.json")
        prepared["draft"] = False
        prepared["core_idea"] = {"text": "用于迁移测试的已核实核心理念。", "sources": [{"attachment_key": MAIN, "page": 1}]}
        for source in prepared["paper"]["attachments"]:
            source["reading_status"] = "read"
        prepared["sections"][0]["paragraphs"][0]["text"] = "先前已核实的阅读报告"
        write_json(directory / "report.json", prepared)
        receipt = publish_report(self.client, prepared, directory / "report.json")
        store_receipt(directory / "report.json", prepared, receipt)
        return directory, receipt

    def new_host(self):
        client = BundleClient()
        client.items = deepcopy(self.client.items)
        client.server_id = "other-host"
        client.snapshots = deepcopy(self.client.snapshots)
        client.snapshots[MAIN]["path"] = "new-host/main.pdf"
        client.snapshots[SUPPLEMENT]["path"] = "new-host/supplement.pdf"
        return client

    def test_revisit_recovers_current_note_when_local_cache_is_missing(self):
        _, receipt = self.saved_session()
        fresh = Path(start_session(self.client, self.root / "fresh", SUPPLEMENT)["session"])
        self.assertEqual(read_json(fresh / "session.json")["stage"], "revisit")
        self.assertIn("先前已核实", (fresh / "existing-note.html").read_text(encoding="utf-8"))
        self.assertEqual(hashlib.sha256((fresh / "existing-note.html").read_bytes()).hexdigest(),
                         read_json(fresh / "session.json")["existing_note"]["sha256"])
        self.assertEqual(read_json(fresh / "report.json")["report_id"], receipt["report_id"])
        self.assertTrue(read_json(fresh / "report.json")["draft"])
        self.assertEqual(len(self.client.posts), 1)

    def test_revisit_keeps_unsaved_local_draft_and_fetches_latest_note(self):
        directory, receipt = self.saved_session()
        prepared = read_json(directory / "report.json")
        prepared["draft"] = True
        prepared["sections"][0]["paragraphs"][0]["text"] = "尚未保存的讨论"
        write_json(directory / "report.json", prepared)
        self.client.items[receipt["note_key"]]["data"]["note"] += "<p>另一电脑更新的要点</p>"
        start_session(self.client, self.root / "sessions", PARENT)
        self.assertEqual(read_json(directory / "report.json"), prepared)
        self.assertIn("另一电脑更新", (directory / "existing-note.html").read_text(encoding="utf-8"))
        self.assertEqual(self.client.patches, [])

    def test_normalize_preserves_report_and_old_resume_alias(self):
        source = self.root / "sessions/drone"
        write_json(source / "report.json", report())
        before = (source / "report.json").read_bytes()
        preview = normalize_sessions(self.root / "sessions", dry_run=True)
        self.assertEqual(len(preview["moves"]), 1)
        self.assertTrue(source.exists())
        normalize_sessions(self.root / "sessions", dry_run=False)
        target = self.root / "sessions" / PARENT
        self.assertEqual((target / "report.json").read_bytes(), before)
        self.assertEqual(session_path(self.root / "sessions", "drone"), target)

    def test_normalize_rejects_duplicate_sessions_before_any_move(self):
        write_json(self.root / "sessions/a/report.json", report())
        write_json(self.root / "sessions/b/report.json", report())
        with self.assertRaisesRegex(ValueError, "多个会话"):
            normalize_sessions(self.root / "sessions", dry_run=False)
        self.assertTrue((self.root / "sessions/a").exists())
        self.assertTrue((self.root / "sessions/b").exists())

    def test_same_library_rebind_updates_paths_and_receipts_without_writing(self):
        directory, receipt = self.saved_session()
        client = self.new_host()
        rebind_session(client, directory)
        state = read_json(directory / "session.json")
        self.assertEqual(state["server_id"], "other-host")
        self.assertEqual(state["pdf"]["path"], "new-host/main.pdf")
        self.assertEqual(read_json(directory / "report.receipt.json")["note_key"], receipt["note_key"])
        self.assertEqual(read_json(directory / "report.receipt.json")["server_id"], "other-host")
        self.assertEqual((client.posts, client.patches, client.authorizations), ([], [], 0))

    def test_rebind_preview_changes_no_files(self):
        directory, _ = self.saved_session()
        before = {path.name: path.read_bytes() for path in directory.iterdir() if path.is_file()}
        result = rebind_session(self.new_host(), directory, dry_run=True)
        self.assertEqual(result["status"], "rebind_ready")
        self.assertEqual(before, {path.name: path.read_bytes() for path in directory.iterdir() if path.is_file()})

    def test_rebind_rejects_changed_pdf_and_preserves_old_binding(self):
        directory, _ = self.saved_session()
        before = read_json(directory / "session.json")
        client = self.new_host()
        client.snapshots[SUPPLEMENT]["sha256"] = "different-pdf"
        with self.assertRaisesRegex(ValueError, "更换|指纹"):
            rebind_session(client, directory)
        self.assertEqual(read_json(directory / "session.json"), before)

    def test_rebind_rejects_different_saved_report(self):
        directory, receipt = self.saved_session()
        before = read_json(directory / "session.json")
        client = self.new_host()
        client.items[receipt["note_key"]]["data"]["note"] += "<p>不同内容</p>"
        with self.assertRaises(ZoteroError):
            rebind_session(client, directory)
        self.assertEqual(read_json(directory / "session.json"), before)

    def test_data_root_and_cli_paths_are_configurable_without_network(self):
        with patch.dict(os.environ, {"ZOTERO_READING_HOME": str(self.root)}):
            self.assertEqual(default_data_root(), self.root.resolve())
        script = Path(__file__).resolve().parents[1] / "scripts/zotero_notes.py"
        result = subprocess.run([sys.executable, str(script), "--data-dir", str(self.root), "paths"],
                                capture_output=True, text=True, encoding="utf-8", check=True)
        self.assertEqual(json.loads(result.stdout)["data_dir"], str(self.root.resolve()))

    def test_release_archives_exclude_runtime_data_and_include_skill_runtime(self):
        packages = build(self.root / "releases")
        for package in packages.values():
            with zipfile.ZipFile(package) as archive:
                names = archive.namelist()
                self.assertFalse(any("/sessions/" in name or "/research/" in name or "/.local/" in name or name.endswith(".pdf") for name in names))
                for suffix in ("SKILL.md", "zotero_notes.py", "MIGRATION.md"):
                    self.assertTrue(any(name.endswith(suffix) for name in names))

    def test_source_release_keeps_ignore_rules_for_future_private_reading_data(self):
        packages = build(self.root / "releases")
        with zipfile.ZipFile(packages["source"]) as archive:
            path = next(name for name in archive.namelist() if name.endswith("/.gitignore"))
            ignored = archive.read(path).decode("utf-8").splitlines()
        for directory in (".local/", "sessions/", "research/"):
            self.assertIn(directory, ignored)

    def test_standalone_manifest_covers_every_runtime_file(self):
        packages = build(self.root / "releases")
        with zipfile.ZipFile(packages["skill"]) as archive:
            prefix = "zotero-reading/"
            manifest = json.loads(archive.read(prefix + "package-manifest.json"))
            actual = {name.removeprefix(prefix) for name in archive.namelist()} - {"package-manifest.json"}
            self.assertEqual(actual, set(manifest["files"]))
            for name, digest in manifest["files"].items():
                self.assertEqual(hashlib.sha256(archive.read(prefix + name)).hexdigest(), digest)
                for private_path in (b"C:\\Users\\PDogan", b"C:/Users/PDogan", b"D:\\Files\\Others\\Codes"):
                    self.assertNotIn(private_path, archive.read(prefix + name))
            for name in ("INSTALL.md", "run.ps1", "install.ps1", "Install-Codex.cmd", "Install-Claude-Code.cmd",
                         "scripts/bootstrap.py", "scripts/paper_materials.py", "scripts/skill_updates.py",
                         "references/report-format.md", "references/updates.md"):
                self.assertIn(name, actual)

    def test_release_skill_references_resolve_without_source_project(self):
        import re
        packages = build(self.root / "releases")
        for kind, filename in packages.items():
            target = self.root / kind
            with zipfile.ZipFile(filename) as archive:
                archive.extractall(target)
            skill = next(target.rglob("SKILL.md"))
            documents = [skill, next(target.glob("*/README.md")), skill.parent / "INSTALL.md",
                         skill.parent / "references/installation.md", skill.parent / "references/updates.md"]
            for document in documents:
                for link in re.findall(r'\]\(([^)]+)\)', document.read_text(encoding="utf-8")):
                    if "://" not in link:
                        self.assertTrue((document.parent / link).resolve().is_file(), str(document.parent / link))


if __name__ == "__main__":
    unittest.main()
