# Render A Scene

Render one registered scene with:

```bash
studio render <deck_id>/<scene_id> --profile draft
```

Example:

```bash
studio render examples/square_to_circle --profile draft
```

## Before Rendering

Check the catalog and target:

```bash
studio catalog validate
studio validate examples/square_to_circle
```

Check render prerequisites:

```bash
studio doctor
```

## Profiles

Use `draft` for fast iteration:

```bash
studio render examples/square_to_circle --profile draft
```

Use `review` when layout and pacing need review artifacts:

```bash
studio render examples/square_to_circle --profile review
```

Use `final` only for delivery-oriented output:

```bash
studio render examples/square_to_circle --profile final
```

## Output

Every render writes an isolated build under `builds/`. The command prints:

- build status
- build ID
- build path

Inspect the result:

```bash
studio inspect <build-id>
```

Scene builds include compatibility files `result.json` and `artifacts.json`,
plus a canonical `manifest.json` with preflight issues, command context, smoke
render status, logs, override flags, beat metadata, and artifact paths.

## Forcing A Render

Use `--force` only when you intentionally want to run despite preflight issues:

```bash
studio render examples/square_to_circle --profile draft --force
```

Smoke render failures still block review/final rendering.
