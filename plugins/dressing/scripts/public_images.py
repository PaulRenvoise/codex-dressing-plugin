"""Public HTTPS image URLs and bounded downloads with pinned DNS destinations."""
import http.client
import ipaddress
import re
import socket
import ssl
from urllib.parse import urljoin, urlsplit, urlunsplit

from dressing import DressingError

MAX_BYTES = 25 * 1024 * 1024
MAX_REDIRECTS = 3


def public_address(value):
    address = ipaddress.ip_address(value)
    address = address.ipv4_mapped if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped else address
    return address.is_global and not address.is_multicast and not address.is_reserved


def image_target(value):
    if (not isinstance(value, str) or len(value) > 8192 or any(ord(c) < 33 or ord(c) == 127 for c in value)
            or "\\" in value):
        raise DressingError("Use a direct public HTTPS image URL without whitespace or control characters.")
    try:
        url = urlsplit(value)
        host = (url.hostname or "").encode("idna").decode("ascii").lower()
        port = 443 if url.port is None else url.port
        if not 1 <= port <= 65535 or url.scheme != "https" or not host or url.username is not None or url.password is not None or "%" in host:
            raise ValueError()
        try:
            literal = ipaddress.ip_address(host)
        except ValueError:
            if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", host) or "." not in host:
                raise ValueError()
        else:
            if not public_address(str(literal)):
                raise ValueError()
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        if not addresses or any(not public_address(a[4][0]) for a in addresses):
            raise ValueError()
    except (ValueError, UnicodeError, OSError) as error:
        raise DressingError("The image URL must resolve only to public HTTPS addresses; local, private and unavailable hosts are not supported.") from error
    authority = f"[{host}]" if ":" in host else host
    if port != 443:
        authority += f":{port}"
    origin = "https://" + authority
    canonical = urlunsplit(("https", authority, url.path or "/", url.query, ""))
    return canonical, origin, host, port, addresses


def image_origin(value):
    return image_target(value)[1]


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host, port, addresses):
        super().__init__(host, port, timeout=20, context=ssl.create_default_context())
        self.addresses = addresses

    def connect(self):
        # Connect to an already validated address without another DNS lookup.
        last_error = None
        for family, socktype, proto, _, address in self.addresses:
            raw = socket.socket(family, socktype, proto)
            raw.settimeout(self.timeout)
            try:
                raw.connect(address)
                self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
                return
            except OSError as error:
                raw.close()
                last_error = error
        raise last_error or OSError("No usable image address.")


def download_image(value):
    """Download only after selection; validate every redirect and final image."""
    from PIL import Image
    import io
    import warnings
    for hop in range(MAX_REDIRECTS + 1):
        url, _, host, port, addresses = image_target(value)
        parts = urlsplit(url)
        connection = PinnedHTTPSConnection(host, port, addresses)
        try:
            connection.request("GET", urlunsplit(("", "", parts.path, parts.query, "")),
                               headers={"User-Agent": "Dressing", "Accept": "image/*", "Accept-Encoding": "identity"})
            response = connection.getresponse()
            if response.status in {301, 302, 303, 307, 308}:
                location = response.getheader("Location")
                if not location or hop == MAX_REDIRECTS:
                    raise DressingError("The image has too many redirects or no redirect destination.")
                value = urljoin(url, location)
                continue
            if response.status != 200:
                raise DressingError(f"The image server returned HTTP {response.status}.")
            if response.getheader("Content-Encoding", "identity").lower() != "identity":
                raise DressingError("Unsupported image transfer encoding.")
            length = response.getheader("Content-Length")
            if length is not None and int(length) > MAX_BYTES:
                raise DressingError("Image exceeds 25 MiB.")
            data = response.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                raise DressingError("Image exceeds 25 MiB.")
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(data)) as image:
                    if image.format not in {"PNG", "JPEG", "GIF", "WEBP"}:
                        raise DressingError("Use a PNG, JPEG, GIF or WebP image.")
                    image.verify()
            return data
        except (OSError, ValueError, http.client.HTTPException, Image.DecompressionBombWarning, Image.DecompressionBombError) as error:
            raise DressingError("The selected image could not be downloaded or validated: " + str(error)) from error
        finally:
            connection.close()
