"""Prepare and explicitly save conversation-authored reports as Zotero notes.

Python standard library only. No database writes and no model/API subscription.
Only `save` and `update` can request authorization or change the Zotero library.
"""

import argparse
import hashlib
from html import escape
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

from reading_sessions import (RECORD_KINDS, ROLE_LABELS, citation_source, draft_from_records, item_key, managed_report,
                              capture_existing_note, normalized_doi, normalize_sessions, paper_children, paper_sources, pdf_snapshot, query_papers, session_sources,
                              read_json, record_discussion, refresh_context, session_path,
                              start_session, timestamp, write_json)


ROOT = Path(__file__).resolve().parents[1]
KEY_PATTERN = re.compile(r"[23456789ABCDEFGHIJKLMNPQRSTUVWXYZ]{8}\Z")


def default_data_root():
    if os.environ.get("ZOTERO_READING_HOME"):
        return Path(os.environ["ZOTERO_READING_HOME"]).expanduser().resolve()
    if Path(__file__).resolve().parent.name == "scripts" and (ROOT / "pyproject.toml").exists():
        return ROOT
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "ZoteroReading"
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/ZoteroReading"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "zotero-reading"


AUTH_FILE = default_data_root() / ".local" / "zotero-auth.json"


class ZoteroError(RuntimeError):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class TextParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.links = []

    def handle_data(self, data):
        self.parts.append(data)

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.links.append(dict(attrs).get("href"))


def plain_text(html):
    parser = TextParser()
    parser.feed(html)
    return re.sub(r"\s+", " ", "".join(parser.parts)).strip()


def source_links(html):
    parser = TextParser()
    parser.feed(html)
    return parser.links


def render_paragraph(paragraph, paper):
    sources = []
    for source in paragraph.get("sources", []):
        attachment = citation_source(paper, source)
        url = f"zotero://open-pdf/library/items/{attachment['key']}?page={source['page']}"
        label = source.get("location", f"PDF第{source['page']}页")
        if len(paper_sources(paper)) > 1:
            label = ROLE_LABELS.get(attachment.get("role"), "相关PDF") + "·" + label
        sources.append(f'<a href="{escape(url, quote=True)}">{escape(label)}</a>')
    for source in paragraph.get("external_sources", []):
        sources.append(f'<a href="{escape(source["url"], quote=True)}">{escape(source["location"])}</a>')
    suffix = " [" + "；".join(sources) + "]" if sources else ""
    content = f"<p>{escape(paragraph['text'])}{suffix}</p>"
    return f"<blockquote>{content}</blockquote>" if paragraph.get("quote") else content


def validate_report(report, require_ready=False):
    if require_ready and report.get("draft"):
        raise ValueError("报告仍为草稿。请完成阅读与证据核对，将draft设为false后再按用户指令保存。")
    paper = report["paper"]
    for name in ("parent_key", "attachment_key"):
        if not KEY_PATTERN.fullmatch(paper[name]):
            raise ValueError(f"Invalid {name}")
    for value in (report["report_id"], report["note_title"], paper["title"]):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Report identifiers and titles must be nonempty strings")
    if not isinstance(paper.get("doi", ""), str):
        raise ValueError("DOI must be a string when provided")
    page_count = paper.get("page_count")
    if page_count is not None and (type(page_count) is not int or page_count < 1):
        raise ValueError("PDF page_count must be a positive integer")
    if "attachments" in paper and (not isinstance(paper["attachments"], list) or not paper["attachments"]):
        raise ValueError("attachments必须包含至少一个PDF来源。")
    attachments = paper_sources(paper)
    keys = [attachment["key"] for attachment in attachments]
    if len(set(keys)) != len(keys) or paper["attachment_key"] not in keys:
        raise ValueError("PDF来源重复或没有包含正文附件。")
    primary = next(attachment for attachment in attachments if attachment["key"] == paper["attachment_key"])
    if page_count is not None and primary.get("page_count") is not None and page_count != primary["page_count"]:
        raise ValueError("正文页数与来源记录不一致；各PDF页数独立，不能填写合并后的总页数。")
    for attachment in attachments:
        if not KEY_PATTERN.fullmatch(attachment["key"]):
            raise ValueError("Invalid attachment_key")
        count = attachment.get("page_count")
        if count is not None and (type(count) is not int or count < 1):
            raise ValueError("PDF page_count must be a positive integer")
        if attachment.get("role", "main") not in ROLE_LABELS:
            raise ValueError("无效的PDF角色。")
        if len(attachments) > 1 and require_ready:
            status = attachment.get("reading_status", "pending")
            if status == "excluded":
                if not attachment.get("exclusion_reason"):
                    raise ValueError("排除的PDF需要说明原因，不能静默忽略补充材料。")
            elif status == "duplicate":
                duplicate = next((source for source in attachments if source["key"] == attachment.get("duplicate_of")), None)
                if not duplicate or duplicate["key"] == attachment["key"] or not attachment.get("pdf_sha256") or duplicate.get("pdf_sha256") != attachment["pdf_sha256"] or duplicate.get("reading_status") != "read":
                    raise ValueError("重复PDF必须指向已读且指纹相同的来源。")
            elif status != "read":
                raise ValueError("联合阅读还有未读PDF。请完成阅读，或明确说明排除原因后再保存。")
    if not report["sections"]:
        raise ValueError("Report must contain sections")
    for section in report["sections"]:
        if not section["heading"] or not section["paragraphs"]:
            raise ValueError("Every section needs a heading and paragraphs")
        for paragraph in section["paragraphs"]:
            if not isinstance(paragraph["text"], str) or not paragraph["text"].strip():
                raise ValueError("Empty report paragraph")
            if "quote" in paragraph and type(paragraph["quote"]) is not bool:
                raise ValueError("quote必须为布尔值。")
            for source in paragraph.get("external_sources", []):
                url = urllib.parse.urlsplit(source.get("url", ""))
                if url.scheme != "https" or not url.hostname or url.username or url.password:
                    raise ValueError("外部证据只允许没有账号信息的HTTPS链接。")
                if not isinstance(source.get("location"), str) or not source["location"].strip():
                    raise ValueError("外部证据需要明确来源及页码位置。")
            for source in paragraph.get("sources", []):
                if type(source["page"]) is not int or source["page"] < 1:
                    raise ValueError("PDF page numbers start at 1")
                attachment = citation_source(paper, source)
                count = attachment.get("page_count")
                if count is not None and source["page"] > count:
                    raise ValueError(f"Citation page {source['page']} exceeds PDF page_count {count}")
                if attachment.get("reading_status") == "excluded":
                    raise ValueError("报告不能引用已排除的PDF。")
    for qa in report.get("qa", []):
        for source in qa.get("sources", []):
            if type(source["page"]) is not int or source["page"] < 1:
                raise ValueError("PDF page numbers start at 1")
            attachment = citation_source(paper, source)
            count = attachment.get("page_count")
            if count is not None and source["page"] > count:
                raise ValueError(f"Citation page {source['page']} exceeds PDF page_count {count}")
            if attachment.get("reading_status") == "excluded":
                raise ValueError("报告不能引用已排除的PDF。")
    return report


def render_note(report):
    validate_report(report)
    paper = report["paper"]
    parts = [f"<h1>{escape(report['note_title'])}</h1>",
             f"<p>论文：{escape(paper['title'])}</p>",
             f"<p>DOI：{escape(paper.get('doi') or '未提供')}；阅读日期：{escape(report['date'])}</p>",
             f"<p>{escape(report['status'])}</p>"]
    if len(paper_sources(paper)) > 1:
        parts.append("<h2>阅读材料</h2>")
        for source in paper_sources(paper):
            status = {"read": "已读", "pending": "待阅读", "duplicate": "相同文件副本", "excluded": "未纳入"}.get(source.get("reading_status", "pending"), "待核实")
            label = ROLE_LABELS.get(source.get("role"), "相关PDF") + "：" + source.get("title", source["key"])
            text = f"{label}（{source.get('page_count', '未知')}页；{status}）"
            if source.get("exclusion_reason"):
                text += "；原因：" + source["exclusion_reason"]
            parts.append(f"<p>{escape(text)}</p>")
    for section in report["sections"]:
        parts.append(f"<h2>{escape(section['heading'])}</h2>")
        for paragraph in section["paragraphs"]:
            parts.append(render_paragraph(paragraph, paper))
    if report.get("qa"):
        parts.append("<h2>讨论与问答要点</h2>")
        for qa in report["qa"]:
            parts.append(f"<p><strong>问：</strong>{escape(qa['question'])}</p>")
            label = {"background": "【背景知识】", "inference": "【阅读推断】", "user": "【用户需求】"}.get(qa.get("evidence_kind"), "")
            parts.append(render_paragraph({"text": "答：" + label + qa["answer"], "sources": qa.get("sources", [])}, paper))
    return "\n".join(parts)


class Client:
    def __init__(self, base_url="http://127.0.0.1:23119/api/"):
        parsed = urllib.parse.urlsplit(base_url)
        if parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
            raise ValueError("仅允许连接本机Zotero接口。")
        self.base_url = base_url.rstrip("/") + "/"
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.server_id = None
        self.key = None

    def request(self, method, path, data=None, extra_headers=None, timeout=10):
        headers = {"Zotero-API-Version": "3"}
        if self.server_id:
            headers["Zotero-Server-ID"] = self.server_id
        if self.key and method != "GET":
            headers["Zotero-API-Key"] = self.key
        headers.update(extra_headers or {})
        body = None
        if data is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(self.base_url + path,
                                         data=body, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
                try:
                    result = json.loads(raw)
                except ValueError:
                    result = raw
                return result, response.headers
        except urllib.error.HTTPError as error:
            raise ZoteroError(f"Zotero HTTP {error.code}: {error.read().decode('utf-8')}", error.code) from None
        except (urllib.error.URLError, TimeoutError) as error:
            raise ZoteroError(f"Cannot reach local Zotero: {error}") from None

    def connect(self):
        _, headers = self.request("GET", "")
        self.server_id = headers.get("Zotero-Server-ID")
        if not self.server_id:
            raise ZoteroError("Local writes require Zotero 10+ with a Server ID")

    def item(self, key):
        return self.request("GET", f"users/0/items/{key}")[0]

    def authorize(self):
        if AUTH_FILE.exists():
            auth = json.loads(AUTH_FILE.read_text(encoding="utf-8"))
            if auth.get("server_id") == self.server_id:
                self.key = auth["key"]
                return
        print("请在 Zotero 的授权弹窗中选择“允许”或“始终允许”。", flush=True)
        auth, _ = self.request("POST", "local/authorize", {"appName": "Zotero 中文阅读报告"}, timeout=180)
        self.key = auth["key"]
        if auth.get("remember"):
            AUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
            AUTH_FILE.write_text(json.dumps({"server_id": self.server_id, "key": self.key}), encoding="utf-8")


def verify_identity(client, report):
    paper = report["paper"]
    parent = client.item(paper["parent_key"])["data"]
    if parent.get("itemType") in ("attachment", "note", "annotation"):
        raise ZoteroError("Report parent must be a bibliographic item")
    if parent.get("title") != paper["title"] or (
            paper.get("doi") and normalized_doi(parent.get("DOI", "")) != normalized_doi(paper["doi"])):
        raise ZoteroError("Target title or DOI differs from the reviewed paper")
    for source in paper_sources(paper):
        attachment = client.item(source["key"])["data"]
        if attachment.get("parentItem") != paper["parent_key"] or attachment.get("contentType") != "application/pdf" or attachment.get("deleted"):
            raise ZoteroError("Source PDF does not belong to the target paper")
        if source.get("pdf_sha256") and pdf_snapshot(client, source["key"])["sha256"] != source["pdf_sha256"]:
            raise ValueError("PDF内容已更换；请重新阅读并核对报告引用：" + source["key"])
    return parent


def verify_managed_note(item, report):
    data = item["data"]
    if data.get("itemType") != "note" or data.get("parentItem") != report["paper"]["parent_key"] or data.get("deleted"):
        raise ZoteroError("The target is not this paper's generated note")
    marker = "reading-report:" + report["report_id"]
    if marker not in {tag["tag"] for tag in data.get("tags", [])}:
        raise ZoteroError("The note key belongs to a different report; no overwrite was attempted")


def verify_note(item, report, html):
    verify_managed_note(item, report)
    data = item["data"]
    if plain_text(data.get("note", "")) != plain_text(html) or source_links(data.get("note", "")) != source_links(html):
        raise ZoteroError("Stored note differs from the prepared report; no overwrite was attempted")


def note_hash(item):
    return hashlib.sha256(item["data"]["note"].encode("utf-8")).hexdigest()


def expected_note_hash(report, receipt):
    # Reuse only the wrapper observed at the last verified save. This permits
    # recovery after a lost response without treating arbitrary formatting edits
    # as a new save baseline.
    wrapper = receipt.get("html_wrapper", {})
    html = wrapper.get("before", "") + render_note(report) + wrapper.get("after", "")
    return hashlib.sha256(html.encode("utf-8")).hexdigest()


def receipt_for_item(client, item, report, status):
    key = item["data"]["key"]
    result = {"status": status, "report_id": report["report_id"], "note_key": key,
            "parent_key": report["paper"]["parent_key"], "server_id": client.server_id,
            "note_url": f"zotero://select/library/items/{key}", "note_version": item["data"].get("version"),
            "content_hash": note_hash(item), "body_verified": True,
            "source_links_verified": len(source_links(item["data"]["note"])), "verified_at": timestamp()}
    html = render_note(report)
    stored = item["data"]["note"]
    if stored.count(html) == 1:
        before, after = stored.split(html, 1)
        result["html_wrapper"] = {"before": before, "after": after}
    return result


def authorized_request(client, method, path, payload, headers=None):
    client.authorize()
    try:
        return client.request(method, path, payload, headers)
    except ZoteroError as error:
        if error.status != 401:
            raise
        if AUTH_FILE.exists():
            AUTH_FILE.unlink()
        client.key = None
        client.authorize()
        return client.request(method, path, payload, headers)


def save_report(client, report):
    validate_report(report, require_ready=True)
    html = render_note(report)
    parent = verify_identity(client, report)
    key = item_key(report["paper"]["parent_key"], report["report_id"])
    try:
        existing = client.item(key)
    except ZoteroError as error:
        if error.status != 404:
            raise
    else:
        verify_note(existing, report, html)
        return receipt_for_item(client, existing, report, "already_saved")
    children = paper_children(client, parent["key"])
    if managed_report(children, parent["key"], client):
        raise ValueError("这篇文献已有本程序的阅读笔记，请沿用它保存，不能再创建第二份。")
    payload = {"key": key, "version": 0, "itemType": "note", "parentItem": parent["key"], "note": html,
               "tags": [{"tag": tag} for tag in ["AI阅读报告", "reading-report:" + report["report_id"]]
                        + report.get("tags", [])], "collections": [], "relations": {}}
    result, _ = authorized_request(client, "POST", "users/0/items", [payload])
    if result.get("failed") or not (result.get("successful") or result.get("success")):
        raise ZoteroError("Zotero did not create the note: " + json.dumps(result, ensure_ascii=False))
    saved = client.item(key)
    verify_note(saved, report, html)
    children = paper_children(client, parent["key"])
    if key not in {child["key"] for child in children}:
        raise ZoteroError("Saved note is missing from the paper children")
    return receipt_for_item(client, saved, report, "saved_and_verified")


def update_report(client, report, receipt, report_path, dry_run=False, overwrite_managed=False):
    validate_report(report, require_ready=True)
    html = render_note(report)
    verify_identity(client, report)
    key = item_key(report["paper"]["parent_key"], report["report_id"])
    if receipt.get("server_id") != client.server_id or receipt.get("note_key") != key:
        raise ValueError("更新回执与当前文献库或报告不匹配。请先接续正确的会话。")
    current = client.item(key)
    verify_managed_note(current, report)
    if not overwrite_managed and (receipt.get("note_version") is None or not receipt.get("content_hash")):
        raise ValueError("旧回执缺少更新基线。请先resume --check，核对上次保存的报告。")
    if plain_text(current["data"]["note"]) == plain_text(html) and source_links(current["data"]["note"]) == source_links(html):
        if not overwrite_managed and note_hash(current) not in (receipt["content_hash"], expected_note_hash(report, receipt)):
            raise ValueError("Zotero笔记在上次保存后已发生正文或格式变化；请先审阅差异，当前操作不会覆盖手工修改。")
        return receipt_for_item(client, current, report, "already_current")
    if not overwrite_managed and note_hash(current) != receipt["content_hash"]:
        raise ValueError("Zotero笔记在上次保存后已发生变化；请先审阅差异，当前操作不会覆盖手工修改。")
    expected_version = current["data"].get("version")
    if type(expected_version) is not int:
        raise ValueError("无法读取当前笔记版本，不能安全更新。")
    if dry_run:
        return {"status": "update_ready", "note_key": key, "expected_version": expected_version}
    backup = Path(report_path).parent / "history" / f"{key}-v{expected_version}-{uuid_hex()}.json"
    write_json(backup, {"backed_up_at": timestamp(), "note": current, "receipt": receipt})
    authorized_request(client, "PATCH", f"users/0/items/{key}", {"note": html},
                       {"If-Unmodified-Since-Version": str(expected_version)})
    updated = client.item(key)
    verify_note(updated, report, html)
    result = receipt_for_item(client, updated, report, "updated_and_verified")
    result["backup"] = str(backup.resolve())
    return result


def publish_report(client, report, report_path, dry_run=False, require_existing=False):
    """Maintain exactly one dedicated note, replacing only its body on save."""
    validate_report(report, require_ready=True)
    parent = verify_identity(client, report)
    children = paper_children(client, parent["key"])
    managed = managed_report(children, parent["key"], client)
    if managed:
        item, report_id = managed
        report["report_id"] = report_id
        # The user has designated this note as replaceable. The current note is
        # backed up and version-checked; other notes never enter this path.
        receipt = {"server_id": client.server_id, "note_key": item["data"]["key"]}
        result = update_report(client, report, receipt, report_path, dry_run, overwrite_managed=True)
        result["dedicated_note_save"] = True
        return result
    if require_existing:
        raise ValueError("这篇文献尚无本程序的阅读笔记，请先用save新建。")
    if dry_run:
        return {"status": "create_ready", "parent_key": parent["key"]}
    report["report_id"] = "review-" + parent["key"]
    return save_report(client, report)


def uuid_hex():
    import uuid
    return uuid.uuid4().hex[:12]


def store_receipt(report_path, report, result):
    report_path = Path(report_path)
    receipt_path = report_path.with_suffix(".receipt.json")
    if receipt_path.exists() and result["status"] in ("already_saved", "already_current") and not result.get("dedicated_note_save"):
        previous = read_json(receipt_path)
        if previous.get("content_hash") and result["content_hash"] not in (previous["content_hash"], expected_note_hash(report, previous)):
            raise ValueError("Zotero笔记有正文或格式修改；重复保存不能重置更新基线，请先审阅手工修改。")
    write_json(receipt_path, result)
    write_json(report_path.with_suffix(".saved.json"), report)
    directory = report_path.parent
    if (directory / "session.json").exists():
        state = read_json(directory / "session.json")
        state["stage"] = "saved"
        write_json(directory / "session.json", state)
        refresh_context(directory)


def check_session(client, directory):
    directory = Path(directory)
    state = read_json(directory / "session.json")
    if state["server_id"] != client.server_id:
        raise ValueError("该会话来自另一文献库。")
    for source in session_sources(state):
        attachment = client.item(source["key"])["data"]
        if attachment.get("parentItem") != state["paper"]["parent_key"] or attachment.get("deleted"):
            raise ValueError("阅读材料已被删除或移到另一文献，请先核对。")
        if pdf_snapshot(client, source["key"])["sha256"] != source["sha256"]:
            raise ValueError("PDF内容已更换；请重新阅读并核对证据：" + source["key"])
    receipt_path = directory / "report.receipt.json"
    if receipt_path.exists():
        receipt = read_json(receipt_path)
        if receipt.get("server_id") != client.server_id:
            raise ValueError("报告回执来自另一文献库。")
        saved_path = directory / "report.saved.json"
        saved_report = read_json(saved_path if saved_path.exists() else directory / "report.json")
        item = client.item(receipt["note_key"])
        verify_note(item, saved_report, render_note(saved_report))
        if receipt.get("note_version") is None:
            # Adopt old receipts only after matching the previously saved content.
            store_receipt(directory / "report.json", saved_report,
                          receipt_for_item(client, item, saved_report, "baseline_adopted"))
        elif note_hash(item) != receipt["content_hash"]:
            raise ValueError("已保存笔记有外部修改；请先检查，不能自动更新保存基线。")
    return refresh_context(directory)


def rebind_session(client, directory, dry_run=False):
    """Refresh a copied session on another host, only with the same IDs and PDFs."""
    directory = Path(directory)
    state = read_json(directory / "session.json")
    report = read_json(directory / "report.json")
    verify_identity(client, report)
    refreshed = []
    for source in session_sources(state):
        attachment = client.item(source["key"])["data"]
        if attachment.get("parentItem") != state["paper"]["parent_key"] or attachment.get("deleted"):
            raise ValueError("来源key与当前文库不匹配；不同账户需先匹配条目，不能直接重绑定。")
        snapshot = pdf_snapshot(client, source["key"])
        if snapshot["sha256"] != source["sha256"]:
            raise ValueError("PDF指纹不同，不能将旧会话直接绑定到新文件。")
        refreshed.append(dict(source, **snapshot))
    children = paper_children(client, state["paper"]["parent_key"])
    managed = managed_report(children, state["paper"]["parent_key"], client)
    receipt_path = directory / "report.receipt.json"
    saved_path = directory / "report.saved.json"
    saved_report = read_json(saved_path if saved_path.exists() else directory / "report.json")
    if receipt_path.exists():
        if not managed:
            raise ValueError("新文库中未找到原程序笔记；请先核对同步是否完成。")
        verify_note(managed[0], saved_report, render_note(saved_report))
    result = {"status": "rebind_ready" if dry_run else "rebound", "from_server_id": state["server_id"],
              "to_server_id": client.server_id, "sources": refreshed}
    if not dry_run:
        state["server_id"] = client.server_id
        state["sources"] = refreshed
        primary = next(source for source in refreshed if source["key"] == state["paper"]["attachment_key"])
        state["pdf"] = {name: primary[name] for name in ("path", "sha256", "page_count") if name in primary}
        state["existing_note"] = capture_existing_note(directory, managed)
        state["rebound_at"] = timestamp()
        if receipt_path.exists():
            write_json(receipt_path, receipt_for_item(client, managed[0], saved_report, "baseline_migrated"))
            write_json(saved_path, saved_report)
        write_json(directory / "session.json", state)
        refresh_context(directory)
    return result


def ensure_qa_merged(report, report_path):
    records_path = Path(report_path).parent / "records.json"
    if not records_path.exists():
        return
    included = set(report.get("discussion_record_ids", []))
    if any(record["kind"] == "qa" and record["important"] and record["id"] not in included
           for record in read_json(records_path)):
        raise ValueError("有重要问答尚未归纳到草稿。请先运行draft，再核对和压缩报告，避免遗漏讨论成果。")


def friendly_error(error):
    if isinstance(error, FileNotFoundError):
        return f"找不到报告文件：{error.filename}。请检查路径；相对路径以当前工作目录为准。"
    if isinstance(error, KeyError):
        return f"报告或接口数据缺少字段：{error}。请按示例报告结构检查。"
    if isinstance(error, ZoteroError):
        if error.status == 403:
            return "Zotero 拒绝了请求。请检查是否启用了本机通信，或是否拒绝了写入授权。"
        if error.status == 401:
            return "Zotero 写入授权无效。请重新运行保存命令并在 Zotero 中授权。"
        if error.status == 412:
            return "Zotero 数据或版本已变化。请重新读取目标文献，再准备保存操作。"
        if error.status == 404:
            return "Zotero 中未找到指定条目。请检查条目标识、所在文献库和回收站状态。"
        message = str(error)
        if "WinError 10061" in message:
            return "无法连接 Zotero。请先启动 Zotero，等待文库加载完成后重试。"
        if "WinError 10013" in message:
            return "运行环境阻止了本机接口连接。需要允许访问 localhost；这与 Zotero 写入授权是两回事。"
        if message.startswith("Cannot reach"):
            return "Zotero 本地接口连接失败或超时。请检查应用状态；若保存结果不确定，可重试同一份报告以核对已有笔记。"
        if message.startswith("Stored note differs"):
            return "已有报告内容与本次草稿不同，尚未覆盖。若用户已明确要求修订，请先检查基线并使用update命令。"
        if message.startswith("Target title or DOI"):
            return "目标论文的标题或 DOI 与报告记录不一致。请核对文献身份或元数据变更后再保存。"
    return "操作未完成：" + str(error)


def main():
    global AUTH_FILE
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version="zotero-reading 0.3.1")
    parser.add_argument("--data-dir", type=Path, help="会话和本机授权数据目录；也可设置ZOTERO_READING_HOME")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("probe")
    sub.add_parser("paths", help="查看当前数据目录，不访问Zotero")
    normalize = sub.add_parser("normalize-sessions", help="将旧会话目录统一为主文献key")
    normalize.add_argument("--dry-run", action="store_true")
    rebind = sub.add_parser("rebind", help="同文库同key换机后核对PDF并刷新本地绑定")
    rebind.add_argument("session")
    rebind.add_argument("--dry-run", action="store_true")
    find = sub.add_parser("find", help="按标题或作者查询论文")
    find.add_argument("query", nargs="?")
    find.add_argument("--doi")
    find.add_argument("--limit", type=int, default=20)
    recent = sub.add_parser("recent", help="按添加时间选择论文")
    recent.add_argument("--limit", type=int, default=10)
    recent.add_argument("--days", type=int)
    recent.add_argument("--from-date")
    recent.add_argument("--to-date")
    start = sub.add_parser("start", help="建立或接续某篇论文的会话")
    start.add_argument("key", nargs="+", help="主条目/PDF key、storage目录或PDF路径；同条目自动联合阅读")
    start.add_argument("--directory", type=Path)
    start.add_argument("--pdf-key")
    resume = sub.add_parser("resume", help="读取可跨对话接续的上下文")
    resume.add_argument("session")
    resume.add_argument("--check", action="store_true", help="只读核对Zotero、PDF和更新基线")
    record = sub.add_parser("record", help="记录讨论、重要问答或待解决问题")
    record.add_argument("session")
    record.add_argument("--kind", choices=RECORD_KINDS, required=True)
    record.add_argument("--text")
    record.add_argument("--question")
    record.add_argument("--answer")
    record.add_argument("--page", type=int, action="append", default=[])
    record.add_argument("--source", help="证据对应的PDF附件key；多PDF页码引用必须指定")
    record.add_argument("--location", default="")
    record.add_argument("--minor", action="store_true")
    record.add_argument("--evidence-kind", choices=("paper", "background", "inference", "user"), default="paper")
    draft = sub.add_parser("draft", help="将尚未归纳的重要问答放入待审核草稿")
    draft.add_argument("session")
    for name in ("preview", "save", "update"):
        command = sub.add_parser(name)
        command.add_argument("report", type=Path)
        if name == "update":
            command.add_argument("--dry-run", action="store_true", help="只读检查更新条件，不请求写入授权")
    args = parser.parse_args()
    data_root = args.data_dir.expanduser().resolve() if args.data_dir else default_data_root()
    AUTH_FILE = data_root / ".local" / "zotero-auth.json"
    sessions_root = data_root / "sessions"
    if args.command == "paths":
        print(json.dumps({"data_dir": str(data_root), "sessions": str(sessions_root)}, ensure_ascii=False))
        return
    if args.command == "normalize-sessions":
        print(json.dumps(normalize_sessions(sessions_root, args.dry_run), ensure_ascii=False, indent=2))
        return
    if args.command == "rebind":
        client = Client()
        client.connect()
        print(json.dumps(rebind_session(client, session_path(sessions_root, args.session), args.dry_run), ensure_ascii=False))
        return
    if args.command in ("resume", "record", "draft"):
        directory = session_path(sessions_root, args.session)
        if args.command == "record":
            result = record_discussion(directory, args.kind, args.text, args.question, args.answer,
                                       args.page, args.location, not args.minor, args.evidence_kind, args.source)
        elif args.command == "draft":
            result = draft_from_records(directory)
        elif args.check:
            client = Client()
            client.connect()
            result = check_session(client, directory)
        else:
            result = refresh_context(directory)
        print(json.dumps(result, ensure_ascii=False))
        return
    if args.command in ("find", "recent", "start"):
        client = Client()
        client.connect()
        if args.command == "find":
            if bool(args.query) == bool(args.doi):
                raise ValueError("find需要标题/作者关键词或--doi之一。")
            result = query_papers(client, query=args.query, limit=args.limit, doi=args.doi)
        elif args.command == "recent":
            result = query_papers(client, limit=args.limit, days=args.days,
                                  from_date=args.from_date, to_date=args.to_date)
        else:
            result = start_session(client, sessions_root, args.key, args.directory, args.pdf_key)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    if args.command == "probe":
        client = Client()
        client.connect()
        print(json.dumps({"status": "connected", "server_id": client.server_id}, ensure_ascii=False))
        return
    report = validate_report(json.loads(args.report.read_text(encoding="utf-8")))
    if args.command == "preview":
        target = args.report.with_suffix(".html")
        target.write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>'
                          + escape(report["note_title"]) + "</title><body>" + render_note(report)
                          + "</body></html>", encoding="utf-8")
        print(json.dumps({"status": "preview_only", "path": str(target.resolve())}, ensure_ascii=False))
        return
    validate_report(report, require_ready=True)
    ensure_qa_merged(report, args.report)
    client = Client()
    client.connect()
    state_file = args.report.parent / "session.json"
    if state_file.exists():
        state = read_json(state_file)
        if state["server_id"] != client.server_id or state["paper"]["parent_key"] != report["paper"]["parent_key"] or state["paper"]["attachment_key"] != report["paper"]["attachment_key"]:
            raise ValueError("报告与会话绑定的文献库或PDF不一致。")
        report["paper"]["pdf_sha256"] = state["pdf"]["sha256"]
        bound = {source["key"]: source for source in session_sources(state)}
        declared = {source["key"]: source for source in paper_sources(report["paper"])}
        if set(bound) != set(declared):
            raise ValueError("报告的PDF来源与会话不一致，请先用start接续并核对材料。")
        for key, source in declared.items():
            if report["paper"].get("attachments"):
                source["pdf_sha256"] = bound[key]["sha256"]
                if bound[key].get("page_count") is not None:
                    source["page_count"] = bound[key]["page_count"]
    dry_run = getattr(args, "dry_run", False)
    result = publish_report(client, report, args.report, dry_run=dry_run,
                            require_existing=args.command == "update")
    if not dry_run:
        write_json(args.report, report)
        store_receipt(args.report, report, result)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except (ZoteroError, ValueError, KeyError, OSError) as error:
        print(friendly_error(error), file=sys.stderr)
        sys.exit(1)
