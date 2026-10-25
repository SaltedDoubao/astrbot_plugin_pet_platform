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
    # seq=1 已被挤出缓冲区，replay(0) 先补 resync，再返回剩余事件
    records = outbox.replay(0)
    assert records[0]["event"] == "resync"
    assert [e["text"] for e in records if e["event"] == "reply"] == ["b", "c"]


def test_subscriber_receives_new_events():
    async def scenario():
        outbox = Outbox(buffer_size=8)
        queue, unsubscribe = outbox.subscribe()
        outbox.append({"event": "reply", "text": "a"})
        record = await asyncio.wait_for(queue.get(), timeout=1)
        assert record["text"] == "a"
        unsubscribe()

    asyncio.run(scenario())


def test_replay_prepends_resync_when_since_predates_buffer():
    outbox = Outbox(buffer_size=3)
    for i in range(5):
        outbox.append({"event": "reply", "text": str(i)})
    records = outbox.replay(0)
    assert records[0]["event"] == "resync"
    assert records[0]["reason"] == "buffer-gap"
    assert [r["seq"] for r in records[1:]] == [3, 4, 5]
    # since=4 仍能衔接缓冲区最旧 seq=3，不需要 resync
    assert [r["seq"] for r in outbox.replay(4)] == [5]
    assert all(r["event"] != "resync" for r in outbox.replay(4))


def test_record_mutation_does_not_corrupt_buffer():
    async def scenario():
        outbox = Outbox(buffer_size=8)
        queue, unsubscribe = outbox.subscribe()
        outbox.append({"event": "reply", "text": "a"})
        delivered = await asyncio.wait_for(queue.get(), timeout=1)
        delivered["text"] = "mutated"
        assert [e["text"] for e in outbox.replay(0)] == ["a"]
        replayed = outbox.replay(0)
        replayed[0]["text"] = "mutated-again"
        assert [e["text"] for e in outbox.replay(0)] == ["a"]
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
        resyncs = [r for r in records if r["event"] == "resync"]
        assert len(resyncs) == 1
        # resync 的 seq=0 是缺口哨兵，不能被客户端当成续传点位。
        assert resyncs[0]["reason"] == "overflow"
        assert resyncs[0]["seq"] == 0
        unsubscribe()

    asyncio.run(scenario())


def test_replay_resyncs_when_since_ahead_of_head():
    # 插件重载后 seq 归零，而客户端仍持有旧的 Last-Event-ID；
    # 此时不能静默返回空列表，必须要求客户端重建。
    outbox = Outbox(buffer_size=8)
    outbox.append({"event": "reply", "text": "a"})
    outbox.append({"event": "reply", "text": "b"})
    records = outbox.replay(99)
    assert records == [
        {"event": "resync", "petId": "", "reason": "buffer-gap", "seq": 0}
    ]


def test_replay_empty_outbox_is_empty():
    outbox = Outbox(buffer_size=8)
    assert outbox.replay(0) == []
