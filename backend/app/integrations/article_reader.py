"""Bounded public-page reader. Connections are pinned to validated public IPs."""
import http.client
import ipaddress
import socket
import ssl
import time
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

MAX_BYTES = 2_000_000


def image_url(value, base=""):
    url = urljoin(base, value or "")
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in ("http", "https") or not host or parsed.username or parsed.password:
        return None
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        return None
    try:
        if not ipaddress.ip_address(host).is_global:
            return None
    except ValueError:
        pass
    return url if len(url) <= 4096 else None


class ArticleParser(HTMLParser):
    def __init__(self, base):
        super().__init__(convert_charrefs=True)
        self.base, self.stack = base, []
        self.all_text, self.article_text, self.main_text, self.title = [], [], [], []
        self.meta, self.images = {}, []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta":
            self.meta[(attrs.get("property") or attrs.get("name") or "").lower()] = attrs.get("content", "")
        if tag == "img" and ("article" in self.stack or "main" in self.stack):
            candidate = image_url(attrs.get("src") or attrs.get("data-src"), self.base)
            if candidate:
                self.images.append(candidate)
        if tag not in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in self.stack:
            self.stack = self.stack[:len(self.stack) - 1 - self.stack[::-1].index(tag)]

    def handle_data(self, text):
        text = " ".join(text.split())
        if "title" in self.stack:
            self.title.append(text)
        if not text or any(tag in self.stack for tag in ("script", "style", "noscript", "nav", "header", "footer", "aside", "head", "svg")):
            return
        self.all_text.append(text)
        if "article" in self.stack:
            self.article_text.append(text)
        if "main" in self.stack:
            self.main_text.append(text)

    def result(self):
        candidates = [self.meta.get("og:image"), self.meta.get("twitter:image"), *self.images]
        preview = next((url for candidate in candidates if candidate and (url := image_url(candidate, self.base))), None)
        return {
            "title": (self.meta.get("og:title") or " ".join(self.title))[:500],
            "text": "\n".join(self.article_text or self.main_text or self.all_text)[:16000],
            "description": (self.meta.get("og:description") or self.meta.get("description") or "")[:2000],
            "image_url": preview,
        }


def public_address(url):
    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Unsupported URL")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if port not in (80, 443):
        raise ValueError("Unsupported port")
    addresses = socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
        raise ValueError("Only public websites can be read")
    return parsed, port, addresses[0][4][0]


def read_article(url):
    deadline = time.monotonic() + 15
    for _ in range(4):
        parsed, port, address = public_address(url)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Page read timed out")
        connection = http.client.HTTPConnection(parsed.hostname, port, timeout=min(5, remaining))
        try:
            connection.sock = socket.create_connection((address, port), timeout=min(5, remaining))
            if parsed.scheme == "https":
                connection.sock = ssl.create_default_context().wrap_socket(connection.sock, server_hostname=parsed.hostname)
            path = parsed.path or "/"
            if parsed.query:
                path += "?" + parsed.query
            connection.request("GET", path, headers={"User-Agent": "ReMe/1.0 ArticlePreview", "Accept": "text/html", "Accept-Encoding": "identity"})
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader("Location")
                if not location:
                    raise ValueError("Missing redirect destination")
                url = urljoin(url, location)
                continue
            if response.status != 200:
                raise ValueError("Page unavailable")
            mime = response.getheader("Content-Type", "").lower()
            if "text/html" not in mime and "application/xhtml+xml" not in mime:
                raise ValueError("Not an HTML article")
            content = bytearray()
            while True:
                if time.monotonic() >= deadline:
                    raise TimeoutError("Page read timed out")
                chunk = response.read(min(65536, MAX_BYTES + 1 - len(content)))
                if not chunk:
                    break
                content.extend(chunk)
                if len(content) > MAX_BYTES:
                    raise ValueError("Page is too large")
            charset = response.headers.get_content_charset() or "utf-8"
            parser = ArticleParser(url)
            parser.feed(content.decode(charset, errors="replace"))
            result = parser.result()
            if not result["text"]:
                raise ValueError("No readable article text")
            return result
        finally:
            connection.close()
    raise ValueError("Too many redirects")
