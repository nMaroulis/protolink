"""Network-related utility functions.

This module provides utilities for network operations such as finding available ports,
handling sockets, and other network-related helper functions.
"""

import socket
from collections.abc import Generator
from contextlib import contextmanager


def get_free_port(host: str = "127.0.0.1") -> int:
    """Find a free TCP port on the specified host.

    This function creates a temporary socket, binds it to the specified host with port 0,
    which lets the OS assign an available port, then returns that port number. The socket
    is immediately closed after retrieving the port.

    Args:
        host: The host address to bind to. Defaults to "127.0.0.1" (localhost).

    Returns:
        int: An available port number that can be used for binding.

    Raises:
        OSError: If no available ports can be found or socket operations fail.

    Examples:
        >>> port = get_free_port()
        >>> isinstance(port, int)
        True
        >>> 1024 <= port <= 65535
        True

        >>> custom_port = get_free_port(host="0.0.0.0")
        >>> isinstance(custom_port, int)
        True

    Note:
        The port returned is only guaranteed to be free at the moment of the call.
        In a multi-threaded or multi-process environment, another process could bind
        to this port before the caller does. Always handle potential port conflicts.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        port = s.getsockname()[1]
    return port


@contextmanager
def reserve_port(host: str = "127.0.0.1") -> Generator[int, None, None]:
    """Context manager that reserves a port for the duration of a context.

    This function provides a context manager that keeps a socket bound to a free port,
    preventing other processes from using it. The port is released when the context exits.

    Args:
        host: The host address to bind to. Defaults to "127.0.0.1" (localhost).

    Yields:
        int: The reserved port number.

    Raises:
        OSError: If no available ports can be found or socket operations fail.

    Examples:
        >>> with reserve_port() as port:
        ...     # Port is reserved here, safe to use
        ...     print(f"Using port {port}")
        ... # Port is released here

    Note:
        This is useful when you need to ensure a port remains available while
        setting up a service, but want automatic cleanup if setup fails.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        port = s.getsockname()[1]
        try:
            yield port
        finally:
            # Socket is automatically closed by context manager
            pass


def is_port_available(port: int, host: str = "127.0.0.1") -> bool:
    """Check if a specific port is available for binding.

    This function attempts to bind to the specified port to determine if it's available.
    The socket is immediately closed after the check.

    Args:
        port: The port number to check.
        host: The host address to bind to. Defaults to "127.0.0.1" (localhost).

    Returns:
        bool: True if the port is available, False otherwise.

    Examples:
        >>> port = get_free_port()
        >>> is_port_available(port)
        True

        >>> is_port_available(80)  # System port, likely in use
        False

    Note:
        This check is not atomic - the port could be taken by another process
        between the check and actual use. Always handle potential conflicts.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind((host, port))
        return True
    except OSError:
        return False
