# Windows CI encoding regressions — 31 October 2026

The commits adding classification and Windows shortcuts failed native CI despite passing local tests. The artifact-retention commit inherited both failures. Failed runs do not publish a new installable package because packaging depends on both setup and runtime jobs.

## Confirmed failures

- [Setup compatibility, a423ab5](https://github.com/alonshoa/Manim-Studio/actions/runs/41220357435/job/124593434108): Windows PowerShell 5.1 read a BOM-less UTF-8 workspace JSON using its ANSI default. The Hebrew fixture path was corrupted before comparison, producing “Absolute studio path is incorrect”. The generated JSON itself was UTF-8 as intended for VS Code.
- [Runtime, 0bd5529](https://github.com/alonshoa/Manim-Studio/actions/runs/41212510643/job/124570274118): subprocess output from an explicitly UTF-8 child was decoded by the parent with CP1252. Its reader thread raised UnicodeDecodeError and the RPC test received stdout=None. Doctor and the Hebrew/TeX render passed in that run; the test failure correctly prevented package publication.
- [Runtime, 7381abf](https://github.com/alonshoa/Manim-Studio/actions/runs/41209655438/job/124561782763): the same subprocess decoding failure.

## Correction

Generated JSON/TOML reads in the setup tests explicitly select UTF-8. Python JSON protocol tests explicitly decode UTF-8. Both authoring and research RPC entrypoints configure stdin/stdout/stderr as UTF-8 independently of the terminal locale, so the transport contract does not depend on the generated workspace environment.

Regression tests start real child processes with PYTHONIOENCODING=cp1252 and PYTHONUTF8=0, send unescaped Hebrew JSON, and assert exact Hebrew values in authoring and classification results. No errors are replaced or ignored and no Windows test is skipped to hide these failures.

## Verification before push

- 206 local Python tests passed, including the CP1252 regression cases.
- The setup regression suite passed with PowerShell 7 on Linux.
- Windows PowerShell 5.1, native runtime and packaging must pass on the fix commit in GitHub Actions. Local validation is not their substitute.

Local results: validation/windows-ci-encoding-fixes.txt, validation/windows-ci-encoding-fixes.xml and validation/windows-ci-powershell-fixes.txt.
