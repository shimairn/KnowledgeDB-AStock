from __future__ import annotations


class BridgeError(Exception):
    def __init__(self, error_code: str, message: str, *, can_fallback: bool = False) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.can_fallback = can_fallback


class DriverUnavailableError(BridgeError):
    def __init__(self, message: str) -> None:
        super().__init__("CAPTURE_FAILED", message, can_fallback=True)


class KBNotFoundError(BridgeError):
    def __init__(self, message: str) -> None:
        super().__init__("KB_NOT_FOUND", message)


class ConfigMismatchError(BridgeError):
    def __init__(self, message: str) -> None:
        super().__init__("CONFIG_MISMATCH", message)


class LoginRequiredError(BridgeError):
    def __init__(self, message: str) -> None:
        super().__init__("LOGIN_REQUIRED", message)


class AskTimeoutError(BridgeError):
    def __init__(self, message: str) -> None:
        super().__init__("ASK_TIMEOUT", message)


class CaptureFailedError(BridgeError):
    def __init__(self, message: str, *, can_fallback: bool = False) -> None:
        super().__init__("CAPTURE_FAILED", message, can_fallback=can_fallback)
