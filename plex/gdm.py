import asyncio
import logging
import socket
from typing import Any

from typing_extensions import override

from settings import settings
from utils import PlexDeviceLike

logger = logging.getLogger(__name__)

GDM_MULTICAST_ADDR = "239.0.0.250"
GDM_MULTICAST_PORT = 32413
GDM_PORT = 32412


def get_protocol(gdm: "PlexGDM") -> type[asyncio.DatagramProtocol]:

    class ClientProtocol(asyncio.DatagramProtocol):

        def __init__(self) -> None:
            self.transport: asyncio.DatagramTransport | None = None
            gdm.protocol = self
            self.is_connected = False

        @override
        def connection_made(self, transport: asyncio.BaseTransport) -> None:
            assert isinstance(transport, asyncio.DatagramTransport)
            self.transport = transport
            self.is_connected = True
            self.transport.sendto(f"HELLO * HTTP/1.0\n{gdm.client_data}".encode('utf8'),
                                  (GDM_MULTICAST_ADDR, GDM_MULTICAST_PORT))

        @override
        def datagram_received(self, data: bytes, addr: tuple[str | Any, int]) -> None:
            if data.decode("utf8").startswith("M-SEARCH * HTTP/1."):
                if addr[0] == "127.0.0.1":
                    return
                if self.transport is None:
                    return
                try:
                    msg = f"HTTP/1.0 200 OK\n{gdm.client_data}"
                    self.transport.sendto(msg.encode('utf8'), addr)
                except Exception as e:
                    logger.warning("unable to send client message: %s", e)

        @override
        def error_received(self, exc: Exception) -> None:
            logger.error("Error received: %s", exc)

        @override
        def connection_lost(self, exc: Exception | None) -> None:
            logger.warning("Socket closed, stop the event loop")
            self.is_connected = False
            self.transport = None

    return ClientProtocol


class PlexGDM:

    def __init__(self, device: PlexDeviceLike) -> None:
        self.server_port = settings.http_port
        self.socket: socket.socket | None = None
        self.protocol: asyncio.DatagramProtocol | None = None
        self.device = device

    @property
    def client_data(self) -> str:
        data = {
            "Name": self.device.name,
            "Port": str(self.server_port),
            "Content-Type": "plex/media-player",
            "Product": self.device.model,
            "Protocol": "plex",
            "Protocol-Version": "1",
            "Protocol-Capabilities": "timeline,playback,playqueues",
            "Version": settings.platform_version,
            "Resource-Identifier": self.device.uuid,
            "Device-Class": "stb"
        }
        client_data = ""
        for key, value in data.items():
            client_data += "%s: %s\n" % (key, value)
        return client_data

    def init_socket(self) -> None:
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        try:
            try:
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except Exception as e:
                logger.warning("socket reuse failed: %s", e)

            self.socket.bind(("", GDM_PORT))
            self.socket.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 255)
            self.socket.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, socket.inet_aton(GDM_MULTICAST_ADDR) +
                                   socket.inet_aton('0.0.0.0'))
            self.socket.setblocking(False)
        except Exception:
            if self.socket:
                try:
                    self.socket.close()
                except Exception as e:
                    logger.debug("Expected cleanup error closing socket: %s", e)
                self.socket = None
            raise

    def run(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        self.init_socket()
        if loop is None:
            loop = asyncio.get_running_loop()
        asyncio.create_task(loop.create_datagram_endpoint(get_protocol(self), sock=self.socket))

    def stop(self) -> None:
        transport = getattr(self.protocol, "transport", None)
        if transport is not None:
            try:
                transport.close()
            except Exception as e:
                logger.debug("Expected cleanup error closing transport: %s", e)
        if self.socket:
            try:
                self.socket.close()
            except Exception as e:
                logger.debug("Expected cleanup error closing socket: %s", e)
            self.socket = None
        self.protocol = None
