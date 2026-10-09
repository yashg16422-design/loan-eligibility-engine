"""SSRF guard for the renderer: only public http(s) URLs may be rendered.

Why it matters: a headless browser on the n8n host can reach things the internet
can't, above all the EC2 instance-metadata endpoint (169.254.169.254), which hands
out the instance role's AWS credentials. Every URL, and every redirect hop, is
resolved and refused if any address is private, loopback, link-local, or reserved.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable, Iterable
from urllib.parse import urlsplit

Resolver = Callable[[str], Iterable[str]]


class UnsafeUrlError(ValueError):
    """The URL must not be fetched by the renderer."""


def resolve_host(host: str) -> list[str]:
    """All IPv4/IPv6 addresses a hostname resolves to."""
    infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    return sorted({info[4][0] for info in infos})


def is_public_ip(address: str) -> bool:
    """True only for globally routable unicast addresses."""
    ip = ipaddress.ip_address(address.split("%", 1)[0])  # strip IPv6 zone id
    return ip.is_global and not ip.is_multicast


def check_url(url: str, resolve: Resolver = resolve_host) -> str:
    """Return the URL if it is safe to render, else raise UnsafeUrlError.

    The resolver is injectable so the rules are unit-testable without DNS.
    """
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise UnsafeUrlError(f"scheme not allowed: {parts.scheme!r}")
    if not parts.hostname:
        raise UnsafeUrlError("missing host")
    if parts.username or parts.password:
        raise UnsafeUrlError("credentials in URL not allowed")
    try:
        addresses = list(resolve(parts.hostname))
    except OSError as err:
        raise UnsafeUrlError(f"cannot resolve {parts.hostname}: {err}") from None
    if not addresses:
        raise UnsafeUrlError(f"no addresses for {parts.hostname}")
    bad = [a for a in addresses if not is_public_ip(a)]
    if bad:
        raise UnsafeUrlError(f"{parts.hostname} resolves to non-public address(es) {bad}")
    return url
