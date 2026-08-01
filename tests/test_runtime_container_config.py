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
        self.assertNotIn("features", config)

    def test_dev_stage_installs_contributor_tools_without_features(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        dockerfile = (repo_root / "Dockerfile").read_text(encoding="utf-8")

        self.assertIn("FROM runtime AS dev", dockerfile)
        self.assertIn("git", dockerfile)
        self.assertIn("openssh-client", dockerfile)
        self.assertIn("sudo", dockerfile)
        self.assertIn("/etc/sudoers.d/manimuser", dockerfile)
        self.assertIn("USER manimuser", dockerfile)

    def test_runtime_smoke_build_uses_runner_uid_gid(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        workflow = (repo_root / ".github" / "workflows" / "tests.yml").read_text(
            encoding="utf-8",
        )

        self.assertIn('--build-arg USER_UID="$(id -u)"', workflow)
        self.assertIn('--build-arg USER_GID="$(id -g)"', workflow)

    def test_publish_container_workflow_is_manual_trial_only(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        workflow = (
            repo_root / ".github" / "workflows" / "publish-container.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("INPUT_VERSION: ${{ inputs.version }}", workflow)
        self.assertIn("feature/project-init|project-init", workflow)
        self.assertIn("0.0.1|0.0.2|0.0.3", workflow)
        self.assertIn("packages: write", workflow)
        self.assertIn("docker/login-action", workflow)
        self.assertIn("docker/build-push-action", workflow)
        self.assertIn("target: dev", workflow)
        self.assertIn('docker push "${IMAGE_NAME}:${IMAGE_TAG}"', workflow)
        self.assertNotIn(":latest", workflow)


if __name__ == "__main__":
    unittest.main()
