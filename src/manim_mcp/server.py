from __future__ import annotations

from typing import Literal

from mcp.server.fastmcp import FastMCP

from manim_mcp import services


def create_server(context: services.StudioContext | None = None) -> FastMCP:
    ctx = context or services.default_context()
    mcp = FastMCP("Manim Studio")

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
    def list_decks() -> dict:
        """List registered decks and scenes."""
        return services.list_decks(ctx)

    @mcp.tool()
    def get_scene_context(target: str) -> dict:
        """Read catalog metadata, source text, and beat metadata for a registered scene."""
        return services.get_scene_context(target, ctx)

    @mcp.tool()
    def validate_scene(target: str, profile: str = "draft") -> dict:
        """Validate a registered scene against a render profile."""
        return services.validate_scene(target, profile, ctx)

    @mcp.tool()
    def render_scene(target: str, profile: str = "draft", force: bool = False) -> dict:
        """Render a registered scene into an isolated build directory."""
        return services.render_scene(target, profile, force, ctx)

    @mcp.tool()
    def render_beat(
        target: str,
        beat_id: str,
        profile: str = "draft",
        force: bool = False,
    ) -> dict:
        """Render a named beat for a registered scene."""
        return services.render_beat(target, beat_id, profile, force, ctx)

    @mcp.tool()
    def build_deck(deck_id: str, profile: str = "review", force: bool = False) -> dict:
        """Render every scene in a registered deck serially."""
        return services.build_deck(deck_id, profile, force, ctx)

    @mcp.tool()
    def get_build_log(
        build_id: str,
        stream: Literal["stdout", "stderr"] = "stdout",
    ) -> dict:
        """Read stdout or stderr for an isolated build."""
        return services.get_build_log(build_id, stream, ctx)

    @mcp.tool()
    def get_artifacts(build_id: str) -> dict:
        """Read artifact metadata for an isolated build."""
        return services.get_artifacts(build_id, ctx)

    @mcp.tool()
    def propose_scene_patch(
        target: str,
        edits: list[dict],
        rationale: str = "",
    ) -> dict:
        """Create a staged patch proposal for one registered scene source."""
        return services.propose_scene_patch(target, edits, rationale, ctx)

    @mcp.tool()
    def inspect_scene_patch(proposal_id: str) -> dict:
        """Inspect staged patch metadata, diff, validation, and render state."""
        return services.inspect_scene_patch(proposal_id, ctx)

    @mcp.tool()
    def validate_scene_patch(proposal_id: str, profile: str = "draft") -> dict:
        """Validate a staged patch proposal inside its isolated workspace."""
        return services.validate_scene_patch(proposal_id, profile, ctx)

    @mcp.tool()
    def render_scene_patch(proposal_id: str) -> dict:
        """Draft-render a staged patch proposal inside its isolated workspace."""
        return services.render_scene_patch(proposal_id, ctx)

    @mcp.tool()
    def apply_scene_patch(proposal_id: str, confirm: str = "apply") -> dict:
        """Apply an approved staged patch to the canonical registered scene source."""
        return services.apply_scene_patch(proposal_id, confirm, ctx)

    @mcp.tool()
    def propose_render_debug_patch(target: str, build_id: str) -> dict:
        """Create a conservative staged patch proposal from a failed render build."""
        return services.propose_render_debug_patch(target, build_id, ctx)

    @mcp.tool()
    def export_deck(
        deck_id: str,
        format: str = "pptx",
        profile: str = "final",
        force: bool = False,
    ) -> dict:
        """Export an all-slides deck to a supported delivery format."""
        return services.export_deck(deck_id, format, profile, force, ctx)

    return mcp


def main() -> None:
    create_server().run()


if __name__ == "__main__":
    main()
