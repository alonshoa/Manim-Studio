# Export PPTX

Export a registered all-slides deck to PowerPoint:

```bash
studio export <deck_id> --format pptx --profile final
```

PPTX is the first supported export format.

## Requirements

Every scene in the deck must use:

```yaml
renderer: manim-slides
```

Decks containing any non-`manim-slides` scene return `unsupported_deck` and list
the incompatible scene targets.

HTML, PDF, ZIP, and other export formats currently return `unsupported`.

## Export Flow

PPTX export:

1. renders each registered Manim Slides scene
2. collects `slides/<ClassName>.json` and `slides/files/<ClassName>/`
3. copies those outputs into an isolated export build
4. runs `manim-slides convert --to=pptx`
5. lists the generated `.pptx` as a `presentation` artifact

The generated file can be discovered with:

```bash
studio inspect <export-build-id>
```

or through the MCP `get_artifacts` tool.

## Compatibility Note

Manim Slides documents PPTX conversion as experimental because playback support
can vary between PowerPoint and LibreOffice versions. PowerPoint or LibreOffice
is not required to generate the file in the runtime container.
