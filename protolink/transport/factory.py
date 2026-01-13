from typing import TYPE_CHECKING

from protolink.transport.base import Transport

if TYPE_CHECKING:
    pass

# Registry stores callables that return the class, or the class itself.
# We store strings or callables to allow lazy loading.
_TRANSPORT_REGISTRY: dict[str, type[Transport] | str] = {
    "http": "protolink.transport.http_transport.HTTPTransport",
    "websocket": "protolink.transport.websocket_transport.WebSocketTransport",
    "runtime": "protolink.transport.runtime_transport.RuntimeTransport",
}


def get_transport(transport: str, **kwargs) -> Transport:
    """Create a transport instance by name.

    Parameters
    ----------
    transport:
        Registered transport name (case-insensitive), e.g. ``"http"`` or ``"websocket"``.
    **kwargs:
        Keyword arguments forwarded to the transport constructor.

    Returns
    -------
    Transport
        Instantiated transport.
    """
    try:
        entry = _TRANSPORT_REGISTRY[transport.lower()]
    except KeyError:
        raise ValueError(f"Unknown transport name: {transport}") from None

    if isinstance(entry, str):
        # Lazy load the module and class
        module_path, class_name = entry.rsplit(".", 1)
        import importlib

        module = importlib.import_module(module_path)
        transport_class = getattr(module, class_name)
        # Cache for next time
        _TRANSPORT_REGISTRY[transport.lower()] = transport_class
    else:
        transport_class = entry

    return transport_class(**kwargs)


def register_transport(name: str, cls: type[Transport] | str) -> None:
    """Register a new transport type.

    Args:
        name: The name to register (case-insensitive).
        cls: The Transport class, or a string 'module.path.ClassName' for lazy loading.
    """
    _TRANSPORT_REGISTRY[name.lower()] = cls
