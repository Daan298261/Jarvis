"""RFC-0207 slice 3: static string, network endpoint (§7) and key-material (§8) scanning.

Sources, all read without executing target code:

* DEX string-ID tables of every ``classes*.dex`` in every APK part;
* decoded resources: apktool ``res/values*/*.xml``, ``res/xml*/*.xml``, ``res/raw*`` and ``assets/``
  text, or, for parts apktool did not decode, the ``resources.arsc`` global string pool and binary
  XML decoded by the host AXML decoder;
* the decoded ``AndroidManifest.xml`` (meta-data values, intent-filter deep links);
* string literals and call sites in jadx-recovered ``.java`` sources.

The scanner is bounded (16 MiB per text file, 256 MiB per DEX, 2 GiB in total) and records every
gap it leaves as an explicit unknown instead of failing silently.
"""
from __future__ import annotations

import hashlib
import ipaddress
import math
import re
import struct
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Iterator
from xml.sax.saxutils import unescape

from .apk_sidecar import _axml_strings, decode_axml

MAX_TEXT_FILE_BYTES = 16 * 1024 * 1024
MAX_DEX_BYTES = 256 * 1024 * 1024
MAX_SCAN_BYTES = 2 * 1024 * 1024 * 1024
MAX_DEX_STRINGS = 5_000_000
MAX_FRAGMENT_CHARS = 64 * 1024
MAX_REFERENCES = 10
MAX_STRINGS_DOC = 50_000
MAX_STRING_DOC_CHARS = 2048
ENDPOINT_CATEGORIES = ("url", "websocket", "custom_scheme", "cloud_service", "ipv4", "ipv6")
SEVERITY_ORDER = {"critical": 0, "high": 1, "warning": 2, "info": 3}
TEXT_SUFFIXES = {".json", ".xml", ".txt", ".properties", ".js", ".mjs", ".html", ".htm", ".cfg", ".conf",
                 ".ini", ".yml", ".yaml", ".pem", ".crt", ".cer", ".key", ".config", ".plist", ".csv",
                 ".toml", ".env", ".graphql", ".proto"}
_DEX_NAME = re.compile(r"classes\d*\.dex")
_AXML_MAGIC = b"\x03\x00\x08\x00"
_XML_ENTITIES = {"&quot;": '"', "&apos;": "'"}


# --- Source enumeration ------------------------------------------------------------------

@dataclass
class Source:
    """One scanned document: ``lines`` holds (line number or None, text) fragments.

    ``atomic`` sources (DEX and resources.arsc pools) hold one standalone string per fragment.
    """
    kind: str
    ref: str
    lines: list[tuple[int | None, str]]
    atomic: bool = False


@dataclass
class ScanStats:
    sources: dict[str, int] = field(default_factory=lambda: {k: 0 for k in ("dex", "resource", "manifest", "java", "asset")})
    dex_strings: int = 0
    bytes_scanned: int = 0
    truncated: bool = False
    oversized: list[str] = field(default_factory=list)
    unknowns: list[str] = field(default_factory=list)
    java_sources: bool = False
    decoded_resources: bool = False

    def admit(self, size: int) -> bool:
        if self.bytes_scanned + size > MAX_SCAN_BYTES:
            if not self.truncated:
                self.truncated = True
                self.unknowns.append(f"Static string scan stopped at its {MAX_SCAN_BYTES // 2**30} GiB budget; "
                                     "later sources were not scanned.")
            return False
        self.bytes_scanned += size
        return True

    def finish(self) -> list[str]:
        out = list(self.unknowns)
        if self.oversized:
            shown = ", ".join(self.oversized[:10]) + (" ..." if len(self.oversized) > 10 else "")
            out.append(f"{len(self.oversized)} source file(s) exceeded the per-file scan cap and were not scanned: {shown}")
        return list(dict.fromkeys(out))

    def coverage(self) -> dict:
        return {"sources": dict(self.sources), "dex_strings": self.dex_strings, "bytes_scanned": self.bytes_scanned,
                "java_sources": self.java_sources, "decoded_resources": self.decoded_resources,
                "truncated": self.truncated, "oversized_files": len(self.oversized)}


def _mutf8(raw: bytes) -> str:
    """Decode DEX Modified UTF-8 (encoded NUL, CESU-style surrogate pairs)."""
    raw = raw.replace(b"\xc0\x80", b"\x00")
    try:
        return raw.decode("utf-8", errors="surrogatepass").encode("utf-16", "surrogatepass").decode("utf-16")
    except UnicodeError:
        return raw.decode("utf-8", errors="replace")


def dex_strings(buf: bytes) -> list[str]:
    """Return every entry of a DEX file's string_ids table (header fields at 0x38/0x3C)."""
    if len(buf) < 0x70 or buf[:4] != b"dex\n" or buf[7] != 0:
        raise ValueError("not a DEX file")
    count, ids_off = struct.unpack_from("<II", buf, 0x38)
    if count > MAX_DEX_STRINGS:
        raise ValueError(f"string_ids_size {count} exceeds the {MAX_DEX_STRINGS} cap")
    if count and (ids_off < 0x70 or ids_off + 4 * count > len(buf)):
        raise ValueError("string_ids table lies outside the file")
    out = []
    for i in range(count):
        p = struct.unpack_from("<I", buf, ids_off + 4 * i)[0]
        shift = 0
        while True:  # uleb128 utf16_size; only its length matters here
            if p >= len(buf) or shift > 28:
                raise ValueError(f"string_data_item {i} is truncated")
            byte = buf[p]
            p += 1
            if byte < 0x80:
                break
            shift += 7
        end = buf.find(b"\x00", p)
        if end < 0:
            raise ValueError(f"string_data_item {i} is not terminated")
        out.append(_mutf8(buf[p:end]))
    return out


def arsc_strings(buf: bytes) -> list[str]:
    """Return the global value string pool of a compiled resources.arsc table."""
    try:
        ctype, header = struct.unpack_from("<HH", buf, 0)
        if ctype != 0x0002 or header < 12:
            raise ValueError("not a resource table")
        if struct.unpack_from("<H", buf, header)[0] != 0x0001:
            raise ValueError("resource table has no leading string pool")
        return _axml_strings(buf, header)
    except (struct.error, IndexError) as exc:
        raise ValueError("malformed resource table string pool") from exc


def _is_text(data: bytes) -> bool:
    return b"\x00" not in data[:8192]


def _lines(text: str, xml: bool) -> list[tuple[int | None, str]]:
    out = []
    for number, line in enumerate(text.splitlines(), 1):
        if xml:
            line = unescape(line, _XML_ENTITIES)
        out.append((number, line[:MAX_FRAGMENT_CHARS]))
    return out


def _xml_text(data: bytes) -> str:
    if data[:4] == _AXML_MAGIC:
        return decode_axml(data)
    return data.decode("utf-8", errors="replace")


def _file_source(path: Path, kind: str, ref: str, stats: ScanStats, sniff: bool = False) -> Source | None:
    if not path.is_file():
        return None
    size = path.stat().st_size
    if size > MAX_TEXT_FILE_BYTES:
        stats.oversized.append(ref)
        return None
    if not stats.admit(size):
        return None
    data = path.read_bytes()
    if sniff and not _is_text(data):
        return None
    try:
        text = _xml_text(data) if path.suffix.lower() == ".xml" else data.decode("utf-8", errors="replace")
    except ValueError as exc:
        stats.unknowns.append(f"{ref}: binary XML could not be decoded ({exc}); not scanned.")
        return None
    stats.sources[kind] += 1
    return Source(kind, ref, _lines(text, path.suffix.lower() == ".xml"))


def _decoded_files(apktool: Path) -> list[tuple[Path, str, bool]]:
    """(path, kind, sniff) for the decoded resource and asset files worth scanning."""
    files: list[tuple[Path, str, bool]] = []
    res = apktool / "res"
    if res.is_dir():
        files += [(p, "resource", False) for p in sorted(res.glob("values*/*.xml")) if p.name != "public.xml"]
        files += [(p, "resource", False) for p in sorted(res.glob("xml*/*.xml"))]
        files += [(p, "asset", True) for p in sorted(res.glob("raw*/*")) if p.is_file()]
    assets = apktool / "assets"
    if assets.is_dir():
        files += [(p, "asset", True) for p in sorted(assets.rglob("*"))
                  if p.is_file() and p.suffix.lower() in TEXT_SUFFIXES]
    return files


def _zip_sources(part: dict, resources_decoded: bool, want_manifest: bool, stats: ScanStats) -> Iterator[Source]:
    name = part["name"]
    try:
        archive = zipfile.ZipFile(part["path"])
    except (OSError, zipfile.BadZipFile):
        stats.unknowns.append(f"APK part {name} could not be opened for string scanning.")
        return
    with archive as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            entry = info.filename.replace("\\", "/")
            ref = f"{name}!{entry}"
            if _DEX_NAME.fullmatch(entry):
                if info.file_size > MAX_DEX_BYTES:
                    stats.oversized.append(ref)
                    continue
                if not stats.admit(info.file_size):
                    return
                data = z.read(info)
                try:
                    strings = dex_strings(data)
                except ValueError as exc:
                    strings = [m.decode("ascii") for m in re.findall(rb"[\x20-\x7e]{6,}", data)]
                    stats.unknowns.append(f"{ref}: DEX string table could not be parsed ({exc}); "
                                          "printable byte runs were scanned instead.")
                stats.sources["dex"] += 1
                stats.dex_strings += len(strings)
                yield Source("dex", ref, [(None, s[:MAX_FRAGMENT_CHARS]) for s in strings], atomic=True)
                continue
            if entry == "AndroidManifest.xml":
                if want_manifest and stats.admit(info.file_size):
                    try:
                        text = _xml_text(z.read(info))
                    except ValueError as exc:
                        stats.unknowns.append(f"{ref}: binary manifest could not be decoded ({exc}); "
                                              "manifest strings were not scanned.")
                        continue
                    stats.sources["manifest"] += 1
                    yield Source("manifest", "AndroidManifest.xml", _lines(text, True))
                continue
            if resources_decoded and (entry == "resources.arsc" or entry.startswith(("res/", "assets/"))):
                continue  # apktool's decoded copy of this part was scanned instead
            if info.file_size > MAX_TEXT_FILE_BYTES and entry != "resources.arsc":
                if entry.startswith(("res/", "assets/")):
                    stats.oversized.append(ref)
                continue
            if entry == "resources.arsc":
                if info.file_size > MAX_DEX_BYTES:
                    stats.oversized.append(ref)
                    continue
                if not stats.admit(info.file_size):
                    return
                try:
                    strings = arsc_strings(z.read(info))
                except ValueError as exc:
                    stats.unknowns.append(f"{ref}: resource string pool could not be parsed ({exc}); not scanned.")
                    continue
                stats.sources["resource"] += 1
                yield Source("resource", ref, [(None, s[:MAX_FRAGMENT_CHARS]) for s in strings], atomic=True)
            elif re.fullmatch(r"res/(?:values[^/]*|xml[^/]*)/[^/]+\.xml", entry):
                if not stats.admit(info.file_size):
                    return
                try:
                    text = _xml_text(z.read(info))
                except ValueError as exc:
                    stats.unknowns.append(f"{ref}: binary XML could not be decoded ({exc}); not scanned.")
                    continue
                stats.sources["resource"] += 1
                yield Source("resource", ref, _lines(text, True))
            elif entry.startswith(("res/raw", "assets/")):
                suffix = Path(entry).suffix.lower()
                if suffix and suffix not in TEXT_SUFFIXES:
                    continue
                if not stats.admit(info.file_size):
                    return
                data = z.read(info)
                if not _is_text(data):
                    continue
                stats.sources["asset"] += 1
                yield Source("asset", ref, _lines(data.decode("utf-8", errors="replace"), suffix == ".xml"))


def iter_sources(apk_root: Path, parts: list[dict], stats: ScanStats) -> Iterator[Source]:
    """Yield every scannable document of an APK investigation, decoded layers first."""
    apktool = apk_root / "apktool"
    decoded = (apktool / "res").is_dir() and not (apktool / ".incomplete").exists()
    stats.decoded_resources = decoded
    manifest_done = False
    for candidate in (apktool / "AndroidManifest.xml", apk_root / "metadata" / "AndroidManifest.decoded.xml"):
        src = _file_source(candidate, "manifest", "AndroidManifest.xml", stats)
        if src is not None:
            manifest_done = True
            yield src
            break
    if decoded:
        for path, kind, sniff in _decoded_files(apktool):
            src = _file_source(path, kind, path.relative_to(apktool).as_posix(), stats, sniff=sniff)
            if src is not None:
                yield src
    sources_dir = apk_root / "jadx" / "sources"
    if sources_dir.is_dir():
        for path in sorted(sources_dir.rglob("*.java")):
            src = _file_source(path, "java", "sources/" + path.relative_to(sources_dir).as_posix(), stats)
            if src is not None:
                stats.java_sources = True
                yield src
    for part in parts:
        base = part.get("role") == "base"
        yield from _zip_sources(part, decoded and base, base and not manifest_done, stats)


def _ref(src: Source, line: int | None) -> str:
    return src.ref if line is None else f"{src.ref}:{line}"


_JAVA_LITERAL = re.compile(r'"((?:[^"\\\n]|\\.)*)"')
_XML_STRING_VALUE = re.compile(r"<string\b[^>]*>([^<]+)</string>")


def _fragments(src: Source) -> Iterator[tuple[int | None, str]]:
    """Text to search for endpoints: whole lines, or only string literals for Java code."""
    if src.kind != "java":
        yield from src.lines
        return
    for line, text in src.lines:
        if '"' in text:
            for m in _JAVA_LITERAL.finditer(text):
                yield line, m.group(1).replace("\\/", "/")


def _strings_of(src: Source) -> Iterator[str]:
    """Standalone string values for strings.json."""
    if src.atomic:
        for _, text in src.lines:
            yield text
    elif src.kind == "java":
        for _, text in _fragments(src):
            yield text
    elif src.kind == "resource":
        for _, text in src.lines:
            for m in _XML_STRING_VALUE.finditer(text):
                yield m.group(1)


# --- Aggregation ---------------------------------------------------------------------------

class _Aggregate:
    def __init__(self) -> None:
        self.items: dict[tuple, dict] = {}

    def add(self, key: tuple, base: dict, ref: str, kind: str) -> dict:
        rec = self.items.get(key)
        if rec is None:
            rec = self.items[key] = {**base, "occurrences": 0, "references": [], "sources": set()}
        rec["occurrences"] += 1
        rec["sources"].add(kind)
        if ref not in rec["references"] and len(rec["references"]) < MAX_REFERENCES:
            rec["references"].append(ref)
        return rec

    def records(self) -> list[dict]:
        return [{**r, "sources": sorted(r["sources"])} for r in self.items.values()]


# --- Endpoints (§7) --------------------------------------------------------------------------

_URL = re.compile(r"https?://[a-zA-Z0-9][-a-zA-Z0-9@:%._+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b[-a-zA-Z0-9()@:%_+.~#?&/=]*", re.I)
_WEBSOCKET = re.compile(r"wss?://[a-zA-Z0-9._-]+(?::[0-9]+)?(?:/[^\s\"'<>`\\]*)?", re.I)
_SCHEME = re.compile(r"(?<![A-Za-z0-9+.\-])([a-zA-Z][a-zA-Z0-9+.\-]+)://[^\"'\s<>`\\]+")
_IPV4 = re.compile(r"(?<![0-9A-Za-z.])(?:\d{1,3}\.){3}\d{1,3}(?![0-9A-Za-z]|\.\d)")
_IPV6 = re.compile(r"(?<![0-9A-Za-z:.])[0-9A-Fa-f:]{3,39}(?![0-9A-Za-z:.])")
_CLOUD_SUFFIXES = {
    "amazonaws.com": "aws", "firebaseio.com": "firebase", "firebaseapp.com": "firebase",
    "firebasestorage.app": "firebase", "web.app": "firebase", "supabase.co": "supabase", "supabase.in": "supabase",
    "azurewebsites.net": "azure", "blob.core.windows.net": "azure", "table.core.windows.net": "azure",
    "queue.core.windows.net": "azure", "file.core.windows.net": "azure", "database.windows.net": "azure",
    "servicebus.windows.net": "azure", "vault.azure.net": "azure", "azure-api.net": "azure",
    "azureedge.net": "azure", "azurefd.net": "azure", "cloudapp.azure.com": "azure", "cloudapp.net": "azure",
    "azure-devices.net": "azure", "googleapis.com": "google_cloud", "appspot.com": "google_cloud",
    "cloudfunctions.net": "google_cloud", "run.app": "google_cloud",
}
_CLOUD = re.compile(
    r"(?<![A-Za-z0-9.\-])((?:[A-Za-z0-9](?:[A-Za-z0-9\-]{0,61}[A-Za-z0-9])?\.)+(?:"
    + "|".join(re.escape(s) for s in sorted(_CLOUD_SUFFIXES, key=len, reverse=True))
    + r"))(?![A-Za-z0-9\-]|\.[A-Za-z0-9])", re.I)
XML_NAMESPACE_HOSTS = {"schemas.android.com", "www.w3.org", "w3.org", "schemas.xmlsoap.org", "xmlpull.org",
                       "www.xmlpull.org", "ns.adobe.com", "xml.org", "xml.apache.org"}
EXCLUDED_SCHEME_PREFIXES = ("android-resource://", "file://", "content://android.")
_NETWORK_SCHEMES = {"http", "https", "ws", "wss"}


def _trim(value: str) -> str:
    while True:
        trimmed = value.rstrip(".,;:!?'\"]}>*")
        if trimmed.endswith(")") and trimmed.count(")") > trimmed.count("("):
            trimmed = trimmed[:-1]
        if trimmed == value:
            return value
        value = trimmed


def _host(url: str) -> str:
    rest = url.split("://", 1)[1]
    host = re.split(r"[/?#]", rest, maxsplit=1)[0].rsplit("@", 1)[-1]
    if host.startswith("["):
        return host[1:].split("]", 1)[0].lower()
    return host.split(":", 1)[0].lower()


def _ip_filter(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str | None:
    if ip.is_loopback:
        return "loopback"
    if ip.is_unspecified:
        return "unspecified"
    if ip.version == 4 and int(ip) == 0xFFFFFFFF:
        return "broadcast"
    if ip.is_link_local:
        return "link_local"
    if ip.version == 4 and ip in ipaddress.IPv4Network("240.0.0.0/4"):
        return "reserved_netmask"
    return None


def _ip_scope(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str:
    if ip.is_multicast:
        return "multicast"
    if ip.is_private:
        return "private"
    if ip.is_reserved:
        return "reserved"
    return "public"


def _plausible_ipv6(text: str) -> bool:
    groups = text.split(":")
    filled = [g for g in groups if g]
    if len(filled) < 2 or max(len(g) for g in filled) < 3:
        return False
    return "::" in text or len(groups) == 8


class EndpointScanner:
    def __init__(self) -> None:
        self.found = _Aggregate()
        self.filtered: dict[str, int] = {}

    def _drop(self, reason: str) -> None:
        self.filtered[reason] = self.filtered.get(reason, 0) + 1

    def _add(self, category: str, value: str, ref: str, kind: str, **extra) -> dict:
        return self.found.add((category, value), {"endpoint": value, "category": category, **extra}, ref, kind)

    def scan(self, text: str, ref: str, kind: str) -> None:
        if "." not in text and ":" not in text:
            return
        if "://" in text:
            for m in _URL.finditer(text):
                url = _trim(m.group(0))
                host = _host(url)
                if host in XML_NAMESPACE_HOSTS or "apache.org/xml" in url.lower():
                    self._drop("xml_namespace")
                    continue
                self._add("url", url, ref, kind, url=url, scheme=url.split("://", 1)[0].lower(), host=host)
            for m in _WEBSOCKET.finditer(text):
                url = _trim(m.group(0))
                if "." not in _host(url) and ":" not in _host(url) and _host(url) != "localhost":
                    continue
                self._add("websocket", url, ref, kind, url=url, host=_host(url))
            for m in _SCHEME.finditer(text):
                scheme = m.group(1).lower()
                if scheme in _NETWORK_SCHEMES:
                    continue
                value = _trim(m.group(0))
                if value.lower().startswith(EXCLUDED_SCHEME_PREFIXES):
                    self._drop("platform_scheme")
                    continue
                if len(value) <= len(scheme) + 3:
                    continue
                self._add("custom_scheme", value, ref, kind, url=value, scheme=scheme)
        for m in _CLOUD.finditer(text):
            host = m.group(1).lower()
            suffix = next(s for s in sorted(_CLOUD_SUFFIXES, key=len, reverse=True) if host.endswith("." + s))
            self._add("cloud_service", host, ref, kind, provider=_CLOUD_SUFFIXES[suffix], suffix=suffix)
        if "." in text:
            for m in _IPV4.finditer(text):
                try:
                    ip = ipaddress.IPv4Address(m.group(0))
                except ValueError:
                    continue
                reason = _ip_filter(ip)
                if reason:
                    self._drop(reason)
                    continue
                self._add("ipv4", str(ip), ref, kind, scope=_ip_scope(ip))
        if "::" in text or text.count(":") >= 7:
            for m in _IPV6.finditer(text):
                if not _plausible_ipv6(m.group(0)):
                    continue
                try:
                    ip = ipaddress.IPv6Address(m.group(0))
                except ValueError:
                    continue
                reason = _ip_filter(ip)
                if reason:
                    self._drop(reason)
                    continue
                self._add("ipv6", ip.compressed, ref, kind, scope=_ip_scope(ip))

    def add_deep_links(self, components: dict | None) -> None:
        """Intent-filter <data> elements combine per filter: every scheme with every host."""
        for comp in (components or {}).get("components", []):
            ref = f"AndroidManifest.xml ({comp.get('name')})"
            for flt in comp.get("intent_filters", []):
                data = flt.get("data", [])
                schemes = sorted({d["scheme"] for d in data if d.get("scheme")})
                hosts = sorted({d["host"] for d in data if d.get("host")}) or [""]
                paths = sorted({d.get("path") or d.get("pathPrefix") or d.get("pathPattern") or "" for d in data}) or [""]
                for scheme in schemes:
                    for host in hosts:
                        for path in paths:
                            value = f"{scheme}://{host}{path if not path or path.startswith('/') else '/' + path}"
                            lower = scheme.lower()
                            if lower in {"http", "https"}:
                                if host:
                                    self._add("url", value, ref, "manifest", url=value, scheme=lower,
                                              host=host.lower(), deep_link=True, component=comp.get("name"))
                            elif value.lower().startswith(EXCLUDED_SCHEME_PREFIXES):
                                self._drop("platform_scheme")
                            else:
                                self._add("custom_scheme", value, ref, "manifest", url=value, scheme=lower,
                                          deep_link=True, component=comp.get("name"))

    def records(self) -> list[dict]:
        order = {c: i for i, c in enumerate(ENDPOINT_CATEGORIES)}
        return sorted(self.found.records(), key=lambda r: (order[r["category"]], -r["occurrences"], r["endpoint"]))


def extract_endpoints(apk_root: Path, parts: list[dict], components: dict | None) -> dict:
    """Scan every source and return the endpoints document plus the strings inventory."""
    stats = ScanStats()
    scanner = EndpointScanner()
    strings: dict[str, None] = {}
    total_strings = 0
    strings_truncated = False
    for src in iter_sources(apk_root, parts, stats):
        for line, text in _fragments(src):
            scanner.scan(text, _ref(src, line), src.kind)
        for value in _strings_of(src):
            total_strings += 1
            if len(strings) < MAX_STRINGS_DOC:
                strings.setdefault(value[:MAX_STRING_DOC_CHARS], None)
            elif value[:MAX_STRING_DOC_CHARS] not in strings:
                strings_truncated = True
    scanner.add_deep_links(components)
    records = scanner.records()
    counts = {c: sum(1 for r in records if r["category"] == c) for c in ENDPOINT_CATEGORIES}
    cloud: dict[str, list[str]] = {}
    for r in records:
        if r["category"] == "cloud_service":
            cloud.setdefault(r["provider"], []).append(r["endpoint"])
    limitations = ["Static extraction only; no endpoint was contacted or resolved.",
                   "Strings assembled at runtime (concatenation, encryption, obfuscation) are not recovered.",
                   "Occurrences count each scanned layer separately: a literal in both a DEX pool and "
                   "recovered Java counts twice."]
    if not stats.java_sources:
        limitations.append("Decompiled Java sources were not present; references point at DEX string pools. "
                           "Run apk_decompile for line-level Java references.")
    if not stats.decoded_resources:
        limitations.append("apktool resources were not present; resource strings come from resources.arsc and "
                           "host-decoded binary XML.")
    return {
        "endpoints": records, "counts": counts, "endpoint_count": len(records),
        "cloud_services": {k: sorted(v) for k, v in sorted(cloud.items())},
        "filtered": dict(sorted(scanner.filtered.items())), "coverage": stats.coverage(),
        "unknowns": stats.finish(), "limitations": limitations,
        "strings": {"total_strings": total_strings, "unique_strings_stored": len(strings),
                    "truncated": strings_truncated, "max_stored": MAX_STRINGS_DOC,
                    "max_chars": MAX_STRING_DOC_CHARS, "strings": list(strings)},
    }


# --- Cryptographic and key-material hints (§8) ----------------------------------------------

RULES = {
    "private_key_pem": ("hardcoded_secret", "critical", "Embedded private key (PEM block)"),
    "aws_access_key_id": ("hardcoded_secret", "critical", "AWS access key ID"),
    "aws_temporary_access_key_id": ("hardcoded_secret", "high", "AWS temporary (STS) access key ID"),
    "generic_secret": ("hardcoded_secret", "high", "Hardcoded API key or secret assignment"),
    "google_api_key": ("hardcoded_secret", "warning", "Google API key"),
    "firebase_database_url": ("hardcoded_secret", "info", "Firebase Realtime Database URL"),
    "ecb_mode": ("insecure_crypto", "high", "Block cipher in ECB mode"),
    "weak_cipher": ("insecure_crypto", "high", "Broken or legacy cipher"),
    "rsa_no_padding": ("insecure_crypto", "high", "RSA without padding"),
    "static_key": ("insecure_crypto", "high", "Symmetric key built from a literal"),
    "static_iv": ("insecure_crypto", "warning", "Hardcoded initialisation vector"),
    "weak_hash": ("insecure_crypto", "warning", "MD5/SHA-1 MessageDigest"),
    "nsc_user_trust_anchor": ("network_security", "high", "User-installed CAs trusted"),
    "nsc_debug_user_trust_anchor": ("network_security", "info", "User CAs trusted in debug-overrides"),
    "nsc_override_pins": ("network_security", "warning", "Trust anchor overrides certificate pins"),
    "nsc_cleartext_permitted": ("network_security", "warning", "Cleartext HTTP permitted"),
    "nsc_certificate_pinning": ("network_security", "info", "Certificate pinning configured"),
    "nsc_pin_set_expired": ("network_security", "warning", "Certificate pin-set expired"),
    "default_user_trust": ("network_security", "warning", "User CAs trusted by platform default"),
    "default_cleartext": ("network_security", "warning", "Cleartext HTTP permitted by platform default"),
    "manifest_cleartext": ("network_security", "warning", "Cleartext HTTP permitted by the manifest"),
    "software_only_keys": ("key_storage", "warning", "Software-only key material"),
}

_PEM = re.compile(r"-----BEGIN ((?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?)PRIVATE KEY-----")
_GOOGLE_KEY = re.compile(r"(?<![0-9A-Za-z_\-])AIza[0-9A-Za-z_\-]{35}(?![0-9A-Za-z_\-])")
_AWS_KEY = re.compile(r"(?<![A-Z0-9])(AKIA|ASIA)[0-9A-Z]{16}(?![A-Z0-9])")
_FIREBASE_URL = re.compile(r"https://[a-z0-9\-]+\.firebaseio\.com", re.I)
_SECRET_NAME = r"[A-Za-z0-9_.]*?(?:api_?key|secret_?key|client_?secret|auth_?token|access_?token)"
_GENERIC_ASSIGN = re.compile(r"(?i)(?<![A-Za-z0-9])(" + _SECRET_NAME + r")[\"']?\s*[:=]\s*[\"']([A-Za-z0-9_\-]{24,})[\"']")
_XML_SECRET = re.compile(r"(?i)<string\s+name=\"([^\"]*(?:api_?key|secret|token)[^\"]*)\"[^>]*>([A-Za-z0-9_\-]{24,})</string>")
_META_SECRET = re.compile(r"(?i)android:name=\"([^\"]*(?:api[_.]?key|secret|token)[^\"]*)\"[^>]*?android:value=\"([A-Za-z0-9_\-]{24,})\"")
_CIPHER = re.compile(r"Cipher\.getInstance\(\s*\"([^\"]+)\"")
_TRANSFORM = re.compile(r"(AES|DES|DESede|TripleDES|3DES|Blowfish|RC2|RC4|ARCFOUR|RSA)(?:/([A-Za-z0-9]+)/([A-Za-z0-9]+))?", re.I)
_STATIC_IV = re.compile(r"new\s+IvParameterSpec\(\s*(?:(new\s+byte\s*\[\s*\]\s*\{[^}]*\}?)|new\s+byte\s*\[\s*(\d+)\s*\]\s*\)"
                        r"|\"((?:[^\"\\]|\\.)*)\"\s*\.getBytes\()")
_STATIC_KEY = re.compile(r"(?:new\s+)?SecretKeySpec\(\s*(?:(new\s+byte\s*\[\s*\]\s*\{[^}]*\}?)|\"((?:[^\"\\]|\\.)*)\"\s*\.getBytes\("
                         r"|Base64\.decode\(\s*\"((?:[^\"\\]|\\.)*)\")")
_WEAK_HASH = re.compile(r"MessageDigest\.getInstance\(\s*\"(MD5|MD2|MD4|SHA-?1|SHA)\"", re.I)
_SENSITIVE = re.compile(r"(?i)passw|passwd|\bpwd\b|\bpin\b|credential|signature|\bsign\(|\bverify\(|\bauth")
_HASH_WINDOW = 20

KEY_STORAGE_JAVA = {
    "android_keystore": re.compile(r"\"AndroidKeyStore\""),
    "strongbox": re.compile(r"setIsStrongBoxBacked\(\s*true\s*\)"),
    "keygen_parameter_spec": re.compile(r"\bKeyGenParameterSpec\b"),
    "user_authentication_required": re.compile(r"setUserAuthenticationRequired\(\s*true\s*\)"),
    "software_keystore": re.compile(r"KeyStore\.getInstance\(\s*\"(BKS|PKCS12|JKS|BouncyCastle|UBER)\"", re.I),
    "kdf": re.compile(r"\"(?:PBKDF2With\w+|HKDF\w*)\"|\bHkdf\w*\b|\bPBEKeySpec\b"),
    "secret_key_spec": re.compile(r"\bSecretKeySpec\("),
    "cipher_api": re.compile(r"\bCipher\.getInstance\("),
}
KEY_STORAGE_DEX = {
    "android_keystore": lambda s: s == "AndroidKeyStore",
    "strongbox": lambda s: s == "setIsStrongBoxBacked",
    "keygen_parameter_spec": lambda s: s == "Landroid/security/keystore/KeyGenParameterSpec;",
    "user_authentication_required": lambda s: s == "setUserAuthenticationRequired",
    "software_keystore": lambda s: s in {"BKS", "JKS", "BouncyCastle", "UBER"},
    "kdf": lambda s: s.startswith("PBKDF2With") or s.upper().startswith("HKDF") or s == "Ljavax/crypto/spec/PBEKeySpec;",
    "secret_key_spec": lambda s: s == "Ljavax/crypto/spec/SecretKeySpec;",
    "cipher_api": lambda s: s == "Ljavax/crypto/Cipher;",
}


def _entropy(value: str) -> float:
    counts: dict[str, int] = {}
    for ch in value:
        counts[ch] = counts.get(ch, 0) + 1
    n = len(value)
    return -sum(c / n * math.log2(c / n) for c in counts.values()) if n else 0.0


def _mask(value: str) -> str:
    return value[:4] + "…" + value[-4:] if len(value) > 12 else value[:2] + "…"


def cipher_findings(transformation: str) -> list[tuple[str, str, str]]:
    """(rule, severity, detail) for one javax.crypto transformation string."""
    m = _TRANSFORM.fullmatch(transformation.strip())
    if not m:
        return []
    alg, mode, pad = m.group(1).upper(), m.group(2), m.group(3)
    out = []
    if alg in {"DES", "RC2", "RC4", "ARCFOUR"}:
        out.append(("weak_cipher", "high", f"{m.group(1)} is cryptographically broken."))
    elif alg in {"DESEDE", "TRIPLEDES", "3DES", "BLOWFISH"}:
        out.append(("weak_cipher", "warning", f"{m.group(1)} is a legacy 64-bit block cipher (Sweet32)."))
    if alg == "RSA":
        if pad and pad.upper() == "NOPADDING":
            out.append(("rsa_no_padding", "high", "Textbook RSA without padding is malleable and deterministic."))
    elif alg not in {"RC4", "ARCFOUR"}:
        if mode is None:
            out.append(("ecb_mode", "high", f"No mode given for {m.group(1)}; the provider default is ECB."))
        elif mode.upper() == "ECB":
            out.append(("ecb_mode", "high", "ECB encrypts equal blocks to equal ciphertext and leaks patterns."))
    return out


class CryptoScanner:
    def __init__(self) -> None:
        self.found = _Aggregate()
        self.inventory = {name: {"occurrences": 0, "references": [], "values": set()} for name in KEY_STORAGE_JAVA}
        self._specific_values: set[str] = set()

    def _add(self, rule: str, key: str, ref: str, kind: str, confidence: str, detail: str,
             severity: str | None = None, **extra) -> None:
        category, default_severity, title = RULES[rule]
        rec = self.found.add((rule, key), {"rule": rule, "category": category,
                                           "severity": severity or default_severity, "confidence": confidence,
                                           "title": title, "detail": detail, **extra}, ref, kind)
        if confidence == "high":
            rec["confidence"] = "high"

    def _inventory(self, name: str, ref: str, value: str | None = None) -> None:
        item = self.inventory[name]
        item["occurrences"] += 1
        if ref not in item["references"] and len(item["references"]) < MAX_REFERENCES:
            item["references"].append(ref)
        if value:
            item["values"].add(value)

    def _secret(self, rule: str, value: str, ref: str, kind: str, detail: str, **extra) -> None:
        self._add(rule, value, ref, kind, "high", detail, value=value, masked=_mask(value),
                  sha256=hashlib.sha256(value.encode("utf-8")).hexdigest(), **extra)

    def _secrets(self, text: str, ref: str, kind: str, src_ref: str) -> None:
        if "-----BEGIN" in text:
            for m in _PEM.finditer(text):
                marker = m.group(0)
                self._add("private_key_pem", f"{src_ref}|{marker}", ref, kind, "high",
                          f"{marker} found; key material is referenced by location, not copied into evidence.",
                          value=marker)
        if "AIza" in text:
            for m in _GOOGLE_KEY.finditer(text):
                self._specific_values.add(m.group(0))
                self._secret("google_api_key", m.group(0), ref, kind,
                             "Google API keys in Firebase configs are often public by design; verify the key's "
                             "API and application restrictions.")
        if "AKIA" in text or "ASIA" in text:
            for m in _AWS_KEY.finditer(text):
                rule = "aws_access_key_id" if m.group(1) == "AKIA" else "aws_temporary_access_key_id"
                self._specific_values.add(m.group(0))
                self._secret(rule, m.group(0), ref, kind, "Long-term IAM access key ID; look for its secret "
                             "access key nearby." if rule == "aws_access_key_id" else "STS session key ID.")
        if "firebaseio" in text.lower():
            for m in _FIREBASE_URL.finditer(text):
                value = m.group(0).lower()
                self._add("firebase_database_url", value, ref, kind, "high",
                          "Realtime Database URL; check whether its security rules allow unauthenticated reads.",
                          value=value)
        lowered = text.lower()
        if "key" in lowered or "secret" in lowered or "token" in lowered:
            for pattern in (_GENERIC_ASSIGN, _XML_SECRET, _META_SECRET):
                for m in pattern.finditer(text):
                    name, value = m.group(1), m.group(2)
                    if _entropy(value) < 3.0:
                        continue
                    self._secret("generic_secret", value, ref, kind, f"{name} is assigned a literal credential.",
                                 name=name)

    def _java(self, src: Source) -> None:
        lines = src.lines
        for index, (line, text) in enumerate(lines):
            ref = _ref(src, line)
            self._secrets(text, ref, "java", src.ref)
            for name, pattern in KEY_STORAGE_JAVA.items():
                for m in pattern.finditer(text):
                    self._inventory(name, ref, m.group(1) if name == "software_keystore" else None)
            if "Cipher" in text:
                for m in _CIPHER.finditer(text):
                    for rule, severity, detail in cipher_findings(m.group(1)):
                        self._add(rule, m.group(1), ref, "java", "high", detail, severity=severity,
                                  value=m.group(1))
            if "IvParameterSpec" in text:
                for m in _STATIC_IV.finditer(text):
                    if m.group(2):
                        detail, value = f"IV is a zero-filled byte[{m.group(2)}].", m.group(0)
                    elif m.group(3) is not None:
                        detail, value = "IV is derived from a string literal.", m.group(3)
                    else:
                        detail, value = "IV is an inline byte array.", m.group(1)
                    self._add("static_iv", value[:200], ref, "java", "high", detail, value=value[:200])
            if "SecretKeySpec" in text:
                for m in _STATIC_KEY.finditer(text):
                    if m.group(2) is not None:
                        detail, value = "Key bytes come from a string literal.", m.group(2)
                    elif m.group(3) is not None:
                        detail, value = "Key bytes come from an inline Base64 literal.", m.group(3)
                    else:
                        detail, value = "Key bytes are an inline byte array.", m.group(1)
                    self._add("static_key", value[:200], ref, "java", "high",
                              detail + " Use AndroidKeyStore or a KDF (PBKDF2/HKDF) instead.", value=value[:200])
            if "MessageDigest" in text:
                for m in _WEAK_HASH.finditer(text):
                    algorithm = m.group(1).upper()
                    window = " ".join(t for _, t in lines[max(0, index - _HASH_WINDOW):index + _HASH_WINDOW + 1])
                    sensitive = bool(_SENSITIVE.search(window))
                    context = "password_or_signature" if sensitive else "general"
                    self._add("weak_hash", f"{algorithm}|{context}", ref, "java", "high",
                              f"{algorithm} used near password/signature handling; it is collision-prone and "
                              "unsuitable there." if sensitive else
                              f"{algorithm} used; acceptable for checksums or cache keys, not for security.",
                              severity="warning" if sensitive else "info", value=algorithm, context=context)

    def _strings(self, src: Source) -> None:
        for line, text in src.lines:
            ref = _ref(src, line)
            self._secrets(text, ref, src.kind, src.ref)
            if src.kind != "dex":
                continue
            for name, test in KEY_STORAGE_DEX.items():
                if test(text):
                    self._inventory(name, ref, text if name == "software_keystore" else None)
            if "/" in text and len(text) < 64:
                m = _TRANSFORM.fullmatch(text)
                if m and m.group(2):
                    for rule, severity, detail in cipher_findings(text):
                        self._add(rule, text, ref, "dex", "medium",
                                  detail + " (transformation constant in a DEX string pool; call site not confirmed)",
                                  severity=severity, value=text)

    def scan(self, src: Source) -> None:
        if src.kind == "java":
            self._java(src)
        else:
            self._strings(src)

    def findings(self) -> list[dict]:
        out = []
        for rec in self.found.records():
            if rec["rule"] == "generic_secret" and rec.get("value") in self._specific_values:
                continue  # already reported under a specific key rule
            out.append(rec)
        return out

    def key_storage(self) -> dict:
        inv = {k: {"occurrences": v["occurrences"], "references": v["references"], **(
            {"types": sorted(v["values"])} if k == "software_keystore" else {})} for k, v in self.inventory.items()}
        if inv["strongbox"]["occurrences"]:
            posture = "strongbox_requested"
            detail = "Keys are generated in AndroidKeyStore and StrongBox backing is requested."
        elif inv["android_keystore"]["occurrences"]:
            posture = "android_keystore"
            detail = ("AndroidKeyStore is used; keys are hardware-backed (TEE) where the device supports it. "
                      "StrongBox was not requested.")
        elif any(inv[k]["occurrences"] for k in ("cipher_api", "secret_key_spec", "software_keystore")):
            posture = "software_only"
            detail = "Cryptographic APIs are used but AndroidKeyStore was not observed; keys live in app memory."
        else:
            posture = "no_crypto_api_observed"
            detail = "No javax.crypto or KeyStore usage was observed in the scanned sources."
        return {"posture": posture, "detail": detail, "indicators": inv}


def _b(value: str | None) -> bool | None:
    return None if value is None else value.strip().lower() == "true"


def parse_nsc(text: str) -> dict:
    """Parse res/xml/network_security_config.xml into base, domain and debug configurations."""
    if "<!DOCTYPE" in text or "<!ENTITY" in text:
        raise ValueError("network security config declares a DTD or entities")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ValueError(str(exc)) from exc
    if root.tag != "network-security-config":
        raise ValueError("no <network-security-config> root element")

    def anchors(el: ET.Element) -> list[dict] | None:
        ta = el.find("trust-anchors")
        if ta is None:
            return None
        return [{"src": c.get("src"), "override_pins": bool(_b(c.get("overridePins")))} for c in ta.findall("certificates")]

    def pins(el: ET.Element) -> dict | None:
        ps = el.find("pin-set")
        if ps is None:
            return None
        found = ps.findall("pin")
        return {"expiration": ps.get("expiration"), "pins": len(found),
                "digests": sorted({p.get("digest") or "SHA-256" for p in found})}

    base = root.find("base-config")
    doc = {"base_config": None if base is None else {"cleartext_permitted": _b(base.get("cleartextTrafficPermitted")),
                                                      "trust_anchors": anchors(base)},
           "domain_configs": [], "debug_overrides": None}
    debug = root.find("debug-overrides")
    if debug is not None:
        doc["debug_overrides"] = {"trust_anchors": anchors(debug)}

    def walk(el: ET.Element, inherited: bool | None) -> None:
        for dc in el.findall("domain-config"):
            own = _b(dc.get("cleartextTrafficPermitted"))
            effective = own if own is not None else inherited
            doc["domain_configs"].append({
                "domains": [{"name": (d.text or "").strip(), "include_subdomains": bool(_b(d.get("includeSubdomains")))}
                            for d in dc.findall("domain")],
                "cleartext_permitted": effective, "trust_anchors": anchors(dc), "pin_set": pins(dc)})
            walk(dc, effective)

    walk(root, doc["base_config"]["cleartext_permitted"] if doc["base_config"] else None)
    return doc


def _nsc_findings(nsc: dict, ref: str, applied: bool, debuggable: bool | None, target_sdk: int | None,
                  today: date) -> list[dict]:
    out: list[dict] = []

    def add(rule: str, detail: str, severity: str | None = None, **extra) -> None:
        category, default, title = RULES[rule]
        sev = severity or default
        if not applied and sev != "info":
            sev = "info"
            detail += " The file is not referenced by the manifest, so the platform does not apply it."
        out.append({"rule": rule, "category": category, "severity": sev, "confidence": "high", "title": title,
                    "detail": detail, "occurrences": 1, "references": [ref], "sources": ["resource"], **extra})

    def names(dc: dict) -> list[str]:
        return [d["name"] for d in dc["domains"]]

    base = nsc["base_config"]
    if base and any(a["src"] == "user" for a in base["trust_anchors"] or []):
        add("nsc_user_trust_anchor", "base-config trusts user-installed CAs for all domains, enabling MitM "
            "interception with a user certificate.", scope="base-config")
    for dc in nsc["domain_configs"]:
        if any(a["src"] == "user" for a in dc["trust_anchors"] or []):
            add("nsc_user_trust_anchor", f"domain-config for {', '.join(names(dc))} trusts user-installed CAs.",
                scope="domain-config", domains=names(dc))
    debug = nsc["debug_overrides"]
    if debug and any(a["src"] == "user" for a in debug["trust_anchors"] or []):
        add("nsc_debug_user_trust_anchor",
            "debug-overrides trust user CAs; active because android:debuggable is true." if debuggable else
            "debug-overrides trust user CAs; only active when the app is debuggable.",
            severity="high" if debuggable else "info", scope="debug-overrides")
    every = ([("base-config", base)] if base else []) + [("domain-config", dc) for dc in nsc["domain_configs"]]
    if debug:
        every.append(("debug-overrides", debug))
    for scope, cfg in every:
        if any(a["override_pins"] for a in cfg.get("trust_anchors") or []):
            add("nsc_override_pins", f"{scope} has trust anchors with overridePins=\"true\", which bypass pin-set "
                "checks for those anchors.", scope=scope)
    if base and base["cleartext_permitted"]:
        add("nsc_cleartext_permitted", "base-config permits cleartext HTTP for all domains.", scope="base-config")
    for dc in nsc["domain_configs"]:
        if dc["cleartext_permitted"] and not (base and base["cleartext_permitted"]):
            add("nsc_cleartext_permitted", f"Cleartext HTTP permitted for {', '.join(names(dc))}.",
                scope="domain-config", domains=names(dc))
        if dc["pin_set"]:
            ps = dc["pin_set"]
            add("nsc_certificate_pinning", f"{ps['pins']} pin(s) ({', '.join(ps['digests']) or 'none'}) enforced for "
                f"{', '.join(names(dc))}" + (f"; expires {ps['expiration']}." if ps["expiration"] else "; no expiration."),
                domains=names(dc), pins=ps["pins"], expiration=ps["expiration"])
            if ps["expiration"]:
                try:
                    expired = date.fromisoformat(ps["expiration"]) < today
                except ValueError:
                    expired = False
                if expired:
                    add("nsc_pin_set_expired", f"pin-set for {', '.join(names(dc))} expired on {ps['expiration']}; "
                        "pinning is no longer enforced.", domains=names(dc), expiration=ps["expiration"])
    if applied and target_sdk is not None:
        if target_sdk < 24 and not (base and base["trust_anchors"] is not None):
            add("default_user_trust", f"targetSdkVersion {target_sdk} < 24 and base-config declares no trust anchors: "
                "user-installed CAs are trusted by default.")
        if target_sdk < 28 and not (base and base["cleartext_permitted"] is not None):
            add("default_cleartext", f"targetSdkVersion {target_sdk} < 28 and base-config does not set "
                "cleartextTrafficPermitted: cleartext HTTP is permitted by default.")
    return out


def _find_nsc(apk_root: Path, parts: list[dict], name: str) -> tuple[str, str] | None:
    res = apk_root / "apktool" / "res"
    for path in sorted(res.glob(f"xml*/{name}.xml")) if res.is_dir() else []:
        if path.stat().st_size <= MAX_TEXT_FILE_BYTES:
            return path.relative_to(apk_root / "apktool").as_posix(), _xml_text(path.read_bytes())
    for part in parts:
        if part.get("role") != "base":
            continue
        try:
            with zipfile.ZipFile(part["path"]) as z:
                for info in z.infolist():
                    entry = info.filename.replace("\\", "/")
                    if re.fullmatch(rf"res/xml[^/]*/{re.escape(name)}\.xml", entry) and info.file_size <= MAX_TEXT_FILE_BYTES:
                        return f"{part['name']}!{entry}", _xml_text(z.read(info))
        except (OSError, zipfile.BadZipFile):
            continue
    return None


def network_security(apk_root: Path, parts: list[dict], manifest: dict | None,
                     today: date | None = None) -> tuple[dict, list[dict], list[str]]:
    """Evaluate the network security config (or platform defaults) → (document, findings, unknowns)."""
    today = today or date.today()
    unknowns: list[str] = []
    app = (manifest or {}).get("application") or {}
    attr = app.get("network_security_config")
    debuggable = app.get("debuggable")
    try:
        target_sdk = int(manifest["target_sdk"]) if manifest and manifest.get("target_sdk") else None
    except (TypeError, ValueError):
        target_sdk = None
    name = attr[5:] if isinstance(attr, str) and attr.startswith("@xml/") else "network_security_config"
    referenced = None if manifest is None else bool(attr)
    if isinstance(attr, str) and attr.startswith("@0x"):
        unknowns.append(f"Manifest references network security config {attr} by unresolved resource ID; "
                        "looked for res/xml/network_security_config.xml instead.")
    try:
        located = _find_nsc(apk_root, parts, name)
    except ValueError as exc:
        located = None
        unknowns.append(f"Network security config {name}.xml could not be decoded: {exc}")
    doc: dict = {"present": located is not None, "name": name, "manifest_attribute": attr,
                 "referenced_by_manifest": referenced}
    findings: list[dict] = []
    if located is not None:
        ref, text = located
        doc["source"] = ref
        try:
            parsed = parse_nsc(text)
        except ValueError as exc:
            unknowns.append(f"{ref} could not be parsed: {exc}")
        else:
            doc.update(parsed)
            findings = _nsc_findings(parsed, ref, referenced is not False, debuggable, target_sdk, today)
    elif attr and not attr.startswith("@0x"):
        unknowns.append(f"Manifest references network security config {attr} but the resource was not found "
                        "(resource paths may be obfuscated).")
    if (located is None or referenced is False) and manifest is not None:
        ref = "AndroidManifest.xml"
        if app.get("uses_cleartext_traffic"):
            category, severity, title = RULES["manifest_cleartext"]
            findings.append({"rule": "manifest_cleartext", "category": category, "severity": severity,
                             "confidence": "high", "title": title,
                             "detail": "android:usesCleartextTraffic=\"true\" permits cleartext HTTP to every host.",
                             "occurrences": 1, "references": [ref], "sources": ["manifest"]})
        elif target_sdk is not None and target_sdk < 28 and app.get("uses_cleartext_traffic") is None:
            category, severity, title = RULES["default_cleartext"]
            findings.append({"rule": "default_cleartext", "category": category, "severity": severity,
                             "confidence": "high", "title": title,
                             "detail": f"targetSdkVersion {target_sdk} < 28 without a network security config: "
                                       "cleartext HTTP is permitted by default.",
                             "occurrences": 1, "references": [ref], "sources": ["manifest"]})
        if target_sdk is not None and target_sdk < 24:
            category, severity, title = RULES["default_user_trust"]
            findings.append({"rule": "default_user_trust", "category": category, "severity": severity,
                             "confidence": "high", "title": title,
                             "detail": f"targetSdkVersion {target_sdk} < 24 without a network security config: "
                                       "user-installed CAs are trusted by default.",
                             "occurrences": 1, "references": [ref], "sources": ["manifest"]})
    return doc, findings, unknowns


def crypto_hints(apk_root: Path, parts: list[dict], manifest: dict | None, today: date | None = None) -> dict:
    """Scan every source for key material, weak crypto, NSC trust policy and key-storage posture."""
    stats = ScanStats()
    scanner = CryptoScanner()
    for src in iter_sources(apk_root, parts, stats):
        scanner.scan(src)
    nsc, nsc_findings, nsc_unknowns = network_security(apk_root, parts, manifest, today)
    storage = scanner.key_storage()
    findings = scanner.findings() + nsc_findings
    ind = storage["indicators"]
    if storage["posture"] == "software_only" and ind["secret_key_spec"]["occurrences"]:
        category, severity, title = RULES["software_only_keys"]
        findings.append({"rule": "software_only_keys", "category": category, "severity": severity,
                         "confidence": "high" if stats.java_sources else "medium", "title": title,
                         "detail": "Symmetric keys are built with SecretKeySpec in app memory and no AndroidKeyStore "
                                   "usage was found; keys are extractable from the APK or a memory dump.",
                         "occurrences": ind["secret_key_spec"]["occurrences"],
                         "references": ind["secret_key_spec"]["references"], "sources": []})
    findings.sort(key=lambda f: (SEVERITY_ORDER[f["severity"]], f["category"], f["rule"], -f["occurrences"]))
    by_severity = {s: sum(1 for f in findings if f["severity"] == s) for s in SEVERITY_ORDER}
    by_category = {}
    for f in findings:
        by_category[f["category"]] = by_category.get(f["category"], 0) + 1
    limitations = ["Static heuristics only; no target code was executed and no credential was tested against "
                   "a remote service.",
                   "Findings with confidence \"medium\" come from DEX string pools: the constant exists, the call "
                   "site was not confirmed.",
                   "Private-key material is referenced by location and is not copied into evidence."]
    if not stats.java_sources:
        limitations.append("Decompiled Java sources were not present; call-site rules (static IV/key, weak "
                           "hashes, Cipher.getInstance) need apk_decompile.")
    if manifest is None:
        limitations.append("No decoded manifest yet; debuggable, targetSdkVersion and the networkSecurityConfig "
                           "reference were not evaluated.")
    return {"findings": findings, "finding_count": len(findings),
            "alert_count": sum(by_severity[s] for s in ("critical", "high", "warning")),
            "by_severity": by_severity, "by_category": dict(sorted(by_category.items())),
            "network_security_config": nsc, "key_storage": storage, "coverage": stats.coverage(),
            "unknowns": list(dict.fromkeys(stats.finish() + nsc_unknowns)), "limitations": limitations}
