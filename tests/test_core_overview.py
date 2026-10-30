"""An independently readable opening with separately located paragraphs."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import zotero_notes as notes
from reading_sessions import bind_sources
from test_autosave import ready_report
from test_reading_workflow import RevisionClient, temporary_workspace


def overview_report():
    value = ready_report()
    value["core_idea"] = {"paragraphs": [
        {"text": "既有长滤波器的缓存开销随记忆增加，本文尝试把这项工作拆给多个短模块。",
         "sources": [{"page": 1, "location": "引言"}]},
        {"text": "这样安排让各部分有明确任务；收益已在所测链路验证，实时硬件收益仍待核实。",
         "sources": [{"page": 4, "location": "结果与限制"}]},
        {"text": "原文摘录：<bounded> & measured", "quote": True,
         "sources": [{"page": 4, "location": "讨论"}]}
    ]}
    return value


class OverviewTests(unittest.TestCase):
    def test_multiple_paragraphs_and_excerpt_precede_details_with_their_own_links(self):
        value = overview_report()
        notes.validate_report(value, require_ready=True)
        html = notes.render_note(value)
        self.assertEqual(html.count("<h2>核心贡献或理念</h2>"), 1)
        self.assertLess(html.index("阅读日期"), html.index("既有长滤波器"))
        self.assertLess(html.index("原文摘录"), html.index("<h2>结果</h2>"))
        self.assertIn("<blockquote><p>原文摘录：&lt;bounded&gt; &amp; measured", html)
        self.assertEqual(notes.source_links(html)[:3], [
            "zotero://open-pdf/library/items/6N5VPAT4?page=1",
            "zotero://open-pdf/library/items/6N5VPAT4?page=4",
            "zotero://open-pdf/library/items/6N5VPAT4?page=4"])
        self.assertNotIn("讨论中", html)

    def test_single_paragraph_opening_keeps_its_exact_saved_html(self):
        value = ready_report()
        expected = ('<h2>核心贡献或理念</h2>\n'
                    '<p>测试系统用一套结构完成两项任务；这里仍是待实验证实的解释。 '
                    '[<a href="zotero://open-pdf/library/items/6N5VPAT4?page=1">引言</a>]</p>')
        self.assertIn(expected, notes.render_note(value))
        notes.validate_report(value, require_ready=True)

    def test_malformed_or_mixed_openings_cannot_drop_explanation_or_sources_silently(self):
        for core in ({"paragraphs": None}, {"paragraphs": "text"},
                     {"paragraphs": [None]}, {"paragraphs": [{"text": " "}]},
                     {"paragraphs": [{"text": 7}]},
                     {"paragraphs": [], "text": "被忽略的文本"},
                     {"paragraphs": [], "sources": [{"page": 1}]}):
            with self.subTest(core=core), self.assertRaises(ValueError):
                notes.validate_report(dict(ready_report(), core_idea=core))

    def test_empty_opening_can_be_previewed_but_not_saved(self):
        value = dict(ready_report(), core_idea={"paragraphs": []})
        self.assertNotIn("<h2>核心贡献或理念</h2>", notes.render_note(value))
        with self.assertRaises(ValueError):
            notes.validate_report(value, require_ready=True)

    def test_excerpts_alone_cannot_replace_the_opening_explanation(self):
        value = overview_report()
        value["core_idea"]["paragraphs"] = [value["core_idea"]["paragraphs"][-1]]
        with self.assertRaisesRegex(ValueError, "不能只有原文摘录"):
            notes.validate_report(value, require_ready=True)

    def test_every_opening_paragraph_needs_its_own_evidence_before_save(self):
        for index in (0, 1, 2):
            value = overview_report()
            value["core_idea"]["paragraphs"][index].pop("sources")
            with self.subTest(index=index), self.assertRaisesRegex(ValueError, "每段"):
                notes.validate_report(value, require_ready=True)

    def test_opening_reuses_page_attachment_external_link_and_quote_validation(self):
        for change in ({"sources": [{"page": 6}]},
                       {"sources": [{"page": 1, "attachment_key": "ABCDEFGH"}]},
                       {"external_sources": [{"url": "javascript:alert(1)", "location": "源"}]},
                       {"external_sources": [{"url": "https://example.org"}]},
                       {"quote": "true"}):
            value = overview_report()
            paragraph = value["core_idea"]["paragraphs"][1]
            paragraph.update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                notes.validate_report(value, require_ready=True)
        value = overview_report()
        value["core_idea"]["paragraphs"][1] = {"text": "外部背景的限定说明。",
            "external_sources": [{"url": "https://example.org/paper#page=2", "location": "外部文献第2页"}]}
        notes.validate_report(value, require_ready=True)
        self.assertIn("https://example.org/paper#page=2", notes.render_note(value))

    def test_new_supplement_keeps_all_original_opening_citation_coordinates(self):
        value = overview_report()
        bind_sources(value, [
            {"key": "6N5VPAT4", "role": "main", "sha256": "main", "page_count": 5},
            {"key": "ABCDEFGH", "role": "supplement", "sha256": "supp", "page_count": 2}], "6N5VPAT4")
        for paragraph in value["core_idea"]["paragraphs"]:
            self.assertEqual(paragraph["sources"][0]["attachment_key"], "6N5VPAT4")
        notes.validate_report(value)

    def test_overview_updates_same_note_and_unchanged_content_skips_writes(self):
        temporary = temporary_workspace()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "report.json"
        client = RevisionClient()
        first = notes.publish_report(client, ready_report(), path)
        value = overview_report()
        updated = notes.publish_report(client, value, path)
        self.assertEqual(first["note_key"], updated["note_key"])
        self.assertEqual(updated["status"], "updated_and_verified")
        before = deepcopy(client.items)
        unchanged = notes.publish_report(client, value, path)
        self.assertEqual(unchanged["status"], "already_current")
        self.assertEqual(before, client.items)
        self.assertEqual(len(client.posts), 1)


if __name__ == "__main__":
    unittest.main()
