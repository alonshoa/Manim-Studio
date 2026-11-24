"""Bounded file reads anchored to the project, including Windows reparse checks."""

from __future__ import annotations

import os
import stat
from pathlib import Path, PurePosixPath

EXCLUDED = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".codex",
}
SECRET_NAMES = {
    ".env",
    "credentials",
    "credentials.json",
    "secrets.json",
    "id_rsa",
    "id_ed25519",
}
TEXT_TYPES = {".py", ".json", ".md", ".yaml", ".yml"}


def relative_path(value, allow_archive=False):
    if (
        not isinstance(value, str)
        or not value
        or "\\" in value
        or ":" in value
        or "\0" in value
    ):
        raise ValueError("unsafe_path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(p in ("..", ".") for p in value.split("/")):
        raise ValueError("unsafe_path")
    parts = path.parts
    if any(
        p.lower() in EXCLUDED
        or p.lower() in SECRET_NAMES
        or p.lower().startswith(".env.")
        for p in parts
    ):
        raise ValueError("excluded_path")
    if (
        not allow_archive
        and len(parts) > 1
        and parts[:2] == (".manim-studio", "research")
    ):
        raise ValueError("excluded_path")
    return path.as_posix()


def _reparse(info):
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & 0x400
    )


def open_project_file(root, relative, internal=False):
    """Return a regular file fd. POSIX uses dirfd; Windows checks the opened handle."""
    relative = relative_path(relative, allow_archive=internal)
    root = Path(root).absolute()
    if os.name != "nt":
        directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            parts = relative.split("/")
            for part in parts[:-1]:
                child = os.open(
                    part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory
                )
                os.close(directory)
                directory = child
            fd = os.open(
                parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
            )
        finally:
            os.close(directory)
    else:
        import ctypes
        import msvcrt
        from ctypes import wintypes

        current = root
        for part in relative.split("/"):
            current = current / part
            if _reparse(current.lstat()):
                raise ValueError("unsafe_path")
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateFileW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.c_void_p,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.GetFinalPathNameByHandleW.argtypes = [
            wintypes.HANDLE,
            wintypes.LPWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
        ]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.CreateFileW(
            str(current), 0x80000000, 7, None, 3, 0x00200000, None
        )
        if handle == wintypes.HANDLE(-1).value:
            raise OSError(ctypes.get_last_error(), "Cannot open project file")
        try:

            class AttributeTag(ctypes.Structure):
                _fields_ = [("attributes", wintypes.DWORD), ("tag", wintypes.DWORD)]

            tag = AttributeTag()
            kernel.GetFileInformationByHandleEx.argtypes = [
                wintypes.HANDLE,
                ctypes.c_int,
                ctypes.c_void_p,
                wintypes.DWORD,
            ]
            if (
                not kernel.GetFileInformationByHandleEx(
                    handle, 9, ctypes.byref(tag), ctypes.sizeof(tag)
                )
                or tag.attributes & 0x400
            ):
                raise ValueError("unsafe_path")
            buffer = ctypes.create_unicode_buffer(32768)
            size = kernel.GetFinalPathNameByHandleW(handle, buffer, len(buffer), 0)
            if not size or size >= len(buffer):
                raise ValueError("unsafe_path")
            final = buffer.value.removeprefix("\\\\?\\")
            if Path(final).resolve() != current or not Path(final).is_relative_to(root):
                raise ValueError("unsafe_path")
            fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
            handle = None
        finally:
            if handle is not None:
                kernel.CloseHandle(handle)
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise ValueError("not_regular_file")
    return fd


def read_project_file(root, relative, limit, internal=False):
    fd = open_project_file(root, relative, internal=internal)
    try:
        before = os.fstat(fd)
        if before.st_size > limit:
            raise ValueError("too_large")
        chunks, total = [], 0
        while True:
            chunk = os.read(fd, min(65536, limit + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > limit:
                raise ValueError("too_large")
        after = os.fstat(fd)
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError("file_changed")
        return b"".join(chunks)
    finally:
        os.close(fd)


def candidates(root, extras=(), max_files=500):
    """No glob follows links, and discovery itself is bounded."""
    root = Path(root)
    found, omitted = set(), []
    with os.scandir(root) as entries:
        for index, entry in enumerate(entries):
            if index >= 5000:
                omitted.append({"path": "*", "reason": "discovery_limit"})
                break
            path = Path(entry.name)
            if (
                path.name.startswith(("lesson-plan", "storyboard"))
                and path.suffix == ".md"
            ):
                if len(found) >= max_files:
                    omitted.append({"path": "*", "reason": "discovery_limit"})
                    break
                found.add(path.name)
    for name in ("catalog/scenes.yaml",):
        if (root / name).exists():
            found.add(name)
    directories = [
        ("scenes", {".py", ".json"}),
        ("decks", {".py", ".json"}),
        (".manim-studio/authoring", {".py", ".json"}),
    ]
    for extra in extras:
        extra = relative_path(extra)
        path = root / extra
        if path.suffix.lower() in TEXT_TYPES:
            found.add(extra)
        else:
            directories.append((extra, TEXT_TYPES))
    visited = 0
    for directory, suffixes in directories:
        pending = [root / directory]
        while pending:
            base = pending.pop()
            try:
                ancestor = base
                unsafe = False
                while ancestor != root:
                    if _reparse(ancestor.lstat()):
                        unsafe = True
                        break
                    ancestor = ancestor.parent
                if unsafe:
                    omitted.append(
                        {
                            "path": base.relative_to(root).as_posix(),
                            "reason": "unsafe_path",
                        }
                    )
                    continue
                with os.scandir(base) as stream:
                    for entry in stream:
                        visited += 1
                        if visited > 5000 or len(found) >= max_files:
                            return sorted(found)[:max_files], omitted + [
                                {"path": "*", "reason": "discovery_limit"}
                            ]
                        relative = Path(entry.path).relative_to(root).as_posix()
                        try:
                            relative_path(relative)
                        except ValueError:
                            continue
                        if _reparse(entry.stat(follow_symlinks=False)):
                            omitted.append({"path": relative, "reason": "unsafe_path"})
                        elif entry.is_dir(follow_symlinks=False):
                            pending.append(Path(entry.path))
                        elif Path(entry.name).suffix.lower() in suffixes:
                            found.add(relative)
            except FileNotFoundError:
                continue
    return sorted(found)[:max_files], omitted
