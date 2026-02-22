from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
from typing import Any

import aiohttp

log = logging.getLogger("tekaz.sellauth")


class SellAuthClient:
    def __init__(self) -> None:
        self.base_url = os.getenv("SELLAUTH_BASE_URL", "https://api.sellauth.com/v1").rstrip("/")
        self.api_key = os.getenv("SELLAUTH_API_KEY", "")
        self.store_id = os.getenv("SELLAUTH_STORE_ID", "")

    async def fetch_order_status(self, sellauth_order_id: str) -> dict[str, Any]:
        if not self.api_key:
            raise RuntimeError("SELLAUTH_API_KEY non configurée")
        url = f"{self.base_url}/orders/{sellauth_order_id}"
        headers = {"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"}
        for attempt in range(3):
            try:
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
                    async with session.get(url, headers=headers) as resp:
                        data = await resp.json(content_type=None)
                        if resp.status >= 400:
                            raise RuntimeError(f"SellAuth HTTP {resp.status}: {data}")
                        return data if isinstance(data, dict) else {"raw": data}
            except Exception as exc:
                if attempt == 2:
                    raise
                log.warning("SellAuth retry %s failed: %s", attempt + 1, exc)
                await asyncio.sleep(1 + attempt)
        raise RuntimeError("SellAuth unreachable")

    async def verify_paid(self, sellauth_order_id: str) -> tuple[bool, str, dict[str, Any]]:
        payload = await self.fetch_order_status(sellauth_order_id)
        status = str(
            payload.get("status")
            or payload.get("data", {}).get("status")
            or payload.get("order", {}).get("status")
            or "unknown"
        ).lower()
        paid = status in {"paid", "completed", "complete", "success"}
        return paid, status, payload


def verify_webhook_signature(body: bytes, provided_signature: str | None, secret: str) -> bool:
    if not provided_signature or not secret:
        return False
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    provided = provided_signature.replace("sha256=", "").strip()
    return hmac.compare_digest(expected, provided)


def extract_webhook_fields(payload: dict[str, Any]) -> dict[str, Any]:
    event = payload.get("event") or payload.get("type") or payload.get("status") or "unknown"
    data = payload.get("data", payload)
    return {
        "event": str(event),
        "sellauth_order_id": str(data.get("order_id") or data.get("id") or payload.get("order_id") or ""),
        "tkz_order_id": str(data.get("custom_id") or data.get("metadata", {}).get("tkz_order_id") or ""),
        "status": str(data.get("status") or event),
        "amount": float(data.get("amount") or data.get("total") or 0),
        "currency": str(data.get("currency") or ""),
        "discord_id": int(data.get("discord_id") or 0) if str(data.get("discord_id") or "").isdigit() else None,
        "email": str(data.get("email") or ""),
        "raw_json": json.dumps(payload, ensure_ascii=False),
    }
