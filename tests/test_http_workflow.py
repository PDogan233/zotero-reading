"""Run the discussion/save/revision flow over an isolated loopback HTTP API."""

from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import threading
import unittest
from unittest.mock import patch
import urllib.parse

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from reading_sessions import draft_from_records, query_papers, read_json, record_discussion, refresh_context, start_session, write_json
from zotero_notes import Client, publish_report, source_links, store_receipt, update_report
from test_reading_workflow import temporary_workspace


class HttpWorkflowTests(unittest.TestCase):
    def test_read_discuss_save_resume_and_update(self):
        try:
            from pypdf import PdfWriter
        except ImportError:
            self.skipTest("Optional pypdf is needed to build a valid source fixture")
        with temporary_workspace() as work:
            root = Path(work)
            pdf_path = root / "isolated-source.pdf"
            writer = PdfWriter()
            writer.add_blank_page(width=612, height=792)
            with pdf_path.open("wb") as output:
                writer.write(output)
            supplement_path = root / "isolated-supplement.pdf"
            supplement = PdfWriter()
            supplement.add_blank_page(width=612, height=792)
            supplement.add_blank_page(width=612, height=792)
            with supplement_path.open("wb") as output:
                supplement.write(output)
            files = {"6N5VPAT4": pdf_path, "YXSKKPJ8": supplement_path}
            items = {
                "IGIEWQ9W": {"key": "IGIEWQ9W", "data": {"key": "IGIEWQ9W", "itemType": "journalArticle", "title": "Isolated test paper", "DOI": "10.1/isolated", "dateAdded": "2026-10-12T09:00:00Z"}},
                "6N5VPAT4": {"key": "6N5VPAT4", "data": {"key": "6N5VPAT4", "itemType": "attachment", "parentItem": "IGIEWQ9W", "contentType": "application/pdf"}},
                "YXSKKPJ8": {"key": "YXSKKPJ8", "data": {"key": "YXSKKPJ8", "itemType": "attachment", "parentItem": "IGIEWQ9W", "contentType": "application/pdf", "title": "Supplemental material"}},
                "ABCDEFGH": {"key": "ABCDEFGH", "data": {"key": "ABCDEFGH", "itemType": "note", "parentItem": "IGIEWQ9W", "note": "<p>其他原有笔记</p>", "tags": [], "version": 1}},
            }
            writes = []

            class Handler(BaseHTTPRequestHandler):
                def log_message(self, *args):
                    pass

                def send(self, status, body=None, content_type="application/json"):
                    encoded = (json.dumps(body, ensure_ascii=False) if content_type == "application/json" else body).encode() if body is not None else b""
                    self.send_response(status)
                    self.send_header("Zotero-Server-ID", "isolated-http-test")
                    self.send_header("Content-Type", content_type)
                    self.send_header("Content-Length", str(len(encoded)))
                    self.end_headers()
                    self.wfile.write(encoded)

                def do_GET(self):
                    path = urllib.parse.urlsplit(self.path).path
                    if path == "/api/":
                        return self.send(200, "local test API", "text/plain")
                    if path.endswith("/file/view/url"):
                        key = path.split("/")[-4]
                        return self.send(200, files[key].as_uri(), "text/plain")
                    if path.endswith("/items/top"):
                        return self.send(200, [items["IGIEWQ9W"]])
                    if path.endswith("/children"):
                        parent = path.split("/")[-2]
                        return self.send(200, [i for i in items.values() if i["data"].get("parentItem") == parent])
                    key = path.rsplit("/", 1)[-1]
                    return self.send(200, items[key]) if key in items else self.send(404, {"error": "missing"})

                def do_POST(self):
                    data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                    if self.path.endswith("/local/authorize"):
                        return self.send(200, {"key": "isolated-test-key", "remember": False})
                    if not self.headers.get("Zotero-API-Key"):
                        return self.send(401, {})
                    item = data[0]
                    if item["key"] in items or item.get("version") != 0:
                        return self.send(412, {})
                    writes.append(("POST", deepcopy(item)))
                    item["version"] = 1
                    item["note"] = '<div class="zotero-note">' + item["note"] + "</div>"
                    items[item["key"]] = {"key": item["key"], "data": item}
                    return self.send(200, {"successful": {"0": items[item["key"]]}, "failed": {}})

                def do_PATCH(self):
                    key = self.path.rsplit("/", 1)[-1]
                    item = items[key]["data"]
                    if not self.headers.get("Zotero-API-Key"):
                        return self.send(401, {})
                    if self.headers.get("If-Unmodified-Since-Version") != str(item["version"]):
                        return self.send(412, {})
                    update = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                    writes.append(("PATCH", deepcopy(update)))
                    item["note"] = '<div class="zotero-note">' + update["note"] + "</div>"
                    item["version"] += 1
                    return self.send(204)

            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                client = Client(f"http://127.0.0.1:{server.server_port}/api/")
                client.connect()
                self.assertEqual(query_papers(client, query="Isolated")[0]["key"], "IGIEWQ9W")
                directory = Path(start_session(client, root / "sessions", "YXSKKPJ8")["session"])
                record_discussion(directory, "qa", question="测试问题1", answer="测试回答1", pages=[1], source_key="6N5VPAT4")
                draft_from_records(directory)
                report_path = directory / "report.json"
                prepared = read_json(report_path)
                prepared["draft"] = False
                for source in prepared["paper"]["attachments"]:
                    source["reading_status"] = "read"
                prepared["sections"][0]["paragraphs"][0]["text"] = "隔离协议测试内容。"
                write_json(report_path, prepared)
                with patch("zotero_notes.AUTH_FILE", root / "test-auth.json"), patch("sys.stdout", new=io.StringIO()):
                    receipt = publish_report(client, prepared, report_path)
                    store_receipt(report_path, prepared, receipt)
                    self.assertEqual(publish_report(client, prepared, report_path)["status"], "already_current")
                    record_discussion(directory, "qa", question="测试问题2", answer="讨论后的测试回答2", pages=[2], source_key="YXSKKPJ8")
                    self.assertEqual(refresh_context(directory)["record_count"], 2)
                    draft_from_records(directory)
                    revision = read_json(report_path)
                    revision["draft"] = False
                    write_json(report_path, revision)
                    revision["report_id"] = "new-session-identifier"
                    updated = publish_report(client, revision, report_path)
                    store_receipt(report_path, revision, updated)
                self.assertEqual(updated["note_key"], receipt["note_key"])
                self.assertEqual(updated["note_version"], 2)
                self.assertTrue(Path(updated["backup"]).exists())
                self.assertEqual([w[0] for w in writes], ["POST", "PATCH"])
                self.assertEqual(refresh_context(directory)["stage"], "saved")
                self.assertIn("测试问题2", items[receipt["note_key"]]["data"]["note"])
                self.assertIn("zotero://open-pdf/library/items/YXSKKPJ8?page=2", source_links(items[receipt["note_key"]]["data"]["note"]))
                self.assertIn("zotero://open-pdf/library/items/6N5VPAT4?page=1", source_links(items[receipt["note_key"]]["data"]["note"]))
                self.assertEqual(update_report(client, revision, updated, report_path)["status"], "already_current")
                current = items[receipt["note_key"]]["data"]
                current["note"] += "<p>模拟用户手工补充</p>"
                current["version"] += 1
                revision["qa"][1]["answer"] = "再次修订"
                with self.assertRaisesRegex(ValueError, "手工修改"):
                    update_report(client, revision, updated, report_path)
                self.assertEqual(len(writes), 2)
                with patch("zotero_notes.AUTH_FILE", root / "test-auth.json"), patch("sys.stdout", new=io.StringIO()):
                    replaced = publish_report(client, revision, report_path)
                    store_receipt(report_path, revision, replaced)
                self.assertEqual(replaced["note_key"], receipt["note_key"])
                self.assertIn("模拟用户手工补充", read_json(replaced["backup"])["note"]["data"]["note"])
                self.assertEqual(items["ABCDEFGH"]["data"]["note"], "<p>其他原有笔记</p>")
                self.assertEqual(len(writes), 3)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
