from __future__ import annotations

from fastapi.testclient import TestClient


def test_pages_and_docs_are_locked_down(app):
    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert "ServiceDeck" in page.text
        assert "/assets/app.js" in page.text
        assert client.get("/assets/app.css").status_code == 200
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404
        assert client.get("/api/status").status_code == 401
        denied = client.post("/api/integrations/obs/actions/go_live", json={"confirm": True})
        assert denied.status_code == 401


def test_unlock_sets_a_session_cookie_and_rate_limits(app, clock):
    with TestClient(app) as client:
        session = client.get("/api/auth/session")
        assert session.json()["authenticated"] is False
        assert session.json()["must_change_passcode"] is True
        assert session.json()["organization"] == "PRBC"

        wrong = client.post("/api/auth/unlock", json={"passcode": "1111"})
        assert wrong.status_code == 401
        assert "sd_session" not in wrong.headers.get("set-cookie", "")

        for _ in range(3):
            client.post("/api/auth/unlock", json={"passcode": "1111"})
        locked = client.post("/api/auth/unlock", json={"passcode": "1111"})
        assert locked.status_code == 429
        assert locked.json()["retry_after"] >= 30

        clock.advance(31)
        opened = client.post("/api/auth/unlock", json={"passcode": "0000"})
        assert opened.status_code == 200
        cookie = opened.headers["set-cookie"].lower()
        assert "sd_session=" in cookie
        assert "httponly" in cookie
        assert "samesite=lax" in cookie
        assert "token" not in opened.json()

        status = client.get("/api/status")
        assert status.status_code == 200
        body = status.json()
        assert body["obs"]["state"] == "not_configured"
        assert body["ptz"]["cameras"] == []
        assert body["placeholders"]["planning_center"]["implemented"] is False
        assert body["placeholders"]["proclaim"]["implemented"] is False
        assert body["placeholders"]["mixer"]["name"] == "Yamaha TF3"

        refused = client.post("/api/integrations/obs/actions/go_live", json={"confirm": False})
        assert refused.status_code == 400

        future = client.post("/api/integrations/planning_center/actions/next", json={})
        assert future.status_code == 501

        tiles = client.put(
            "/api/dashboard",
            json={"tiles": [{"id": "ptz", "visible": True, "order": 0}, {"id": "obs", "visible": False, "order": 1}]},
        )
        assert tiles.status_code == 200
        assert tiles.json()["tiles"][0]["id"] == "ptz"
        assert client.get("/api/status").json()["dashboard"][0]["id"] == "ptz"

        changed = client.post("/api/auth/passcode", json={"current": "0000", "new": "2468"})
        assert changed.status_code == 200
        assert client.get("/api/auth/session").json()["must_change_passcode"] is False

        client.post("/api/auth/lock")
        assert client.get("/api/status").status_code == 401
        assert client.post("/api/auth/unlock", json={"passcode": "0000"}).status_code == 401
        assert client.post("/api/auth/unlock", json={"passcode": "2468"}).status_code == 200


def test_settings_round_trip_does_not_return_the_obs_password(app):
    with TestClient(app) as client:
        client.post("/api/auth/unlock", json={"passcode": "0000"})
        saved = client.put(
            "/api/config",
            json={
                "organization": "PRBC",
                "server": {"host": "0.0.0.0", "port": 8090},
                "obs": {
                    "host": "10.1.1.8",
                    "port": 4455,
                    "password": "booth-secret",
                    "use_start_scene": False,
                    "start_scene": "",
                },
                "cameras": [
                    {
                        "name": "Main",
                        "host": "10.1.1.9",
                        "port": 52381,
                        "protocol": "visca_ip",
                        "presets": [{"number": 1, "label": "Wide"}],
                    }
                ],
            },
        )
        assert saved.status_code == 200
        payload = saved.json()
        assert payload["obs"]["password_set"] is True
        assert "booth-secret" not in saved.text
        assert payload["cameras"][0]["presets"][0]["label"] == "Wide"
        assert payload["server"]["port"] == 8090

        again = client.get("/api/config")
        assert "booth-secret" not in again.text
        assert app.state.store.snapshot()["obs"]["password"] == "booth-secret"
