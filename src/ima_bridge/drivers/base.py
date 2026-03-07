from __future__ import annotations

from abc import ABC, abstractmethod

from ima_bridge.schemas import AskResponse, DriverHealth


class AskDriver(ABC):
    source_driver: str

    @abstractmethod
    def health(self) -> DriverHealth:
        raise NotImplementedError

    @abstractmethod
    def ask(self, question: str) -> AskResponse:
        raise NotImplementedError
