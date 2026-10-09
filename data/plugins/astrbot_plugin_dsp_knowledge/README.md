# DSP Shared Vector Knowledge

This AstrBot plugin owns the single `dsp-major-mods` knowledge base used by both Yunqi and Yelin.

## Corpus

Only authoritative surfaces from the six large DSP mods are indexed:

- Fractionate Everything
- Project Genesis
- Project Orbital Ring
- More Mega Structures
- They Come From Void / DSP Battle
- Project Eden

The catalog includes source code, current README and changelog material, manifests, project metadata, and structured gameplay data. Build output, dependencies, binary assets, IDE state, tests, archived changelogs, experiments, and stale planning documents are excluded.

## Retrieval path

AstrBot owns the physical FAISS index and uses the configured `openai_embedding` and `bailian_rerank` providers. Yunqi retrieves it directly. A loopback-only endpoint on `127.0.0.1:8081` returns the same bounded evidence to Yelin's `qqbot_knowledge` plugin; Yelin still uses its own chat model to write the final response.

The endpoint is intentionally not exposed on LAN interfaces:

- `GET /v1/knowledge/dsp/health`
- `POST /v1/knowledge/dsp/search`

Search payloads contain `query` and optional `group_id`. Responses never include absolute source paths.

## Incremental synchronization

The plugin transforms each source file into path-labelled chunks and assigns files to stable per-module shards. It records shard digests and AstrBot document IDs under `data/plugin_data/astrbot_plugin_dsp_knowledge/`.

Synchronization runs at startup and every 600 seconds by default. Unchanged shards make no embedding requests. A changed shard is uploaded before its previous document is deleted; if old-document deletion fails, the replacement is rolled back. The previous complete index therefore remains recoverable after ordinary provider or storage failures.
