# Research logging (v1)

This is collection infrastructure for the Human-in-the-loop study. It does not
choose adaptive checkpoints, score pedagogical quality, or equate a user's stated
reason with measured improvement. Existing authoring behavior stays unchanged.

## Architecture and coverage

- `manim_studio.research`: standalone SQLite event ledger and bounded source snapshots.
- `manim_mcp.services`: opt-in wrappers around existing service operations. Results,
  failures, build IDs/manifests and run arguments are retained without changing returns.
- `manim_mcp.server`: request-local research IDs on existing tools; `research_log` bridge.
- `AuthoringSessionController.dispatch`: the VS Code JSON-RPC boundary; accepts reserved
  `_research: {session_id, prompt_id}` parameters. Existing request shape still works.
- `studio-research` / `python -m manim_studio.research_cli`: JSON stdin bridge for hosts
  and retrospective labeling. No dialogs, automatic LLM calls or extra dependency.

**External chat is not observable by this server.** The LLM client must submit each
user prompt and model response to the bridge, including planning-only turns that
invoke no Manim tool. Without that host adapter, this is a partial tool-operation
trace, not a complete research conversation. Never infer a prompt from tool arguments.
There is no built-in automatic classification model or VS Code classification UI yet.
Use the bridge for manual labeling or to submit host-generated suggestions.

MCP operations and the authoring RPC boundary are instrumented. Direct Python calls
to core builders and ordinary `studio render` CLI commands bypass those boundaries;
these are not captured automatically. Direct editor changes appear at the next
snapshot boundary, without an inferred edit timestamp or author. A custom catalog
path or source outside the documented snapshot scope needs a later explicit adapter.

## Start and record (JSON payloads)

Run `studio-research --root /path/to/project configure` with stdin:

```json
{"enabled": true}
```

For each command below, pass the JSON object on stdin. The same operation is available
through MCP `research_log(action, payload)`. Return shape is `{ok, data}`; identifiers
are returned in `data`. Keep IDs from the actual response.

| Action | Payload example |
|---|---|
| `start_session` | `{"label":"Vectors", "model":{"provider":"example", "model":"model-name", "version":null}, "run_settings":{"temperature":0.2,"seed":null,"client_version":"example"}}` |
| `record_prompt` | `{"session_id":"SESSION_ID", "text":"Explain the dot product", "stage":"lesson_plan", "model":{"model":"model-name","version":null}}` |
| `record_response` | `{"session_id":"SESSION_ID", "prompt_id":"PROMPT_ID", "text":"Model response", "model":{"model":"model-name","version":null}}` |
| `classify` | `{"session_id":"SESSION_ID", "prompt_id":"PROMPT_ID", "source":"model", "prompt_type":"corrective", "reasons":["narrative_order","unclear_explanation"]}` |
| `classify` | `{"session_id":"SESSION_ID", "prompt_id":"PROMPT_ID", "source":"human", "prompt_type":"corrective", "reasons":["narrative_order"], "human_seconds":12}` |
| `export` | `{"destination":"/path/to/new-metadata.jsonl"}` |
| `export` | `{"destination":"/path/to/new-full.jsonl", "include_content":true}` |
| `configure` | `{"enabled":false}` |

`schema` and `status` take no stdin. Model/provider/revision/settings are supplied by
the host, never guessed. Supply exact available model/deployment versions, generation
parameters, seed, client version and code revision; unavailable values should be null.
Studio and Python versions are recorded at session start. Store no credentials in metadata.

After recording a prompt, include `research_session_id` and `research_prompt_id` on
each subsequent MCP authoring call. Each request has its own immutable context; there
is no shared 'last prompt' that could mix concurrent conversations. For authoring RPC,
pass `_research` on each request. For a dedicated local process, environment variables
`MANIM_STUDIO_RESEARCH_SESSION` and optionally `MANIM_STUDIO_RESEARCH_PROMPT` can supply
fallback IDs. A prompt fallback is fixed for that process: restart/update it per prompt,
or prefer explicit request IDs. A session without a prompt yields an explicitly
unlinked action, never a fabricated association. Unknown/cross-session IDs warn and
skip instrumentation while the normal authoring operation proceeds.

The host must only submit `source: human` after an actual user choice. A model suggestion
is never confirmation. This local API trusts its caller; it cannot authenticate human
intent. Deferring/skipping classification requires no call. A later human classification
with null type/reasons explicitly clears that classification; history remains intact.

## Classification v1

Prompt type is one optional value, separate from the optional list of reasons:

| Code | Meaning |
|---|---|
| `initial` | Initial task / task definition |
| `continuation` | Ordinary continuation |
| `corrective` | Corrective intervention (may have multiple reasons) |
| `irrelevant` | Not relevant to the study |

| Reason code | Meaning |
|---|---|
| `factual_math` | Factual or mathematical error |
| `narrative_order` | Narrative or explanation order |
| `unclear_explanation` | Incomplete or unclear explanation |
| `add_content` | Add content |
| `remove_content` | Remove unnecessary content |
| `visual_animation` | Visual or animation issue |
| `intent_mismatch` | Mismatch with user intent |
| `technical_render` | Technical or render failure |
| `other` | Other; optional `other` text field |

Stages: `task`, `lesson_plan`, `storyboard`, `scene_creation`, `revision`, `validation`,
`render`, `export`, `other`, `unknown`. Prompt stage is host-supplied. Linked actions
inherit it, with render/validation/export operations identified by their operation name.
An unclassified prompt has null classification. Suggested and confirmed classifications
are independent append-only events, including later corrections. Analysis should select
the latest human event per prompt, without promoting a suggestion when no human event exists.
No missing classification means `continuation`.

`human_seconds` is optional, self-reported human time attributed to that prompt. It is
not wall-clock delay, measured improvement, or automatically inferred active work.
Keep labeling overhead separate in analysis. Action durations are monotonic elapsed time;
they may include nested operations and must not be blindly summed.

## Event schema, replay and privacy

SQLite lives at `.manim-studio/research/events.sqlite3` (already gitignored). Logging
is disabled by default. Enabling explicitly opts into local collection of prompt,
response, arguments, results, source text and selected project state. Pause blocks new
content collection; pausing mid-action may leave a start without a finish. A crash or
logging failure may also leave an incomplete action. Instrumentation warnings go to
stderr, never the JSON-RPC stdout protocol. They indicate a collection gap.

Each event has schema version (v1 in session/export), durable project ID (config/export),
UUID event/session IDs, optional prompt and parent IDs, UTC timestamp, actor, stage,
payload and SQLite sequence number. Sequence defines ledger insertion order; concurrent
operations can overlap. Event types:

| Event | Payload |
|---|---|
| `session.started` | Label, supplied model/run settings, runtime/schema versions |
| `prompt.recorded` | Original prompt, model metadata, null initial classification |
| `model.responded` | Response text and model metadata |
| `classification.suggested` | Model-supplied type/reasons |
| `classification.confirmed` | Human-supplied type/reasons and optional self-reported time |
| `action.started` | Operation, arguments, before snapshot |
| `action.finished` | Result or exception, elapsed seconds, after snapshot; parent=start ID |

Actions are system execution events. An operation named `accept` does not establish
that a human made the decision. Prompts/classifications record their declared source;
external human decisions must be supplied by the host rather than inferred.

Snapshots cover `catalog/scenes.yaml`, and `.py`/`.json` files under `scenes`, `decks`,
and `.manim-studio/authoring`. They use relative path → SHA-256 maps and deduplicated
SQLite binary blobs. A full export includes `source.blob` rows with base64 bytes.
Resolve a snapshot's hashes against those rows to reconstruct captured files; compare
path sets for creations/deletions and hashes for edits. This is source-state recovery,
not deterministic re-execution of a stochastic model, complete OS state or video recovery.
Staged workspace files, custom paths, video bytes, arbitrary assets and environment
variables are not swept into storage. Build references/results remain in action records.

Symlinks, files over 1 MB and files exceeding a 10 MB per-snapshot cap are omitted
explicitly. Missing snapshots/logging warnings and unmatched starts are analysis gaps,
not successful completions. Full content remains sensitive: opting in does not redact
secrets in a submitted prompt, response, source or result. Review before sharing.

Default export keeps structural IDs, stages, type/reason codes, timing, operation names
and source hash maps; it excludes free text, model/run settings, arguments, results and
source bytes. Filenames and classification reasons remain and may reveal context.
Full-content export must be explicit. Exports create a new file and never overwrite.
To remove local research data, stop all logging processes and remove only the research
directory; this resets project identity and history. No remote transmission is performed.

## Validation and study boundary

Tests exercise persistence/concurrent writers, invalid/cross-session links, separate
classifications, null values, pause/resume, source recovery/deletion, symlink/size
omissions, metadata export, MCP/RPC request association and fail-open behavior.
Run `PYTHONPATH=src python -m pytest tests/test_research.py -q`.

Before collecting the 8–10 development workflows, connect and validate the external
host's prompt/response adapter on a complete small workflow, including a planning-only
turn, an edit, a failed render and an actual user classification. Do not label existing
operation traces as complete prompt capture. Adaptive checkpoint policy, measured
quality changes, blinded evaluation and the held-out C/D experiment remain later work.
