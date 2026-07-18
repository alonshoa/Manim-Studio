from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class StudioError:
    code: str
    message: str
    detail: Any = None

    def to_json(self) -> dict[str, Any]:
        data = {
            "code": self.code,
            "message": self.message,
        }
        if self.detail is not None:
            data["detail"] = _jsonable(self.detail)
        return data


def success(data: Any, status: str = "success") -> dict[str, Any]:
    return {
        "ok": True,
        "status": status,
        "data": _jsonable(data),
        "error": None,
    }


def failure(
    code: str,
    message: str,
    *,
    status: str = "error",
    data: Any = None,
    detail: Any = None,
) -> dict[str, Any]:
    return {
        "ok": False,
        "status": status,
        "data": _jsonable(data),
        "error": StudioError(code, message, detail).to_json(),
    }


def _jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return value.as_posix()
    if is_dataclass(value) and not isinstance(value, type):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value

