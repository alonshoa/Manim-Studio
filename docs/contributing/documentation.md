# Documentation

The GitHub Pages site is built with MkDocs and Material for MkDocs.

## Install Docs Dependencies

```bash
python -m pip install -r requirements-docs.txt
```

## Build Locally

```bash
mkdocs build --strict
```

## Serve Locally

```bash
mkdocs serve
```

## Add A Page

1. Add the Markdown file under `docs/`.
2. Add the page to `mkdocs.yml` navigation.
3. Keep command examples aligned with the real `studio` CLI.
4. Run `mkdocs build --strict`.

## GitHub Pages

The Pages workflow builds on pushes and pull requests targeting `main`.
Pull requests build the site but do not deploy it. Pushes to `main` upload and
deploy the generated site through GitHub Pages.

Repository settings must use:

```text
Settings -> Pages -> Source -> GitHub Actions
```

The default public URL is:

```text
https://alonshoa.github.io/Manim-Studio/
```

## Canonical Docs

GitHub Pages is the canonical documentation surface. If GitHub Wiki is enabled,
keep it as a short index that links readers back to the Pages site.
