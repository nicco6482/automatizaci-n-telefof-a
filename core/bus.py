"""Bus de eventos sobre Redis Streams: el simulador publica, el orquestador consume."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import ResponseError

from core.schemas import BusEvent

STREAM = "teleco:events"
GROUP = "orquestador"
MAXLEN = 10_000


class EventBus:
    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    @classmethod
    def from_url(cls, url: str) -> EventBus:
        return cls(Redis.from_url(url, decode_responses=True))

    async def publish(self, event: BusEvent) -> str:
        if event.at is None:
            event = event.model_copy(update={"at": datetime.now(UTC)})
        msg_id = await self.redis.xadd(
            STREAM, {"data": event.model_dump_json(exclude={"id"})}, maxlen=MAXLEN, approximate=True
        )
        return str(msg_id)

    async def ensure_group(self) -> None:
        try:
            await self.redis.xgroup_create(STREAM, GROUP, id="0", mkstream=True)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def read(self, consumer: str, count: int = 50, block_ms: int = 1000) -> list[BusEvent]:
        response: Any = await self.redis.xreadgroup(GROUP, consumer, {STREAM: ">"}, count=count, block=block_ms)
        events = []
        for _stream, messages in response or []:
            for msg_id, fields in messages:
                events.append(BusEvent.model_validate_json(fields["data"]).model_copy(update={"id": msg_id}))
        return events

    async def ack(self, event: BusEvent) -> None:
        await self.redis.xack(STREAM, GROUP, event.id)

    async def recent(self, count: int = 100) -> list[BusEvent]:
        messages: Any = await self.redis.xrevrange(STREAM, count=count)
        return [BusEvent.model_validate_json(f["data"]).model_copy(update={"id": i}) for i, f in messages]
