from __future__ import annotations

from pathlib import Path


def test_skill_docs_mention_closed_loop_commands() -> None:
    root = Path(__file__).resolve().parents[1]
    joined = "\n".join(
        [
            (root / "SKILL.md").read_text(encoding="utf-8"),
            (root / "references" / "task_workflow.md").read_text(encoding="utf-8"),
        ]
    )
    for token in [
        "scripts/run_batch.py",
        "--prepare-only",
        "init-runtime",
        "split-requirements",
        "prepare-pipeline",
        "collect-exam-sources",
        "--input",
        "--ingest",
        "plan-knowledge",
        "plan-evidence",
        "generate-candidates",
        "audit-question-similarity",
        "review-candidate",
        "uv run python",
        "ModelScope",
        "Qwen3-Embedding",
        "--no-embed",
    ]:
        assert token in joined
    assert "auto-selected local port" in joined or "free local port" in joined


def test_llama_cpp_reference_requires_uv_and_functional_model_gate() -> None:
    root = Path(__file__).resolve().parents[1]
    reference = (root / "references" / "llama_cpp.md").read_text(encoding="utf-8")

    for token in [
        "uv sync",
        "uv run python scripts/run_batch.py",
        "uv run python scripts/init_modelscope_runtime.py",
        "ModelScope",
        "Qwen/Qwen3-Embedding-0.6B-GGUF",
        "Hard gate",
        "`--no-embed` is disabled",
        "Qwen3-4B is not required",
        "prepare-pipeline",
        "No external port opening is expected",
    ]:
        assert token in reference

    assert "Qwen/Qwen3-4B-GGUF" not in reference


def test_llama_cpp_reference_covers_three_platform_runtime_setup() -> None:
    root = Path(__file__).resolve().parents[1]
    reference = (root / "references" / "llama_cpp.md").read_text(encoding="utf-8")

    for token in [
        "Platform Runtime Setup",
        "Windows",
        "macOS",
        "Linux",
        "winget install llama.cpp",
        "brew install llama.cpp",
        "nix profile install nixpkgs#llama-cpp",
        "ghcr.io/ggml-org/llama.cpp:server",
        "llama-server --help",
        "Runtime Checklist",
        "run_batch.py",
    ]:
        assert token in reference


def test_runtime_setup_has_single_cli_entrypoint() -> None:
    root = Path(__file__).resolve().parents[1]
    assert not (root / "scripts" / "init_local_runtime.py").exists()


def test_modelscope_initializer_does_not_require_generation_model() -> None:
    root = Path(__file__).resolve().parents[1]
    script = (root / "scripts" / "init_modelscope_runtime.py").read_text(encoding="utf-8")

    for token in [
        "DEFAULT_EMBED_REPO",
        "--embed-model-path",
        "generation\": \"not required",
    ]:
        assert token in script
    for token in [
        "DEFAULT_LLM_REPO",
        "--llm-model-path",
        "Qwen3-4B-GGUF",
    ]:
        assert token not in script


def test_acceptance_checklist_is_discoverable() -> None:
    root = Path(__file__).resolve().parents[1]
    skill = (root / "SKILL.md").read_text(encoding="utf-8")
    checklist = (root / "references" / "acceptance_checklist.md").read_text(encoding="utf-8")

    assert "references/acceptance_checklist.md" in skill
    for token in [
        "Civil-Service Exam",
        "University Final",
        "AI Engineer Hiring Assessment",
        "Flow compliance",
        "Evidence completeness",
    ]:
        assert token in checklist


def test_local_llms_map_keeps_skill_references_discoverable() -> None:
    root = Path(__file__).resolve().parents[1]
    skill = (root / "SKILL.md").read_text(encoding="utf-8")
    llms_map = (root / "llms.txt").read_text(encoding="utf-8")

    assert "llms.txt" in skill
    for token in [
        "references/task_workflow.md",
        "references/evidence_gate.md",
        "references/llama_cpp.md",
        "references/llamaindex_mcp.md",
        "scripts/run_batch.py",
        "scripts/export_provider_env.py",
        "scripts/llamaindex_rag.py",
        "scripts/llamaindex_sqlite_vec_rag.py",
        "scripts/senior_exam_writer_lib/prepare_pipeline.py",
        "scripts/senior_exam_writer_lib/source_archive.py",
        "SQLite",
        "vector-first",
    ]:
        assert token in llms_map


def test_llamaindex_mcp_reference_documents_strict_sqlite_vec_and_optional_provider_path() -> None:
    root = Path(__file__).resolve().parents[1]
    reference = (root / "references" / "llamaindex_mcp.md").read_text(encoding="utf-8")

    for token in [
        "LlamaIndex/sqlite-vec Local RAG And Optional MCP",
        "Required Local RAG Path",
        "sqlite-vec",
        "`sqlite-vec` stores vectors",
        "FTS5 is only the lexical side",
        "uv sync --extra rag --extra test",
        "uv run --extra rag python scripts/llamaindex_sqlite_vec_rag.py index",
        "uv run --extra rag python scripts/llamaindex_sqlite_vec_rag.py query",
        "Three-Platform Environment Notes",
        "Windows",
        "macOS",
        "Linux",
        "lexical_terms",
        "Refusal Conditions",
        "cannot import",
        "empty vectors",
        "inconsistent dimensions",
        "Optional LlamaIndex CLI Usage",
        "llamaindex-cli rag",
        "RagCLI",
        "IngestionPipeline",
        "QueryPipeline",
        "custom embedding model",
        "custom LLM",
        "custom vector database",
        "Connector Plan And Original Archive",
        "original_sources",
        "connector_plan",
        "PDF -> `pdf_reader`",
        "scripts/export_provider_env.py",
        "scripts/llamaindex_rag.py",
        "provider/base URL",
        "Do not let LlamaIndex default to OpenAI",
    ]:
        assert token in reference


def test_llamaindex_sqlite_vec_rag_path_is_documented() -> None:
    root = Path(__file__).resolve().parents[1]
    skill = (root / "SKILL.md").read_text(encoding="utf-8")
    reference = (root / "references" / "llamaindex_mcp.md").read_text(encoding="utf-8")

    for token in [
        "scripts/llamaindex_sqlite_vec_rag.py",
        "sqlite-vec",
        "FTS5+vector hybrid retrieval",
        "source_path",
        "chunk_id",
        "lexical_terms",
        "knowledge_judgement",
        "Treat `sqlite-vec`, LlamaIndex, and local embeddings as mandatory",
    ]:
        assert token in skill + reference


def test_question_rules_document_calculation_contract() -> None:
    root = Path(__file__).resolve().parents[1]
    reference = (root / "references" / "question_rules.md").read_text(encoding="utf-8")

    for token in [
        "Calculation Rules",
        "solution_steps",
        "formula_reference",
        "complete solution steps",
    ]:
        assert token in reference
