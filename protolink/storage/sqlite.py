from typing import Any

from protolink.storage.base import Storage


class SQLiteStorage(Storage):
    def __init__(self, db_path: str):
        self.db_path = db_path

    def save(self, data: Any) -> None:
        pass

    def load(self) -> Any:
        pass

    def update(self, data: Any) -> None:
        pass

    def delete(self) -> None:
        pass
