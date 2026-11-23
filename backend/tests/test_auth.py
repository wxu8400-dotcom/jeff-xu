from __future__ import annotations


def test_password_gate_enforced_and_login_flow(make_client):
    client = make_client(password="SecretRadar2026!", mock_mode=True)

    # Health is always public
    assert client.get("/api/health").status_code == 200

    # Auth status shows protected & unauthenticated
    status = client.get("/api/auth/status").json()
    assert status == {"password_required": True, "authenticated": False}

    # Protected endpoints must reject unauthenticated requests
    assert client.get("/api/scans").status_code == 401
    assert client.get("/api/system/config-check").status_code == 401

    # Wrong password rejected
    bad = client.post("/api/auth/login", json={"password": "wrong"})
    assert bad.status_code == 401

    # Correct password succeeds and sets cookie
    ok = client.post("/api/auth/login", json={"password": "SecretRadar2026!"})
    assert ok.status_code == 200
    assert ok.json()["ok"] is True

    # Now protected endpoints work
    assert client.get("/api/auth/status").json()["authenticated"] is True
    assert client.get("/api/scans").status_code == 200
    cfg = client.get("/api/system/config-check").json()
    assert cfg["password_protected"] is True
    assert cfg["mock_mode"] is True

    # Logout clears session
    client.post("/api/auth/logout")
    assert client.get("/api/scans").status_code == 401
