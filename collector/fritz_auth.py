"""SID login for the FRITZ!Box web interface (stdlib only).

Implements the challenge/response login of ``login_sid.lua``:
PBKDF2-HMAC-SHA256 ("2$..." challenge, FRITZ!OS >= 7.24) with an MD5 fallback
for older firmware. The session ID (SID) is renewed proactively before the
box's 20 minute inactivity timeout. The password is never logged.
"""
from __future__ import annotations

import hashlib
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

_SID_MAX_AGE_S = 18 * 60  # box expires sessions after 20 min; renew early
_SID_NULL = "0000000000000000"
_MAX_LOGIN_BYTES = 65536


class AuthError(Exception):
    """Raised when logging in to the FRITZ!Box finally fails."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse every redirect so credentials/SID never reach another host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def build_box_opener(ca_file: str | None = None) -> urllib.request.OpenerDirector:
    """Opener for all requests to the box: no redirects, TLS always verified.

    ``ca_file`` (optional) is a PEM certificate to trust for https, e.g. the
    box's own certificate. Certificate verification cannot be switched off.
    """
    ctx = ssl.create_default_context(cafile=ca_file) if ca_file else None
    handlers: list = [_NoRedirect()]
    if ctx is not None:
        handlers.append(urllib.request.HTTPSHandler(context=ctx))
    return urllib.request.build_opener(*handlers)


class FritzAuth:
    """Manages the SID lifecycle for one FRITZ!Box."""

    def __init__(self, box_url: str, username: str, password: str,
                 timeout: float = 10.0, ca_file: str | None = None) -> None:
        self._base = box_url.rstrip("/")
        self._username = username
        self._password = password
        self._timeout = timeout
        self._opener = build_box_opener(ca_file)
        self._sid = _SID_NULL
        self._obtained_at = 0.0

    def _sid_is_stale(self) -> bool:
        if self._sid == _SID_NULL:
            return True
        return (time.time() - self._obtained_at) >= _SID_MAX_AGE_S

    def ensure_sid(self) -> str:
        """Return a valid SID, logging in again if needed (one retry)."""
        if not self._sid_is_stale():
            return self._sid
        try:
            return self.get_sid()
        except AuthError:
            return self.get_sid()

    def get_sid(self) -> str:
        """Force a fresh login and return the new SID."""
        sid = self._fetch_sid()
        self._sid = sid
        self._obtained_at = time.time()
        return sid

    @property
    def opener(self) -> urllib.request.OpenerDirector:
        return self._opener

    def _read_xml(self, req) -> ET.Element:
        with self._opener.open(req, timeout=self._timeout) as resp:
            return ET.fromstring(resp.read(_MAX_LOGIN_BYTES))

    def _fetch_sid(self) -> str:
        try:
            root = self._read_xml(f"{self._base}/login_sid.lua?version=2")
        except (urllib.error.URLError, OSError, ET.ParseError) as exc:
            raise AuthError(f"FRITZ!Box not reachable: {type(exc).__name__}") from exc

        sid_el = root.find("SID")
        if sid_el is None or not sid_el.text:
            raise AuthError("Invalid login response: <SID> missing")
        if sid_el.text != _SID_NULL:
            return sid_el.text  # session already active

        challenge_el = root.find("Challenge")
        if challenge_el is None or not challenge_el.text:
            raise AuthError("Invalid login response: <Challenge> missing")
        challenge = challenge_el.text

        if challenge.startswith("2$"):
            parts = challenge.split("$")
            if len(parts) < 5:
                raise AuthError("Malformed PBKDF2 challenge")
            try:
                iter1, salt1 = int(parts[1]), bytes.fromhex(parts[2])
                iter2, salt2 = int(parts[3]), bytes.fromhex(parts[4])
            except ValueError as exc:
                raise AuthError("Malformed PBKDF2 challenge") from exc
            hash1 = hashlib.pbkdf2_hmac("sha256", self._password.encode(), salt1, iter1)
            hash2 = hashlib.pbkdf2_hmac("sha256", hash1, salt2, iter2)
            response = f"{parts[4]}${hash2.hex()}"
        else:
            raw = f"{challenge}-{self._password}".encode("utf-16le")
            response = f"{challenge}-{hashlib.md5(raw).hexdigest()}"  # legacy firmware

        data = urllib.parse.urlencode(
            {"username": self._username, "response": response}).encode()
        try:
            root = self._read_xml(
                urllib.request.Request(f"{self._base}/login_sid.lua", data=data))
        except (urllib.error.URLError, OSError, ET.ParseError) as exc:
            raise AuthError(f"Login request failed: {type(exc).__name__}") from exc

        sid_el = root.find("SID")
        if sid_el is None or not sid_el.text:
            raise AuthError("Invalid login response: <SID> missing")
        if sid_el.text == _SID_NULL:
            raise AuthError("Login failed - check user name and password")
        return sid_el.text
