# 报告JSON与预览

仅在准备报告时读取；无需为了找论文加载脚本源码。先start建立会话，在它生成的report.json上填写内容，保留真实paper字段、report_id和指纹；不要新造条目编号。

最小结构示意（示例身份不能用于真实写入）：

```json
{
  "report_id": "review-ABCD2345",
  "note_title": "论文阅读报告：示例论文",
  "date": "2026-10-23",
  "status": "已完成初步阅读，供讨论与核对；尚未保存。",
  "draft": true,
  "paper": {
    "parent_key": "ABCD2345",
    "attachment_key": "EFGH6789",
    "title": "示例论文",
    "doi": "",
    "page_count": 10,
    "attachments": [
      {"key": "EFGH6789", "role": "main", "page_count": 10,
       "pdf_sha256": "由start提供的真实SHA-256", "reading_status": "read"}
    ]
  },
  "sections": [
    {"heading": "1. 总结与动机分析", "paragraphs": [
      {"text": "经原文支持的中文总结、贡献、动机及研究空白。",
       "sources": [{"attachment_key": "EFGH6789", "page": 1, "location": "PDF第1页，摘要"}]},
      {"text": "原文摘录：“经逐字核对的原语言关键片段”", "quote": true,
       "sources": [{"attachment_key": "EFGH6789", "page": 1, "location": "PDF第1页，摘要"}]}
    ]},
    {"heading": "2. 挑战与解决方法", "paragraphs": [{"text": "挑战、方案及其机制、证据与适用条件。"}]},
    {"heading": "3. 优点与缺点分析", "paragraphs": [{"text": "有证据的优点、局限及它们对结论的影响。"}]}
  ],
  "qa": [],
  "discussion_record_ids": []
}
```

三个模块均须补充真正支持结论的sources和原文短摘录。上例中的通用说明、占位指纹不可原样保存。

- quote=true仅改变引用块排版；引语放在text中，不能只填一个不会显示的quote_text字段。
- sources的page从该PDF第1页开始；location写章节/图表/段落。多来源必须带attachment_key。
- 新来源reading_status保持pending，实际读完再标read；相同副本duplicate需duplicate_of，排除excluded需exclusion_reason。不把已抽取文本误当已读。
- 仅从出版社取得、尚未收录Zotero的补充文件用external_sources：`[{"url":"https://出版社/补充.pdf#page=7","location":"补充PDF第7页，§4.2"}]`。记录来源、指纹和阅读范围，不伪造attachment_key。
- qa仅放真实用户问答，字段question、answer、sources及evidence_kind；没有实际问题时保持空列表。Agent主动辨析放正文并用record --kind insight记录。
- 用record保存重要讨论，再draft合入未处理QA；核对、压缩后把已归纳记录id写入discussion_record_ids。
- 本地报告初稿可以保持draft=true供用户看效果；只有内容核对通过后才设false。draft=false表示内容已就绪，不等于获得本轮写入授权。
- preview生成同目录report.html；明确保存后才save，更新已有笔记可先update --dry-run。不要修改report.saved.json、回执或旧笔记快照来绕过校验。
