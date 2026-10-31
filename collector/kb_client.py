"""Thin client for the KB증권 Open API (REST, POST + Bearer token).

Every request is POST {base}/api/v1/<tr> with body
{"dataHeader": {"ipAddr", "macAddr"}, "dataBody": {...}}.
The token is tied to the caller's IP/MAC, so a cached token is reused only
while both still match.
"""
import json
import socket
import threading
import time
import uuid
from pathlib import Path

import requests

BASE_URL = "https://developer.kbsec.com:32484"


def local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))  # no packet is sent; this just picks the outbound interface
        return s.getsockname()[0]
    finally:
        s.close()


def local_mac():
    n = uuid.getnode()
    return "-".join(f"{(n >> s) & 0xFF:02X}" for s in range(40, -1, -8))


class ApiError(Exception):
    def __init__(self, tr, code, msg, rate_limited=False):
        super().__init__(f"{tr}: [{code}] {msg}")
        self.tr, self.code, self.msg, self.rate_limited = tr, code, msg, rate_limited


class RateLimiter:
    """Spaces calls evenly. The real limit isn't published, so it backs off on refusal."""

    def __init__(self, per_sec):
        self.gap = 1.0 / per_sec
        self.next = 0.0
        self.lock = threading.Lock()

    def wait(self):
        with self.lock:
            now = time.monotonic()
            if now < self.next:
                time.sleep(self.next - now)
                now = self.next
            self.next = now + self.gap

    def slow_down(self):
        self.gap = min(self.gap * 1.5, 5.0)


def _looks_rate_limited(status, msg):
    return status == 429 or any(k in (msg or "") for k in ("제한", "초과", "limit", "LIMIT"))


class KBClient:
    def __init__(self, app_key, app_secret, token_path, per_sec=4.0, ip=None, mac=None,
                 base_url=BASE_URL, timeout=5):
        if not app_key or not app_secret:
            raise ValueError("appKey/appSecret이 없습니다. config.json 또는 KB_APP_KEY/KB_APP_SECRET 환경변수를 설정하세요.")
        self.app_key, self.app_secret = app_key, app_secret
        self.token_path = Path(token_path)
        self.ip = ip or local_ip()
        self.mac = mac or local_mac()
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.limiter = RateLimiter(per_sec)
        self.session = requests.Session()
        self._token = None

    # ---- token ----
    def _load_cached(self):
        try:
            t = json.loads(self.token_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if t.get("ip") != self.ip or t.get("mac") != self.mac:
            return None
        if t.get("expires_at", 0) - time.time() < 600:
            return None
        return t["access_token"]

    def token(self, force=False):
        if self._token and not force:
            return self._token
        if not force:
            self._token = self._load_cached()
            if self._token:
                return self._token
        self.limiter.wait()
        r = self.session.post(f"{self.base_url}/oauth2/token", timeout=self.timeout, json={
            "appKey": self.app_key, "appSecret": self.app_secret, "grantType": "client_credentials",
        })
        r.raise_for_status()
        j = r.json()
        body = j.get("dataBody", j)  # the guide shows a flat body, the spec a wrapped one
        if "access_token" not in body:
            raise ApiError("token", r.status_code, json.dumps(j, ensure_ascii=False)[:300])
        self._token = body["access_token"]
        self.token_path.write_text(json.dumps({
            "access_token": self._token, "ip": self.ip, "mac": self.mac,
            "expires_at": time.time() + int(body.get("expires_in", 86400)),
        }), encoding="utf-8")
        return self._token

    # ---- calls ----
    def call(self, tr, body, retries=3):
        url = f"{self.base_url}/api/v1/{tr.lower()}"
        payload = {"dataHeader": {"ipAddr": self.ip, "macAddr": self.mac}, "dataBody": body}
        refreshed = False
        for attempt in range(retries + 1):
            self.limiter.wait()
            try:
                r = self.session.post(url, json=payload, timeout=self.timeout, headers={
                    "Content-Type": "application/json", "Authorization": f"Bearer {self.token()}",
                })
            except requests.RequestException as e:
                if attempt == retries:
                    raise ApiError(tr, "NET", str(e))
                time.sleep(0.5 * 2 ** attempt)
                continue

            if r.status_code == 401 and not refreshed:
                self.token(force=True)
                refreshed = True
                continue
            try:
                j = r.json()
            except ValueError:
                j = {}
            head = j.get("dataHeader", {})
            msg = head.get("processMessage") or head.get("resultMessage") or r.text[:200]
            if _looks_rate_limited(r.status_code, msg):
                self.limiter.slow_down()
                if attempt < retries:
                    time.sleep(1.0 * 2 ** attempt)
                    continue
                raise ApiError(tr, r.status_code, msg, rate_limited=True)
            ok = r.status_code == 200 and str(head.get("resultCode", "200")) == "200" and head.get("processFlag") != "B"
            if not ok:
                raise ApiError(tr, head.get("processCode") or r.status_code, msg)
            return j.get("dataBody", {})
        raise ApiError(tr, "RETRY", "retries exhausted")
