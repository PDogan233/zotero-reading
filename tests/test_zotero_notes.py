"""Exercise the safety-relevant save behavior without touching Zotero."""

from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from zotero_notes import ZoteroError, friendly_error, item_key, render_note, save_report, source_links, validate_report


def report():
    return {"report_id": "test-v1", "note_title": "中文阅读报告", "date": "2026-10-13", "status": "测试",
            "paper": {"parent_key": "IGIEWQ9W", "attachment_key": "6N5VPAT4", "title": "Example paper", "doi": "10.1/test"},
            "sections": [{"heading": "结果", "paragraphs": [{"text": "BER < 0.1 & 有条件", "sources": [{"page": 2}]}]}],
            "qa": []}


class FakeClient:
    def __init__(self):
        self.server_id = "test-server"
        self.items = {
            "IGIEWQ9W": {"data": {"key": "IGIEWQ9W", "itemType": "journalArticle", "title": "Example paper", "DOI": "10.1/test"}},
            "6N5VPAT4": {"data": {"parentItem": "IGIEWQ9W", "contentType": "application/pdf"}},
        }
        self.authorizations = 0
        self.posts = []
        self.post_headers = []
        self.partial_failure = False
        self.lose_post_response = False
        self.corrupt_body = False
        self.hide_child = False

    def item(self, key):
        if key not in self.items:
            raise ZoteroError("Missing item", 404)
        return self.items[key]

    def authorize(self):
        self.authorizations += 1

    def request(self, method, path, data=None, extra_headers=None):
        if method == "GET":
            children = [] if self.hide_child else [{"key": key} for key, item in self.items.items() if item["data"].get("itemType") == "note"]
            return children, {}
        self.posts.append(deepcopy(data))
        self.post_headers.append(extra_headers or {})
        if "key" in data[0] and "version" not in data[0]:
            return {"successful": {}, "failed": {"0": {"code": 428, "message": "Version required for key-based writes"}}}, {}
        if self.partial_failure:
            return {"successful": {}, "failed": {"0": {"code": 400, "message": "bad parent"}}}, {}
        note = deepcopy(data[0])
        note["note"] = '<div class="zotero-note"><div data-schema-version="9">' + note["note"] + "</div></div>"
        if self.corrupt_body:
            note["note"] += "<p>unexpected</p>"
        self.items[note["key"]] = {"data": note}
        if self.lose_post_response:
            raise ZoteroError("Connection closed after committing")
        return {"successful": {"0": {"key": note["key"]}}, "failed": {}}, {}


class SaveTests(unittest.TestCase):
    def test_excerpt_keeps_text_and_pdf_link(self):
        prepared = report()
        prepared["sections"][0]["paragraphs"][0].update(quote=True, text='原文："training < readout & only"')
        rendered = render_note(prepared)
        self.assertIn('<blockquote><p>原文：&quot;training &lt; readout &amp; only&quot;', rendered)
        self.assertIn('zotero://open-pdf/library/items/6N5VPAT4?page=2', rendered)

    def test_external_supplement_link_and_escaping(self):
        prepared = report()
        prepared["sections"][0]["paragraphs"][0]["external_sources"] = [
            {"url": 'https://example.org/supplement.pdf?x=1&y=2#page=7', "location": '补充材料第7页 < §4.2'}]
        rendered = render_note(prepared)
        self.assertIn('href="https://example.org/supplement.pdf?x=1&amp;y=2#page=7"', rendered)
        self.assertIn('补充材料第7页 &lt; §4.2', rendered)
        self.assertEqual(len(source_links(rendered)), 2)

    def test_save_roundtrip_verifies_excerpt_and_both_link_types(self):
        prepared = report()
        prepared["sections"][0]["paragraphs"][0].update(
            quote=True, text='原文摘录：“readout only”',
            external_sources=[{"url": 'https://example.org/supplement.pdf#page=7', "location": '补充第7页'}])
        client = FakeClient()
        result = save_report(client, prepared)
        self.assertEqual(result["status"], "saved_and_verified")
        self.assertIn('<blockquote>', client.posts[0][0]["note"])
        self.assertEqual(len(source_links(client.posts[0][0]["note"])), 2)

    def test_external_evidence_rejects_unsafe_urls_and_missing_location(self):
        for url in ['javascript:alert(1)', 'file:///private.pdf', 'http://example.org/a', 'https://user:secret@example.org/a']:
            prepared = report()
            prepared["sections"][0]["paragraphs"][0]["external_sources"] = [{"url": url, "location": '补充材料第7页'}]
            with self.subTest(url=url), self.assertRaises(ValueError):
                render_note(prepared)
        prepared["sections"][0]["paragraphs"][0]["external_sources"] = [{"url": 'https://example.org/a'}]
        with self.assertRaises(ValueError):
            validate_report(prepared)

    def test_saves_chinese_child_and_verifies(self):
        client = FakeClient()
        result = save_report(client, report())
        self.assertEqual(result["status"], "saved_and_verified")
        self.assertEqual(client.posts[0][0]["parentItem"], "IGIEWQ9W")
        self.assertIn("中文阅读报告", client.posts[0][0]["note"])

    def test_repeated_save_does_not_authorize_or_post_again(self):
        client = FakeClient()
        save_report(client, report())
        self.assertEqual(save_report(client, report())["status"], "already_saved")
        self.assertEqual((len(client.posts), client.authorizations), (1, 1))

    def test_new_item_key_supplies_version_zero(self):
        client = FakeClient()
        save_report(client, report())
        self.assertEqual(client.posts[0][0]["version"], 0)
        self.assertNotIn("Zotero-Write-Token", client.post_headers[0])

    def test_reconcile_lost_success_response(self):
        client = FakeClient()
        client.lose_post_response = True
        with self.assertRaises(ZoteroError):
            save_report(client, report())
        self.assertEqual(save_report(client, report())["status"], "already_saved")
        self.assertEqual(len(client.posts), 1)

    def test_wrong_doi_never_authorizes(self):
        client = FakeClient()
        client.items["IGIEWQ9W"]["data"]["DOI"] = "10.1/different"
        with self.assertRaises(ZoteroError):
            save_report(client, report())
        self.assertEqual((client.authorizations, client.posts), (0, []))

    def test_paper_without_doi_can_be_saved(self):
        prepared = report()
        prepared["paper"].pop("doi")
        client = FakeClient()
        self.assertEqual(save_report(client, prepared)["status"], "saved_and_verified")
        self.assertIn("DOI：未提供", client.posts[0][0]["note"])

    def test_missing_doi_still_requires_matching_title(self):
        prepared = report()
        prepared["paper"]["doi"] = ""
        client = FakeClient()
        client.items["IGIEWQ9W"]["data"]["title"] = "Different paper"
        with self.assertRaises(ZoteroError):
            save_report(client, prepared)
        self.assertEqual(client.authorizations, 0)

    def test_wrong_pdf_parent_never_authorizes(self):
        client = FakeClient()
        client.items["6N5VPAT4"]["data"]["parentItem"] = "UN43QYKL"
        with self.assertRaises(ZoteroError):
            save_report(client, report())
        self.assertEqual(client.authorizations, 0)

    def test_http_200_with_failed_object_is_failure(self):
        client = FakeClient()
        client.partial_failure = True
        with self.assertRaisesRegex(ZoteroError, "did not create"):
            save_report(client, report())

    def test_corrupt_readback_is_failure(self):
        client = FakeClient()
        client.corrupt_body = True
        with self.assertRaisesRegex(ZoteroError, "differs"):
            save_report(client, report())

    def test_missing_child_is_failure(self):
        client = FakeClient()
        client.hide_child = True
        with self.assertRaisesRegex(ZoteroError, "missing"):
            save_report(client, report())

    def test_changed_report_does_not_overwrite(self):
        client = FakeClient()
        save_report(client, report())
        changed = report()
        changed["sections"][0]["paragraphs"][0]["text"] = "修订"
        with self.assertRaisesRegex(ZoteroError, "differs"):
            save_report(client, changed)
        self.assertEqual(len(client.posts), 1)

    def test_changed_citation_does_not_silently_skip(self):
        client = FakeClient()
        save_report(client, report())
        changed = report()
        changed["sections"][0]["paragraphs"][0]["sources"][0]["page"] = 3
        with self.assertRaisesRegex(ZoteroError, "differs"):
            save_report(client, changed)

    def test_key_collision_does_not_overwrite(self):
        client = FakeClient()
        prepared = report()
        save_report(client, prepared)
        key = item_key("IGIEWQ9W", "test-v1")
        client.items[key]["data"]["tags"] = []
        with self.assertRaisesRegex(ZoteroError, "different report"):
            save_report(client, prepared)
        self.assertEqual(len(client.posts), 1)

    def test_plain_content_is_escaped_and_pdf_page_is_linked(self):
        html = render_note(report())
        self.assertIn("BER &lt; 0.1 &amp;", html)
        self.assertEqual(source_links(html), ["zotero://open-pdf/library/items/6N5VPAT4?page=2"])

    def test_reject_bad_key_and_page_zero(self):
        prepared = report()
        prepared["paper"]["parent_key"] = "../wrong"
        with self.assertRaises(ValueError):
            validate_report(prepared)
        prepared = report()
        prepared["sections"][0]["paragraphs"][0]["sources"][0]["page"] = 0
        with self.assertRaises(ValueError):
            validate_report(prepared)

    def test_qa_keeps_evidence_link(self):
        prepared = report()
        prepared["qa"] = [{"question": "这是飞行速率吗？", "answer": "不是同一测试条件。", "sources": [{"page": 7}]}]
        self.assertIn("?page=7", render_note(prepared))

    def test_citation_must_fit_known_pdf_length(self):
        prepared = report()
        prepared["paper"]["page_count"] = 9
        prepared["sections"][0]["paragraphs"][0]["sources"][0]["page"] = 999
        with self.assertRaisesRegex(ValueError, "exceeds"):
            validate_report(prepared)
        prepared["sections"][0]["paragraphs"][0]["sources"][0]["page"] = 9
        self.assertTrue(validate_report(prepared))

    def test_qa_citation_checks_pdf_length(self):
        prepared = report()
        prepared["paper"]["page_count"] = 6
        prepared["qa"] = [{"question": "Q", "answer": "A", "sources": [{"page": 7}]}]
        with self.assertRaisesRegex(ValueError, "exceeds"):
            validate_report(prepared)

    def test_legacy_report_without_page_count_still_works(self):
        self.assertTrue(validate_report(report()))

    def test_actionable_chinese_errors(self):
        missing = FileNotFoundError(2, "not found", "absent.json")
        self.assertIn("找不到报告文件", friendly_error(missing))
        self.assertIn("启动 Zotero", friendly_error(ZoteroError("Cannot reach local Zotero: WinError 10061")))


if __name__ == "__main__":
    unittest.main()
