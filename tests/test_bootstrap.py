"""First-use setup, installer isolation, and standalone reading utilities."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import bootstrap
from build_release import build
from paper_materials import extract, render
from reading_sessions import file_sha256, read_json, write_json
from test_reading_workflow import temporary_workspace
from zotero_notes import ZoteroError


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        temporary = temporary_workspace()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_existing_runtime_never_installs(self):
        with patch.object(bootstrap, "dependency_versions", return_value={"pypdf": "6.10.0"}), \
                patch.object(bootstrap.venv, "EnvBuilder") as venv, patch.object(bootstrap.subprocess, "run") as process:
            result = bootstrap.ensure_runtime(self.root)
        self.assertFalse(result["installed"])
        self.assertEqual(Path(result["python"]), Path(sys.executable).resolve())
        venv.assert_not_called()
        process.assert_not_called()

    def test_managed_runtime_is_reused_without_download(self):
        with patch.object(bootstrap, "dependency_versions", side_effect=[None, {"pypdf": "6.10.0"}]), \
                patch.object(bootstrap.subprocess, "run") as process:
            result = bootstrap.ensure_runtime(self.root)
        self.assertEqual(Path(result["python"]), bootstrap.runtime_python(self.root).resolve())
        self.assertFalse(result["installed"])
        process.assert_not_called()

    def test_first_install_targets_own_environment_and_includes_renderer_dependencies(self):
        with patch.object(bootstrap, "dependency_versions", side_effect=[None, None, {"pypdf": "6.10.0", "pypdfium2": "5.14.0", "Pillow": "12.0.0"}]), \
                patch.object(bootstrap.venv, "EnvBuilder") as venv, patch.object(bootstrap.subprocess, "run") as process:
            result = bootstrap.ensure_runtime(self.root, renderer=True)
        self.assertTrue(result["installed"])
        self.assertEqual(venv.return_value.create.call_args.args[0], self.root / ".local/runtime")
        command = process.call_args.args[0]
        self.assertEqual(command[0], str(bootstrap.runtime_python(self.root)))
        self.assertIn(bootstrap.PACKAGES["Pillow"], command)
        self.assertNotIn("--user", command)

    def test_no_install_failure_preserves_existing_discussion(self):
        source = self.root / "sessions/example/discussion.md"
        source.parent.mkdir(parents=True)
        source.write_text("未保存讨论", encoding="utf-8")
        with patch.object(bootstrap, "dependency_versions", return_value=None), \
                patch.object(bootstrap.venv, "EnvBuilder") as venv:
            with self.assertRaises(bootstrap.SetupError):
                bootstrap.ensure_runtime(self.root, allow_install=False)
        self.assertEqual(source.read_text(encoding="utf-8"), "未保存讨论")
        venv.assert_not_called()

    def test_failed_download_does_not_claim_ready(self):
        with patch.object(bootstrap, "dependency_versions", return_value=None), \
                patch.object(bootstrap.venv, "EnvBuilder"), \
                patch.object(bootstrap.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "pip")):
            with self.assertRaises(bootstrap.SetupError):
                bootstrap.ensure_runtime(self.root)
        self.assertFalse((self.root / ".local/setup.json").exists())

    def test_unmanaged_runtime_cannot_receive_package_installation(self):
        python = bootstrap.runtime_python(self.root)
        python.parent.mkdir(parents=True)
        python.write_bytes(b"not-a-venv")
        with patch.object(bootstrap, "dependency_versions", return_value=None), \
                patch.object(bootstrap.subprocess, "run") as process:
            with self.assertRaises(bootstrap.SetupError):
                bootstrap.ensure_runtime(self.root)
        process.assert_not_called()

    def test_setup_does_not_authorize_or_write_zotero(self):
        with patch.object(bootstrap, "ensure_runtime", return_value={"python": sys.executable, "packages": {"pypdf": "6.10.0"}}), \
                patch.object(bootstrap, "Client") as client:
            client.return_value.server_id = "test-only-server"
            result = bootstrap.setup(self.root)
        self.assertEqual(result["status"], "ready")
        client.return_value.authorize.assert_not_called()
        client.return_value.request.assert_not_called()
        self.assertEqual(read_json(self.root / ".local/setup.json")["zotero"]["server_id"], "test-only-server")

    def test_zotero_disabled_yields_action_instead_of_write_authorization(self):
        with patch.object(bootstrap, "ensure_runtime", return_value={}), patch.object(bootstrap, "Client") as client:
            client.return_value.connect.side_effect = ZoteroError("Forbidden", 403)
            result = bootstrap.setup(self.root)
        self.assertEqual(result["status"], "needs_user_action")
        self.assertFalse(result["zotero"]["ready"])
        client.return_value.authorize.assert_not_called()

    def test_managed_subprocess_does_not_inherit_foreign_python_paths(self):
        with patch.dict(os.environ, {"PYTHONPATH": "foreign-packages", "PYTHONHOME": "foreign-home"}):
            environment = bootstrap.child_environment(bootstrap.runtime_python(self.root))
            current = bootstrap.child_environment(sys.executable)
        self.assertNotIn("PYTHONPATH", environment)
        self.assertNotIn("PYTHONHOME", environment)
        self.assertEqual(current["PYTHONPATH"], "foreign-packages")


@unittest.skipUnless(importlib.util.find_spec("pypdf"), "PDF utility tests need pypdf")
class MaterialTests(unittest.TestCase):
    def setUp(self):
        from pypdf import PdfWriter
        temporary = temporary_workspace()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.pdf = self.root / "paper.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        writer.add_blank_page(width=200, height=200)
        writer.write(self.pdf)
        self.session = self.root / "sessions/ABCD2345"
        self.state = {"paper": {"parent_key": "ABCD2345"}, "sources": [{"key": "EFGH6789", "role": "main", "path": str(self.pdf), "sha256": file_sha256(self.pdf), "reading_status": "pending"}]}
        write_json(self.session / "session.json", self.state)

    def test_extract_uses_stable_source_names_without_marking_read(self):
        result = extract(self.root, "ABCD2345")
        record = result["files"][0]
        self.assertEqual(record["page_count"], 2)
        self.assertEqual(record["empty_text_pages"], [1, 2])
        self.assertEqual(record["characters"], 0)
        self.assertEqual(Path(record["text_path"]), self.root / ".local/papers/ABCD2345/EFGH6789.txt")
        extract(self.root, "ABCD2345")
        self.assertEqual(len(list((self.root / ".local/papers/ABCD2345").glob("*.txt"))), 1)
        self.assertEqual(read_json(self.session / "session.json"), self.state)

    def test_changed_pdf_is_rejected_before_extraction(self):
        self.pdf.write_bytes(self.pdf.read_bytes() + b"\nchanged")
        with self.assertRaisesRegex(ValueError, "更换"):
            extract(self.root, "ABCD2345")
        self.assertFalse((self.root / ".local/papers").exists())

    @unittest.skipUnless(importlib.util.find_spec("pypdfium2"), "Renderer not available")
    def test_render_checks_page_range_and_returns_real_images(self):
        result = render(self.root, "ABCD2345", "EFGH6789", [2, 2])
        self.assertEqual(len(result["files"]), 1)
        self.assertTrue(Path(result["files"][0]["image_path"]).read_bytes().startswith(b"\x89PNG"))
        with self.assertRaises(ValueError):
            render(self.root, "ABCD2345", "EFGH6789", [3])
        self.assertEqual(read_json(self.session / "session.json"), self.state)


@unittest.skipUnless(os.name == "nt", "Windows installer integration")
class InstallationTests(unittest.TestCase):
    def setUp(self):
        temporary = temporary_workspace()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        packages = build(self.root / "releases")
        with zipfile.ZipFile(packages["skill"]) as archive:
            archive.extractall(self.root / "解压目录 with spaces")
        self.skill = self.root / "解压目录 with spaces/zotero-reading"

    def install(self, client="Codex", success=True, overwrite_local=False):
        target = self.root / client / "zotero-reading"
        result = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                                 str(self.skill / "install.ps1"), "-Client", client, "-Destination", str(target),
                                 "-BackupRoot", str(self.root / "backups"),
                                 *(["-OverwriteLocal"] if overwrite_local else [])], capture_output=True, text=True, encoding="utf-8")
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return json.loads(result.stdout.splitlines()[0])
        self.assertNotEqual(result.returncode, 0)
        return result

    def test_both_clients_install_and_reinstall_without_python_or_data(self):
        for client in ("Codex", "ClaudeCode"):
            result = self.install(client)
            target = Path(result["path"])
            self.assertEqual(result["status"], "installed")
            self.assertTrue((target / "SKILL.md").exists())
            self.assertTrue((target / "scripts/bootstrap.py").exists())
            self.assertFalse((target / "sessions").exists())
            self.assertEqual(self.install(client)["status"], "already_installed")

    def test_update_backs_up_edits_outside_skill_discovery(self):
        result = self.install()
        target = Path(result["path"])
        (target / "SKILL.md").write_text("用户对技能的修改", encoding="utf-8")
        (target / "extra.txt").write_text("保留", encoding="utf-8")
        stopped = self.install(success=False)
        self.assertEqual(json.loads(stopped.stdout)["status"], "local_changes")
        self.assertEqual((target / "SKILL.md").read_text(encoding="utf-8"), "用户对技能的修改")
        result = self.install(overwrite_local=True)
        self.assertEqual((Path(result["backup"]) / "SKILL.md").read_text(encoding="utf-8"), "用户对技能的修改")
        self.assertTrue(Path(result["backup"]).is_relative_to(self.root / "backups"))
        self.assertEqual((target / "extra.txt").read_text(encoding="utf-8"), "保留")

    def test_tampered_package_does_not_create_destination(self):
        (self.skill / "SKILL.md").write_text("changed", encoding="utf-8")
        self.install(success=False)
        self.assertFalse((self.root / "Codex/zotero-reading").exists())

    def test_unmanaged_skill_is_not_overwritten(self):
        target = self.root / "Codex/zotero-reading"
        target.mkdir(parents=True)
        (target / "SKILL.md").write_text("已有技能", encoding="utf-8")
        self.install(success=False)
        self.assertEqual((target / "SKILL.md").read_text(encoding="utf-8"), "已有技能")

    def test_manifest_cannot_write_outside_skill_directory(self):
        path = self.skill / "package-manifest.json"
        data = read_json(path)
        data["files"]["../outside.txt"] = "0" * 64
        write_json(path, data)
        self.install(success=False)
        self.assertFalse((self.root / "Codex/outside.txt").exists())

    def invoke_generic_installer(self, arguments=(), **environment_updates):
        environment = dict(os.environ, USERPROFILE=str(self.root / "recipient home"),
                           LOCALAPPDATA=str(self.root / "recipient appdata"))
        environment.pop("DSH_HOME", None)
        environment.update(environment_updates)
        return subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                               str(self.skill / "install.ps1"), *map(str, arguments)], env=environment,
                              capture_output=True, text=True, encoding="utf-8")

    def test_unspecified_agent_never_defaults_to_codex(self):
        response = self.invoke_generic_installer()
        self.assertEqual(response.returncode, 2, response.stdout + response.stderr)
        self.assertEqual(json.loads(response.stdout)["status"], "needs_install_target")
        # PowerShell itself may initialize shell directories in a fresh home.
        self.assertFalse((self.root / "recipient home/.agents/skills/zotero-reading").exists())
        self.assertFalse((self.root / "recipient home/.dsh/skills/zotero-reading").exists())

    def test_custom_agent_requires_directory(self):
        response = self.invoke_generic_installer(["-Client", "Custom"])
        self.assertEqual(response.returncode, 2, response.stdout + response.stderr)
        self.assertEqual(json.loads(response.stdout)["status"], "needs_skill_directory")
        self.assertFalse((self.root / "recipient home/.agents/skills/zotero-reading").exists())
        self.assertFalse((self.root / "recipient home/.dsh/skills/zotero-reading").exists())

    def test_installer_backup_honors_existing_data_home_after_consent(self):
        target = self.root / "other-agent/zotero-reading"
        data_home = self.root / "Documents Codex/custom data"
        response = self.invoke_generic_installer(["-Destination", target], ZOTERO_READING_HOME=str(data_home))
        self.assertEqual(response.returncode, 0, response.stderr)
        (target / "SKILL.md").write_text("本地改动", encoding="utf-8")
        stopped = self.invoke_generic_installer(["-Destination", target], ZOTERO_READING_HOME=str(data_home))
        self.assertEqual(stopped.returncode, 2, stopped.stderr)
        self.assertFalse(data_home.exists())
        response = self.invoke_generic_installer(["-Destination", target, "-OverwriteLocal"], ZOTERO_READING_HOME=str(data_home))
        self.assertEqual(response.returncode, 0, response.stderr)
        result = json.loads(response.stdout.splitlines()[0])
        self.assertTrue(Path(result["backup"]).is_relative_to(data_home / "skill-backups"))
        self.assertEqual((Path(result["backup"]) / "SKILL.md").read_text(encoding="utf-8"), "本地改动")

    def test_confirmed_directory_supports_other_agents_without_a_client_name(self):
        target = self.root / "other harness/custom skills/zotero-reading"
        response = self.invoke_generic_installer(["-Destination", target])
        self.assertEqual(response.returncode, 0, response.stdout + response.stderr)
        result = json.loads(response.stdout.splitlines()[0])
        self.assertEqual(result["client"], "Custom")
        self.assertEqual(Path(result["path"]), target)
        self.assertTrue((target / "INSTALL.md").exists())
        self.assertTrue((target / "scripts/bootstrap.py").exists())

    def test_deepseek_uses_its_default_skill_root(self):
        response = self.invoke_generic_installer(["-Client", "DeepSeekHarness"])
        self.assertEqual(response.returncode, 0, response.stdout + response.stderr)
        target = self.root / "recipient home/.dsh/skills/zotero-reading"
        self.assertEqual(Path(json.loads(response.stdout.splitlines()[0])["path"]), target)
        self.assertTrue((target / "SKILL.md").exists())
        self.assertFalse((self.root / "recipient home/.agents").exists())

    def test_deepseek_respects_custom_dsh_home(self):
        dsh_home = self.root / "custom DSH configuration"
        response = self.invoke_generic_installer(["-Client", "DeepSeekHarness"], DSH_HOME=str(dsh_home))
        self.assertEqual(response.returncode, 0, response.stdout + response.stderr)
        target = dsh_home / "skills/zotero-reading"
        self.assertEqual(Path(json.loads(response.stdout.splitlines()[0])["path"]), target)
        self.assertTrue((target / "references/report-format.md").exists())

    @unittest.skipUnless(importlib.util.find_spec("pypdf"), "Runtime reuse needs pypdf")
    def test_installed_entry_handles_spaces_utf8_and_shared_explicit_data_root(self):
        runtime_data = self.root / "共享数据 with spaces"
        for client in ("Codex", "ClaudeCode"):
            result = self.install(client)
            environment = dict(os.environ, ZOTERO_READING_PYTHON=sys.executable)
            response = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                                       str(Path(result["path"]) / "run.ps1"), "--data-dir", str(runtime_data),
                                       "setup", "--skip-zotero", "--no-install"], env=environment,
                                      capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(response.returncode, 0, response.stdout + response.stderr)
            setup = json.loads(response.stdout)
            self.assertEqual(setup["data_dir"], str(runtime_data))
            self.assertFalse(setup["runtime"]["installed"])
            self.assertEqual(setup["zotero"]["status"], "not_checked")


if __name__ == "__main__":
    unittest.main()
