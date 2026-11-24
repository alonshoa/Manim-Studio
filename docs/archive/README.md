# Preserved development and research evidence

The historical TODO snapshots are [todo.md](todo.md) and [feature_todo.md](feature_todo.md).
Current product acceptance is tracked in [#17](https://github.com/alonshoa/Manim-Studio/issues/17),
and practical documentation in [#31](https://github.com/alonshoa/Manim-Studio/issues/31).
Unchecked historical boxes do not establish missing implementation. Automated classification,
research analysis and adaptive checkpoints remain future proposals, not v0.1.0 commitments.

| Paths | Classification and disposition |
| --- | --- |
| `decks/interactive-test/`, `decks/interactive-test1/` | Removed on maintainer request: duplicate red-dot scaling smoke sessions without educational content; source/ledgers remain recoverable from Git history. |
| `decks/interactive-vsc/`, `decks/interactive/` | Removed on maintainer request: two empty scenes and the third identical red-dot scaling session; matching catalog entries removed. |
| `decks/test-movie/` | Incremental axes/sine movie example with accepted-change history; retain. |
| `validation/` | Historical test/browser/package reports; retain unchanged. They are not results for this release revision. |
| `tests/fixtures/`, `baselines/` | Regression fixtures and curated rendering references; retain. |
| `docs/design/` | Research lifecycle design history; retain. |
| `scripts/*demo*`, `scripts/test-*-ui.js` | Reproducible UI demonstrations/checks; retain. |

The initial release review preserved all sessions. In the subsequent PR review, the
maintainer explicitly requested removal of empty and trivial/duplicate development
decks. Five such sessions (ten source/ledger files) and their catalog entries were
removed. Git history, substantive examples, research databases and historical
validation evidence were not rewritten or purged.
No duplicate issues were opened after reviewing the current issue tracker.
