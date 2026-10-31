# Research session management

Research sessions are separate from authoring sessions. Research controls collection;
pausing or finishing research does not cancel renders or close a presentation.

## VS Code workflow

1. Use **Manim Studio Research: Start Session**, enter an attempt name and choose
   or enter a topic. If collection is disabled, enable it using the displayed action.
2. Attach the observed Codex conversation. If no source is listed, open the Codex
   conversation in the configured project and use **Attach Conversation** again.
   Send the first research prompt after attachment. No client API is assumed to
   expose the active Codex tab, and old transcript contents are not imported.
3. Use **Open Terminal** to open a terminal bound to this research. A terminal
   for another research keeps its own identity even when the UI selection changes.
4. Use **Pause Session**, **Resume Session**, **Finish Session**, and **Show Status**.
   Closing VS Code is not Finish. Reopening restores the selected research from
   SQLite. A source ending is not the same as research ending.
5. If a management request times out, **Retry Pending Action** sends the exact
   original request ID and parameters. It does not retry creation/render actions.

**Select Session** can also adopt an existing legacy capture. Adoption keeps its
session ID and all historical event IDs. For a new topic, start a new research and
a new Codex conversation. One conversation per research is supported in this version.

The status bar reports lifecycle separately from source coverage. Active does not
prove delivery. Show Status reports last observation times, known gaps, source
connections and actions without verified completion. An unavailable status refresh
is displayed as not current, rather than a green collection state.

## Shared service and transport

Management operations use `research.*` through the authoring RPC transport or the
MCP `research_log` tool. The CLI accepts the same names; JSON is supplied on stdin:

```bash
python -X utf8 -m manim_studio.research_cli --root /path/to/project research.list
```

For `research.list` supply `{}`. To create research, supply the following JSON to
`research.create` after explicitly enabling collection:

```json
{"title":"Vectors attempt 1","topic":"Vectors","request_id":"a-new-stable-uuid"}
```

`research.configure` accepts `{"enabled":true}` or `{"enabled":false}`. Enabling
through this research interface also enables managed source discovery: new sources
wait for explicit attachment. Existing legacy threads are not silently reassigned.

Lifecycle changes require `session_id`, `expected_revision`, and `request_id`.
Reuse the same request ID only for a retry of the identical operation. Changed
parameters with that ID are rejected. Two clients changing the same revision do
not overwrite each other: the second receives `revision_conflict`.

Use `research.sources` to discover source IDs, then `research.attach_source` with
`session_id`, `source_id`, `expected_revision`, and `request_id`. Source binding
defines the coverage start. A new source without binding retains metadata only.

For MCP operations, pass `research_client_id`, or explicit `research_session_id`
and optionally `research_prompt_id`. A client is bound with `research.bind_client`
(`session_id`, `client_id`, `client_type`, `request_id`). Client types are `rpc`,
`mcp`, and `terminal`. Explicit session/client context overrides server environment
context as a whole; it is not mixed with stale environment prompt/session IDs.
In managed mode, inherited environment session IDs without a registered client
are rejected as unbound. This prevents an already-running legacy MCP server from
silently recording a new workflow in an installer-created legacy session.

RPC authoring requests carry the same context in reserved `_research` metadata.
An explicitly empty `_research` is not replaced with inherited environment IDs.
An operation without a known prompt retains a null prompt ID. Invalid/conflicting
research context does not select another research and does not block authoring.

## Persistence and coverage boundaries

Lifecycle, revision and management events commit atomically. Stable request
receipts allow recovery after a committed reply was lost. If the process dies
before commit, that transaction rolls back. Source cursor and source deduplication
continue using the capture adapter's transaction. Committed history is retained.

On pause/resume, source cursors skip the paused interval and old turns cannot
supply a late response to a new prompt. If a boundary skips unread bytes, the
known coverage gap persists after resumption. The implementation favors an explicit
gap over importing content whose collection interval is uncertain.

An in-flight action crossing a boundary keeps its original identity. Its result
is not backfilled and its observation is marked incomplete; it is not labeled a
failed render or automatically executed again. Finished research accepts no new
content, but existing prompts can still be classified through the existing bridge.

Pause excludes paused message/action observations. It does not redact a file's
earlier edits from a fresh snapshot taken during later active work, or redact text
that the user explicitly submits again while active. Snapshot scope and omission
rules remain those of the existing source collector.

Parallel research records are isolated. Concurrent edits of the same project
files are not automatically merged or globally locked; use separate project
folders or worktrees for concurrent writing. Multi-root VS Code workspaces and
multiple Codex conversations within one research are outside this version.

The new schema is additive (v3). Use the updated capture adapter and bridge together;
mixed old/new adapter processes are not a supported managed-collection setup.
No absence-of-gaps status substitutes for comparing against actual source delivery.

See the [validation report](research-session-management-validation-he.md) for what
has been executed and the remaining native-client acceptance gates.
