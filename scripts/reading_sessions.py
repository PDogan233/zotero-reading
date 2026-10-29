"""Local reading sessions and read-only Zotero discovery."""

from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import urllib.parse
import uuid


HK = timezone(timedelta(hours=8))
KEY = re.compile(r"[23456789ABCDEFGHIJKLMNPQRSTUVWXYZ]{8}\Z")
KEY_CHARS = "23456789ABCDEFGHIJKLMNPQRSTUVWXYZ"
RECORD_KINDS = ("qa", "fact", "insight", "open-question", "focus")
ROLE_LABELS = {"main": "正文", "supplement": "补充材料", "related": "相关PDF"}


def reference_key(reference):
    value = str(reference).rstrip("/\\")
    if KEY.fullmatch(value):
        return value
    parts = re.split(r"[/\\]", value)
    candidate = parts[-2] if value.lower().endswith(".pdf") and len(parts) > 1 else parts[-1]
    if not KEY.fullmatch(candidate):
        raise ValueError("请提供Zotero条目key、storage附件目录或该目录中的PDF路径。")
    return candidate


def resolve_paper(client, references):
    references = [references] if isinstance(references, (str, Path)) else references
    parents = set()
    for reference in references:
        key = reference_key(reference)
        item = client.item(key)["data"]
        if item.get("deleted"):
            raise ValueError("输入条目已删除。")
        if item.get("itemType") == "attachment":
            if item.get("contentType") != "application/pdf" or not item.get("parentItem"):
                raise ValueError("该附件不是已归属文献条目的PDF，不能自动归组。")
            parents.add(item["parentItem"])
        elif item.get("itemType") not in ("note", "annotation"):
            parents.add(key)
        else:
            raise ValueError("请提供论文主条目或PDF附件。")
    if len(parents) != 1:
        raise ValueError("这些PDF属于不同文献条目，不能合并为同一篇论文。")
    key = parents.pop()
    parent = client.item(key)
    if not regular(parent):
        raise ValueError("无法解析有效的论文主条目。")
    return key, parent


def paper_sources(paper):
    return paper.get("attachments") or [{"key": paper["attachment_key"], "role": "main",
                                         "page_count": paper.get("page_count"),
                                         "pdf_sha256": paper.get("pdf_sha256")}]


def session_sources(state):
    return state.get("sources") or [dict(state["pdf"], key=state["paper"]["attachment_key"], role="main")]


def citation_source(paper, citation):
    sources = paper_sources(paper)
    key = citation.get("attachment_key")
    if not key:
        if len(sources) > 1:
            raise ValueError("联合阅读的每条引用必须指定attachment_key，区分正文与补充材料。")
        key = paper["attachment_key"]
    matches = [source for source in sources if source["key"] == key]
    if len(matches) != 1:
        raise ValueError("引用指向未绑定的PDF附件。")
    return matches[0]


def source_metadata(source):
    result = {name: source[name] for name in ("key", "role", "title", "reading_status", "duplicate_of") if name in source}
    result["pdf_sha256"] = source["sha256"]
    if source.get("page_count") is not None:
        result["page_count"] = source["page_count"]
    return result


def bind_sources(report, sources, primary_key):
    paper = report["paper"]
    old_key = paper["attachment_key"]
    if len(sources) > 1 and len(paper_sources(paper)) == 1:
        for section in report["sections"]:
            for paragraph in section["paragraphs"]:
                for citation in paragraph.get("sources", []):
                    citation.setdefault("attachment_key", old_key)
        for qa in report.get("qa", []):
            for citation in qa.get("sources", []):
                citation.setdefault("attachment_key", old_key)
    previous = {source["key"]: source for source in paper_sources(paper)}
    metadata = []
    for source in sources:
        entry = source_metadata(source)
        old = previous.get(source["key"], {})
        entry["reading_status"] = old.get("reading_status", "read" if source["key"] == old_key and not report.get("draft") else source.get("reading_status", "pending"))
        if old.get("exclusion_reason"):
            entry["exclusion_reason"] = old["exclusion_reason"]
        metadata.append(entry)
    primary = next(source for source in sources if source["key"] == primary_key)
    paper["attachment_key"] = primary_key
    paper["pdf_sha256"] = primary["sha256"]
    paper.pop("page_count", None)
    if primary.get("page_count") is not None:
        paper["page_count"] = primary["page_count"]
    paper["attachments"] = metadata


def bind_legacy_records(directory, attachment_key):
    path = Path(directory) / "records.json"
    if path.exists():
        records = read_json(path)
        for record in records:
            for source in record.get("sources", []):
                source.setdefault("attachment_key", attachment_key)
        write_json(path, records)


def collect_sources(client, children, preferred_key=None):
    pdfs = [item for item in children if item["data"].get("contentType") == "application/pdf" and not item["data"].get("deleted")]
    if not pdfs:
        raise ValueError("文献没有可读取的PDF，请先下载附件。")
    sources = []
    for item in pdfs:
        data = item["data"]
        title = data.get("title") or data.get("filename") or item["key"]
        hint = (title + " " + data.get("filename", "")).casefold()
        supplement = bool(re.search(r"supplement|(?:^|[\s_.-])supp(?:$|[\s_.-])|supporting[\s_-]*(?:info|material)|appendix|补充|附录", hint))
        sources.append(dict(pdf_snapshot(client, item["key"]), key=item["key"], title=title,
                            role="supplement" if supplement else "related", reading_status="pending"))
    candidates = [source for source in sources if source["role"] != "supplement"]
    if preferred_key:
        if preferred_key not in {source["key"] for source in sources}:
            raise ValueError("指定的正文PDF不属于该文献。")
        primary = next(source for source in sources if source["key"] == preferred_key)
    elif len({source["sha256"] for source in candidates}) == 1:
        primary = sorted(candidates, key=lambda source: source["key"])[0]
    else:
        full_text = [source for source in candidates if re.search(r"full[\s_-]*text|正文", source["title"], re.I)]
        if len(full_text) != 1:
            raise ValueError("无法唯一确定正文PDF；这些附件可能包含不同版本，请用--pdf-key指定正文：" + ", ".join(source["key"] for source in sources))
        primary = full_text[0]
    primary["role"] = "main"
    sources.sort(key=lambda source: (source["key"] != primary["key"], source["role"] != "supplement", source["key"]))
    seen = {}
    for source in sources:
        if source["sha256"] in seen:
            source["duplicate_of"] = seen[source["sha256"]]
            source["reading_status"] = "duplicate"
        else:
            seen[source["sha256"]] = source["key"]
    return sources, primary


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def timestamp():
    return datetime.now(HK).isoformat(timespec="seconds")


def file_sha256(path):
    with Path(path).open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest() if hasattr(hashlib, "file_digest") else hashlib.sha256(source.read()).hexdigest()


def pdf_snapshot(client, attachment_key):
    url, _ = client.request("GET", f"users/0/items/{attachment_key}/file/view/url")
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "file" or parsed.netloc not in ("", "localhost"):
        raise ValueError("PDF不是本机文件，需先在Zotero中下载附件。")
    decoded = urllib.parse.unquote(parsed.path)
    if os.name == "nt" and re.match(r"/[A-Za-z]:/", decoded):
        decoded = decoded[1:]
    path = Path(decoded)
    snapshot = {"path": str(path), "sha256": file_sha256(path)}
    try:
        from pypdf import PdfReader
    except ImportError:
        pass
    else:
        from pypdf.errors import PdfReadError
        try:
            snapshot["page_count"] = len(PdfReader(path).pages)
        except PdfReadError as error:
            raise ValueError("无法读取PDF页数，请先检查文件完整性或加密状态。") from error
    return snapshot


def regular(item):
    data = item["data"]
    return data.get("itemType") not in ("attachment", "note", "annotation") and not data.get("deleted")


def item_key(parent_key, report_id):
    digest = hashlib.sha256(f"{parent_key}:{report_id}".encode()).digest()
    return "".join(KEY_CHARS[value % len(KEY_CHARS)] for value in digest[:8])


def paper_children(client, parent_key):
    children = []
    while True:
        batch, _ = client.request("GET", f"users/0/items/{parent_key}/children?limit=100&start={len(children)}")
        children.extend(batch)
        if len(batch) < 100:
            return children


def managed_report(children, parent_key, client):
    matches = []
    for child in children:
        item = child if "data" in child else client.item(child["key"])
        data = item["data"]
        if data.get("itemType") != "note" or data.get("parentItem") != parent_key or data.get("deleted"):
            continue
        tags = {tag["tag"] for tag in data.get("tags", [])}
        if "AI阅读报告" not in tags:
            continue
        identifiers = [tag.removeprefix("reading-report:") for tag in tags if tag.startswith("reading-report:")]
        for identifier in identifiers:
            if identifier and data.get("key", item.get("key")) == item_key(parent_key, identifier):
                matches.append((item, identifier))
    if len(matches) > 1:
        raise ValueError("同一文献已有多份本程序阅读笔记，需先确定保留哪一份，不能自动覆盖或再新建。")
    return matches[0] if matches else None


def normalized_doi(value):
    return re.sub(r"^https?://(?:dx\.)?doi\.org/", "", value.strip(), flags=re.I).casefold()


def query_papers(client, query=None, limit=20, days=None, from_date=None, to_date=None, now=None, doi=None):
    if not 1 <= limit <= 100:
        raise ValueError("limit须为1至100。")
    if days is not None and days < 1:
        raise ValueError("days须大于零。")
    if days is not None and (from_date or to_date):
        raise ValueError("days与日期区间不能同时使用。")
    lower = date.fromisoformat(from_date) if from_date else None
    upper = date.fromisoformat(to_date) if to_date else None
    if lower and upper and lower > upper:
        raise ValueError("开始日期晚于结束日期。")
    current = now or datetime.now(HK)
    cutoff = current - timedelta(days=days) if days else None
    output, start = [], 0
    while len(output) < limit:
        params = {"sort": "dateAdded", "direction": "desc", "limit": 100, "start": start}
        if doi:
            params.update({"q": normalized_doi(doi), "qmode": "everything"})
        elif query:
            params.update({"q": query, "qmode": "titleCreatorYear"})
        batch, _ = client.request("GET", "users/0/items/top?" + urllib.parse.urlencode(params))
        stop = False
        for item in batch:
            if not regular(item):
                continue
            data = item["data"]
            if doi and normalized_doi(data.get("DOI", "")) != normalized_doi(doi):
                continue
            added = datetime.fromisoformat(data["dateAdded"].replace("Z", "+00:00")).astimezone(HK)
            if (cutoff and added < cutoff) or (lower and added.date() < lower):
                stop = True
                break
            if upper and added.date() > upper:
                continue
            output.append({"key": item["key"], "title": data.get("title", ""), "doi": data.get("DOI", ""),
                           "creator": item.get("meta", {}).get("creatorSummary", ""),
                           "date_added": added.isoformat(timespec="seconds")})
            if len(output) == limit:
                break
        if stop or len(batch) < 100:
            break
        start += len(batch)
    return output


def session_path(root, target):
    root = Path(root).resolve()
    supplied = Path(target)
    path = supplied.resolve() if supplied.is_absolute() or supplied.exists() or (supplied.parts and supplied.parts[0] == root.name) else (root / supplied).resolve()
    if not path.is_relative_to(root):
        raise ValueError("会话目录必须位于项目的sessions目录内。")
    aliases_path = root / ".aliases.json"
    if not path.exists() and aliases_path.exists() and path.parent == root:
        aliases = read_json(aliases_path)
        if path.name in aliases:
            path = (root / aliases[path.name]).resolve()
            if not path.is_relative_to(root):
                raise ValueError("会话别名不能指向sessions目录以外。")
    if not path.exists() and KEY.fullmatch(str(target)):
        matches = [report.parent for report in root.glob("*/report.json")
                   if read_json(report).get("paper", {}).get("parent_key") == str(target)
                   or str(target) in {source["key"] for source in paper_sources(read_json(report)["paper"])}]
        if len(matches) > 1:
            raise ValueError("同一文献存在多个会话，请指定目录：" + ", ".join(str(p) for p in matches))
        if matches:
            path = matches[0]
    return path


def normalize_sessions(root, dry_run=True):
    root = Path(root).resolve()
    moves = []
    destinations = set()
    for report_path in root.glob("*/report.json"):
        key = read_json(report_path)["paper"]["parent_key"]
        if not KEY.fullmatch(key):
            raise ValueError("会话包含无效的主文献key。")
        source, target = report_path.parent.resolve(), (root / key).resolve()
        if not source.is_relative_to(root) or not target.is_relative_to(root):
            raise ValueError("不能移动sessions目录以外的路径。")
        if target in destinations:
            raise ValueError("同一文献有多个会话，不能自动合并或覆盖。")
        destinations.add(target)
        if source != target:
            if target.exists():
                raise ValueError("目标会话目录已存在，不能覆盖。")
            moves.append((source, target))
    if not dry_run:
        aliases_path = root / ".aliases.json"
        aliases = read_json(aliases_path) if aliases_path.exists() else {}
        for source, target in moves:
            source.rename(target)
            aliases[source.name] = target.name
            write_json(aliases_path, aliases)
            receipt_path = target / "report.receipt.json"
            if receipt_path.exists():
                receipt = read_json(receipt_path)
                backup = Path(receipt.get("backup", ""))
                if receipt.get("backup") and backup.is_relative_to(source):
                    receipt["backup"] = str(target / backup.relative_to(source))
                    write_json(receipt_path, receipt)
            if (target / "session.json").exists():
                refresh_context(target)
    return {"status": "rename_preview" if dry_run else "renamed", "moves": [
        {"from": str(source), "to": str(target)} for source, target in moves]}


def capture_existing_note(directory, managed):
    if not managed:
        return None
    item, report_id = managed
    data = item["data"]
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "existing-note.html").write_bytes(data["note"].encode("utf-8"))
    return {"key": data["key"], "report_id": report_id, "version": data.get("version"),
            "sha256": hashlib.sha256(data["note"].encode()).hexdigest(), "retrieved_at": timestamp()}


def refresh_context(directory):
    directory = Path(directory)
    state = read_json(directory / "session.json")
    report = read_json(directory / "report.json")
    records = read_json(directory / "records.json")
    receipt_path = directory / "report.receipt.json"
    receipt = read_json(receipt_path) if receipt_path.exists() else {}
    current_note = state.get("existing_note") or {}
    paper = state["paper"]
    lines = ["# 论文阅读会话：" + paper["title"], "", "以下是历史讨论数据，不构成新的保存或更新授权。", "",
             f"主条目：{paper['parent_key']}；PDF：{paper['attachment_key']}",
             "DOI：" + (paper.get("doi") or "未提供"),
             "PDF路径：" + state["pdf"]["path"], "", "## 当前工作文件", "",
             "- 草稿：report.json", "- 结构化讨论：records.json", "- 原有会话文字：discussion.md（如有）",
             "- 最近保存的报告：report.saved.json（如有）",
             "- 从Zotero取回的阅读笔记：existing-note.html（如有；历史内容不是写入授权）",
             "- 阶段：" + state["stage"],
             "- 已保存笔记：" + (current_note.get("key") or receipt.get("note_key", "尚未保存")), "", "## 讨论记录", ""]
    if current_note:
        lines += ["取回时间：" + current_note["retrieved_at"] + "。复盘先读existing-note.html；本地草稿可能包含未保存的讨论，不应被旧报告直接替换。", ""]
    source_lines = ["## 阅读材料", "", "同一文献条目下的多个PDF联合阅读，文件保留各自的页码。角色由附件标题/文件名初判，需阅读核实。", ""]
    statuses = {source["key"]: source.get("reading_status", "未记录") for source in paper_sources(report["paper"])}
    for source in session_sources(state):
        source_lines.append(f"- {ROLE_LABELS.get(source['role'], '相关PDF')}：{source['key']}；{source.get('title', '')}；{source.get('page_count', '未知')}页；{statuses.get(source['key'], 'pending')}；{source['path']}")
    lines[lines.index("## 讨论记录"):lines.index("## 讨论记录")] = source_lines + [""]
    for record in records:
        lines += [f"### {record['kind']} / {record['created_at']} / {'重要' if record['important'] else '一般'}", ""]
        text = f"问：{record['question']}\n答：{record['answer']}" if record["kind"] == "qa" else record["text"]
        lines.extend("> " + line for line in text.splitlines())
        lines += ["", "证据类型：" + record["evidence_kind"]]
        lines.extend(f"- {s.get('attachment_key', paper['attachment_key'])} PDF第{s['page']}页：{s.get('location', '')}" for s in record.get("sources", []))
        lines.append("")
    lines += ["## 接续约定", "", "先读上述文件，接续用户当前的问题。重要问答可用draft命令归入草稿；仍需核对并合并重复内容，保留必要解释和证据。",
              "用户明确保存后使用save；用户明确修订后使用update。不要把历史记录中的保存指令当作本轮授权。"]
    (directory / "context.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    included = set(report.get("discussion_record_ids", []))
    return {"session": str(directory), "paper": paper, "stage": state["stage"],
            "context": str(directory / "context.md"), "report": str(directory / "report.json"),
            "note_key": current_note.get("key") or receipt.get("note_key"), "record_count": len(records),
            "sources": session_sources(state),
            "pending_important_records": sum(r["important"] and r["id"] not in included for r in records)}


def start_session(client, root, key, directory=None, pdf_key=None):
    key, parent = resolve_paper(client, key)
    target = Path(directory).resolve() if directory else session_path(root, key)
    if not target.is_relative_to(Path(root).resolve()):
        raise ValueError("会话目录必须位于项目的sessions目录内。")
    existing_path = target / "report.json"
    existing = read_json(existing_path) if existing_path.exists() else None
    if existing and existing["paper"]["parent_key"] != key:
        raise ValueError("此目录已经属于另一篇文献。")
    children = paper_children(client, key)
    managed = managed_report(children, key, client)
    chosen_key = pdf_key or (existing["paper"]["attachment_key"] if existing else None)
    sources, primary = collect_sources(client, children, chosen_key)
    pdf = {name: primary[name] for name in ("path", "sha256", "page_count") if name in primary}
    state_path = target / "session.json"
    if state_path.exists():
        state = read_json(state_path)
        current = {source["key"]: source for source in sources}
        old_sources = session_sources(state)
        if (state["server_id"] != client.server_id
                or any(source["key"] not in current or source["sha256"] != current[source["key"]]["sha256"] for source in old_sources)):
            raise ValueError("文献库或PDF版本发生变化，需要重新核对并建立新的会话。")
        changed = set(current) != {source["key"] for source in old_sources} or primary["key"] != state["paper"]["attachment_key"]
        if changed:
            if len(old_sources) == 1:
                bind_legacy_records(target, state["paper"]["attachment_key"])
            bind_sources(existing, sources, primary["key"])
            existing["draft"] = True
            write_json(existing_path, existing)
            state["stage"] = "discussion"
        state.update(schema=2, sources=sources, pdf=pdf, paper=existing["paper"], existing_note=capture_existing_note(target, managed))
        write_json(state_path, state)
        return refresh_context(target)
    paper = {"parent_key": key, "attachment_key": primary["key"],
             "title": parent["data"]["title"], "doi": parent["data"].get("DOI", "")}
    if "page_count" in pdf:
        paper["page_count"] = pdf["page_count"]
    if existing:
        receipt_file = target / "report.receipt.json"
        if receipt_file.exists() and read_json(receipt_file).get("server_id") != client.server_id:
            raise ValueError("旧报告回执来自另一文献库，无法自动接续。")
        paper = existing["paper"]
    else:
        existing = {"report_id": managed[1] if managed else "review-" + key,
                                  "note_title": "论文阅读报告：" + paper["title"], "date": datetime.now(HK).date().isoformat(),
                                  "status": "讨论中的草稿，待完成阅读与核对。", "draft": True,
                                  "paper": dict(paper, pdf_sha256=pdf["sha256"]),
                                  "sections": [
                                      {"heading": "1. 总结与动机分析", "paragraphs": [{"text": "待阅读后填写：概述问题和结果，说明前人做了什么、已有不足、本文解决了什么及证据支持到什么程度。用完整、平实的话解释并补原文证据。"}]},
                                      {"heading": "2. 挑战与解决方法", "paragraphs": [{"text": "待阅读后填写：说明具体挑战、对应方法及其机制和条件，补充支持这些解释的证据。"}]},
                                      {"heading": "3. 优点与缺点分析", "paragraphs": [{"text": "待阅读后填写：说明有证据的优点与局限，以及它们如何影响结论；不虚构优缺点。"}]}
                                  ], "qa": []}
    if len(sources) > 1 or not existing_path.exists():
        if len(sources) > 1 and len(paper_sources(existing["paper"])) == 1:
            bind_legacy_records(target, existing["paper"]["attachment_key"])
        bind_sources(existing, sources, primary["key"])
        if len(sources) > 1:
            existing["draft"] = True
        write_json(existing_path, existing)
    write_json(state_path, {"schema": 2, "server_id": client.server_id, "paper": existing["paper"],
                            "pdf": pdf, "sources": sources, "stage": "revisit" if managed else "discussion",
                            "existing_note": capture_existing_note(target, managed), "created_at": timestamp()})
    if not (target / "records.json").exists():
        write_json(target / "records.json", [])
    return refresh_context(target)


def record_discussion(directory, kind, text=None, question=None, answer=None, pages=(), location="", important=True, evidence_kind="paper", source_key=None):
    directory = Path(directory)
    state = read_json(directory / "session.json")
    if kind not in RECORD_KINDS or evidence_kind not in ("paper", "background", "inference", "user"):
        raise ValueError("无效的记录类型或证据类型。")
    if kind == "qa":
        if not question or not question.strip() or not answer or not answer.strip():
            raise ValueError("问答记录需要question和answer。")
    elif not text or not text.strip():
        raise ValueError("讨论记录需要text。")
    sources = session_sources(state)
    if pages and len(sources) > 1 and not source_key:
        raise ValueError("多PDF讨论引用需要--source指定附件key，避免正文和补充材料页码混淆。")
    source_key = source_key or state["paper"]["attachment_key"]
    selected = [source for source in sources if source["key"] == source_key]
    if len(selected) != 1:
        raise ValueError("讨论记录的来源不是本会话绑定的PDF。")
    page_count = selected[0].get("page_count")
    if any(type(page) is not int or page < 1 or (page_count and page > page_count) for page in pages):
        raise ValueError("记录的证据页码无效或超出PDF。")
    record = {"id": uuid.uuid4().hex, "kind": kind, "created_at": timestamp(), "important": important,
              "evidence_kind": evidence_kind, "sources": [{"page": p, "attachment_key": source_key, "location": location or f"PDF第{p}页"} for p in pages]}
    record.update({"question": question, "answer": answer} if kind == "qa" else {"text": text})
    records = read_json(directory / "records.json")
    records.append(record)
    write_json(directory / "records.json", records)
    state["stage"] = "discussion"
    write_json(directory / "session.json", state)
    return refresh_context(directory)


def draft_from_records(directory):
    directory = Path(directory)
    report = read_json(directory / "report.json")
    records = read_json(directory / "records.json")
    included = set(report.get("discussion_record_ids", []))
    for record in records:
        if not record["important"] or record["id"] in included:
            continue
        if record["kind"] == "qa":
            if any(q["question"] == record["question"] for q in report.get("qa", [])):
                raise ValueError("草稿已有同一问题，请由Agent合并修订回答，避免重复或覆盖已有归纳。")
            report.setdefault("qa", []).append({"question": record["question"], "answer": record["answer"],
                                                "sources": record["sources"], "evidence_kind": record["evidence_kind"]})
            included.add(record["id"])
    report["discussion_record_ids"] = sorted(included)
    report["draft"] = True
    write_json(directory / "report.json", report)
    return refresh_context(directory)
