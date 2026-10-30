# 报告JSON与预览

仅在准备报告时读取；无需为了找论文加载脚本源码。先start建立会话，在它生成的report.json上填写内容，保留真实paper字段、report_id和指纹；不要新造条目编号。

最小结构示意（示例身份不能用于真实写入）：

```json
{
  "report_id": "review-ABCD2345",
  "note_title": "论文阅读报告：示例论文",
  "date": "2026-10-23",
  "format_version": 2,
  "draft": true,
  "core_idea": {
    "paragraphs": [
      {"text": "用实际内容解释问题、相关已有做法和本文改动，让读者无需先看后文也能理解主要工作。保留有帮助的技术细节，不能只填流程或抽象口号。",
       "sources": [{"attachment_key": "EFGH6789", "page": 1, "location": "引言或实际支持位置"}]},
      {"text": "接着讲清为什么这样改、主要结果及取舍，保留必要条件。以上角度可按论文取舍，不要求固定顺序或段数；替换为实际有依据的解释。",
       "sources": [{"attachment_key": "EFGH6789", "page": 2, "location": "设计、结果及限制的实际位置"}]},
      {"text": "原文摘录：经核对的关键短句；此占位文字不能保存。", "quote": true,
       "sources": [{"attachment_key": "EFGH6789", "page": 2, "location": "实际摘录位置"}]}
    ]
  },
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
      {"text": "工作概述与主要结论：用完整、平实的话解释论文研究什么，以及主要结果和测试条件。",
       "sources": [{"attachment_key": "EFGH6789", "page": 1, "location": "PDF第1页，摘要"}]},
      {"text": "前人做了什么：依据本文引言或相关工作，说明与本研究直接相关的已有方法及它们已经能完成什么。仅转述本文对前作的概括，不冒充独立查阅。",
       "sources": [{"attachment_key": "EFGH6789", "page": 1, "location": "PDF第1页，引言，按实际内容调整"}]},
      {"text": "已有不足：说明作者指出的具体限制和适用条件，不把本文未讨论的问题说成整个领域没有研究。",
       "sources": [{"attachment_key": "EFGH6789", "page": 1, "location": "PDF第1页，引言，按实际内容调整"}]},
      {"text": "本文解决了什么：解释针对哪项不足改了什么，以及结果实际支持它解决到什么程度。研究目标与已验证的贡献分别交代。",
       "sources": [{"attachment_key": "EFGH6789", "page": 1, "location": "PDF第1页，贡献说明，按实际内容调整"}]},
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

format_version=2把core_idea显示在阅读日期下面，早于材料清单和所有章节，不显示全局status。默认使用可独立阅读的开篇：只看本节应能理解论文主要做什么、设计依据和关键取舍，后文三模块继续展开和核实。可以联系问题、已有方案、改动、理由、结果及边界，按论文类型取舍，不机械列五个小标题或显式标注“巧思”。保留必要技术细节，不堆参数，也不泛化成空洞启发；用户关注点可调整侧重，但不能代替主要工作的介绍。

多段开篇用core_idea.paragraphs，数组内每项沿用普通段落的text、sources/external_sources和可选quote。每段分别定位，重要结论的短摘录也放在本节，不以长引文代替解释。旧的core_idea={"text":"...","sources":[...]}继续兼容且渲染不变；同一个core_idea不能同时放paragraphs与顶层text/引用字段，避免内容被静默忽略。正文三模块保留，不逐句复写开篇；关键认识改变时同步修订受影响内容。区分论文事实、作者主张与阅读归纳，不夸大首次或删掉关键限定。

内部draft仅表示本轮内容是否经过核对，可以反复讨论而不展示“讨论中”。保存要求开篇包含解释性正文且每段有来源，不能只有原文摘录；空的初始core_idea.paragraphs可留在本地预览，不能自动保存。程序检查结构与定位，不通过字数或关键词判断开篇是否讲清论文。旧格式没有该字段仍按原样渲染以保留笔记校验基线，后续实际讨论更新时再补新开篇；不要直接改report.saved.json。

第一模块的“工作概述、前人工作、已有不足、本文解决内容”可以自然衔接成几段，也可以用小标题帮助阅读；不要求机械复用示例标签。每个重要判断就近给证据和必要的关键摘录，不能用一条摘要引用支撑所有前作比较。用完整句子解释，允许为说明机制展开，不把报告写成只有关键词的提纲。

- quote=true仅改变引用块排版；引语放在text中，不能只填一个不会显示的quote_text字段。
- sources的page从该PDF第1页开始；location写章节/图表/段落。多来源必须带attachment_key。
- 新来源reading_status保持pending，实际读完再标read；相同副本duplicate需duplicate_of，排除excluded需exclusion_reason。不把已抽取文本误当已读。
- 仅从出版社取得、尚未收录Zotero的补充文件用external_sources：`[{"url":"https://出版社/补充.pdf#page=7","location":"补充PDF第7页，§4.2"}]`。记录来源、指纹和阅读范围，不伪造attachment_key。
- qa仅放真实用户问答，字段question、answer、sources及evidence_kind；没有实际问题时保持空列表。Agent主动辨析放正文并用record --kind insight记录。
- 用record保存重要讨论，再draft合入未处理QA；核对并合并重复内容后，把已归纳记录id写入discussion_record_ids，保留必要解释。
- 本轮未核对的内容保持draft=true；完成核对后设false，不必等所有讨论结束。未读来源/未归纳重要问答仍会阻止自动保存，不通过状态标签代替证据。
- 默认每轮实质更新后preview再autosave；manual或用户暂停时只保留本地讨论，显式保存可save/update。不重复生成整个报告，只改受影响的段落、核心理念和重要问答，再由程序渲染完整HTML。不要修改已保存快照/回执来绕过校验。
