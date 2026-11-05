from app.security import hash_password, verify_password, create_access_token, decode_token


def test_password_hash_roundtrip():
    h = hash_password("secret123")
    assert verify_password("secret123", h)
    assert not verify_password("wrong", h)


def test_token_roundtrip():
    token = create_access_token({"sub": "64f000000000000000000000", "role": "teacher"})
    payload = decode_token(token)
    assert payload["sub"] == "64f000000000000000000000"
    assert payload["role"] == "teacher"