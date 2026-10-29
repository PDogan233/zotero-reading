"""Per-turn saving, user pause preferences, and the opening evidence-backed idea."""
from copy import deepcopy
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import bootstrap
import zotero_notes as notes
from reading_sessions import bind_sources, read_json, read_save_mode, set_save_mode, write_json
from test_reading_workflow import RevisionClient, temporary_workspace
from test_zotero_notes import report


def ready_report():
    value = report()
    value.update(format_version=2, draft=False, status="讨论中",
                 core_idea={"text": "测试系统用一套结构完成两项任务；这里仍是待实验证实的解释。",
                            "sources": [{"page": 1, "location": "引言"}]})
    value["paper"]["page_count"] = 5
    value["paper"]["attachments"] = [{"key": "6N5VPAT4", "role": "main", "page_count": 5, "reading_status": "read"}]
    return value


class Output(io.StringIO):
    def reconfigure(self, **kwargs):
        pass


class AutosaveTests(unittest.TestCase):
    def setUp(self):
        temporary = temporary_workspace()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / "sessions/IGIEWQ9W/report.json"
        self.path.parent.mkdir(parents=True)

    def command(self, arguments, client=None):
        output = Output()
        with patch("sys.argv", ["zotero_notes.py", "--data-dir", str(self.root), *arguments]), \
                patch("sys.stdout", output), patch.object(notes, "Client") as factory:
            if client:
                client.connect = lambda: None
                factory.return_value = client
            notes.main()
        return json.loads(output.getvalue()), factory

    def test_default_is_auto_and_session_pause_survives_global_changes(self):
        self.assertEqual(read_save_mode(self.root)["mode"], "auto")
        write_json(self.path.parent / "session.json", {"save_mode": "manual"})
        set_save_mode(self.root, "auto")
        self.assertEqual(read_save_mode(self.root, self.path.parent), {"mode": "manual", "scope": "session"})
        set_save_mode(self.root, "auto", self.path.parent)
        self.assertEqual(read_save_mode(self.root, self.path.parent)["mode"], "auto")

    def test_invalid_saved_preferences_never_silently_enable_writes(self):
        for invalid in ({"save_mode": "unknown"}, []):
            write_json(self.root / ".local/reading-preferences.json", invalid)
            with self.assertRaises(ValueError):
                notes.autosave_preflight(ready_report(), self.path, self.root)

    def test_paused_autosave_never_connects_or_requests_authorization(self):
        set_save_mode(self.root, "manual")
        write_json(self.path, ready_report())
        result, client = self.command(["autosave", str(self.path)])
        self.assertEqual(result["status"], "autosave_disabled")
        client.assert_not_called()
        self.assertFalse(self.path.with_suffix(".receipt.json").exists())

    def test_unready_or_missing_core_is_deferred_before_connection(self):
        for value in (dict(ready_report(), draft=True), report()):
            write_json(self.path, value)
            result, client = self.command(["autosave", str(self.path)])
            self.assertEqual(result["status"], "autosave_deferred")
            client.assert_not_called()

    def test_new_unmerged_important_qa_prevents_automatic_write(self):
        write_json(self.path.parent / "records.json", [{"id": "new", "kind": "qa", "important": True}])
        write_json(self.path, ready_report())
        result, client = self.command(["autosave", str(self.path)])
        self.assertEqual(result["status"], "autosave_deferred")
        self.assertIn("重要问答", result["action"])
        client.assert_not_called()

    def test_unread_source_is_deferred_even_when_a_core_idea_is_filled(self):
        value = ready_report()
        value["paper"]["attachments"][0]["reading_status"] = "pending"
        write_json(self.path, value)
        result, client = self.command(["autosave", str(self.path)])
        self.assertEqual(result["status"], "autosave_deferred")
        client.assert_not_called()

    def test_create_update_and_no_change_keep_one_note_and_preserve_other_notes(self):
        client = RevisionClient()
        other = {"data": {"key": "ABCDEFGH", "parentItem": "IGIEWQ9W", "itemType": "note",
                          "note": "<p>手写内容</p>", "tags": [], "version": 1}}
        client.items["ABCDEFGH"] = deepcopy(other)
        write_json(self.path, ready_report())
        first, _ = self.command(["autosave", str(self.path)], client)
        self.assertEqual(first["status"], "saved_and_verified")
        value = read_json(self.path)
        value["core_idea"]["text"] = "进一步讨论后，把同一结构如何并行工作作为本次阅读重点。"
        write_json(self.path, value)
        second, _ = self.command(["autosave", str(self.path)], client)
        self.assertEqual(second["status"], "updated_and_verified")
        self.assertEqual(first["note_key"], second["note_key"])
        backups = list((self.path.parent / "history").glob("*.json"))
        self.assertEqual(len(backups), 1)
        third, _ = self.command(["autosave", str(self.path)], client)
        self.assertEqual(third["status"], "already_current")
        self.assertEqual(len(client.patches), 1)
        self.assertEqual(list((self.path.parent / "history").glob("*.json")), backups)
        self.assertEqual(client.items["ABCDEFGH"], other)

    def test_explicit_save_can_save_once_while_default_remains_manual(self):
        set_save_mode(self.root, "manual")
        write_json(self.path, ready_report())
        result, _ = self.command(["save", str(self.path)], RevisionClient())
        self.assertEqual(result["status"], "saved_and_verified")
        self.assertEqual(read_save_mode(self.root)["mode"], "manual")

    def test_preference_command_does_not_initialize_pdf_runtime(self):
        with patch.object(bootstrap, "ensure_runtime") as runtime, patch.object(bootstrap.subprocess, "call", return_value=0) as command:
            self.assertEqual(bootstrap.main(["--data-dir", str(self.root), "save-mode", "manual"]), 0)
        runtime.assert_not_called()
        self.assertIn("save-mode", command.call_args.args[0])


class CoreIdeaTests(unittest.TestCase):
    def test_core_is_after_date_before_materials_and_sections_without_status(self):
        value = ready_report()
        value["paper"]["attachments"].append({"key": "ABCDEFGH", "role": "supplement", "page_count": 2, "reading_status": "read"})
        value["core_idea"]["sources"][0]["attachment_key"] = "6N5VPAT4"
        value["sections"][0]["paragraphs"][0]["sources"][0]["attachment_key"] = "6N5VPAT4"
        html = notes.render_note(value)
        self.assertLess(html.index("阅读日期"), html.index("核心贡献或理念"))
        self.assertLess(html.index("核心贡献或理念"), html.index("<h2>阅读材料</h2>"))
        self.assertLess(html.index("核心贡献或理念"), html.index("<h2>结果</h2>"))
        self.assertNotIn("讨论中", html)
        self.assertIn("仍是待实验证实", html)
        self.assertIn("6N5VPAT4?page=1", html)

    def test_new_supplement_preserves_original_core_citation_coordinates(self):
        value = ready_report()
        sources = [{"key": "6N5VPAT4", "role": "main", "sha256": "main", "page_count": 5},
                   {"key": "ABCDEFGH", "role": "supplement", "sha256": "supplement", "page_count": 2}]
        bind_sources(value, sources, "6N5VPAT4")
        self.assertEqual(value["core_idea"]["sources"][0]["attachment_key"], "6N5VPAT4")
        notes.validate_report(value)
        self.assertIn("6N5VPAT4?page=1", notes.render_note(value))

    def test_core_uses_normal_escaping_and_rejects_unsafe_or_wrong_evidence(self):
        value = ready_report()
        value["core_idea"]["text"] = "<script>alert(1)</script> & 核心"
        self.assertIn("&lt;script&gt;", notes.render_note(value))
        for core in ({"text": "越界", "sources": [{"page": 6}]},
                     {"text": "不安全", "external_sources": [{"url": "javascript:alert(1)", "location": "来源"}]},
                     {"text": "错附件", "sources": [{"page": 1, "attachment_key": "ABCDEFGH"}]}):
            with self.subTest(core=core), self.assertRaises(ValueError):
                notes.validate_report(dict(value, core_idea=core), require_ready=True)

    def test_core_must_be_populated_and_located_before_new_format_save(self):
        for core in (None, {"text": "", "sources": []}, {"text": "没有证据的判断"}):
            with self.subTest(core=core), self.assertRaises(ValueError):
                notes.validate_report(dict(ready_report(), core_idea=core), require_ready=True)

    def test_legacy_snapshot_rendering_remains_identical_during_upgrade(self):
        value = report()
        old = notes.render_note(value)
        self.assertIn("<p>测试</p>", old)
        self.assertNotIn("核心贡献或理念", old)
        notes.validate_report(value, require_ready=True)
        client = RevisionClient()
        temporary = temporary_workspace()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "report.json"
        original = notes.publish_report(client, value, path)
        upgraded = ready_report()
        result = notes.publish_report(client, upgraded, path)
        self.assertEqual(result["note_key"], original["note_key"])
        self.assertEqual(result["status"], "updated_and_verified")
        self.assertIn("核心贡献或理念", client.items[result["note_key"]]["data"]["note"])


if __name__ == "__main__":
    unittest.main()
