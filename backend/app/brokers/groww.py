"""Groww Trade API — READ-ONLY holdings adapter (official API, documented TOTP token flow).

Only two endpoints can ever be called; any other path raises before a request is sent:
  POST /v1/token/api/access   (key_type=totp)  -> daily access token
  GET  /v1/holdings/user                       -> demat holdings
Secrets come from .env only, are never logged, and the access token lives in memory until its expiry.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation

import httpx

from app.brokers.base import BrokerError, BrokerHolding
from app.brokers.totp import totp

BASE_URL = "https://api.groww.in"
ALLOWED = frozenset({("POST", "/v1/token/api/access"), ("GET", "/v1/holdings/user")})


class GrowwAdapter:
    name = "groww"

    def __init__(self, api_key: str, totp_secret: str | None = None, transport: httpx.BaseTransport | None = None,
                 clock=None):
        if not api_key:
            raise BrokerError("GROWW_API_KEY is not set in .env")
        self.__api_key = api_key
        self.__totp_secret = totp_secret or None
        self.__token: str | None = None
        self.__token_expiry: datetime | None = None
        self._clock = clock or (lambda: datetime.now().astimezone())
        self._http = httpx.Client(base_url=BASE_URL, timeout=20.0, transport=transport,
                                  headers={"Accept": "application/json", "X-API-VERSION": "1.0"})

    def __repr__(self) -> str:  # never expose secrets in logs/tracebacks
        return f"GrowwAdapter(token={'set' if self.__token else 'none'})"

    def _request(self, method: str, path: str, **kw) -> httpx.Response:
        if (method, path) not in ALLOWED:
            raise BrokerError(f"Blocked: {method} {path} is not an allowed read-only endpoint")
        try:
            return self._http.request(method, path, **kw)
        except httpx.HTTPError as e:
            raise BrokerError(f"Groww unreachable ({type(e).__name__})") from None

    @property
    def token_valid(self) -> bool:
        return bool(self.__token and self.__token_expiry and self.__token_expiry > self._clock())

    def login(self, totp_code: str | None = None) -> datetime | None:
        """Exchange API key + TOTP for today's access token. The code may come from the UI (used once)."""
        code = totp_code or (totp(self.__totp_secret) if self.__totp_secret else None)
        if not code:
            raise BrokerError("Enter the current 6-digit TOTP code, or set GROWW_TOTP_SECRET in .env")
        r = self._request("POST", "/v1/token/api/access", json={"key_type": "totp", "totp": code},
                          headers={"Authorization": f"Bearer {self.__api_key}", "Content-Type": "application/json"})
        if r.status_code != 200:
            raise BrokerError(f"Groww token request was rejected (HTTP {r.status_code}); approve the key on the Groww "
                              "Cloud API keys page and check the TOTP code")
        body = r.json()
        token = body.get("token")
        if not token:
            raise BrokerError("Groww returned no token")
        self.__token = token
        try:
            exp = datetime.fromisoformat(body.get("expiry", ""))
            self.__token_expiry = exp if exp.tzinfo else exp.astimezone()
        except ValueError:
            self.__token_expiry = None
        return self.__token_expiry

    def holdings(self) -> list[BrokerHolding]:
        if not self.token_valid:
            self.login()
        r = self._request("GET", "/v1/holdings/user", headers={"Authorization": f"Bearer {self.__token}"})
        if r.status_code != 200:
            raise BrokerError(f"Groww holdings request failed (HTTP {r.status_code})")
        body = r.json()
        if body.get("status") != "SUCCESS":
            raise BrokerError("Groww holdings request did not succeed")
        out = []
        for h in (body.get("payload") or {}).get("holdings", []):
            try:
                qty = Decimal(str(h["quantity"]))
                avg = Decimal(str(h["average_price"])) if h.get("average_price") is not None else None
            except (KeyError, InvalidOperation):
                continue
            if h.get("isin"):
                out.append(BrokerHolding(h["isin"].upper(), h.get("trading_symbol"), qty, avg))
        return out
