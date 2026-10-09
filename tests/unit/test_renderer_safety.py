"""SSRF guard of the headless renderer: only public http(s) targets may be rendered."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "renderer"))
from url_safety import UnsafeUrlError, check_url, is_public_ip


def fake_dns(mapping: dict[str, list[str]]):
    return lambda host: mapping[host]


@pytest.mark.parametrize(
    "address",
    [
        "169.254.169.254",  # EC2 instance metadata: would leak the instance role's credentials
        "127.0.0.1",
        "10.0.0.201",  # our own n8n host
        "172.16.5.4",
        "192.168.1.1",
        "100.64.0.1",  # carrier-grade NAT
        "::1",
        "fe80::1%eth0",  # IPv6 link-local with zone id
        "fd00::1",  # IPv6 unique-local
        "0.0.0.0",
        "224.0.0.1",  # multicast
    ],
)
def test_non_public_addresses_are_refused(address):
    assert not is_public_ip(address)


def test_public_site_is_allowed():
    url = "https://www.bankbazaar.com/hdfc-personal-loan.html"
    assert check_url(url, fake_dns({"www.bankbazaar.com": ["104.18.1.1"]})) == url


def test_dns_rebinding_style_mixed_answer_is_refused():
    # One public and one private answer: refuse, since the browser could pick either.
    with pytest.raises(UnsafeUrlError, match="non-public"):
        check_url(
            "https://evil.example/",
            fake_dns({"evil.example": ["93.184.216.34", "169.254.169.254"]}),
        )


@pytest.mark.parametrize(
    ("url", "message"),
    [
        ("file:///etc/passwd", "scheme"),
        ("javascript:alert(1)", "scheme"),
        ("ftp://example.com/x", "scheme"),
        ("https:///no-host", "missing host"),
        ("https://user:pw@example.com/", "credentials"),
    ],
)
def test_bad_urls(url, message):
    with pytest.raises(UnsafeUrlError, match=message):
        check_url(url, fake_dns({"example.com": ["93.184.216.34"]}))


def test_unresolvable_host_is_refused():
    def boom(host):
        raise OSError("NXDOMAIN")

    with pytest.raises(UnsafeUrlError, match="cannot resolve"):
        check_url("https://nope.invalid/", boom)
