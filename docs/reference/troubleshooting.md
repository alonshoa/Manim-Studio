# Troubleshooting

Start with:

```bash
studio doctor
studio doctor --catalog
```

Then inspect the failing build:

```bash
studio inspect <build-id>
```

## `studio` Is Not Found

Install the project in the current Python environment:

```bash
python -m pip install -e ".[dev]"
```

In the runtime container, verify `/opt/venv/bin` is on `PATH`.

## Python Version Is Too Old

Manim Studio requires Python 3.11 or newer. The current Windows host may have an
older interpreter even when the devcontainer/runtime is correct.

Use the devcontainer or runtime image for the supported reproducible path.

## Render Tools Are Missing

`studio doctor` checks Manim, Manim Slides, FFmpeg, LaTeX, XeLaTeX, `dvisvgm`,
and Hebrew-capable fonts.

If one of those checks fails on the host, use the Docker runtime:

```bash
docker build --target runtime -t manim-studio:local .
```

## Hebrew Fonts Are Missing

The runtime installs DejaVu and Noto Hebrew fonts. Verify with:

```bash
studio doctor
```

Scenes should use `hebrew_text` or explicitly select a Hebrew-capable font.

## Catalog Validation Fails

Run:

```bash
studio catalog validate --strict-metadata
```

Check that every entry has a valid `source_path`, `class_name`, `renderer`, and
stable target IDs.

## MCP Hangs Or Emits Unexpected Output

MCP stdio clients must start `manim-mcp` as a non-interactive process. Do not
allocate a TTY:

```bash
docker run --rm -i ...
```

Do not use:

```bash
docker run --rm -it ...
```

On Windows, prefer the devcontainer/runtime container or WSL Linux paths when
renders are expected.

## PPTX Export Is Unsupported

PPTX export requires every scene in the deck to use:

```yaml
renderer: manim-slides
```

Mixed decks return `unsupported_deck`. HTML, PDF, ZIP, and other formats
currently return `unsupported`.
