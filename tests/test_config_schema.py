import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_conf_schema_has_required_fields():
    schema = json.loads((ROOT / "_conf_schema.json").read_text(encoding="utf-8"))
    for key in ("token", "bind_host", "bind_port", "pet_ids", "event_buffer_size", "whisper_provider_id"):
        assert key in schema, key
    assert schema["token"]["secret"] is True
    assert schema["bind_port"]["default"] == 6199
    assert schema["pet_ids"]["default"] == ["main"]
