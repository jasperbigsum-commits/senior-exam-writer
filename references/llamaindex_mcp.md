# LlamaIndex/sqlite-vec Local RAG And Optional MCP

Use this reference when the task needs file-level RAG over local source files, source chunk matching, or optional LlamaIndex CLI/MCP integration.

## Required Local RAG Path

For this skill's local source-file RAG, use `scripts/llamaindex_sqlite_vec_rag.py`. This path is strict:

- LlamaIndex loads files and splits text into nodes/chunks.
- A local llama.cpp embedding endpoint creates vectors with the same Chinese-friendly embedding model used by the evidence workflow.
- `sqlite-vec` stores vectors in a local SQLite `vec0` table.
- `rag_knowledge_points` and `rag_knowledge_hits` persist knowledge-point to source-chunk bindings after query.
- FTS5 is only the lexical side of hybrid recall and source locator matching; it is never an FTS-only evidence path.
- If LlamaIndex, `sqlite-vec`, embedding, vector dimension, or index creation fails, stop and fix the environment instead of continuing with context-only, keyword-only, or remote-default retrieval.

Install dependencies from the skill directory:

```powershell
uv sync --extra rag --extra test
```

For Bash/Zsh:

```bash
uv sync --extra rag --extra test
```

Start or reuse a loopback-only llama.cpp embedding endpoint. Prefer ModelScope Qwen3-Embedding GGUF models described in [llama_cpp.md](llama_cpp.md). A local generation model such as Qwen3-4B is not required.

```powershell
uv run python scripts/init_modelscope_runtime.py
llama-server -m C:\path\to\qwen3-embedding.gguf --embedding --pooling last --host 127.0.0.1 --port 8081
```

Index local files:

```powershell
uv run --extra rag python scripts/llamaindex_sqlite_vec_rag.py index `
  --db ./local_rag.sqlite `
  --input ./prepared_pipeline/original_sources `
  --embed-url http://127.0.0.1:8081 `
  --embed-model local-embedding `
  --reset
```

Run hybrid retrieval:

```powershell
uv run --extra rag python scripts/llamaindex_sqlite_vec_rag.py query `
  --db ./local_rag.sqlite `
  --query "样本方差为什么使用 n-1" `
  --knowledge-point "样本方差" `
  --knowledge-point "无偏估计" `
  --embed-url http://127.0.0.1:8081 `
  --embed-model local-embedding
```

The query output must include `source_path`, `source_name`, `source_id`, `chunk_id`, `node_id`, `chunk_index`, `locator`, `char_start`, `char_end`, `retrieval_modes`, `lexical_terms`, `snippet`, `hit_text`, `knowledge_judgement`, `knowledge_hit_ids`, and `persisted_knowledge_hits`.

Use `knowledge_judgement` to decide whether the hit really supports the requested knowledge point. Use `retrieval_modes` to audit whether a hit came from vector retrieval, FTS5 lexical recall, or both.

After query, inspect persisted knowledge bindings when auditing a run:

```sql
SELECT p.knowledge_point, h.status, h.semantic_score, h.lexical_match,
       c.source_path, c.locator, h.matched_text
FROM rag_knowledge_hits h
JOIN rag_knowledge_points p ON p.id = h.knowledge_point_id
JOIN rag_chunks c ON c.id = h.chunk_id
ORDER BY p.knowledge_point, h.updated_at DESC;
```

## Three-Platform Environment Notes

Windows:

- Use PowerShell with UTF-8 enabled when paths or materials contain Chinese text: `$env:PYTHONUTF8="1"; $env:PYTHONIOENCODING="utf-8"`.
- Prefer JSON files and backtick line continuations in examples; avoid long inline JSON.
- If Windows Firewall prompts for `llama-server.exe`, allow loopback/private access and rerun. Do not open router or public firewall ports for local use.

macOS:

- Install `llama.cpp` with `brew install llama.cpp` or another local package manager.
- Use `uv run --extra rag ...` from the skill directory so Python dependencies stay isolated.
- Bind the embedding endpoint to `127.0.0.1`; no extra port exposure is needed for same-machine RAG.

Linux:

- Install `llama.cpp` with Linuxbrew, Nix, Docker, or a source build as described in [llama_cpp.md](llama_cpp.md).
- Keep `PYTHONUTF8=1` or a UTF-8 locale for Chinese filenames and JSON output.
- Use a loopback endpoint for local RAG unless another machine explicitly needs access.

## Connector Plan And Original Archive

`prepare-pipeline` writes reusable source artifacts before embedding:

- `original_sources/`: copied source files preserving relative directory structure.
- `source_manifest.json`: one record per file with `connector_plan`, `archive_path`, and `archive_relative_path`.

The LlamaIndex model is simple: choose a reader/connector for each source type, load documents, split nodes, embed/index them, then query through hybrid retrieval.

Connector hints:

- PDF -> `pdf_reader`
- DOCX -> `docx_reader`
- EPUB -> `epub_reader`
- Markdown -> `markdown_reader`
- TXT -> `text_reader`
- JSON/JSONL -> `json_reader` / `jsonl_reader`

If richer connectors are added later, replace only the connector implementation. Keep the archived original path and SQLite source metadata stable.

## Optional LlamaIndex CLI Usage

`llamaindex-cli rag` and LlamaIndex `RagCLI` can be useful for experiments or external workflows. Treat them as optional and separate from the required local `sqlite-vec` script.

When using tools that read `OPENAI_BASE_URL` and `OPENAI_API_KEY`, export values from the current Codex provider config instead of hardcoding OpenAI:

```powershell
uv run python scripts/export_provider_env.py --format powershell
```

For POSIX shells:

```bash
uv run python scripts/export_provider_env.py --format posix
```

The wrapper keeps provider/base URL explicit and caches the raw result locally:

```powershell
uv run python scripts/llamaindex_rag.py `
  --files ./prepared_pipeline/original_sources `
  --question "检索与样本方差有关的证据" `
  --output-json ./llamaindex_results/sample_variance.json `
  --embed-base-url http://127.0.0.1:8081 `
  --embed-model local-embedding
```

LlamaIndex's advanced Python API can customize `RagCLI` with an `IngestionPipeline`, a `QueryPipeline`, custom embedding model, custom LLM, and custom vector database. Do not let LlamaIndex default to OpenAI environment variables; pass provider/base URL and embedding settings explicitly.

If the installed package does not provide `llamaindex-cli`, the wrapper fails closed with a JSON error report. In that case, pass `--executable` to a real CLI script, use an MCP retrieval server, or stay on `scripts/llamaindex_sqlite_vec_rag.py`.

## Optional MCP Service Pattern

Local search did not find an installed LlamaIndex retrieval/MCP skill. Public candidates included `davila7/claude-code-templates@llamaindex`, `mindrally/skills@llamaindex-development`, `yonatangross/orchestkit@rag-retrieval`, and `skills.volces.com@mcp-finder`. Install one only if the user wants that external workflow.

If using an MCP retrieval service:

- Add it as an optional MCP server, not a required skill dependency.
- Bind local services to loopback unless another machine explicitly needs access.
- Pass provider/base URL through `scripts/export_provider_env.py`.
- Require each result to include source path or URL, locator, text snippet, score, and backend metadata.
- Cache returned materials and retrieval hits locally before using them as candidate evidence.
- Store external hits back into the SQLite audit trail before approval.

## Refusal Conditions

Refuse or stop when:

- `sqlite-vec` or LlamaIndex cannot import.
- The local embedding endpoint is missing, non-loopback, returns empty vectors, or returns inconsistent dimensions.
- The index contains no chunks or no vector dimension metadata.
- Retrieved hits lack stable source paths, chunk IDs, or locators.
- CLI/MCP retrieval creates vectors with a different embedding model from the local evidence store.
- The task contains confidential exam materials and the external provider or MCP service is not approved.
