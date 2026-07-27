# Project Model

Manim Studio adds structured project services around normal Manim Python code.
It does not replace Manim with a separate animation language.

## Deck

A deck is a collection of related scenes that form a presentation or teaching
unit. Registered deck IDs currently include `examples`, `matrix_work`, and
`losses`.

Deck targets use only the deck ID:

```bash
studio build examples --profile review
```

## Scene

A scene is a normal Manim Python class registered in the catalog. Scenes may use
`Scene`, `MovingCameraScene`, `ThreeDScene`, `Slide`, or another suitable Manim
base class.

Scene targets use `<deck_id>/<scene_id>`:

```bash
studio render examples/square_to_circle --profile draft
```

## Beat

A beat is an optional named conceptual segment inside a scene. Beats make long
scenes easier to inspect and iterate on.

Slide-based scenes can call:

```python
self.beat("resultant", label="Reveal resultant vector")
```

`studio beats <deck>/<scene>` discovers literal beat calls without rendering the
scene. `studio render <deck>/<scene> --beat <beat-id>` then requests
section-aware output for that beat.

## Build

A build is one isolated rendering, deck build, or export attempt. Scene builds
store metadata such as command arguments, environment details, preflight
results, logs, manifests, beat metadata, and artifacts.

Builds are written under `builds/`, which is local-only and ignored by Git.

## Artifact

An artifact is any output produced by a build, such as:

- MP4 videos
- PNG review frames
- contact sheets
- PPTX files
- logs
- metadata files

Use `studio inspect <build-id>` to list artifacts from a completed build.

## Manim Kit

`manim_kit` is the shared component layer for recurring presentation needs. It
currently includes theme values, Hebrew/RTL helpers, panel helpers, slide base
classes, and beat helpers.

The kit is intentionally small and Python-native. It is not a replacement for
ordinary Manim code.
