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

    def test_devcontainer_forwards_wslg_gui_environment_for_live_preview(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        config = json.loads(
            (repo_root / ".devcontainer" / "devcontainer.json").read_text(
                encoding="utf-8",
            )
        )

        mounts = config["mounts"]
        remote_env = config["remoteEnv"]

        self.assertIn("source=/mnt/wslg,target=/mnt/wslg,type=bind", mounts)
        self.assertIn("source=/tmp/.X11-unix,target=/tmp/.X11-unix,type=bind", mounts)
        self.assertEqual("${localEnv:DISPLAY}", remote_env["DISPLAY"])
        self.assertEqual("${localEnv:WAYLAND_DISPLAY}", remote_env["WAYLAND_DISPLAY"])
        self.assertEqual("${localEnv:XDG_RUNTIME_DIR}", remote_env["XDG_RUNTIME_DIR"])
        self.assertEqual("1", remote_env["MANIM_STUDIO_ALLOW_CONTAINER_LIVE"])
        self.assertEqual("1", remote_env["LIBGL_ALWAYS_SOFTWARE"])

    def test_runtime_installs_opengl_and_x11_libraries_for_live_preview(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        dockerfile = (repo_root / "Dockerfile").read_text(encoding="utf-8")

        for package in (
            "libegl1",
            "libgl1",
            "libgl1-mesa-dri",
            "libglx-mesa0",
            "libxkbcommon-x11-0",
            "mesa-utils",
        ):
            self.assertIn(package, dockerfile)

    def test_runtime_smoke_build_uses_runner_uid_gid(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        workflow = (repo_root / ".github" / "workflows" / "tests.yml").read_text(
            encoding="utf-8",
        )

        self.assertIn('--build-arg USER_UID="$(id -u)"', workflow)
        self.assertIn('--build-arg USER_GID="$(id -g)"', workflow)


if __name__ == "__main__":
    unittest.main()
