from __future__ import annotations

import json
import logging
import os

from aiohttp import web

from core.helpers import utcnow_iso
from integrations.sellauth import extract_webhook_fields, verify_webhook_signature

log = logging.getLogger("tekaz.webhook")


async def start_webhook_server(bot) -> web.AppRunner | None:
    host = os.getenv("WEBHOOK_HOST", "0.0.0.0")
    port = int(os.getenv("WEBHOOK_PORT", "8080"))
    if os.getenv("ENABLE_WEBHOOK_SERVER", "true").lower() not in {"1", "true", "yes"}:
        return None

    app = web.Application()

    async def health(_: web.Request) -> web.Response:
        return web.json_response({"status": "ok"})

    async def sellauth_webhook(request: web.Request) -> web.Response:
        raw = await request.read()
        secret = os.getenv("SELLAUTH_WEBHOOK_SECRET", "")
        signature = request.headers.get("X-SellAuth-Signature") or request.headers.get("X-Hub-Signature-256")
        if secret and not verify_webhook_signature(raw, signature, secret):
            return web.json_response({"error": "invalid signature"}, status=401)

        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return web.json_response({"error": "invalid json"}, status=400)

        data = extract_webhook_fields(payload)
        tkz_order_id = data["tkz_order_id"]
        guild_id = int(payload.get("guild_id", 0))
        if not guild_id and tkz_order_id:
            order = await bot.db.fetchone("SELECT guild_id FROM orders WHERE order_id = ?", (tkz_order_id,))
            guild_id = int(order["guild_id"]) if order else 0

        await bot.db.execute(
            """
            INSERT INTO payments(guild_id, tkz_order_id, sellauth_order_id, status, amount, currency, raw_json, created_at, updated_at)
            VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (guild_id, tkz_order_id, data["sellauth_order_id"], data["status"], data["amount"], data["currency"], data["raw_json"], utcnow_iso(), utcnow_iso()),
        )

        mapped = str(data["status"]).lower()
        order_status = None
        if mapped in {"paid", "order.paid", "completed", "order.completed", "complete"}:
            order_status = "Paid"
        elif mapped in {"refunded", "order.refunded"}:
            order_status = "Refunded"
        elif mapped in {"chargeback", "order.chargeback"}:
            order_status = "Disputed"
        elif mapped in {"cancelled", "order.cancelled"}:
            order_status = "Cancelled"

        if order_status and tkz_order_id:
            await bot.db.execute(
                "UPDATE orders SET status = ?, updated_at = ? WHERE order_id = ?",
                (order_status, utcnow_iso(), tkz_order_id),
            )

        if guild_id:
            await bot.audit(guild_id, 0, "SELLAUTH_WEBHOOK", tkz_order_id or data["sellauth_order_id"], {"event": data["event"], "status": data["status"]})

        return web.json_response({"ok": True})

    app.router.add_get("/health", health)
    app.router.add_post("/webhooks/sellauth", sellauth_webhook)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host=host, port=port)
    await site.start()
    log.info("Webhook server started on %s:%s", host, port)
    return runner
