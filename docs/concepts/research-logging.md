# Research logging

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

**MCP alone cannot observe external chat.** The optional Codex adapter below receives
client hooks, including planning-only turns that invoke no Manim tool. Other clients
must still submit prompts/responses to the bridge. Never infer prompts from tool arguments.
The [VS Code classification panel](prompt-classification-ui.md) supports retrospective
human annotation and displays existing model suggestions separately. There is no built-in
automatic classification model. The bridge also supports host-generated suggestions.

## Managed research sessions

Explicit lifecycle, topic selection, independent pause/resume, source/client binding,
and the VS Code research controls are documented in [research sessions](research-sessions.md).
The additive v6 schema keeps existing ledger/capture identities, management
state and stable request receipts, and versions annotation events. Native client delivery remains a separate acceptance gate.

The [human time and run metadata panel](research-time.md) adds explicit timers, retrospective reports, versioned corrections and provenance-labelled runtime/model contexts. It never infers human effort from message gaps.

## Automatic Codex capture

The passive adapter uses Codex's documented [hooks](https://developers.openai.com/codex/hooks):
`SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `Stop`, `Interrupt`,
`SessionEnd`, `PreCompact`, and `PostCompact`. It does not create a new chat UI,
call a model, change tool arguments/permissions, or inject text into model context.
Normal hook output is `{}`. Failures warn on stderr and return success so authoring
continues. A failed hook is a collection gap, not evidence that collection succeeded.

From the selected project, run once with the Python interpreter that has Studio:

```bash
python -m manim_studio.research_cli --root /path/to/project codex-connect
```

This explicitly enables local logging and merges this adapter's handlers into
`.codex/hooks.json`, preserving unrelated hooks. Repeating it replaces only this
adapter's marked handlers. The generated configuration uses machine-specific absolute
paths and is gitignored. Existing `.codex/config.toml` is untouched. To inspect
configuration without changing anything, use `codex-config` instead.

Review/trust the hook definitions in Codex (the CLI provides `/hooks`), then start or
resume the conversation. A connected project alone does not prove that the client
delivers hooks: confirm your actual CLI/IDE release by sending a planning-only prompt,
then checking:

```bash
python -m manim_studio.research_cli --root /path/to/project capture-status
```

Status lists observed thread/research-session IDs, last hook time, transcript byte
offset and gap count. No observed threads means capture has not been demonstrated.
Rejected CLI deliveries are persisted as content-free `failures` diagnostics. A
rejection attributable to an observed thread adds a `hook_delivery_rejected` gap
and marks that thread partial. Malformed or unidentifiable deliveries increment
`unassigned_failure_count` without creating a session. Diagnostics contain only
IDs, timestamps, recognized hook names and exception types; rejected message text
is not retained. Paused collection does not retain these diagnostics. If storage
itself fails, stderr reports that persistence was unavailable; status cannot prove
completeness in that case. Project-level diagnostics are available through status,
while attributable gap events also appear in exports.
Only hooks whose `cwd` belongs to this project are accepted. Each Codex thread maps
durably to a separate research session; no global last-prompt context is used.

The supported hook contract provides user prompts, tool calls/results, and the latest
assistant message at `Stop`. Intermediate assistant messages are additionally read
from the explicitly supplied transcript. Its format is **not a stable Codex API**.
The reader supports JSONL `session_meta`, `turn_context`, and `response_item` messages;
it ignores duplicated `event_msg` text, internal reasoning, system/developer content
and unrelated metadata. Non-text assistant content is flagged as unsupported, not
silently converted. It never searches all Codex histories or reads authentication files.

Coverage status is deliberately conservative:

| Status | Meaning |
|---|---|
| `hooks_only` | Hooks observed; intermediate-message coverage is unverified |
| `hooks_and_transcript_best_effort` | Recognized transcript dialect, no detected gaps; not a guarantee of completeness |
| `partial` | A gap, unknown format, missing context or unsupported record was detected |

User prompts retain null classification. A prompt submission is client-reported user
input, not independent proof of human authorship; other Codex hooks can generate
continuation prompts. Model/provider/client information uses an allowlist of supplied
fields; unavailable revision/settings are not guessed. No hidden chain of thought is
collected. Source metadata includes client/thread/turn/item or tool-call identifiers,
source timestamps when available, and transcript byte offsets. Ledger timestamps are
observation times; transcript offsets define source order, not causal relationships.

Tool hooks record their own `action.started`/`action.finished` boundary with snapshots.
The start's prompt association is retained even if the user steers while it runs.
With multiple submissions in a turn, events carry `related_prompt_ids` as turn
membership and leave the causal `prompt_id` null when ambiguous. Missing tool starts
are flagged. This does not retroactively join separate inner service events: if MCP/RPC
instrumentation is also enabled, it may record nested/duplicate work. Use the `source`
field to select a boundary for analysis; do not count both or sum overlapping durations.
Hook durations are observation wall-clock differences, explicitly labeled; they are
neither human active time nor the core service's monotonic execution time.

Events, deduplication receipts and transcript cursors commit in one SQLite transaction.
Incomplete trailing JSON/UTF-8 waits for a newline. Transcript replay and repeated
tool-call IDs do not duplicate messages/actions. Hosts retrying `CodexCapture.handle`
can pass a stable `delivery_id`; native hooks provide no delivery ID, so repeated
identical user submissions are deliberately kept, rather than text-deduplicated.
This cannot distinguish an undocumented duplicate native prompt delivery from a
second genuine identical submission.

`configure` with `{"enabled":false}` pauses collection. On re-enable, the adapter
skips to the transcript's current end and marks the gap, so content produced during
the pause is never backfilled. This can also omit buffered messages around resumption;
that loss is explicit. A first attachment to an existing/resumed conversation likewise
does not import its old history. File replacement/truncation invalidates the cursor
and marks a gap. Full content export includes captured messages/actions; default
metadata export retains source IDs and gap codes but excludes their free text.

Run `PYTHONPATH=src python -m pytest tests/test_research_capture.py tests/test_research.py -q`.
An optional native-client smoke test is in `scripts/test-codex-capture.py`; it supplies
a local fake model, uses only a temporary project, and makes no paid inference calls.
Real interactive VS Code delivery and Windows hook invocation still need validation
on their actual client versions before research collection.

MCP operations and the authoring RPC boundary are instrumented. Direct Python calls
to core builders and ordinary `studio render` CLI commands bypass those boundaries.
When Codex invokes them through a hooked tool, the outer tool call is captured;
manual terminal commands outside that client are not. Direct editor changes appear at the next
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
| `classify` | `{"session_id":"SESSION_ID", "prompt_id":"PROMPT_ID", "source":"human", "prompt_type":"corrective", "reasons":["narrative_order"], "human_seconds":12, "request_id":"UNIQUE_REQUEST_ID", "expected_human_head":null}` |
| `export` | `{"destination":"/path/to/new-metadata.jsonl"}` |
| `export` | `{"destination":"/path/to/new-full.jsonl", "include_content":true}` |
| `configure` | `{"enabled":false}` |

Before a human write, call `classification.get` with session/prompt IDs and copy its
`human_head_event_id` into `expected_human_head` (explicit null for the first write).
Use a new unique `request_id` for each decision; retry the exact same payload with
the same ID after an unknown outcome. Old human writers missing these fields are
rejected rather than silently overwriting a concurrent decision.

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
intent. `classification.skip` records an explicit deferral; it is not an irrelevant
classification. `classification.clear` invalidates the current human classification
without deleting history. The legacy `classify` human call with null type/reasons
also clears, subject to the same versioned-write contract.

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

Each event has schema version (v5 in new session/export records), durable project ID (config/export),
UUID event/session IDs, optional prompt and parent IDs, UTC timestamp, actor, stage,
payload and SQLite sequence number. Sequence defines ledger insertion order; concurrent
operations can overlap. Event types:

| Event | Payload |
|---|---|
| `session.started` | Label, supplied model/run settings, runtime/schema versions |
| `prompt.recorded` | Original prompt, model metadata, null initial classification |
| `model.responded` | Response text and model metadata |
| `classification.suggested` | Model-supplied type/reasons |
| `classification.confirmed` | Versioned human type/reasons and optional self-reported time |
| `classification.skipped` | Explicit deferral without a human classification |
| `classification.cleared` | Invalidates current human classification, preserving history |
| `action.started` | Operation, arguments, before snapshot |
| `action.finished` | Result or exception, elapsed seconds, after snapshot; parent=start ID |
| `capture.gap` | Machine-readable gap code and source context |
| `client.*` | Observed session, turn, interruption and compaction lifecycle |

The v2 adapter adds `capture_threads` (thread mapping/state/cursor),
`capture_receipts` (source deduplication), and `capture_failures` (content-free CLI
rejection diagnostics) tables without rewriting v1 events. Capture
pause epochs live in `config`. Existing v1 sessions remain readable/exportable.

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

Local development validation (2026-10-30): 93 tests passed across research capture,
the existing ledger, MCP services, authoring sessions, CLI and font checks. This includes
34 new capture tests and generated hook execution through a real Python subprocess.
The optional native Codex 0.166.0 smoke test timed out during session initialization,
before the first hook or local fake-model request. Native-client end-to-end capture
has therefore **not** passed validation here; interactive VS Code and Windows delivery
remain unverified. Do not treat fixture/subprocess tests as proof of complete native capture.

Before collecting the 8–10 development workflows, connect and validate the external
host's prompt/response adapter on a complete small workflow, including a planning-only
turn, an edit, a failed render and an actual user classification. Do not label existing
operation traces as complete prompt capture. Adaptive checkpoint policy, measured
quality changes, blinded evaluation and the held-out C/D experiment remain later work.

## Retained research evidence

The [artifacts and decisions panel](research-artifacts.md) archives configured source
snapshots, proposal candidates/baselines and bounded immutable build evidence. It
keeps missing/omitted content and unknown decision origins explicit. Schema v5 adds
backed-up transactional migrations. Read the feature guide for retention quotas,
capture-boundary behavior, commands and the remaining native Windows acceptance gate.
