from __future__ import annotations

import json
from pathlib import Path
import unittest


class RuntimeContainerConfigTests(unittest.TestCase):
    def test_login_shells_restore_runtime_virtualenv_path(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        dockerfile = (repo_root / "Dockerfile").read_text(encoding="utf-8")

        self.assertIn("/etc/profile.d/manim-studio-path.sh", dockerfile)
        self.assertIn("export VIRTUAL_ENV=/opt/venv", dockerfile)
        self.assertIn(
            'export PATH="/opt/venv/bin:/manim/.local/bin:/home/manimuser/.local/bin:${PATH}"',
            dockerfile,
        )

    def test_devcontainer_post_create_uses_runtime_virtualenv(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        config = json.loads(
            (repo_root / ".devcontainer" / "devcontainer.json").read_text(
                encoding="utf-8",
            )
        )

        post_create = config["postCreateCommand"]

        self.assertIn("/opt/venv/bin/python -m pip install", post_create)
        self.assertIn("/opt/venv/bin/python -m manim_studio.cli doctor", post_create)


if __name__ == "__main__":
    unittest.main()
