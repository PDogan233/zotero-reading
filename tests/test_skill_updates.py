"""Controlled release fixtures; never download a real release or touch a user Skill."""

from copy import deepcopy
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import py_compile
import subprocess
import sys
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import bootstrap
from build_release import build, VERSION
import skill_updates as updates
from test_reading_workflow import temporary_workspace


REPOSITORY = "PDogan233/zotero-reading"


class FakeGitHub:
    def __init__(self, package, version=VERSION):
        self.package = package
        self.downloads = 0
        self.release = {"tag_name": "v" + version, "draft": False, "prerelease": False, "assets": [{
            "name": f"zotero-reading-{version}-skill.zip", "state": "uploaded", "size": len(package),
            "url": f"https://api.github.com/repos/{REPOSITORY}/releases/assets/123",
            "digest": "sha256:" + hashlib.sha256(package).hexdigest()}]}

    def latest(self, repository):
        return deepcopy(self.release)

    def download(self, asset, destination):
        self.downloads += 1
        Path(destination).write_bytes(self.package)


class SkillUpdateTests(unittest.TestCase):
    def setUp(self):
        temporary = temporary_workspace()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        package = build(self.root / "releases")["skill"]
        self.package = Path(package).read_bytes()
        self.github = FakeGitHub(self.package)
        self.target = self.root / "已安装 skills/zotero-reading"
        self.data = self.root / "自定义 数据目录"
        with zipfile.ZipFile(io.BytesIO(self.package)) as archive:
            archive.extractall(self.target.parent)
        manifest = json.loads((self.target / updates.MANIFEST).read_text(encoding="utf-8"))
        manifest["version"] = "0.2.1"
        manifest.pop("update_repository")
        (self.target / "scripts/skill_updates.py").unlink()
        manifest["files"].pop("scripts/skill_updates.py")
        # Mimic a complete older installation, rather than only changing metadata.
        for name in ("scripts/bootstrap.py", "scripts/zotero_notes.py"):
            path = self.target / name
            path.write_bytes(path.read_bytes().replace(VERSION.encode(), b"0.2.1"))
            manifest["files"][name] = updates.sha256(path)
        (self.target / updates.MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")

    def apply(self, **kwargs):
        return updates.apply(self.target, self.data, REPOSITORY, github=self.github, **kwargs)

    def revise_zip(self, change):
        with zipfile.ZipFile(io.BytesIO(self.package)) as archive:
            files = {name: archive.read(name) for name in archive.namelist()}
        change(files)
        result = io.BytesIO()
        with zipfile.ZipFile(result, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, data in files.items():
                archive.writestr(name, data)
        self.github = FakeGitHub(result.getvalue())

    def test_check_is_read_only_and_uses_explicit_repository_for_old_package(self):
        before = updates.snapshot(self.target)
        result = updates.check(self.target, REPOSITORY, self.github)[0]
        self.assertEqual(result["status"], "update_available")
        self.assertEqual(result["current_version"], "0.2.1")
        self.assertEqual(result["latest_version"], VERSION)
        self.assertEqual(result["local_changes"], [])
        self.assertEqual(updates.snapshot(self.target), before)
        self.assertFalse(self.data.exists())
        self.assertEqual(self.github.downloads, 0)

    def test_apply_preserves_private_data_extras_and_environment(self):
        private = self.data / "sessions/ABCD2345/discussion.md"
        private.parent.mkdir(parents=True)
        private.write_text("未保存讨论", encoding="utf-8")
        authorization = self.data / ".local/zotero-auth.json"
        authorization.parent.mkdir()
        authorization.write_text('{"test-only":"not-a-real-key"}', encoding="utf-8")
        extra = self.target / "personal.txt"
        extra.write_text("额外资料", encoding="utf-8")
        before = updates.snapshot(self.data)
        with patch.dict(os.environ, {"ZOTERO_READING_HOME": str(self.data)}):
            result = self.apply()
            self.assertEqual(os.environ["ZOTERO_READING_HOME"], str(self.data))
        self.assertEqual(result["status"], "updated")
        self.assertEqual(result["installed_version"], VERSION)
        self.assertEqual(updates.installed_manifest(self.target)["update_repository"], REPOSITORY)
        self.assertEqual(updates.local_changes(self.target, updates.installed_manifest(self.target)), [])
        self.assertEqual(extra.read_text(encoding="utf-8"), "额外资料")
        for name, digest in before.items():
            self.assertEqual(updates.sha256(self.data / name), digest)
        self.assertTrue(Path(result["backup"]).is_relative_to(self.data))
        self.assertFalse((self.target / "sessions").exists())
        self.assertEqual(self.github.downloads, 1)

    def test_local_edits_stop_without_downloading_and_explicit_override_backs_up(self):
        path = self.target / "SKILL.md"
        path.write_text("用户修改的提示词", encoding="utf-8")
        result = self.apply()
        self.assertEqual(result["status"], "local_changes")
        self.assertIn({"path": "SKILL.md", "kind": "modified"}, result["local_changes"])
        self.assertEqual(self.github.downloads, 0)
        self.assertFalse(self.data.exists())
        result = self.apply(overwrite_local=True)
        self.assertEqual(result["status"], "updated")
        self.assertEqual((Path(result["backup"]) / "SKILL.md").read_text(encoding="utf-8"), "用户修改的提示词")

    def test_new_managed_file_cannot_claim_an_extra_without_confirmation(self):
        path = self.target / "scripts/skill_updates.py"
        path.write_text("个人文件", encoding="utf-8")
        result = self.apply()
        self.assertEqual(result["status"], "local_changes")
        self.assertIn({"path": "scripts/skill_updates.py", "kind": "unmanaged_collision"}, result["local_changes"])
        self.assertEqual(path.read_text(encoding="utf-8"), "个人文件")

    def test_no_downgrade_or_same_version_reinstall(self):
        for version in ("0.1.0", "0.2.1"):
            github = FakeGitHub(self.package, version)
            result = updates.apply(self.target, self.data, REPOSITORY, github=github)
            self.assertEqual(result["status"], "up_to_date")
            self.assertEqual(github.downloads, 0)
        self.assertFalse(self.data.exists())

    def test_zip_hash_mismatch_changes_nothing(self):
        before = updates.snapshot(self.target)
        self.github.package += b"tampering"
        with self.assertRaisesRegex(updates.UpdateError, "SHA256"):
            self.apply()
        self.assertEqual(updates.snapshot(self.target), before)
        self.assertFalse(list(self.data.rglob("*.lock")))

    def test_actual_http_check_download_and_structured_404(self):
        package, release, requests = self.package, self.github.release, []
        class Handler(BaseHTTPRequestHandler):
            missing = False

            def do_GET(self):
                requests.append((self.path, dict(self.headers)))
                if self.missing:
                    self.send_error(404)
                    return
                body = package if self.path.endswith("/assets/123") else json.dumps(release).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        class LoopbackTransport:
            def open(self, request, timeout):
                from urllib.parse import urlsplit
                local = f"http://127.0.0.1:{server.server_port}" + urlsplit(request.full_url).path
                return urllib.request.urlopen(urllib.request.Request(local, headers=dict(request.header_items())), timeout=timeout)
        github = updates.GitHub()
        github.opener = LoopbackTransport()
        try:
            result = updates.apply(self.target, self.data, REPOSITORY, github=github)
            self.assertEqual(result["status"], "updated")
            self.assertEqual(len(requests), 2)
            self.assertEqual(requests[1][1]["Accept"], "application/octet-stream")
            self.assertFalse(any("Authorization" in headers for _, headers in requests))
            Handler.missing = True
            with patch.object(updates, "GitHub", return_value=github), patch("sys.stdout", new_callable=io.StringIO) as output:
                status = updates.main(["check", "--skill-dir", str(self.target)])
            self.assertEqual(status, 2)
            self.assertEqual(json.loads(output.getvalue())["http_status"], 404)
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=5)

    def test_archive_traversal_and_unlisted_files_are_rejected(self):
        before = updates.snapshot(self.target)
        for name in ("../outside.txt", "zotero-reading/../../outside.txt", "zotero-reading/C:/outside.txt",
                     "zotero-reading/extra-undeclared.txt", "zotero-reading/CON.txt"):
            with self.subTest(name=name):
                self.revise_zip(lambda files: files.update({name: b"bad"}))
                with self.assertRaises(updates.UpdateError):
                    self.apply()
                self.assertEqual(updates.snapshot(self.target), before)
        self.assertFalse((self.root / "outside.txt").exists())

    def test_internal_hash_version_and_repository_are_checked(self):
        before = updates.snapshot(self.target)
        cases = (lambda files: files.update({"zotero-reading/SKILL.md": b"tampered"}),)
        for change in cases:
            self.revise_zip(change)
            with self.assertRaisesRegex(updates.UpdateError, "摘要"):
                self.apply()
        for key, value in (("version", "9.9.9"), ("update_repository", "other/repo")):
            def change(files):
                name = "zotero-reading/" + updates.MANIFEST
                manifest = json.loads(files[name])
                manifest[key] = value
                files[name] = json.dumps(manifest).encode()
            self.revise_zip(change)
            with self.assertRaisesRegex(updates.UpdateError, "版本或更新仓库"):
                self.apply()
        self.assertEqual(updates.snapshot(self.target), before)

    def test_interrupted_copy_restores_every_original_file(self):
        before = updates.snapshot(self.target)
        original = updates.copy_file
        calls = 0
        def fail_once(source, destination):
            nonlocal calls
            calls += 1
            if calls == 3:
                raise OSError("simulated write failure")
            return original(source, destination)
        with patch.object(updates, "copy_file", side_effect=fail_once):
            result = self.apply()
        self.assertEqual(result["status"], "rolled_back")
        self.assertEqual(updates.snapshot(self.target), before)
        self.assertTrue(Path(result["backup"]).is_dir())

    def test_failed_post_update_health_check_restores_added_and_removed_files(self):
        manifest = updates.installed_manifest(self.target)
        path = self.target / "old-managed.txt"
        path.write_bytes(b"obsolete")
        manifest["files"][path.name] = updates.sha256(path)
        (self.target / updates.MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")
        before = updates.snapshot(self.target)
        with patch.object(updates, "healthcheck", side_effect=[None, updates.UpdateError("simulated")]):
            result = self.apply()
        self.assertEqual(result["status"], "rolled_back")
        self.assertEqual(updates.snapshot(self.target), before)

    def test_failed_restore_explicitly_reports_retained_backup(self):
        original = updates.shutil.copytree
        def fail_restore(source, destination, *args, **kwargs):
            if kwargs.get("dirs_exist_ok"):
                raise PermissionError("simulated restore denial")
            return original(source, destination, *args, **kwargs)
        with patch.object(updates.shutil, "copytree", side_effect=fail_restore), \
                patch.object(updates, "copy_file", side_effect=PermissionError("simulated write denial")):
            with self.assertRaisesRegex(updates.UpdateError, "恢复未完成"):
                self.apply()
        self.assertEqual(len(list((self.data / ".local/skill-updates").glob("backup-*/package-manifest.json"))), 1)

    def test_same_timestamp_python_cache_cannot_keep_old_code_after_update(self):
        updates.healthcheck(self.target, "0.2.1")
        path = self.target / "scripts/zotero_notes.py"
        py_compile.compile(str(path), doraise=True)
        old_stat = path.stat()
        original = updates.copy_file
        def preserve_old_time(source, destination):
            original(source, destination)
            if Path(destination) == path:
                os.utime(path, (old_stat.st_atime, old_stat.st_mtime))
        with patch.object(updates, "copy_file", side_effect=preserve_old_time):
            result = self.apply()
        self.assertEqual(result["status"], "updated")
        updates.healthcheck(self.target, VERSION)

    def test_concurrent_edit_of_an_already_modified_file_is_detected(self):
        path = self.target / "SKILL.md"
        path.write_text("第一版本地修改", encoding="utf-8")
        original = self.github.download
        def download(asset, destination):
            original(asset, destination)
            path.write_text("下载期间再次编辑", encoding="utf-8")
        with patch.object(self.github, "download", side_effect=download):
            with self.assertRaisesRegex(updates.UpdateError, "发生变化"):
                self.apply(overwrite_local=True)
        self.assertEqual(path.read_text(encoding="utf-8"), "下载期间再次编辑")

    def test_existing_lock_stops_second_updater_and_remains_for_review(self):
        work = self.data / ".local/skill-updates"
        work.mkdir(parents=True)
        identifier = hashlib.sha256(os.path.normcase(str(self.target.absolute())).encode()).hexdigest()[:16]
        lock = work / (identifier + ".lock")
        lock.write_text("other-process")
        with self.assertRaisesRegex(updates.UpdateError, "更新锁"):
            self.apply()
        self.assertEqual(self.github.downloads, 0)
        self.assertTrue(lock.exists())

    def test_source_tree_and_nested_data_directory_are_rejected(self):
        with self.assertRaises(updates.UpdateError):
            updates.check(Path(__file__).resolve().parents[1], REPOSITORY, self.github)
        with self.assertRaisesRegex(updates.UpdateError, "相互独立"):
            updates.apply(self.target, self.target / "data", REPOSITORY, github=self.github)
        self.assertEqual(self.github.downloads, 0)

    def test_missing_repository_requests_configuration_not_an_assumed_source(self):
        with self.assertRaisesRegex(updates.UpdateError, "明确指定"):
            updates.check(self.target, github=self.github)

    def test_github_404_reports_unpublished_repository_without_leaking_request(self):
        with patch.object(updates.GitHub, "latest", side_effect=urllib.error.HTTPError("https://api.github.com/x", 404, "Not found", {}, None)), \
                patch("sys.stdout", new_callable=io.StringIO) as output:
            code = updates.main(["check", "--repo", REPOSITORY, "--skill-dir", str(self.target)])
        result = json.loads(output.getvalue())
        self.assertEqual(code, 2)
        self.assertEqual(result["http_status"], 404)
        self.assertIn("正式Release", result["action"])

    def test_bootstrap_routes_updates_without_runtime_setup_or_zotero(self):
        with patch.object(updates, "main", return_value=0) as command, \
                patch.object(bootstrap, "ensure_runtime") as runtime, patch.object(bootstrap, "Client") as client:
            self.assertEqual(bootstrap.main(["--data-dir", str(self.data), "skill-update", "check"]), 0)
        command.assert_called_once_with(["check"], data_root=self.data.resolve())
        runtime.assert_not_called()
        client.assert_not_called()

    @unittest.skipUnless(os.name == "nt", "Windows packaged entry")
    def test_new_packaged_powershell_entry_exposes_update_help(self):
        # Exercise the actual new Windows entry after an upgrade.
        result = self.apply()
        self.assertEqual(result["status"], "updated")
        before = updates.snapshot(self.target)
        response = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
            str(self.target / "run.ps1"), "skill-update", "check", "--help"],
            env=dict(os.environ, ZOTERO_READING_PYTHON=sys.executable), capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(response.returncode, 0, response.stdout + response.stderr)
        self.assertIn("--overwrite-local", response.stdout)
        self.assertEqual(updates.snapshot(self.target), before)


class ReleaseValidationTests(unittest.TestCase):
    def test_numeric_versions_and_repository_normalization(self):
        self.assertGreater(updates.version_tuple("0.10.0"), updates.version_tuple("0.9.9"))
        self.assertEqual(updates.repository_name("https://github.com/PDogan233/zotero-reading.git"), REPOSITORY)
        for value in ("../x", "https://evil.test/owner/repo", "owner/repo/extra"):
            with self.assertRaises(updates.UpdateError):
                updates.repository_name(value)
        for value in ("v0.3.0", "0.3.0-rc1", "0.03.0", None):
            with self.assertRaises(updates.UpdateError):
                updates.version_tuple(value)

    def test_prerelease_wrong_asset_url_and_missing_digest_are_rejected(self):
        github = FakeGitHub(b"fake")
        for change in (lambda r: r.update(prerelease=True), lambda r: r.update(draft=True),
                       lambda r: r["assets"][0].update(digest=None),
                       lambda r: r["assets"][0].update(url="https://evil.test/a"),
                       lambda r: r["assets"][0].update(name="source.zip")):
            release = deepcopy(github.release)
            change(release)
            with self.assertRaises(updates.UpdateError):
                updates.release_info(release, REPOSITORY)

    def test_manifest_cannot_exploit_windows_names_case_or_prefix_collisions(self):
        for names in (("SKILL.md", "skill.md"), ("a", "a/b"), ("CON.txt",), ("a/.. /b",), ("a\\b",)):
            with self.subTest(names=names), self.assertRaises(updates.UpdateError):
                updates.manifest_data({"name": "zotero-reading", "version": VERSION,
                                      "files": {name: "0" * 64 for name in names}})

    def test_redirects_accept_github_assets_and_reject_other_hosts_or_http(self):
        handler = updates.GitHubRedirects()
        request = urllib.request.Request("https://api.github.com/repos/x/y/releases/assets/1")
        accepted = handler.redirect_request(request, None, 302, "Found", {}, "https://release-assets.githubusercontent.com/file")
        self.assertTrue(accepted.full_url.startswith("https://release-assets."))
        for url in ("http://github.com/a", "https://github.com.evil.test/a", "https://user:secret@github.com/a"):
            with self.assertRaises(updates.UpdateError):
                handler.redirect_request(request, None, 302, "Found", {}, url)


if __name__ == "__main__":
    unittest.main()
