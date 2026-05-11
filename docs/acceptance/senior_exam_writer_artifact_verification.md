# senior-exam-writer 题包与知识库产物认证核验报告

- 认证时间: 2026-05-11 19:21:55 Asia/Shanghai
- 总体结论: PASS
- Word 题包: `C:\Users\coxx\Downloads\senior_exam_writer_actual_question_package.docx`
- JSON 题包: `C:\Users\coxx\Downloads\senior_exam_writer_actual_question_package.json`
- 题目数量: 9
- 证据数量: 6

## 场景核验
### scenario1_civil_service
- materials: 3; archived originals: 3
- stages: 8; writer_count: 3; manifest: 3; archived manifest: 3
- sqlite-vec loaded: True; db size: 4423680
- rag counts: `{"rag_sources": 3, "rag_chunks": 3, "rag_chunks_fts": 3, "rag_vec": 3, "rag_knowledge_points": 3, "rag_knowledge_hits": 9}`
- knowledge points: 找规律, 数量关系, 时事政治

### scenario2_university_pdf
- materials: 1; archived originals: 1
- stages: 8; writer_count: 3; manifest: 1; archived manifest: 1
- sqlite-vec loaded: True; db size: 4362240
- rag counts: `{"rag_sources": 1, "rag_chunks": 1, "rag_chunks_fts": 1, "rag_vec": 1, "rag_knowledge_points": 3, "rag_knowledge_hits": 3}`
- knowledge points: Correlation coefficient, Sample variance, n-1

### scenario3_ai_hiring
- materials: 2; archived originals: 2
- stages: 8; writer_count: 3; manifest: 2; archived manifest: 2
- sqlite-vec loaded: True; db size: 4399104
- rag counts: `{"rag_sources": 2, "rag_chunks": 2, "rag_chunks_fts": 2, "rag_vec": 2, "rag_knowledge_points": 4, "rag_knowledge_hits": 8}`
- knowledge points: LLM 基础, Python, 机器学习, 系统设计追问

## 缺口
- 未发现阻断性缺口。

## 说明
- 当前核验对象为小型模拟资料验收产物，验证流程完整性与证据链持久化，不代表真实考试正式资料。
- 仓库 docs 目录仍受 Windows 安全中心受控文件夹访问影响，最终题包与核验报告已输出到 Downloads。