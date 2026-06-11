"""Serialization utilities for Protolink.

This module provides common serialization and deserialization functions
for Protolink objects.
"""

import json
from datetime import datetime
from typing import Any, TypeVar

from protolink.core.message import Message
from protolink.core.task import Task

T = TypeVar("T")


class Serializer:
    """Serialization helper class for Protolink objects."""

    @staticmethod
    def serialize_to_json(obj: Any, **kwargs) -> str:
        """Serialize an object to JSON string.

        Args:
            obj: Object to serialize
            **kwargs: Additional arguments to pass to json.dumps()

        Returns:
            JSON string representation of the object

        Raises:
            TypeError: If the object is not JSON serializable
        """

        def default_serializer(o):
            if isinstance(o, (Message, Task)):
                return o.to_dict()
            if isinstance(o, datetime):
                return o.isoformat()
            raise TypeError(f"Object of type {type(o).__name__} is not JSON serializable")

        return json.dumps(obj, default=default_serializer, **kwargs)

    @staticmethod
    def deserialize_from_json(json_str: str, target_cls: type[T] | None = None, **kwargs) -> dict[str, Any] | T:
        """Deserialize a JSON string to an object.

        Args:
            json_str: JSON string to deserialize
            target_cls: Optional target class for deserialization
            **kwargs: Additional arguments to pass to json.loads()

        Returns:
            Deserialized object or dictionary if no target class provided

        Raises:
            json.JSONDecodeError: If the string is not valid JSON
            ValueError: If the JSON cannot be deserialized to the target class
        """
        data = json.loads(json_str, **kwargs)

        if target_cls is None:
            return data

        if target_cls == Message:
            return Message.from_dict(data)  # type: ignore[return-value]
        elif target_cls == Task:
            return Task.from_dict(data)  # type: ignore[return-value]
        else:
            raise ValueError(f"Unsupported target class: {target_cls.__name__}")

    @staticmethod
    def serialize_to_dict(obj: Any) -> dict[str, Any] | Any:
        """Serialize an object to a dictionary.

        Args:
            obj: Object to serialize

        Returns:
            Dictionary representation of the object

        Raises:
            TypeError: If the object cannot be converted to a dictionary
        """
        if hasattr(obj, "to_dict"):
            return obj.to_dict()
        elif isinstance(obj, dict):
            return {k: Serializer.serialize_to_dict(v) for k, v in obj.items()}
        elif isinstance(obj, (list, tuple, set)):
            return [Serializer.serialize_to_dict(item) for item in obj]
        elif isinstance(obj, (str, int, float, bool)) or obj is None:
            return obj
        else:
            raise TypeError(f"Cannot serialize object of type {type(obj).__name__}")

    @staticmethod
    def deserialize_from_dict(data: dict, target_cls: type[T] | None = None) -> dict[str, Any] | T:
        """Deserialize a dictionary to an object.

        Args:
            data: Dictionary to deserialize
            target_cls: Optional target class for deserialization

        Returns:
            Deserialized object or dictionary if no target class provided

        Raises:
            ValueError: If the dictionary cannot be deserialized to the target class
        """
        if target_cls is None:
            return data

        if not hasattr(target_cls, "from_dict"):
            raise ValueError(f"Target class {target_cls.__name__} does not support from_dict")

        return target_cls.from_dict(data)  # type: ignore[call-arg]
