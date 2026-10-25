from astrbot_plugin_pet_platform.pet_auth import (
    AuthConfig,
    check_auth,
    validate_send,
)

CONFIG = AuthConfig(token="secret-token", pet_ids=frozenset({"main"}))


def test_check_auth_accepts_exact_bearer():
    result = check_auth({"Authorization": "Bearer secret-token"}, CONFIG)
    assert result.ok is True


def test_check_auth_rejects_empty_config_token():
    result = check_auth({"Authorization": "Bearer "}, AuthConfig(token="", pet_ids=CONFIG.pet_ids))
    assert (result.ok, result.code) == (False, "server-token-empty")


def test_check_auth_rejects_wrong_token():
    result = check_auth({"Authorization": "Bearer nope"}, CONFIG)
    assert (result.ok, result.code) == (False, "unauthorized")


def test_validate_send_accepts_valid_body():
    request, result = validate_send(
        {"petId": "main", "requestId": "r1", "text": "你好"}, CONFIG
    )
    assert result.ok is True
    assert request == {"petId": "main", "requestId": "r1", "text": "你好"}


def test_validate_send_rejects_unknown_pet():
    request, result = validate_send(
        {"petId": "other", "requestId": "r1", "text": "你好"}, CONFIG
    )
    assert request is None
    assert (result.ok, result.code) == (False, "forbidden-pet")


def test_validate_send_rejects_empty_or_too_long_text():
    for text in ("", "   ", "x" * 32769):
        request, result = validate_send(
            {"petId": "main", "requestId": "r1", "text": text}, CONFIG
        )
        assert request is None
        assert (result.ok, result.code) == (False, "bad-request")
