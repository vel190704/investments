"""RFC 6238 TOTP (HMAC-SHA1), stdlib only. Used to generate the Groww login code from GROWW_TOTP_SECRET."""

from __future__ import annotations

import base64
import hashlib
import hmac
import struct
import time


def totp(secret_b32: str, at: float | None = None, digits: int = 6, step: int = 30) -> str:
    key = base64.b32decode(secret_b32.replace(" ", "").upper() + "=" * (-len(secret_b32.replace(" ", "")) % 8))
    counter = int((time.time() if at is None else at) // step)
    mac = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = mac[-1] & 0x0F
    code = (struct.unpack(">I", mac[offset:offset + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(code).zfill(digits)
