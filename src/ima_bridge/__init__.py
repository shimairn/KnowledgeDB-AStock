from __future__ import annotations

__all__ = ["IMAAskService"]


def __getattr__(name: str):
    if name == "IMAAskService":
        from ima_bridge.service import IMAAskService

        return IMAAskService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(__all__)
