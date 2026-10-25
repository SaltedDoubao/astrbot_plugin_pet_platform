import asyncio

from astrbot_plugin_pet_platform.pet_outbox import Outbox


def test_append_increments_seq_and_replay_filters():
    outbox = Outbox(buffer_size=8)
    assert outbox.append({"event": "reply", "petId": "main", "text": "a"}) == 1
    assert outbox.append({"event": "reply", "petId": "main", "text": "b"}) == 2
    assert [e["text"] for e in outbox.replay(0)] == ["a", "b"]
    assert [e["text"] for e in outbox.replay(1)] == ["b"]


def test_buffer_drops_oldest_when_full():
    outbox = Outbox(buffer_size=2)
    outbox.append({"event": "reply", "text": "a"})
    outbox.append({"event": "reply", "text": "b"})
    outbox.append({"event": "reply", "text": "c"})
    assert [e["text"] for e in outbox.replay(0)] == ["b", "c"]


def test_subscriber_receives_new_events():
    async def scenario():
        outbox = Outbox(buffer_size=8)
        queue, unsubscribe = outbox.subscribe()
        outbox.append({"event": "reply", "text": "a"})
        record = await asyncio.wait_for(queue.get(), timeout=1)
        assert record["text"] == "a"
        unsubscribe()

    asyncio.run(scenario())


def test_subscriber_overflow_emits_resync():
    async def scenario():
        # 订阅队列最多 2 条：不消费的情况下追加 3 条，第 3 条触发溢出并补 resync
        outbox = Outbox(buffer_size=8, subscriber_queue_size=2)
        queue, unsubscribe = outbox.subscribe()
        for i in range(3):
            outbox.append({"event": "reply", "text": str(i)})
        records = [await asyncio.wait_for(queue.get(), timeout=1) for _ in range(2)]
        assert any(r["event"] == "resync" for r in records)
        unsubscribe()

    asyncio.run(scenario())
