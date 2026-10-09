import base64
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def appclient(tmp_path_factory):
    os.environ["HROT_DATA_DIR"] = str(tmp_path_factory.mktemp("hrot-test-db"))
    os.environ["HROT_MODE"] = "demo"
    os.environ.pop("HROT_ADMIN_TOKEN", None)
    import server
    with TestClient(server.app) as client:
        yield client, server


def test_bootstrap_demo_is_explicit(appclient):
    client, _ = appclient
    assert client.get("/api/health").json()["status"] == "ok"
    response = client.get("/api/bootstrap")
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "demo"
    assert body["site"]["is_demo"] is True
    assert body["stats"]["tracks"] == 3
    assert all(row["is_demo"] == 1 for row in body["tracks"])
    assert all(row["status"] != "connected" for row in body["sensors"])


def test_enrollment_real_ed25519_challenge_and_replay(appclient):
    client, _ = appclient
    private = Ed25519PrivateKey.generate()
    public = base64.b64encode(private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw
    )).decode()
    enroll = client.post("/api/identities", json={
        "id": "BENCH-001", "label": "Test signer", "issuer": "Lab operator",
        "public_key": public, "protection_claim": "puf_declared"
    })
    assert enroll.status_code == 201
    assert enroll.json()["key_protection_verified"] is False

    challenge = client.post("/api/verify/challenge", json={"identity_id": "BENCH-001"})
    assert challenge.status_code == 200
    data = challenge.json()
    assert data["transcript"].startswith("HROT-AirTrust/v1/identity-proof|")
    signature = base64.b64encode(private.sign(data["transcript"].encode())).decode()
    proof = client.post("/api/verify/complete", json={
        "challenge_id":data["challenge_id"], "signature":signature
    })
    assert proof.status_code == 200
    assert proof.json()["verified"] is True
    assert proof.json()["physical_track_bound"] is False
    assert proof.json()["hardware_protection_verified"] is False
    assert client.post("/api/verify/complete", json={
        "challenge_id":data["challenge_id"], "signature":signature
    }).status_code == 409


def test_invalid_signature_rejected(appclient):
    client, _ = appclient
    challenge = client.post("/api/verify/challenge", json={"identity_id":"BENCH-001"}).json()
    attacker = Ed25519PrivateKey.generate()
    bad = base64.b64encode(attacker.sign(challenge["transcript"].encode())).decode()
    result = client.post("/api/verify/complete", json={
        "challenge_id":challenge["challenge_id"], "signature":bad
    })
    assert result.status_code == 200
    assert result.json()["verified"] is False
    assert result.json()["reason"] == "invalid_signature"
    assert client.post("/api/verify/complete", json={
        "challenge_id":challenge["challenge_id"], "signature":bad
    }).status_code == 409


def test_mission_approval_is_separate_from_authentication(appclient):
    client, _ = appclient
    start=datetime.now(timezone.utc)+timedelta(minutes=2)
    end=start+timedelta(hours=1)
    created=client.post("/api/missions",json={
        "title":"Bench inspection permit","identity_id":"BENCH-001",
        "location":"Authorized test sector",
        "start_time":start.isoformat(),"end_time":end.isoformat()
    })
    assert created.status_code == 201
    assert created.json()["status"] == "pending"
    mid=created.json()["id"]
    approved=client.post("/api/missions/"+mid+"/approve")
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert client.post("/api/missions/"+mid+"/approve").status_code == 404


def test_adapter_observation_never_auto_verifies_identity(appclient):
    client, _ = appclient
    response=client.post("/api/observations",json={
        "id":"TRK-REAL-001","label":"Adapter test","source":"pytest-adapter",
        "lat":12.915,"lon":77.607,"alt_m":70,"heading":112,"speed_ms":4
    })
    assert response.status_code == 201
    assert response.json()["identity_state"]=="unavailable"
    assert response.json()["association_state"]=="ambiguous"
    entry=next(x for x in client.get("/api/bootstrap").json()["tracks"] if x["id"]=="TRK-REAL-001")
    assert entry["is_demo"] == 0
    assert entry["authorization_state"] == "not_established"


def test_simulated_scenarios_never_change_real_track(appclient):
    client, _ = appclient
    assert client.post("/api/demo/scenario",json={"scenario":"conflict"}).status_code == 200
    data=client.get("/api/bootstrap").json()
    assert next(t for t in data["tracks"] if t["id"]=="TRK-041")["association_state"]=="contradicted"
    assert client.post("/api/demo/scenario",json={"scenario":"reset"}).status_code == 200
    data=client.get("/api/bootstrap").json()
    assert next(t for t in data["tracks"] if t["id"]=="TRK-REAL-001")["is_demo"] == 0


def test_revoke_prevents_new_challenges(appclient):
    client, _ = appclient
    r=client.post("/api/identities/BENCH-001/revoke")
    assert r.status_code == 200
    assert client.post("/api/verify/challenge",json={"identity_id":"BENCH-001"}).status_code == 404


def test_evidence_chain_detects_modification(appclient):
    client, server = appclient
    result=client.get("/api/evidence/check").json()
    assert result["valid"] is True
    assert result["entries_checked"] >= 8
    with sqlite3.connect(server.DB_PATH) as db:
        seq,original=db.execute("SELECT seq,detail FROM evidence ORDER BY seq DESC LIMIT 1").fetchone()
        db.execute("UPDATE evidence SET detail='tampered' WHERE seq=?",(seq,))
    fail=client.get("/api/evidence/check").json()
    assert fail["valid"] is False
    with sqlite3.connect(server.DB_PATH) as db:
        db.execute("UPDATE evidence SET detail=? WHERE seq=?",(original,seq))
    assert client.get("/api/evidence/check").json()["valid"] is True


def test_web_shell_and_assets_are_served(appclient):
    client, _ = appclient
    home=client.get("/")
    assert home.status_code == 200
    assert "HROT AirTrust" in home.text
    assert "operationalMap" in home.text
    assert "Mission Permits" in home.text
    css=client.get("/assets/app.css")
    js=client.get("/assets/app.js")
    assert css.status_code == 200 and "--accent:" in css.text
    assert js.status_code == 200 and "renderMap()" in js.text


def test_expired_challenge_consumed_once(appclient):
    client, server = appclient
    private = Ed25519PrivateKey.generate()
    public=base64.b64encode(private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,format=serialization.PublicFormat.Raw)).decode()
    assert client.post("/api/identities",json={
        "id":"EXPIRE-KEY","label":"Expiry test","issuer":"Lab",
        "public_key":public
    }).status_code == 201
    challenge=client.post("/api/verify/challenge",json={"identity_id":"EXPIRE-KEY"}).json()
    with sqlite3.connect(server.DB_PATH) as db:
        db.execute("UPDATE challenges SET expires_at=1 WHERE id=?",(challenge["challenge_id"],))
    signature=base64.b64encode(private.sign(challenge["transcript"].encode())).decode()
    payload={"challenge_id":challenge["challenge_id"],"signature":signature}
    result=client.post("/api/verify/complete",json=payload)
    assert result.status_code == 200
    assert result.json()["verified"] is False
    assert result.json()["reason"] == "challenge_expired"
    assert client.post("/api/verify/complete",json=payload).status_code == 409
