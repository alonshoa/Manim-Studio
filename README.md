Manim Studio

A local, reproducible workspace for building educational presentations, animations, and interactive slide decks with Manim Community and manim-slides.

This project is intended to become the main home for Manim-based presentation work: from individual visual explanations and reusable animation components to complete teaching decks with structured rendering, review artifacts, and future AI-assisted workflows.

Status: early foundation stage.
The repository now includes a scene catalog, a reusable Studio CLI, render
profiles, and isolated build directories for registered pilot scenes.

---

Why this project exists

Manim projects often begin as individual Python files that gradually grow into a collection of scenes, experiments, reusable snippets, assets, and rendering commands.

That works well at first, but becomes difficult to manage when presentations become larger:

- Scenes depend on local environment details, fonts, assets, and rendering flags.
- Long scenes are expensive to re-render after small changes.
- Similar layout, Hebrew/RTL handling, colors, diagrams, and animations are repeatedly reimplemented.
- Render outputs, logs, and exports are mixed together or overwritten.
- It becomes hard to use AI tools safely without giving them uncontrolled access to the project.

Manim Studio is designed to provide structure around that work without replacing the flexibility of normal Manim Python code.

---

Core principles

Python remains the source of truth

Scenes are written as normal Manim code.

Metadata, scene plans, and future YAML specifications are supporting layers for documentation, orchestration, and AI assistance. They do not replace expressive Python animation code.

Build the studio before adding agents

The first goal is a reliable local workflow:

Scene code
   ↓
Validation
   ↓
Draft render
   ↓
Review artifacts
   ↓
Final render and export

Only after this workflow is stable should MCP tools and AI skills be added.

Migrate selectively, not through a rewrite

Existing Manim scenes will be imported gradually as pilot examples.

The project should first prove that it supports real presentation needs:

- Hebrew and RTL text
- "Slide" and "manim-slides"
- complex transforms and layouts
- long scenes with many animation steps
- camera movement, updaters, or 3D scenes where needed

Local-first and reproducible

The primary environment is a local devcontainer running through VS Code, Docker, and WSL where relevant.

The project should be usable without cloud infrastructure, remote workers, or external orchestration services.

Safe AI integration

Future MCP tools should expose structured project operations such as:

- inspect a scene
- validate a scene
- render a draft
- render a selected section
- inspect logs and artifacts
- export a deck

They should not expose unrestricted shell access or allow unvalidated changes directly into working scenes.

---

Main concepts

Deck

A collection of related scenes that form a presentation or teaching unit.

Examples:

- vectors and matrices
- neural networks
- convolution
- model evaluation
- NLP
- dynamic systems

Scene

A normal Manim Python class representing one animation or slide sequence.

A scene may use "Scene", "MovingCameraScene", "ThreeDScene", "Slide", or another suitable Manim base class.

Beat

A named conceptual segment inside a scene.

For slide-based scenes, a beat will usually correspond to a "next_slide()" transition or a logical animation section.

Examples:

intro
show_problem
build_intuition
derive_formula
worked_example
summary

Beats make long scenes easier to review, document, and eventually render selectively.

Build

A single rendering attempt with an isolated output directory.

Each build should preserve:

- the command that was executed
- render profile
- environment information
- stdout and stderr logs
- generated video files
- preview images
- exported artifacts

Artifact

Any output produced by a build.

Examples:

- MP4 video
- PNG preview frames
- contact sheet
- HTML presentation
- PowerPoint export
- render logs
- validation report

Manim Kit

A reusable internal library for common presentation components.

Expected areas include:

- themes and typography
- Hebrew and RTL utilities
- slide layout helpers
- text and explanation panels
- code panels
- axes and graph helpers
- neural-network diagrams
- reusable educational visualizations

---

Planned workflow

Teaching goal or visual idea
        ↓
Scene plan and named beats
        ↓
Manim Python implementation
        ↓
Validation and smoke render
        ↓
Draft render
        ↓
Preview frames / contact sheet / sections
        ↓
Review and targeted fixes
        ↓
Final render
        ↓
HTML / PPTX / video export

---

Planned repository structure

manim-studio/
├─ .devcontainer/           # Reproducible development environment
├─ docs/                    # Architecture, conventions, environment notes
├─ catalog/                 # Deck and scene registry
├─ decks/                   # Presentation content and scenes
│  ├─ vectors/
│  ├─ neural_networks/
│  └─ experiments/
├─ src/
│  ├─ manim_kit/            # Reusable visual and layout components
│  ├─ manim_studio/         # Build, validation, catalog, artifacts
│  └─ manim_mcp/            # Future local MCP server
├─ scripts/                 # CLI entry points and utilities
├─ tests/                   # Validation and regression tests
├─ builds/                  # Local render outputs, ignored by Git
├─ pyproject.toml
└─ README.md

---

Render profiles

The project will support a small number of standard render modes.

Draft

Fast iteration mode for development.

- low resolution
- lower frame rate where appropriate
- preview frames
- section metadata where available

Review

Medium-quality output intended for checking structure, layout, and pacing.

- video output
- contact sheet or representative frames
- logs and validation report
- section-aware artifacts

Final

High-quality render intended for delivery.

- final video output
- HTML presentation export where relevant
- PowerPoint export where relevant
- complete build metadata

---

Initial milestones

1. Reproducible environment

- Define the devcontainer.
- Pin important tool versions.
- Install Manim, "manim-slides", fonts, LaTeX dependencies, and rendering tools.
- Document the known-good local setup.

2. Scene catalog

- Register existing pilot scenes without rewriting them.
- Record source path, class name, deck, renderer, and scene type.
- Select a few representative scenes as regression examples.

3. Studio CLI

Create a single command interface for common operations.

Implemented commands:

studio list
studio validate examples/square_to_circle
studio beats matrix_work/vectors_ab_to_v
studio render examples/square_to_circle --profile draft
studio render matrix_work/vectors_ab_to_v --profile draft --beat resultant
studio build examples --profile review
studio inspect <build-id>

Registered pilot targets include:

- examples/square_to_circle
- examples/basic_slide
- matrix_work/vectors_ab_to_v
- matrix_work/parametric_curve_3d
- losses/binary_cross_entropy

Export commands are planned but not implemented yet.

4. Isolated builds and artifacts

- Generate a unique build directory for every render.
- Preserve logs, commands, artifacts, and metadata.
- Avoid shared output folders and accidental overwrites.

5. Named beats and partial rendering

- Optional named beats are available through `manim_kit.beats.BeatMixin`.
- `studio beats <deck>/<scene>` lists discoverable beat IDs and labels.
- `studio render <deck>/<scene> --beat <beat-id>` uses Manim sections for a
  targeted iteration workflow and records beat metadata with the build.
- Targeted rendering is section-based rather than arbitrary frame slicing; if a
  scene cannot be isolated cleanly, render the full scene with saved sections
  and review the selected section artifact.

6. Reusable presentation kit

- Extract common Hebrew, RTL, layout, typography, and diagram patterns.
- Keep the abstraction lightweight and Python-native.
- Avoid building a rigid Manim DSL.

7. Validation and review workflow

- Check imports, assets, class names, and scene configuration.
- Run smoke renders before expensive final renders.
- Produce review artifacts that make layout and animation issues easier to find.

8. Local MCP integration

Expose structured tools over the existing studio services.

Initial MCP capabilities should include:

list_decks
get_scene_context
validate_scene
render_scene
render_beat
build_deck
get_build_log
get_artifacts
export_deck

---

Non-goals

The project is not intended to become:

- a replacement for Manim itself
- a generic slide editor
- a cloud rendering platform
- a YAML-only animation language
- an uncontrolled autonomous coding agent
- a distributed GPU rendering system in its first stages

The focus is a reliable, maintainable local workflow for serious Manim presentation work.

---

Future direction

Once the build pipeline and local MCP tools are reliable, the project can gain specialized AI-assisted workflows such as:

- Manim render debugging
- Hebrew and RTL presentation review
- scene lifecycle planning
- reusable component extraction
- deck-level orchestration
- visual regression checks
- guided migration of legacy scenes

These capabilities should always operate through explicit project structure, validation, and render artifacts.

---

Starting point

The first implementation goal is intentionally small:

«Create a reproducible devcontainer and a minimal studio CLI that can register, validate, and draft-render a few existing Manim scenes without rewriting them.»

Everything else should build on that foundation.
