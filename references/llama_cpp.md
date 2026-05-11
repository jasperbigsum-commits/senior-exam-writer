# llama.cpp Managed Local Embedding

This skill requires a local embedding model for vectorization, evidence retrieval, and historical-question similarity review. Codex/agent is the writer and reviewer, so a local generation model such as Qwen3-4B is not required by default.

Hard gate: do not ingest, plan evidence, retrieve, generate candidates, audit similarity, or complete review until a real Chinese embedding request succeeds. The preferred `run_batch.py` path performs this probe automatically; manual workflows must run `init-runtime`.

## Recommended Chinese Embedding Models

Use an embedding model that is strong on Chinese semantic retrieval:

- `Qwen/Qwen3-Embedding-0.6B-GGUF` from ModelScope for a lighter local setup: https://modelscope.cn/models/Qwen/Qwen3-Embedding-0.6B-GGUF
- `Qwen/Qwen3-Embedding-4B-GGUF` from ModelScope when you can afford more memory and want stronger retrieval: https://modelscope.cn/models/Qwen/Qwen3-Embedding-4B-GGUF
- BGE/GTE multilingual or Chinese GGUF variants from ModelScope when your organization standardizes on those models.

Do not use a general chat/instruct model as the embedding server. It may start, but retrieval quality and vector shape can be wrong for evidence matching.

Do not download or start Qwen3-4B just because this skill is running. Use a local LLM only if you intentionally run the legacy script-driven `generate` command or want optional offline LLM verification.

## Preferred Managed Batch Runner

Use `uv` for Python dependencies and script execution. From the skill directory:

```bash
uv sync --extra test --extra pdf-fixtures
```

For normal batch work, let the runner manage the embedding process:

```bash
uv run python scripts/run_batch.py \
  --requirements "根据考试大纲和材料生成分层试题" \
  --input ./materials \
  --output-dir ./exam_run \
  --db ./exam_evidence.sqlite
```

What the runner does:

- Resolves or downloads a Chinese-friendly ModelScope embedding GGUF.
- Starts `llama-server` only on `127.0.0.1`.
- Auto-selects a free local port unless `--port` is explicitly supplied.
- Probes Chinese embeddings before creating any usable evidence.
- Ingests files with embeddings and runs duplicate audit.
- Stops the temporary server when finished unless `--keep-server` is set.

No external port opening is expected for this path. The local endpoint is for same-machine communication only; do not bind to `0.0.0.0` unless another machine intentionally needs access.

If embedding is not ready and the user only wants deterministic preparation:

```bash
uv run python scripts/run_batch.py \
  --prepare-only \
  --requirements "根据考试大纲和材料生成分层试题" \
  --input ./materials \
  --output-dir ./prepared_pipeline \
  --db ./exam_evidence.sqlite
```

`--prepare-only` does not start `llama-server` and does not produce usable citations, vectors, similarity scores, or approved questions.

## ModelScope-First Preparation

Use this when you need to pre-download or inspect the embedding model instead of letting `run_batch.py` do it during the managed run.

Download or locate the embedding GGUF and print the llama.cpp launch command:

```bash
uv run python scripts/init_modelscope_runtime.py
```

If you already downloaded the embedding GGUF manually:

```bash
uv run python scripts/init_modelscope_runtime.py \
  --embed-model-path C:/path/to/Qwen3-Embedding-0.6B-Q8_0.gguf
```

## Platform Runtime Setup

Set up `uv`, `llama-server`, and ModelScope before running any exam workflow. The command `llama-server --help` must work, or pass the executable path to `run_batch.py` or `init_modelscope_runtime.py` with `--llama-server`.

Common preparation for all platforms:

```bash
cd /path/to/senior-exam-writer
uv sync --extra test --extra pdf-fixtures
uv run python scripts/init_modelscope_runtime.py
```

### Windows

Use one of these routes:

- Package manager: `winget install llama.cpp`, then verify with `where llama-server`.
- Manual binary or source build: locate `llama-server.exe`, then pass it explicitly:

```powershell
uv run python scripts/init_modelscope_runtime.py `
  --llama-server "C:\path\to\llama-server.exe"
```

Prefer `run_batch.py` after this check. If Windows Firewall blocks `llama-server.exe`, allow local/private loopback access and rerun the batch command; do not add router port forwarding or public firewall rules.

### macOS

Use one of these routes:

- Homebrew: `brew install llama.cpp`, then verify with `which llama-server`.
- MacPorts: `sudo port install llama.cpp`.
- Nix: `nix profile install nixpkgs#llama-cpp`.

For Apple Silicon, prefer a package-manager build unless you need a custom backend. Then use `run_batch.py` so the local server lifecycle stays temporary.

### Linux

Use one of these routes:

- Linuxbrew: `brew install llama.cpp`, then verify with `which llama-server`.
- Nix: `nix profile install nixpkgs#llama-cpp`.
- Docker: use the official `ghcr.io/ggml-org/llama.cpp:server` image when you want an isolated server process.
- Source build fallback:

```bash
git clone https://github.com/ggml-org/llama.cpp
cd llama.cpp
cmake -B build
cmake --build build --config Release -t llama-server
export LLAMA_SERVER="$PWD/build/bin/llama-server"
```

For NVIDIA GPU Docker runs, use an official CUDA server image and pass GPU support through Docker. For CPU-only or simple validation, a package-manager or source build is enough. Prefer `run_batch.py` for the skill workflow.

## Runtime Checklist

Before ingestion, all items must be true:

- `uv run python scripts/init_modelscope_runtime.py` can locate one embedding GGUF in the user ModelScope cache, or an explicit `--embed-model-path` points to an existing GGUF outside the skill folder.
- `run_batch.py` can start `llama-server` on `127.0.0.1` with `--embedding --pooling last`, or a manually supplied loopback endpoint is already running.
- The embedding probe returns `ok: true` with a positive vector dimension.
- If any check fails, stop and fix the local runtime. Do not ingest sources or create a half-indexed database.

If embedding is not deployed yet, you may still run `prepare-pipeline` for batch preparation. That mode only parses local files, writes manifests and prompt packages, and emits next commands; it does not create usable evidence, vectors, or similarity-review results.

## Advanced Manual Embedding Server

Manual server setup is an advanced fallback for users who want a reusable local endpoint. Run an embedding server bound to loopback:

```bash
llama-server -m /path/to/qwen3-embedding.gguf --embedding --pooling last --host 127.0.0.1 --port 8081
```

Then call commands with:

```bash
--embed-url http://127.0.0.1:8081
```

Initialize and probe the local runtime before running the closed loop:

```bash
uv run python scripts/senior_exam_writer.py init-runtime \
  --db ./exam_evidence.sqlite \
  --embed-url http://127.0.0.1:8081
```

Environment variable alternatives:

```bash
export LLAMA_CPP_EMBED_URL=http://127.0.0.1:8081
export LLAMA_CPP_EMBED_MODEL=local-embedding
```

Only open a firewall port if another machine must connect to this embedding endpoint. For this skill's normal local pipeline, no extra port exposure is needed.

## Endpoint Compatibility

Embedding calls try:

- `/v1/embeddings`
- `/embedding`

Optional local LLM verification still supports `/v1/chat/completions`, then `/completion`, but it is not part of the required runtime.

## Practical Settings

- Increase `--top-k` and `--min-evidence` for high-stakes current-affairs topics.
- `--no-embed` is disabled for evidence-gated workflows. If embeddings fail, stop and fix the local ModelScope/llama.cpp runtime; do not continue with keyword-only retrieval.
- Retrieval uses the local embedding endpoint for query/candidate vectors and compares them with `embedding_json` stored in SQLite. FTS5/BM25 is not used in the evidence path. It does not require a separate vector database or remote embedding provider.
- Historical duplicate review requires local embeddings. `audit-question-similarity` refuses non-loopback `--embed-url` values and fails closed when candidate/final question text is missing.
- For closed-loop review, ingest `historical_exam` and `question_bank` sources with embeddings before approval.
- `generate-candidates`, `plan-evidence`, `retrieve`, `audit-question-similarity`, and `complete-task` reject databases that contain any unembedded chunks.
- The legacy `generate` command still needs a local LLM because that command calls a model itself. Prefer Codex/agent generation from retrieved evidence unless offline local-only generation is explicitly required.

## Official References

- llama.cpp install methods: https://github.com/ggml-org/llama.cpp/blob/master/docs/install.md
- llama.cpp server quick start: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
