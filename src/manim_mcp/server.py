from __future__ import annotations

from typing import Literal
from dataclasses import replace
from manim_studio.research_cli import dispatch

from mcp.server.fastmcp import FastMCP

from manim_mcp import services


def create_server(context: services.StudioContext | None = None) -> FastMCP:
    base_ctx = replace(context or services.default_context(), research_decision_origin="automation", research_origin_evidence="mcp_tool_call")
    ctx = base_ctx
    mcp = FastMCP("Manim Studio")

    def research_context(session_id, prompt_id, client_id):
        # Explicit session/client context is a complete request-local override.
        # Never combine a new client with a stale server environment session.
        if session_id is not None or client_id is not None:
            return replace(base_ctx, research_session_id=session_id,
                           research_prompt_id=prompt_id, research_client_id=client_id,
                           research_context_origin='explicit')
        return replace(base_ctx, research_prompt_id=prompt_id if prompt_id is not None
                       else base_ctx.research_prompt_id)

    @mcp.resource("manim-studio://conventions")
    def project_conventions() -> str:
        """Read the project conventions document."""
        return services.response_to_json_text(services.conventions_resource(ctx))

    @mcp.resource("manim-studio://catalog")
    def catalog() -> str:
        """Read registered Manim Studio decks and scenes."""
        return services.response_to_json_text(services.catalog_resource(ctx))

    @mcp.resource("manim-studio://scene/{deck_id}/{scene_id}")
    def scene_context(deck_id: str, scene_id: str) -> str:
        """Read registered scene context and discovered beats."""
        return services.response_to_json_text(
            services.get_scene_context(f"{deck_id}/{scene_id}", ctx)
        )

    @mcp.resource("manim-studio://build/{build_id}/manifest")
    def build_manifest(build_id: str) -> str:
        """Read a build manifest."""
        return services.response_to_json_text(services.get_build_manifest(build_id, ctx))

    @mcp.resource("manim-studio://build/{build_id}/artifacts")
    def build_artifacts(build_id: str) -> str:
        """Read build artifact metadata."""
        return services.response_to_json_text(services.get_artifacts(build_id, ctx))

    @mcp.resource("manim-studio://build/{build_id}/log/{stream}")
    def build_log(build_id: str, stream: Literal["stdout", "stderr"]) -> str:
        """Read a build stdout or stderr log."""
        return services.response_to_json_text(
            services.get_build_log(build_id, stream, ctx)
        )

    @mcp.tool()
    def list_decks(
        research_session_id: str | None = None,
        research_prompt_id: str | None = None,
        research_client_id: str | None = None,
    ) -> dict:
        """List registered decks and scenes."""
        ctx = research_context(research_session_id, research_prompt_id, research_client_id)
        return services.list_decks(ctx)

    @mcp.tool()
    def get_scene_context(
        target: str,
        research_session_id: str | None = None,
        research_prompt_id: str | None = None,
        research_client_id: str | None = None,
    ) -> dict:
        """Read catalog metadata, source text, and beat metadata for a registered scene."""
        ctx = research_context(research_session_id, research_prompt_id, research_client_id)
        return services.get_scene_context(target, ctx)

    @mcp.tool()
    def validate_scene(
        target: str,
        profile: str = "draft",
        research_session_id: str | None = None,
        research_prompt_id: str | None = None,
        research_client_id: str | None = None,
    ) -> dict:
        """Validate a registered scene against a render profile."""
        ctx = research_context(research_session_id, research_prompt_id, research_client_id)
        return services.validate_scene(target, profile, ctx)

    @mcp.tool()
    def render_scene(
        target: str,
        profile: str = "draft",
        force: bool = False,
        research_session_id: str | None = None,
        research_prompt_id: str | None = None,
        research_client_id: str | None = None,
    ) -> dict:
        """Render a registered scene into an isolated build directory."""
        ctx = research_context(research_session_id, research_prompt_id, research_client_id)
        return services.render_scene(target, profile, force, ctx)

    @mcp.tool()
    def render_beat(
        target: str,
        beat_id: str,
        profile: str = "draft",
        force: bool = False,
        research_session_id: str | None = None,
        research_prompt_id: str | None = None,
        research_client_id: str | None = None,
    ) -> dict:
        """Render a named beat for a registered scene."""
        ctx = research_context(research_session_id, research_prompt_id, research_client_id)
        return services.render_beat(target, beat_id, profile, force, ctx)

    @mcp.tool()
    def build_deck(
        deck_id: str,
        profile: str = "review",
        force: bool = False,
        research_session_id: str | None = None,
        research_prompt_id: str | None = None,
        research_client_id: str | None = None,
    ) -> dict:
        """Render every scene in a registered deck serially."""
        ctx = research_context(research_session_id, research_prompt_id, research_client_id)
        return services.build_deck(deck_id, profile, force, ctx)

    @mcp.tool()
    def get_build_log(
        build_id: str,
        stream: Literal["stdout", "stderr"] = "stdout",
        research_session_id: str | None = None,
        research_prompt_id: str | None = None,
        research_client_id: str | None = None,
    ) -> dict:
        """Read stdout or stderr for an isolated build."""
        ctx = research_context(research_session_id, research_prompt_id, research_client_id)
        return services.get_build_log(build_id, stream, ctx)

    @mcp.tool()
    def get_artifacts(
        build_id: str,
        research_session_id: str | None = None,
        research_prompt_id: str | None = None,
        research_client_id: str | None = None,
    ) -> dict:
        """Read artifact metadata for an isolated build."""
        ctx = research_context(research_session_id, research_prompt_id, research_client_id)
        return services.get_artifacts(build_id, ctx)

    @mcp.tool()
    def propose_scene_patch(
        target: str,
        edits: list[dict],
        rationale: str = "",
        research_session_id: str | None = None,
        research_prompt_id: str | None = None,
        research_client_id: str | None = None,
    ) -> dict:
        """Create a staged patch proposal for one registered scene source."""
        ctx = research_context(research_session_id, research_prompt_id, research_client_id)
        return services.propose_scene_patch(target, edits, rationale, ctx)

    @mcp.tool()
    def inspect_scene_patch(
        proposal_id: str,
        research_session_id: str | None = None,
        research_prompt_id: str | None = None,
        research_client_id: str | None = None,
    ) -> dict:
        """Inspect staged patch metadata, diff, validation, and render state."""
        ctx = research_context(research_session_id, research_prompt_id, research_client_id)
        return services.inspect_scene_patch(proposal_id, ctx)

    @mcp.tool()
    def validate_scene_patch(
        proposal_id: str,
        profile: str = "draft",
        research_session_id: str | None = None,
        research_prompt_id: str | None = None,
        research_client_id: str | None = None,
    ) -> dict:
        """Validate a staged patch proposal inside its isolated workspace."""
        ctx = research_context(research_session_id, research_prompt_id, research_client_id)
        return services.validate_scene_patch(proposal_id, profile, ctx)

    @mcp.tool()
    def render_scene_patch(
        proposal_id: str,
        research_session_id: str | None = None,
        research_prompt_id: str | None = None,
        research_client_id: str | None = None,
    ) -> dict:
        """Draft-render a staged patch proposal inside its isolated workspace."""
        ctx = research_context(research_session_id, research_prompt_id, research_client_id)
        return services.render_scene_patch(proposal_id, ctx)

    @mcp.tool()
    def apply_scene_patch(
        proposal_id: str,
        confirm: str = "apply",
        research_session_id: str | None = None,
        research_prompt_id: str | None = None,
        research_client_id: str | None = None,
    ) -> dict:
        """Apply an approved staged patch to the canonical registered scene source."""
        ctx = research_context(research_session_id, research_prompt_id, research_client_id)
        return services.apply_scene_patch(proposal_id, confirm, ctx)

    @mcp.tool()
    def propose_render_debug_patch(
        target: str,
        build_id: str,
        research_session_id: str | None = None,
        research_prompt_id: str | None = None,
        research_client_id: str | None = None,
    ) -> dict:
        """Create a conservative staged patch proposal from a failed render build."""
        ctx = research_context(research_session_id, research_prompt_id, research_client_id)
        return services.propose_render_debug_patch(target, build_id, ctx)

    @mcp.tool()
    def start_movie_session(
        title: str = "Interactive Movie",
        deck_id: str = "interactive",
        scene_id: str | None = None,
        class_name: str | None = None,
        research_session_id: str | None = None,
        research_prompt_id: str | None = None,
        research_client_id: str | None = None,
    ) -> dict:
        """Create a registered empty-slate movie session for live iteration."""
        ctx = research_context(research_session_id, research_prompt_id, research_client_id)
        return services.start_movie_session(title, deck_id, scene_id, class_name, ctx)

    @mcp.tool()
    def get_movie_session(
        session_id: str,
        research_session_id: str | None = None,
        research_prompt_id: str | None = None,
        research_client_id: str | None = None,
    ) -> dict:
        """Inspect accepted steps and live command for a movie session."""
        ctx = research_context(research_session_id, research_prompt_id, research_client_id)
        return services.get_movie_session(session_id, ctx)

    @mcp.tool()
    def list_authoring_sessions(
        research_session_id: str | None = None,
        research_prompt_id: str | None = None,
        research_client_id: str | None = None,
    ) -> dict:
        """List persisted authoring sessions with compact state summaries."""
        ctx = research_context(research_session_id, research_prompt_id, research_client_id)
        return services.list_authoring_sessions(ctx)

    @mcp.tool()
    def get_authoring_session_status(
        session_id: str,
        research_session_id: str | None = None,
        research_prompt_id: str | None = None,
        research_client_id: str | None = None,
    ) -> dict:
        """Read compact authoring-session and live-preview state."""
        ctx = research_context(research_session_id, research_prompt_id, research_client_id)
        return services.get_authoring_session_status(session_id, ctx)

    @mcp.tool()
    def discover_active_proposal(
        session_id: str,
        research_session_id: str | None = None,
        research_prompt_id: str | None = None,
        research_client_id: str | None = None,
    ) -> dict:
        """Discover the newest actionable staged proposal for an authoring session."""
        ctx = research_context(research_session_id, research_prompt_id, research_client_id)
        return services.discover_active_proposal(session_id, ctx)

    @mcp.tool()
    def propose_movie_step(
        session_id: str,
        edits: list[dict],
        rationale: str = "",
        research_session_id: str | None = None,
        research_prompt_id: str | None = None,
        research_client_id: str | None = None,
    ) -> dict:
        """Create a staged addon proposal for a movie session's registered scene."""
        ctx = research_context(research_session_id, research_prompt_id, research_client_id)
        return services.propose_movie_step(session_id, edits, rationale, ctx)

    @mcp.tool()
    def propose_next_movie_step(
        session_id: str,
        body: str,
        title: str = "Next step",
        rationale: str = "",
        research_session_id: str | None = None,
        research_prompt_id: str | None = None,
        research_client_id: str | None = None,
    ) -> dict:
        """Append the next semantic free-form authoring step inside construct()."""
        ctx = research_context(research_session_id, research_prompt_id, research_client_id)
        return services.propose_next_movie_step(session_id, body, title, rationale, ctx)

    @mcp.tool()
    def preview_movie_step(
        session_id: str,
        proposal_id: str,
        research_session_id: str | None = None,
        research_prompt_id: str | None = None,
        research_client_id: str | None = None,
    ) -> dict:
        """Preview a staged movie proposal without changing canonical source."""
        ctx = research_context(research_session_id, research_prompt_id, research_client_id)
        return services.preview_movie_step(session_id, proposal_id, ctx)

    @mcp.tool()
    def accept_movie_step(
        session_id: str,
        proposal_id: str,
        note: str = "",
        confirm: str = "accept",
        research_session_id: str | None = None,
        research_prompt_id: str | None = None,
        research_client_id: str | None = None,
    ) -> dict:
        """Apply an approved staged proposal and append it to the session steps ledger."""
        ctx = research_context(research_session_id, research_prompt_id, research_client_id)
        return services.accept_movie_step(session_id, proposal_id, note, confirm, ctx)

    @mcp.tool()
    def reject_movie_step(
        session_id: str,
        proposal_id: str | None = None,
        research_session_id: str | None = None,
        research_prompt_id: str | None = None,
        research_client_id: str | None = None,
    ) -> dict:
        """Reject the active movie proposal and return live preview to accepted source."""
        ctx = research_context(research_session_id, research_prompt_id, research_client_id)
        return services.reject_movie_step(session_id, proposal_id, ctx)

    @mcp.tool()
    def revise_movie_step(
        session_id: str,
        feedback: str,
        proposal_id: str | None = None,
        research_session_id: str | None = None,
        research_prompt_id: str | None = None,
        research_client_id: str | None = None,
    ) -> dict:
        """Request a distinct revision and expose feedback to authoring context."""
        ctx = research_context(research_session_id, research_prompt_id, research_client_id)
        return services.revise_movie_step(session_id, feedback, proposal_id, ctx)

    @mcp.tool()
    def pause_authoring_session(
        session_id: str,
        proposal_policy: str = "keep",
        research_session_id: str | None = None,
        research_prompt_id: str | None = None,
        research_client_id: str | None = None,
    ) -> dict:
        """Pause an authoring session and optionally keep or reject an active draft."""
        ctx = research_context(research_session_id, research_prompt_id, research_client_id)
        return services.pause_authoring_session(session_id, proposal_policy, ctx)

    @mcp.tool()
    def resume_authoring_session(
        session_id: str,
        research_session_id: str | None = None,
        research_prompt_id: str | None = None,
        research_client_id: str | None = None,
    ) -> dict:
        """Resume a paused authoring session and restore live preview."""
        ctx = research_context(research_session_id, research_prompt_id, research_client_id)
        return services.resume_authoring_session(session_id, ctx)

    @mcp.tool()
    def finish_authoring_session(
        session_id: str,
        research_session_id: str | None = None,
        research_prompt_id: str | None = None,
        research_client_id: str | None = None,
    ) -> dict:
        """Validate and draft-render the accepted canonical session scene."""
        ctx = research_context(research_session_id, research_prompt_id, research_client_id)
        return services.finish_authoring_session(session_id, ctx)

    @mcp.tool()
    def start_authoring_live(
        session_id: str,
        research_session_id: str | None = None,
        research_prompt_id: str | None = None,
        research_client_id: str | None = None,
    ) -> dict:
        """Start local live preview for the authoring session."""
        ctx = research_context(research_session_id, research_prompt_id, research_client_id)
        return services.start_authoring_live(session_id, ctx)

    @mcp.tool()
    def restart_authoring_live(
        session_id: str,
        research_session_id: str | None = None,
        research_prompt_id: str | None = None,
        research_client_id: str | None = None,
    ) -> dict:
        """Restart local live preview for the authoring session."""
        ctx = research_context(research_session_id, research_prompt_id, research_client_id)
        return services.restart_authoring_live(session_id, ctx)

    @mcp.tool()
    def stop_authoring_live(
        session_id: str,
        research_session_id: str | None = None,
        research_prompt_id: str | None = None,
        research_client_id: str | None = None,
    ) -> dict:
        """Stop local live preview for the authoring session."""
        ctx = research_context(research_session_id, research_prompt_id, research_client_id)
        return services.stop_authoring_live(session_id, ctx)

    @mcp.tool()
    def export_deck(
        deck_id: str,
        format: str = "pptx",
        profile: str = "final",
        force: bool = False,
        research_session_id: str | None = None,
        research_prompt_id: str | None = None,
        research_client_id: str | None = None,
    ) -> dict:
        """Export an all-slides deck to a supported delivery format."""
        ctx = research_context(research_session_id, research_prompt_id, research_client_id)
        return services.export_deck(deck_id, format, profile, force, ctx)

    @mcp.tool()
    def research_log(
        action: str,
        payload: dict,
    ) -> dict:
        """Opt-in research bridge. Record host prompts/responses, classify later, or export.

        Call schema for enums, or classification.schema/list/get and artifacts.list/history/policy for the annotation UI contract.
        Human classification.save requires request_id and expected_human_head (null initially).
        This tool does not observe the external chat automatically.
        Use returned session/prompt IDs on subsequent authoring tool calls.
        """
        try:
            return {"ok": True, "data": dispatch(base_ctx.repo_root, action, payload)}
        except (ValueError, TypeError, OSError) as exc:
            return {"ok": False, "error": str(exc)}

    return mcp


def main() -> None:
    create_server().run()


if __name__ == "__main__":
    main()
