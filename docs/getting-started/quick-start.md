# Quick Start

Use this path to verify the project, inspect registered scenes, render one
scene, and inspect the generated build.

## Check The Environment

```bash
studio doctor
studio doctor --catalog
```

If `studio` is not available in your shell, install the project first:

```bash
python -m pip install -e ".[dev]"
```

## Inspect Registered Content

List registered decks and scenes:

```bash
studio list
```

Current deck IDs include:

- `examples`
- `matrix_work`
- `losses`

Check one registered target:

```bash
studio validate examples/square_to_circle
```

Validate the whole catalog:

```bash
studio catalog validate
```

## Render A Scene

Render the minimal Manim scene with the fast draft profile:

```bash
studio render examples/square_to_circle --profile draft
```

The command prints a build ID and a path under `builds/`. Keep the build ID for
inspection.

## Inspect A Build

```bash
studio inspect <build-id>
```

Build inspection shows status, target, profile, preflight result, smoke render
result when present, logs, artifacts, and discovered beat metadata.

## Render A Named Beat

List beats for a registered scene:

```bash
studio beats matrix_work/vectors_ab_to_v
```

Render one beat:

```bash
studio render matrix_work/vectors_ab_to_v --profile draft --beat resultant
```

Named beat rendering is section-aware. If a beat depends on earlier scene state,
render the full scene and review the selected section artifact.

## Build And Export

Build a deck with review artifacts:

```bash
studio build examples --profile review
```

Export an all-slides deck to PowerPoint:

```bash
studio export <all-slide-deck> --format pptx --profile final
```

PPTX export currently requires every scene in the deck to use
`renderer: manim-slides`.
