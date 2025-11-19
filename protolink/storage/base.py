from abc import ABC, abstractmethod
from typing import Any


class Storage(ABC):
    @abstractmethod
    def save(self, data: Any) -> None:
        pass

    @abstractmethod
    def load(self) -> Any:
        pass

    @abstractmethod
    def update(self, data: Any) -> None:
        pass

    @abstractmethod
    def delete(self) -> None:
        pass
