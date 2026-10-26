"""Persistent discussion and explicit report revisions, without a real library."""

from copy import deepcopy
from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.parse

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from reading_sessions import (HK, draft_from_records, item_key, managed_report, paper_children, query_papers, read_json, record_discussion,
                              refresh_context, session_path, start_session, write_json)
from zotero_notes import (ZoteroError, ensure_qa_merged, publish_report, save_report, store_receipt, update_report)
from test_zotero_notes import FakeClient, report

TEST_TMP = Path(__file__).resolve().parents[1] / ".local" / "test-runs"


def temporary_workspace():
    TEST_TMP.mkdir(parents=True, exist_ok=True)
    temporary = tempfile.TemporaryDirectory(dir=TEST_TMP)
    if not Path(temporary.name).resolve().is_relative_to(TEST_TMP.resolve()):
        raise ValueError("Test cleanup target escaped its intended temporary directory")
    return temporary


class RevisionClient(FakeClient):
    def __init__(self):
        super().__init__()
        self.patches = []
        self.race = False
        self.lose_patch_response = False

    def request(self, method, path, data=None, extra_headers=None):
        if method != "PATCH":
            value = super().request(method, path, data, extra_headers)
            if method == "POST" and value[0].get("successful"):
                self.items[data[0]["key"]]["data"]["version"] = 1
            return value
        key = path.rsplit("/", 1)[1]
        note = self.items[key]["data"]
        if self.race:
            note["version"] += 1
        if str(note["version"]) != extra_headers["If-Unmodified-Since-Version"]:
            raise ZoteroError("Concurrent edit", 412)
        self.patches.append(deepcopy(data))
        note["note"] = '<div class="zotero-note"><div data-schema-version="9">' + data["note"] + "</div></div>"
        note["version"] += 1
        if self.lose_patch_response:
            raise ZoteroError("Response lost after update")
        return "", {}


class RevisionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = temporary_workspace()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "report.json"
        self.client = RevisionClient()
        self.original = report()
        self.receipt = save_report(self.client, self.original)
        self.revision = deepcopy(self.original)
        self.revision["qa"] = [{"question": "测试问题", "answer": "经过讨论的测试回答", "sources": [{"page": 2}]}]

    def test_explicit_update_uses_same_note_and_backs_up_old_content(self):
        result = update_report(self.client, self.revision, self.receipt, self.path)
        self.assertEqual(result["status"], "updated_and_verified")
        self.assertEqual(result["note_key"], self.receipt["note_key"])
        backup = read_json(result["backup"])
        self.assertNotIn("测试问题", backup["note"]["data"]["note"])
        self.assertIn("测试问题", self.client.items[result["note_key"]]["data"]["note"])
        self.assertEqual(self.client.patches, [{"note": self.client.patches[0]["note"]}])

    def test_external_body_edit_is_never_overwritten(self):
        note = self.client.items[self.receipt["note_key"]]["data"]
        note["note"] += "<p>用户手写补充</p>"
        note["version"] += 1
        with self.assertRaisesRegex(ValueError, "手工修改"):
            update_report(self.client, self.revision, self.receipt, self.path)
        self.assertEqual(self.client.patches, [])
        self.assertEqual(self.client.authorizations, 1)

    def test_metadata_only_edit_preserves_user_tags(self):
        note = self.client.items[self.receipt["note_key"]]["data"]
        note["tags"].append({"tag": "用户自定义标签"})
        note["version"] += 1
        result = update_report(self.client, self.revision, self.receipt, self.path)
        self.assertEqual(result["status"], "updated_and_verified")
        self.assertIn({"tag": "用户自定义标签"}, note["tags"])

    def test_unchanged_text_with_manual_format_cannot_reset_update_baseline(self):
        note = self.client.items[self.receipt["note_key"]]["data"]
        note["note"] = note["note"].replace("有条件", "<strong>有条件</strong>")
        note["version"] += 1
        with self.assertRaisesRegex(ValueError, "手工修改"):
            update_report(self.client, self.original, self.receipt, self.path)
        self.assertEqual(self.client.patches, [])

    def test_repeated_save_cannot_refresh_baseline_after_manual_format_edit(self):
        store_receipt(self.path, self.original, self.receipt)
        note = self.client.items[self.receipt["note_key"]]["data"]
        note["note"] = note["note"].replace("有条件", "<strong>有条件</strong>")
        note["version"] += 1
        result = save_report(self.client, self.original)
        with self.assertRaisesRegex(ValueError, "手工修改"):
            store_receipt(self.path, self.original, result)
        self.assertEqual(read_json(self.path.with_suffix(".receipt.json")), self.receipt)
        self.assertEqual(read_json(self.path.with_suffix(".saved.json")), self.original)

    def test_optimistic_version_check_blocks_race(self):
        self.client.race = True
        with self.assertRaises(ZoteroError) as failure:
            update_report(self.client, self.revision, self.receipt, self.path)
        self.assertEqual(failure.exception.status, 412)
        self.assertEqual(self.client.patches, [])

    def test_dry_run_never_authorizes_or_writes(self):
        result = update_report(self.client, self.revision, self.receipt, self.path, dry_run=True)
        self.assertEqual(result["status"], "update_ready")
        self.assertEqual(self.client.authorizations, 1)
        self.assertFalse((self.path.parent / "history").exists())

    def test_lost_update_response_can_be_reconciled(self):
        self.client.lose_patch_response = True
        with self.assertRaises(ZoteroError):
            update_report(self.client, self.revision, self.receipt, self.path)
        result = update_report(self.client, self.revision, self.receipt, self.path)
        self.assertEqual(result["status"], "already_current")
        self.assertEqual(len(self.client.patches), 1)

    def test_other_library_or_handwritten_note_is_rejected(self):
        wrong = dict(self.receipt, server_id="other")
        with self.assertRaises(ValueError):
            update_report(self.client, self.revision, wrong, self.path)
        self.client.items[self.receipt["note_key"]]["data"]["tags"] = []
        with self.assertRaises(ZoteroError):
            update_report(self.client, self.revision, self.receipt, self.path)
        self.assertEqual(self.client.patches, [])

    def test_format_edit_after_lost_response_is_not_adopted(self):
        self.client.lose_patch_response = True
        with self.assertRaises(ZoteroError):
            update_report(self.client, self.revision, self.receipt, self.path)
        note = self.client.items[self.receipt["note_key"]]["data"]
        note["note"] = note["note"].replace("测试问题", "<strong>测试问题</strong>")
        note["version"] += 1
        with self.assertRaisesRegex(ValueError, "手工修改"):
            update_report(self.client, self.revision, self.receipt, self.path)
        self.assertEqual(len(self.client.patches), 1)

    def test_draft_cannot_be_published(self):
        draft = dict(self.revision, draft=True)
        with self.assertRaisesRegex(ValueError, "草稿"):
            save_report(self.client, draft)
        with self.assertRaisesRegex(ValueError, "草稿"):
            update_report(self.client, draft, self.receipt, self.path)

    def test_old_receipt_requires_verified_baseline(self):
        old = dict(self.receipt)
        old.pop("note_version")
        old.pop("content_hash")
        with self.assertRaisesRegex(ValueError, "基线"):
            update_report(self.client, self.revision, old, self.path)


class DedicatedNoteTests(unittest.TestCase):
    def setUp(self):
        self.temporary = temporary_workspace()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "report.json"
        self.client = RevisionClient()

    def handwritten(self):
        key = "ABCDEFGH"
        item = {"data": {"key": key, "itemType": "note", "parentItem": "IGIEWQ9W",
                         "note": "<p>保留原来的手写笔记</p>", "version": 1, "tags": []}}
        self.client.items[key] = item
        return key, deepcopy(item)

    def test_first_save_creates_one_dedicated_note_and_keeps_existing_notes(self):
        handwritten_key, handwritten = self.handwritten()
        prepared = report()
        result = publish_report(self.client, prepared, self.path)
        self.assertEqual(result["status"], "saved_and_verified")
        self.assertEqual(prepared["report_id"], "review-IGIEWQ9W")
        self.assertEqual(self.client.items[handwritten_key], handwritten)
        self.assertEqual(len(self.client.posts), 1)

    def test_save_in_a_new_session_replaces_the_same_legacy_note(self):
        handwritten_key, handwritten = self.handwritten()
        receipt = save_report(self.client, report())
        revision = report()
        revision["report_id"] = "different-session-id"
        revision["sections"][0]["paragraphs"][0]["text"] = "新的阅读结论"
        result = publish_report(self.client, revision, self.path)
        self.assertEqual(result["note_key"], receipt["note_key"])
        self.assertEqual(revision["report_id"], receipt["report_id"])
        self.assertEqual(len(self.client.posts), 1)
        self.assertEqual(len(self.client.patches), 1)
        self.assertEqual(self.client.items[handwritten_key], handwritten)
        self.assertTrue(Path(result["backup"]).exists())

    def test_designated_note_can_be_replaced_without_a_local_receipt(self):
        receipt = save_report(self.client, report())
        current = self.client.items[receipt["note_key"]]["data"]
        current["note"] += "<p>专用AI笔记里的手动编辑</p>"
        current["version"] += 1
        revision = report()
        revision["sections"][0]["paragraphs"][0]["text"] = "重新整理的完整报告"
        result = publish_report(self.client, revision, self.path)
        backup = read_json(result["backup"])
        self.assertIn("手动编辑", backup["note"]["data"]["note"])
        self.assertNotIn("手动编辑", current["note"])
        self.assertEqual(result["note_key"], receipt["note_key"])

    def test_similar_title_or_generic_ai_tag_does_not_claim_another_note(self):
        key, _ = self.handwritten()
        self.client.items[key]["data"]["tags"] = [{"tag": "AI阅读报告"}, {"tag": "reading-report:foreign"}]
        original = deepcopy(self.client.items[key])
        result = publish_report(self.client, report(), self.path)
        self.assertNotEqual(result["note_key"], key)
        self.assertEqual(self.client.items[key], original)

    def test_two_legacy_managed_notes_are_not_arbitrarily_chosen(self):
        first = save_report(self.client, report())
        second = deepcopy(self.client.items[first["note_key"]])
        second["data"]["key"] = item_key("IGIEWQ9W", "second-legacy-report")
        second["data"]["tags"] = [{"tag": "AI阅读报告"}, {"tag": "reading-report:second-legacy-report"}]
        self.client.items[second["data"]["key"]] = second
        with self.assertRaisesRegex(ValueError, "多份"):
            publish_report(self.client, report(), self.path)
        self.assertEqual(self.client.patches, [])

    def test_direct_create_cannot_add_a_second_report_id_for_the_paper(self):
        save_report(self.client, report())
        other = report()
        other["report_id"] = "second-report"
        with self.assertRaisesRegex(ValueError, "第二份"):
            save_report(self.client, other)
        self.assertEqual(len(self.client.posts), 1)

    def test_existing_managed_note_beyond_first_page_is_found(self):
        receipt = save_report(self.client, report())
        children = [{"data": {"itemType": "annotation"}} for _ in range(100)]
        children.append(self.client.items[receipt["note_key"]])
        requested = []

        def pages(method, path, *args):
            requested.append(path)
            start = int(urllib.parse.parse_qs(urllib.parse.urlsplit(path).query)["start"][0])
            return children[start:start + 100], {}

        with patch.object(self.client, "request", side_effect=pages):
            found = managed_report(paper_children(self.client, "IGIEWQ9W"), "IGIEWQ9W", self.client)
        self.assertEqual(found[1], receipt["report_id"])
        self.assertEqual(len(requested), 2)

    def test_dedicated_overwrite_still_checks_the_current_version(self):
        save_report(self.client, report())
        self.client.race = True
        revision = report()
        revision["sections"][0]["paragraphs"][0]["text"] = "准备覆盖的报告"
        with self.assertRaises(ZoteroError) as failure:
            publish_report(self.client, revision, self.path)
        self.assertEqual(failure.exception.status, 412)
        self.assertEqual(self.client.patches, [])

    def test_overwrite_preview_never_authorizes_backs_up_or_writes(self):
        save_report(self.client, report())
        revision = report()
        revision["sections"][0]["paragraphs"][0]["text"] = "准备覆盖的报告"
        result = publish_report(self.client, revision, self.path, dry_run=True)
        self.assertEqual(result["status"], "update_ready")
        self.assertEqual(self.client.authorizations, 1)
        self.assertFalse((self.path.parent / "history").exists())


class DiscoveryClient:
    server_id = "session-server"

    def __init__(self, items):
        self.items = items
        self.queries = []

    def request(self, method, path, *args):
        self.queries.append(path)
        params = urllib.parse.parse_qs(urllib.parse.urlsplit(path).query)
        start = int(params.get("start", [0])[0])
        return self.items[start:start + 100], {}


def paper_item(key="IGIEWQ9W", added="2026-10-12T09:13:57Z", item_type="journalArticle"):
    return {"key": key, "meta": {"creatorSummary": "Author"}, "data": {
        "itemType": item_type, "title": "Example paper", "dateAdded": added, "DOI": "10.1/test"}}


class SessionClient:
    server_id = "session-server"

    def __init__(self):
        self.pdfs = [{"key": "6N5VPAT4", "data": {"contentType": "application/pdf"}}]

    def item(self, key):
        return paper_item(key)

    def request(self, method, path, *args):
        return self.pdfs, {}


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = temporary_workspace()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "sessions"
        self.client = SessionClient()
        self.snapshot = {"path": "source.pdf", "sha256": "test-digest", "page_count": 9}
        self.source_patch = patch("reading_sessions.pdf_snapshot", return_value=self.snapshot)
        self.source_patch.start()
        self.addCleanup(self.source_patch.stop)

    def test_find_encodes_query_and_filters_non_papers(self):
        client = DiscoveryClient([paper_item(item_type="note"), paper_item()])
        items = query_papers(client, query="中文 title", limit=1)
        self.assertEqual(items[0]["key"], "IGIEWQ9W")
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(client.queries[0]).query)
        self.assertEqual(query["q"], ["中文 title"])

    def test_recent_date_range_uses_hong_kong_calendar(self):
        client = DiscoveryClient([paper_item("UN43QYKL", "2026-10-12T16:05:00Z"),
                                  paper_item("IGIEWQ9W", "2026-10-12T15:55:00Z")])
        items = query_papers(client, from_date="2026-10-13", to_date="2026-10-13")
        self.assertEqual([i["key"] for i in items], ["UN43QYKL"])

    def test_doi_search_filters_exact_metadata_match(self):
        other = paper_item("UN43QYKL")
        other["data"]["DOI"] = "10.1/other"
        client = DiscoveryClient([other, paper_item()])
        items = query_papers(client, doi="https://doi.org/10.1/TEST")
        self.assertEqual([i["key"] for i in items], ["IGIEWQ9W"])

    def test_recent_days_and_pagination(self):
        items = [paper_item(item_type="note") for _ in range(100)] + [paper_item()]
        client = DiscoveryClient(items)
        found = query_papers(client, days=2, now=datetime(2026, 10, 13, tzinfo=HK), limit=1)
        self.assertEqual(len(found), 1)
        self.assertEqual(len(client.queries), 2)

    def test_start_creates_draft_and_resume_keeps_records(self):
        result = start_session(self.client, self.root, "IGIEWQ9W")
        directory = Path(result["session"])
        self.assertTrue(read_json(directory / "report.json")["draft"])
        record_discussion(directory, "qa", question="测试Q", answer="测试A", pages=[6], location="图4")
        resumed = refresh_context(directory)
        self.assertEqual(resumed["record_count"], 1)
        self.assertIn("测试Q", (directory / "context.md").read_text(encoding="utf-8"))
        draft_from_records(directory)
        prepared = read_json(directory / "report.json")
        self.assertEqual(prepared["qa"][0]["answer"], "测试A")
        self.assertEqual(prepared["qa"][0]["sources"][0]["page"], 6)
        draft_from_records(directory)
        self.assertEqual(len(read_json(directory / "report.json")["qa"]), 1)

    def test_start_does_not_overwrite_existing_draft(self):
        directory = Path(start_session(self.client, self.root, "IGIEWQ9W")["session"])
        content = read_json(directory / "report.json")
        content["sections"][0]["paragraphs"][0]["text"] = "已有讨论成果"
        write_json(directory / "report.json", content)
        start_session(self.client, self.root, "IGIEWQ9W")
        self.assertEqual(read_json(directory / "report.json"), content)

    def test_new_session_reuses_the_report_identifier_found_in_zotero(self):
        key = item_key("IGIEWQ9W", "legacy-review")
        self.client.pdfs.append({"key": key, "data": {
            "key": key, "itemType": "note", "parentItem": "IGIEWQ9W",
            "note": "<p>已保存的测试阅读笔记</p>",
            "tags": [{"tag": "AI阅读报告"}, {"tag": "reading-report:legacy-review"}]}})
        directory = Path(start_session(self.client, self.root, "IGIEWQ9W")['session'])
        self.assertEqual(read_json(directory / "report.json")["report_id"], "legacy-review")

    def test_multiple_pdfs_are_not_silently_selected(self):
        self.client.pdfs.append({"key": "PMQGVYHX", "data": {"contentType": "application/pdf"}})
        with patch("reading_sessions.pdf_snapshot", side_effect=lambda client, key: dict(self.snapshot, sha256=key)), self.assertRaisesRegex(ValueError, "唯一"):
            start_session(self.client, self.root, "IGIEWQ9W")

    def test_start_adopts_existing_legacy_session_without_duplicate_folder(self):
        directory = self.root / "legacy"
        prepared = report()
        write_json(directory / "report.json", prepared)
        result = start_session(self.client, self.root, "IGIEWQ9W")
        self.assertEqual(Path(result["session"]), directory)
        self.assertEqual(read_json(directory / "report.json"), prepared)
        self.assertFalse((self.root / "IGIEWQ9W").exists())

    def test_ambiguous_existing_sessions_require_a_directory(self):
        write_json(self.root / "one" / "report.json", report())
        write_json(self.root / "two" / "report.json", report())
        with self.assertRaisesRegex(ValueError, "多个会话"):
            start_session(self.client, self.root, "IGIEWQ9W")

    def test_session_paths_and_wrong_library_are_rejected(self):
        with self.assertRaises(ValueError):
            start_session(self.client, self.root, "IGIEWQ9W", directory=self.root.parent / "outside")
        directory = Path(start_session(self.client, self.root, "IGIEWQ9W")["session"])
        self.client.server_id = "different"
        with self.assertRaisesRegex(ValueError, "文献库"):
            start_session(self.client, self.root, "IGIEWQ9W")
        self.assertEqual(session_path(self.root, "IGIEWQ9W"), directory)

    def test_changed_pdf_or_bad_record_page_is_rejected(self):
        directory = Path(start_session(self.client, self.root, "IGIEWQ9W")["session"])
        with self.assertRaises(ValueError):
            record_discussion(directory, "fact", text="test", pages=[10])
        self.snapshot["sha256"] = "changed"
        with self.assertRaisesRegex(ValueError, "PDF版本"):
            start_session(self.client, self.root, "IGIEWQ9W")

    def test_minor_qa_is_kept_in_context_but_not_drafted(self):
        directory = Path(start_session(self.client, self.root, "IGIEWQ9W")["session"])
        record_discussion(directory, "qa", question="minor", answer="answer", important=False)
        draft_from_records(directory)
        self.assertEqual(read_json(directory / "report.json")["qa"], [])
        self.assertEqual(refresh_context(directory)["record_count"], 1)

    def test_important_qa_must_be_considered_before_saving(self):
        directory = Path(start_session(self.client, self.root, "IGIEWQ9W")["session"])
        record_discussion(directory, "qa", question="important", answer="answer")
        with self.assertRaisesRegex(ValueError, "尚未归纳"):
            ensure_qa_merged(read_json(directory / "report.json"), directory / "report.json")
        draft_from_records(directory)
        ensure_qa_merged(read_json(directory / "report.json"), directory / "report.json")


if __name__ == "__main__":
    unittest.main()
