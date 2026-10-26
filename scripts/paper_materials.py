"""Extract or render bound local PDFs without changing their reading status."""

import argparse
import json
from pathlib import Path
import sys

from reading_sessions import KEY, file_sha256, read_json, session_path, session_sources
from zotero_notes import default_data_root


def prepare_sources(data_root, session, source_key=None):
    state = read_json(session_path(data_root / "sessions", session) / "session.json")
    parent = state["paper"]["parent_key"]
    if not KEY.fullmatch(parent):
        raise ValueError("会话的主条目key无效。")
    sources = [s for s in session_sources(state) if source_key is None or s["key"] == source_key]
    if not sources:
        raise ValueError("没有对应的PDF来源，请核对附件key。")
    for source in sources:
        if not KEY.fullmatch(source["key"]):
            raise ValueError("PDF来源key无效。")
        if file_sha256(source["path"]) != source["sha256"]:
            raise ValueError("PDF内容已更换，请重新核对来源；不能沿用旧页码证据。")
    return parent, sources


def extract(data_root, session, source_key=None):
    from pypdf import PdfReader
    parent, sources = prepare_sources(data_root, session, source_key)
    output = data_root / ".local/papers" / parent
    output.mkdir(parents=True, exist_ok=True)
    files = []
    for source in sources:
        reader = PdfReader(source["path"])
        texts = [page.extract_text() or "" for page in reader.pages]
        parts = [f"===== {source['key']} PDF第{i}页 =====\n" + text for i, text in enumerate(texts, 1)]
        target = output / (source["key"] + ".txt")
        target.write_text("\n\n".join(parts), encoding="utf-8")
        files.append({"attachment_key": source["key"], "page_count": len(reader.pages),
                      "text_path": str(target), "characters": sum(len(text.strip()) for text in texts),
                      "empty_text_pages": [i for i, text in enumerate(texts, 1) if not text.strip()]})
    return {"status": "extracted", "files": files,
            "reminder": "抽取不代表完成阅读；检查空白页、双栏、公式和图表，必要时render或OCR。"}


def render(data_root, session, source_key, pages, scale=1.5):
    import pypdfium2 as pdfium
    if not pages or not 0 < scale <= 4:
        raise ValueError("需要有效页码，渲染比例应大于0且不超过4。")
    parent, sources = prepare_sources(data_root, session, source_key)
    if len(sources) != 1:
        raise ValueError("渲染需要--source指定一个PDF附件。")
    output = data_root / ".local/papers" / parent
    output.mkdir(parents=True, exist_ok=True)
    files = []
    with pdfium.PdfDocument(sources[0]["path"]) as pdf:
        if any(page < 1 or page > len(pdf) for page in pages):
            raise ValueError("渲染页码超出该PDF范围。")
        for page in dict.fromkeys(pages):
            target = output / f"{source_key}-p{page}.png"
            bitmap = pdf[page - 1].render(scale=scale)
            bitmap.to_pil().save(target)
            bitmap.close()
            files.append({"attachment_key": source_key, "page": page, "image_path": str(target)})
    return {"status": "rendered", "files": files}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("extract", "render"):
        item = sub.add_parser(command)
        item.add_argument("session")
        item.add_argument("--source", required=command == "render")
        if command == "render":
            item.add_argument("--page", type=int, action="append", required=True)
            item.add_argument("--scale", type=float, default=1.5)
    args = parser.parse_args()
    root = args.data_dir.expanduser().resolve() if args.data_dir else default_data_root()
    result = extract(root, args.session, args.source) if args.command == "extract" else render(root, args.session, args.source, args.page, args.scale)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, ImportError) as error:
        print(json.dumps({"status": "materials_error", "action": str(error)}, ensure_ascii=False))
        sys.exit(2)
