"""Joint reading uses Zotero ownership and each PDF's own evidence coordinates."""

from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from reading_sessions import (draft_from_records, read_json, record_discussion, reference_key,
                              resolve_paper, session_path, start_session, write_json)
from zotero_notes import publish_report, render_note, source_links, validate_report
from test_reading_workflow import RevisionClient, temporary_workspace
from test_zotero_notes import report


MAIN = "6N5VPAT4"
SUPPLEMENT = "YXSKKPJ8"
PARENT = "IGIEWQ9W"


class BundleClient(RevisionClient):
    def __init__(self):
        super().__init__()
        self.items[MAIN]["data"].update(key=MAIN, itemType="attachment", title="Full Text PDF", filename="main.pdf")
        self.items[SUPPLEMENT] = {"key": SUPPLEMENT, "data": {
            "key": SUPPLEMENT, "itemType": "attachment", "contentType": "application/pdf",
            "parentItem": PARENT, "title": "Supplemental material", "filename": "supplement.pdf"}}
        self.snapshots = {MAIN: {"path": "main.pdf", "sha256": "main-hash", "page_count": 10},
                          SUPPLEMENT: {"path": "supplement.pdf", "sha256": "supplement-hash", "page_count": 4}}

    def snapshot(self, client, key):
        return deepcopy(self.snapshots[key])

    def request(self, method, path, data=None, extra_headers=None):
        if method == "GET" and "/children" in path:
            return [{"key": key, "data": deepcopy(item["data"])} for key, item in self.items.items()
                    if item["data"].get("parentItem") == PARENT], {}
        return super().request(method, path, data, extra_headers)


class JointReadingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = temporary_workspace()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "sessions"
        self.client = BundleClient()
        for namespace in ("reading_sessions", "zotero_notes"):
            source_patch = patch(namespace + ".pdf_snapshot", side_effect=self.client.snapshot)
            source_patch.start()
            self.addCleanup(source_patch.stop)

    def start(self, references=SUPPLEMENT):
        return Path(start_session(self.client, self.root, references)["session"])

    def prepared(self, directory):
        prepared = read_json(directory / "report.json")
        prepared["draft"] = False
        prepared["core_idea"] = {"text": "正文与补充材料共同支持的测试理念。", "sources": [{"attachment_key": MAIN, "page": 2}]}
        for source in prepared["paper"]["attachments"]:
            source["reading_status"] = "read"
        prepared["sections"][0]["paragraphs"][0] = {"text": "正文与补充材料共同支持的测试结论。", "sources": [
            {"attachment_key": MAIN, "page": 2, "location": "图1"},
            {"attachment_key": SUPPLEMENT, "page": 4, "location": "表S1"}]}
        return prepared

    def test_start_from_supplement_automatically_groups_the_whole_paper(self):
        directory = self.start()
        state = read_json(directory / "session.json")
        self.assertEqual(state["paper"]["parent_key"], PARENT)
        self.assertEqual(state["paper"]["attachment_key"], MAIN)
        self.assertEqual([(s["key"], s["role"], s["page_count"]) for s in state["sources"]],
                         [(MAIN, "main", 10), (SUPPLEMENT, "supplement", 4)])
        self.assertIn("supplement.pdf", (directory / "context.md").read_text(encoding="utf-8"))
        self.assertEqual(session_path(self.root, SUPPLEMENT), directory)

    def test_two_attachment_keys_or_storage_paths_resolve_to_one_session(self):
        directory = self.start([MAIN, SUPPLEMENT])
        same = self.start([r"C:\Users\test\Zotero\storage\YXSKKPJ8",
                           r"C:\Users\test\Zotero\storage\6N5VPAT4\main.pdf"])
        self.assertEqual(directory, same)
        self.assertEqual(reference_key(r"C:\Zotero\storage\YXSKKPJ8/"), SUPPLEMENT)

    def test_attachments_of_different_papers_are_never_combined(self):
        self.client.items[SUPPLEMENT]["data"]["parentItem"] = "UN43QYKL"
        with self.assertRaisesRegex(ValueError, "不同文献"):
            resolve_paper(self.client, [MAIN, SUPPLEMENT])

    def test_standalone_pdf_cannot_be_assigned_by_filename(self):
        self.client.items[SUPPLEMENT]["data"].pop("parentItem")
        with self.assertRaisesRegex(ValueError, "不能自动归组"):
            resolve_paper(self.client, SUPPLEMENT)

    def test_citations_link_to_their_respective_pdfs(self):
        prepared = self.prepared(self.start())
        html = render_note(prepared)
        self.assertEqual(source_links(html), [f"zotero://open-pdf/library/items/{MAIN}?page=2",
                                               f"zotero://open-pdf/library/items/{MAIN}?page=2",
                                               f"zotero://open-pdf/library/items/{SUPPLEMENT}?page=4"])
        self.assertIn("正文·图1", html)
        self.assertIn("补充材料·表S1", html)

    def test_supplement_page_limit_is_checked_independently(self):
        prepared = self.prepared(self.start())
        prepared["sections"][0]["paragraphs"][0]["sources"][1]["page"] = 5
        with self.assertRaisesRegex(ValueError, "page_count 4"):
            validate_report(prepared)

    def test_primary_page_count_is_not_the_sum_of_all_pdfs(self):
        prepared = self.prepared(self.start())
        prepared["paper"]["page_count"] = 14
        with self.assertRaisesRegex(ValueError, "独立"):
            validate_report(prepared)

    def test_multisource_citation_cannot_silently_default_to_main(self):
        prepared = self.prepared(self.start())
        prepared["sections"][0]["paragraphs"][0]["sources"][1].pop("attachment_key")
        with self.assertRaisesRegex(ValueError, "attachment_key"):
            validate_report(prepared)

    def test_foreign_attachment_citation_is_rejected(self):
        prepared = self.prepared(self.start())
        prepared["sections"][0]["paragraphs"][0]["sources"][1]["attachment_key"] = "PMQGVYHX"
        with self.assertRaisesRegex(ValueError, "未绑定"):
            validate_report(prepared)

    def test_joint_discussion_keeps_supplement_sources_when_drafted(self):
        directory = self.start()
        with self.assertRaisesRegex(ValueError, "--source"):
            record_discussion(directory, "qa", question="Q", answer="A", pages=[2])
        record_discussion(directory, "qa", question="Q", answer="A", pages=[4], source_key=SUPPLEMENT)
        draft_from_records(directory)
        qa = read_json(directory / "report.json")["qa"][0]
        self.assertEqual(qa["sources"][0]["attachment_key"], SUPPLEMENT)
        with self.assertRaisesRegex(ValueError, "超出"):
            record_discussion(directory, "fact", text="fact", pages=[5], source_key=SUPPLEMENT)

    def test_unread_supplement_cannot_be_published_as_complete(self):
        prepared = self.prepared(self.start())
        prepared["paper"]["attachments"][1]["reading_status"] = "pending"
        with self.assertRaisesRegex(ValueError, "未读PDF"):
            publish_report(self.client, prepared, self.root / "report.json")
        self.assertEqual(self.client.authorizations, 0)

    def test_excluded_source_needs_a_reason_and_cannot_be_cited(self):
        prepared = self.prepared(self.start())
        prepared["paper"]["attachments"][1]["reading_status"] = "excluded"
        prepared["sections"][0]["paragraphs"][0]["sources"].pop()
        with self.assertRaisesRegex(ValueError, "排除"):
            validate_report(prepared, require_ready=True)
        prepared["paper"]["attachments"][1]["exclusion_reason"] = "经核对为另一版本，未混入当前结论。"
        validate_report(prepared, require_ready=True)

    def test_changed_supplement_fingerprint_blocks_save(self):
        prepared = self.prepared(self.start())
        self.client.snapshots[SUPPLEMENT]["sha256"] = "replacement"
        with self.assertRaisesRegex(ValueError, "内容已更换"):
            publish_report(self.client, prepared, self.root / "report.json")
        self.assertEqual(self.client.authorizations, 0)

    def test_joint_report_keeps_one_note_and_preserves_handwritten_notes(self):
        directory = self.start()
        self.client.items["ABCDEFGH"] = {"data": {"key": "ABCDEFGH", "itemType": "note",
            "parentItem": PARENT, "note": "<p>手写笔记</p>", "tags": [], "version": 1}}
        prepared = self.prepared(directory)
        first = publish_report(self.client, prepared, directory / "report.json")
        prepared["sections"][0]["paragraphs"][0]["text"] = "联合阅读后的新结论。"
        updated = publish_report(self.client, prepared, directory / "report.json")
        self.assertEqual(first["note_key"], updated["note_key"])
        self.assertEqual(len(self.client.posts), 1)
        self.assertEqual(self.client.items["ABCDEFGH"]["data"]["note"], "<p>手写笔记</p>")

    def test_old_session_adds_new_supplement_without_losing_old_coordinates(self):
        directory = self.root / "old"
        old = report()
        old["draft"] = False
        write_json(directory / "report.json", old)
        write_json(directory / "records.json", [{"id": "old-qa", "kind": "qa", "created_at": "old", "important": True,
            "evidence_kind": "paper", "question": "old", "answer": "answer", "sources": [{"page": 2}]}])
        write_json(directory / "session.json", {"schema": 1, "server_id": self.client.server_id,
            "paper": old["paper"], "pdf": self.client.snapshots[MAIN], "stage": "saved"})
        start_session(self.client, self.root, MAIN)
        upgraded = read_json(directory / "report.json")
        self.assertTrue(upgraded["draft"])
        self.assertEqual(upgraded["sections"][0]["paragraphs"][0]["sources"][0]["attachment_key"], MAIN)
        self.assertEqual(read_json(directory / "records.json")[0]["sources"][0]["attachment_key"], MAIN)
        self.assertEqual([s["reading_status"] for s in upgraded["paper"]["attachments"]], ["read", "pending"])

    def test_duplicate_pdfs_are_recognized_by_hash(self):
        self.client.snapshots[SUPPLEMENT] = dict(self.client.snapshots[MAIN], path="copy.pdf")
        directory = self.start()
        prepared = self.prepared(directory)
        duplicate = prepared["paper"]["attachments"][1]
        duplicate["reading_status"] = "duplicate"
        self.assertEqual(duplicate["duplicate_of"], MAIN)
        validate_report(prepared, require_ready=True)

    def test_ambiguous_main_versions_need_a_primary_choice(self):
        self.client.items[MAIN]["data"]["title"] = "Version A"
        self.client.items[SUPPLEMENT]["data"].update(title="Version B", filename="version-b.pdf")
        with self.assertRaisesRegex(ValueError, "正文PDF"):
            self.start()
        directory = Path(start_session(self.client, self.root, MAIN, pdf_key=MAIN)["session"])
        self.assertEqual(len(read_json(directory / "session.json")["sources"]), 2)

    def test_legacy_single_pdf_report_html_is_unchanged(self):
        expected = '\n'.join([
            '<h1>中文阅读报告</h1>', '<p>论文：Example paper</p>',
            '<p>DOI：10.1/test；阅读日期：2026-10-13</p>', '<p>测试</p>', '<h2>结果</h2>',
            '<p>BER &lt; 0.1 &amp; 有条件 [<a href="zotero://open-pdf/library/items/6N5VPAT4?page=2">PDF第2页</a>]</p>'])
        self.assertEqual(render_note(report()), expected)


if __name__ == "__main__":
    unittest.main()
