import asyncio
import sys
from unittest.mock import MagicMock

import pytest

# Purge any leftover stub modules from earlier test files (e.g. test_adapter_*).
for _key in list(sys.modules):
    if not (
        _key in ("dlna", "dlna.discover", "plex", "plex.gdm", "settings", "utils")
        or _key.startswith(("utils.", "settings."))
    ):
        continue
    _mod = sys.modules[_key]
    if isinstance(_mod, MagicMock) or (
        hasattr(_mod, "__file__") and _mod.__file__ and "<stub" in str(_mod.__file__)
    ):
        del sys.modules[_key]

from dlna.discover import DlnaDiscover, get_protocol as get_dlna_protocol
from plex.gdm import GDM_MULTICAST_ADDR, GDM_MULTICAST_PORT, PlexGDM, get_protocol as get_gdm_protocol


class _DuckTypedUDPTransport:
    """Mimics uvloop.loop.UDPTransport, which does NOT subclass asyncio.DatagramTransport."""

    def __init__(self) -> None:
        self.sent: list[tuple[bytes, tuple[str, int]]] = []

    def sendto(self, data: bytes, addr: tuple[str, int]) -> None:
        self.sent.append((data, addr))


@pytest.mark.asyncio
async def test_dlna_discover_connection_made_accepts_duck_typed_udp_transport():
    discover = MagicMock(spec=DlnaDiscover)
    protocol_cls = get_dlna_protocol(discover)
    protocol = protocol_cls()
    transport = _DuckTypedUDPTransport()

    assert not isinstance(transport, asyncio.DatagramTransport)
    protocol.connection_made(transport)  # type: ignore[arg-type]

    assert protocol.transport is transport
    assert protocol.is_connected is True
    # Clean up the background send_loop task spawned by connection_made.
    protocol.is_connected = False
    await asyncio.sleep(0)


def test_plex_gdm_connection_made_accepts_duck_typed_udp_transport():
    device = MagicMock()
    device.uuid = "test-uuid"
    device.model = "TestModel"
    device.name = "TestPlayer"
    gdm = PlexGDM(device)
    protocol_cls = get_gdm_protocol(gdm)
    protocol = protocol_cls()
    transport = _DuckTypedUDPTransport()

    assert not isinstance(transport, asyncio.DatagramTransport)
    protocol.connection_made(transport)  # type: ignore[arg-type]

    assert protocol.transport is transport
    assert protocol.is_connected is True
    assert len(transport.sent) == 1
    payload, addr = transport.sent[0]
    assert addr == (GDM_MULTICAST_ADDR, GDM_MULTICAST_PORT)
    assert payload.startswith(b"HELLO * HTTP/1.0\n")
