# llama.cpp Local Model Setup

The script is designed for local llama.cpp servers and uses OpenAI-compatible endpoints when available.

## Recommended Two-Server Setup

Run an embedding server:

```bash
llama-server -m /path/to/embedding-model.gguf --embedding --host 127.0.0.1 --port 8081
```

Run a generation server:

```bash
llama-server -m /path/to/instruct-model.gguf --host 127.0.0.1 --port 8080 -c 8192
```

Then call the script with:

```bash
--embed-url http://127.0.0.1:8081 --llm-url http://127.0.0.1:8080
```

Environment variable alternatives:

```bash
export LLAMA_CPP_EMBED_URL=http://127.0.0.1:8081
export LLAMA_CPP_LLM_URL=http://127.0.0.1:8080
export LLAMA_CPP_EMBED_MODEL=local-embedding
export LLAMA_CPP_LLM_MODEL=local-instruct
```

## Endpoint Compatibility

The script tries:

- embeddings: `/v1/embeddings`, then `/embedding`;
- chat generation: `/v1/chat/completions`, then `/completion`.

Use an embedding model suitable for Chinese semantic retrieval, for example a BGE, GTE, Qwen embedding, or other Chinese-capable GGUF embedding model. Use an instruction model with enough context length for the retrieved evidence and requested question count.

## Practical Settings

- Keep `--count` small when context length is limited.
- Increase `--top-k` and `--min-evidence` for high-stakes current-affairs topics.
- Use `--no-embed` only for fast indexing tests; semantic retrieval quality will drop.
- Keep temperature low for exam generation: the script defaults to `0.2`.
