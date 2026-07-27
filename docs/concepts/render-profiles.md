# Render Profiles

Render profiles encode the quality and review behavior for a render or deck
build.

## Draft

`draft` is the fast iteration profile. Use it while changing scene logic,
layout, text, or beats.

```bash
studio render examples/square_to_circle --profile draft
```

Draft builds still run preflight validation and write an isolated build
directory with logs, metadata, and collected artifacts.

## Review

`review` is the medium-quality profile for checking layout, pacing, and visual
artifacts.

```bash
studio build examples --profile review
```

Review builds run a draft-quality smoke render before the more expensive
profile render. Preflight failures stop the build unless `--force` is provided.
Smoke render failures always stop review rendering.

When FFmpeg can extract frames from the rendered video, successful review builds
produce representative PNG frames and `review/contact_sheet.png`.

## Final

`final` is the high-quality path for delivery-oriented output.

```bash
studio export <all-slide-deck> --format pptx --profile final
```

Final builds follow the same smoke-render guard as review builds. Use final only
after draft and review passes are clean enough to justify the slower render.

## Force Behavior

`--force` allows render/build/export commands to continue despite preflight
validation failures:

```bash
studio render examples/square_to_circle --profile draft --force
```

It does not bypass review/final smoke render failures.
