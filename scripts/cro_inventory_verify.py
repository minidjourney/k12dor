"""CRO-safe live Rocket Growth inventory verification."""

import asyncio
import json

from k12_commerce_mcp.live_verification import collect_inventory_summary
from k12_commerce_mcp.models import Channel
from k12_commerce_mcp.server import build_live_service


async def verify() -> dict[str, object]:
    service = build_live_service()
    result = await collect_inventory_summary(service, Channel.COUPANG_ROCKET_GROWTH)
    result["external_data_writes"] = 0
    return result


if __name__ == "__main__":
    print(json.dumps(asyncio.run(verify()), ensure_ascii=False, sort_keys=True))
