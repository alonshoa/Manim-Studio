# Configuration

Manim Studio is intentionally light on configuration. The catalog and build
paths default to conventional locations, and both the CLI and MCP server can be
pointed at external projects.

## Catalog Path

Default:

```text
catalog/scenes.yaml
```

CLI commands accept `--catalog` where target-specific catalog access is needed:

```bash
studio list --catalog catalog/scenes.yaml
studio catalog validate --catalog catalog/scenes.yaml
```

The MCP server reads:

```text
MANIM_STUDIO_CATALOG
```

when set. Otherwise it uses `catalog/scenes.yaml`.

## Repository Root

Most CLI commands accept `--repo-root`. When omitted, the current working
directory is used.

The MCP server reads:

```text
MANIM_STUDIO_REPO_ROOT
```

when set. Otherwise it uses the current working directory.

## Builds Root

Default:

```text
builds
```

Render, build, export, and inspect commands accept `--builds-root`:

```bash
studio render examples/square_to_circle --builds-root builds
studio inspect <build-id> --builds-root builds
```

The MCP server reads:

```text
MANIM_STUDIO_BUILDS_ROOT
```

when set. Otherwise it uses `builds`.

## Pinned Runtime Dependencies

The runtime currently pins:

- base image: `manimcommunity/manim:v0.20.1`
- Python package: `manim==0.20.1`
- Python package: `manim-slides==5.6.0`
- Python package: `python-pptx==1.0.2`
- Python package: `PyYAML==6.0.2`
- Python package: `mcp>=1.28,<2`

The image also installs FFmpeg, TeX Live LaTeX/XeLaTeX support, `dvisvgm`,
fontconfig, DejaVu fonts, and Noto fonts.
