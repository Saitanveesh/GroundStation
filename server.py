"""HROT AirTrust — standalone, local-first verification and observation service.

Security boundary: DEMO data is synthetic. Signature verification proves possession of
an enrolled Ed25519 key; it does not prove airframe identity, location, or PUF origin.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
DATA = Path(os.getenv("HROT_DATA_DIR", str(ROOT / "data")))
DATA.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA / "hrot.db"
MODE = os.getenv("HROT_MODE", "demo").lower()
if MODE not in ("demo", "live"):
    raise RuntimeError("HROT_MODE must be demo or live")
ADMIN_TOKEN = os.getenv("HROT_ADMIN_TOKEN", "")
if MODE == "live" and len(ADMIN_TOKEN) < 24:
    raise RuntimeError("HROT_MODE=live requires HROT_ADMIN_TOKEN of at least 24 characters")
LOCK = threading.RLock()
app = FastAPI(title="HROT AirTrust", version="0.1.0", docs_url="/api/docs", openapi_url="/api/openapi.json")

@app.middleware("http")
async def headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    return response

@contextmanager
def connect():
    db = sqlite3.connect(DB_PATH, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

def rows(db, query, params=()):
    return [dict(x) for x in db.execute(query, params).fetchall()]

def audit(db, kind: str, detail: str, severity: str = "info", source: str = "core"):
    latest = db.execute("SELECT hash FROM evidence ORDER BY seq DESC LIMIT 1").fetchone()
    prev = latest["hash"] if latest else "0" * 64
    entry = {
        "time": now_iso(), "kind": kind, "detail": detail,
        "severity": severity, "source": source, "prev_hash": prev
    }
    canonical = json.dumps(entry, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    db.execute(
        "INSERT INTO evidence (timestamp,kind,detail,severity,source,prev_hash,hash) VALUES (?,?,?,?,?,?,?)",
        (entry["time"], kind, detail, severity, source, prev, digest)
    )
    return digest

def demo_seed(db):
    # All demo tracks and status labels are fabricated UI fixtures, NOT sensor measurements.
    sample = [
        ("TRK-041", "Survey Alpha", "camera-demo", "multirotor", 12.9172, 77.6086, 64, 38, 6.1, "LAB-PUF-01", "verified", "corroborated", "permitted"),
        ("TRK-042", "Contractor Beta", "rid-demo", "multirotor", 12.9148, 77.6044, 93, 294, 4.3, "CONTRACT-02", "unverified", "ambiguous", "not_established"),
        ("TRK-043", "Unidentified 03", "camera-demo", "unknown", 12.9129, 77.6099, 110, 225, 8.6, None, "unavailable", "ambiguous", "not_established"),
    ]
    for t in sample:
        db.execute("""INSERT INTO tracks
          (id,label,source,aircraft_type,lat,lon,alt_m,heading,speed_ms,claimed_identity,identity_state,association_state,authorization_state,observed_at,is_demo)
          VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)""", (*t, now_iso()))
    db.execute("""INSERT INTO sensors(id,label,type,status,last_seen,is_demo) VALUES
      ('SEN-CAM-01','Perimeter Camera A','Optical','demo',?,1),
      ('SEN-RID-01','Remote ID Receiver','Remote ID','demo',?,1),
      ('SEN-RF-01','RF Observation Adapter','RF','not_connected',NULL,0)""", (now_iso(), now_iso()))
    db.execute("""INSERT INTO missions
      (id,title,identity_id,location,start_time,end_time,status,is_demo) VALUES
      ('MIS-1001','West perimeter inspection','LAB-PUF-01','Training Sector 7','2026-10-09T08:00:00Z','2026-10-10T18:00:00Z','approved',1),
      ('MIS-1002','Electrical survey','CONTRACT-02','Training Sector 7','2026-10-09T08:00:00Z','2026-10-10T18:00:00Z','pending',1)""")
    audit(db, "DEMO_INITIALIZED", "Synthetic training tracks, missions and sensor fixtures loaded", "info", "demo")
    audit(db, "OBSERVATION", "Three simulated tracks available for interface evaluation", "info", "demo")
    audit(db, "ASSOCIATION_PENDING", "TRK-043 has no authenticated identity evidence", "attention", "demo")

def init():
    with LOCK, connect() as db:
        db.executescript("""
          PRAGMA journal_mode=WAL;
          CREATE TABLE IF NOT EXISTS identities(
            id TEXT PRIMARY KEY, label TEXT NOT NULL, issuer TEXT NOT NULL,
            public_key TEXT NOT NULL, key_type TEXT NOT NULL DEFAULT 'Ed25519',
            protection_claim TEXT NOT NULL DEFAULT 'not_attested',
            status TEXT NOT NULL DEFAULT 'active', created_at TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS tracks(
            id TEXT PRIMARY KEY, label TEXT NOT NULL, source TEXT NOT NULL,
            aircraft_type TEXT NOT NULL, lat REAL NOT NULL, lon REAL NOT NULL,
            alt_m REAL NOT NULL, heading REAL NOT NULL, speed_ms REAL NOT NULL,
            claimed_identity TEXT, identity_state TEXT NOT NULL,
            association_state TEXT NOT NULL, authorization_state TEXT NOT NULL,
            observed_at TEXT NOT NULL, is_demo INTEGER NOT NULL DEFAULT 0);
          CREATE TABLE IF NOT EXISTS missions(
            id TEXT PRIMARY KEY, title TEXT NOT NULL, identity_id TEXT NOT NULL,
            location TEXT NOT NULL, start_time TEXT NOT NULL, end_time TEXT NOT NULL,
            status TEXT NOT NULL, is_demo INTEGER NOT NULL DEFAULT 0);
          CREATE TABLE IF NOT EXISTS sensors(
            id TEXT PRIMARY KEY, label TEXT NOT NULL, type TEXT NOT NULL,
            status TEXT NOT NULL, last_seen TEXT, is_demo INTEGER NOT NULL DEFAULT 0);
          CREATE TABLE IF NOT EXISTS evidence(
            seq INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL,
            kind TEXT NOT NULL, detail TEXT NOT NULL, severity TEXT NOT NULL,
            source TEXT NOT NULL, prev_hash TEXT NOT NULL, hash TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS challenges(
            id TEXT PRIMARY KEY, identity_id TEXT NOT NULL, nonce TEXT NOT NULL,
            expires_at INTEGER NOT NULL, used INTEGER NOT NULL DEFAULT 0);
          CREATE TABLE IF NOT EXISTS incidents(
            id TEXT PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL,
            severity TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL,
            track_id TEXT, is_demo INTEGER NOT NULL DEFAULT 0);
        """)
        n = db.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]
        if n == 0 and MODE == "demo":
            demo_seed(db)
            db.execute("""INSERT INTO incidents(id,title,description,severity,status,created_at,track_id,is_demo)
              VALUES (?,?,?,?,?,?,?,1)""", (
                "INC-001", "Unidentified aircraft observation",
                "Camera fixture reports an unresolved aerial target. No cryptographic identity is available.",
                "attention", "open", now_iso(), "TRK-043"
            ))
        if db.execute("SELECT COUNT(*) FROM evidence").fetchone()[0] == 0:
            audit(db, "SERVICE_INITIALIZED", "HROT local evidence ledger initialized")

init()

def authorized(x_hrot_token: str | None = Header(default=None)):
    # DEMO is intentionally local-only by deployment instructions; never expose it publicly.
    if MODE == "demo" and not ADMIN_TOKEN:
        return True
    if not x_hrot_token or not hmac.compare_digest(x_hrot_token, ADMIN_TOKEN):
        raise HTTPException(401, "Valid X-HROT-Token required")
    return True

def read_authorized(x_hrot_token: str | None = Header(default=None)):
    if MODE != "live":
        return True
    return authorized(x_hrot_token)

class IdentityIn(BaseModel):
    id: str = Field(min_length=3, max_length=60, pattern=r"^[A-Za-z0-9_-]+$")
    label: str = Field(min_length=2, max_length=100)
    issuer: str = Field(min_length=2, max_length=100)
    public_key: str = Field(min_length=40, max_length=64)
    protection_claim: Literal["not_attested", "software_declared", "puf_declared", "secure_element_declared"] = "not_attested"

    @field_validator("public_key")
    @classmethod
    def validate_key(cls, value):
        try:
            raw = base64.b64decode(value, validate=True)
            Ed25519PublicKey.from_public_bytes(raw)
        except Exception:
            raise ValueError("Expected base64 of a 32-byte Ed25519 public key")
        return value

class MissionIn(BaseModel):
    title: str = Field(min_length=3, max_length=120)
    identity_id: str = Field(min_length=3, max_length=60)
    location: str = Field(min_length=2, max_length=120)
    start_time: datetime
    end_time: datetime

    @field_validator("start_time", "end_time")
    @classmethod
    def timezone_required(cls, value):
        if value.tzinfo is None:
            raise ValueError("Timezone is required")
        return value

class ChallengeIn(BaseModel):
    identity_id: str

class ProofIn(BaseModel):
    challenge_id: str
    signature: str

class ObservationIn(BaseModel):
    id: str = Field(min_length=3, max_length=60, pattern=r"^[A-Za-z0-9_-]+$")
    label: str = Field(min_length=1, max_length=100)
    source: str = Field(min_length=2, max_length=80)
    aircraft_type: str = "unknown"
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    alt_m: float = Field(ge=-1000, le=20000)
    heading: float = Field(ge=0, lt=360)
    speed_ms: float = Field(ge=0, le=500)

class ScenarioIn(BaseModel):
    scenario: Literal["unknown", "conflict", "clear", "reset"]

@app.get("/api/health")
def health():
    return {"service": "HROT AirTrust", "status": "ok", "mode": MODE, "time": now_iso(), "version": "0.1.0"}

@app.get("/api/bootstrap", dependencies=[Depends(read_authorized)])
def bootstrap():
    with LOCK, connect() as db:
        tracks = rows(db, "SELECT * FROM tracks ORDER BY id")
        incidents = rows(db, "SELECT * FROM incidents ORDER BY created_at DESC")
        evidence = rows(db, "SELECT * FROM evidence ORDER BY seq DESC LIMIT 120")
        return {
            "mode": MODE, "version": "0.1.0", "server_time": now_iso(),
            "site": {"name":"TRAINING SECTOR 7" if MODE=="demo" else "LOCAL OBSERVATION SITE",
                     "lat": 12.9150, "lon": 77.6070, "radius_m": 1250, "is_demo": MODE=="demo"},
            "tracks": tracks,
            "missions": rows(db, "SELECT * FROM missions ORDER BY start_time DESC"),
            "identities": rows(db, "SELECT id,label,issuer,key_type,protection_claim,status,created_at FROM identities ORDER BY created_at DESC"),
            "incidents": incidents,
            "sensors": rows(db, "SELECT * FROM sensors ORDER BY id"),
            "evidence": evidence,
            "stats": {
                "tracks": len(tracks),
                "unresolved": sum(t["association_state"] != "corroborated" for t in tracks),
                "authorized": sum(t["authorization_state"] == "permitted" for t in tracks),
                "active_incidents": sum(x["status"] == "open" for x in incidents)
            }
        }

@app.post("/api/identities", dependencies=[Depends(authorized)], status_code=201)
def add_identity(inp: IdentityIn):
    with LOCK, connect() as db:
        try:
            db.execute("""INSERT INTO identities(id,label,issuer,public_key,key_type,protection_claim,status,created_at)
                          VALUES (?,?,?,?,'Ed25519',?,'active',?)""",
                       (inp.id, inp.label, inp.issuer, inp.public_key, inp.protection_claim, now_iso()))
        except sqlite3.IntegrityError:
            raise HTTPException(409, "Identity already exists")
        audit(db,"IDENTITY_ENROLLED", "Operator enrolled identity " + inp.id + "; protection claim is not independently attested")
    return {"id": inp.id, "status": "active", "key_protection_verified": False}

@app.post("/api/identities/{identity_id}/revoke", dependencies=[Depends(authorized)])
def revoke_identity(identity_id: str):
    with LOCK, connect() as db:
        cur = db.execute("UPDATE identities SET status='revoked' WHERE id=? AND status='active'", (identity_id,))
        if cur.rowcount == 0:
            raise HTTPException(404, "Active identity not found")
        audit(db, "IDENTITY_REVOKED", "Operator revoked identity " + identity_id, "attention")
    return {"id":identity_id,"status":"revoked"}

@app.post("/api/verify/challenge", dependencies=[Depends(authorized)])
def issue_challenge(inp: ChallengeIn):
    with LOCK, connect() as db:
        identity = db.execute("SELECT status FROM identities WHERE id=?", (inp.identity_id,)).fetchone()
        if not identity or identity["status"] != "active":
            raise HTTPException(404, "Active identity not found")
        challenge_id = str(uuid.uuid4())
        nonce = base64.b64encode(secrets.token_bytes(16)).decode("ascii")
        expires_at = int(time.time()) + 90
        db.execute("INSERT INTO challenges VALUES (?,?,?,?,0)", (challenge_id, inp.identity_id, nonce, expires_at))
        transcript = f"HROT-AirTrust/v1/identity-proof|{challenge_id}|{inp.identity_id}|{nonce}"
        audit(db, "CHALLENGE_ISSUED", "Challenge issued to " + inp.identity_id)
    return {"challenge_id":challenge_id,"identity_id":inp.identity_id,"nonce":nonce,
            "transcript":transcript,"encoding":"UTF-8","expires_at_unix":expires_at}

@app.post("/api/verify/complete", dependencies=[Depends(authorized)])
def complete_challenge(inp: ProofIn):
    with LOCK, connect() as db:
        challenge = db.execute("SELECT * FROM challenges WHERE id=?", (inp.challenge_id,)).fetchone()
        if not challenge or challenge["used"]:
            raise HTTPException(409, "Challenge missing or already used")
        # Atomic single-use consumption occurs before verification, even on failure/timeout.
        db.execute("UPDATE challenges SET used=1 WHERE id=? AND used=0", (inp.challenge_id,))
        if challenge["expires_at"] < time.time():
            audit(db, "PROOF_EXPIRED", "Expired proof for " + challenge["identity_id"], "attention")
            raise HTTPException(410, "Challenge expired")
        identity = db.execute("SELECT * FROM identities WHERE id=?", (challenge["identity_id"],)).fetchone()
        if not identity or identity["status"] != "active":
            audit(db, "PROOF_REJECTED", "Revoked or missing identity", "attention")
            return {"verified":False,"reason":"identity_not_active"}
        transcript = f"HROT-AirTrust/v1/identity-proof|{challenge['id']}|{identity['id']}|{challenge['nonce']}"
        valid = False
        try:
            sig = base64.b64decode(inp.signature, validate=True)
            Ed25519PublicKey.from_public_bytes(base64.b64decode(identity["public_key"])).verify(sig, transcript.encode("utf-8"))
            valid = True
        except (ValueError, InvalidSignature):
            pass
        audit(db, "IDENTITY_VERIFIED" if valid else "PROOF_REJECTED",
              f"Cryptographic key-possession proof {'accepted' if valid else 'rejected'} for {identity['id']}",
              "info" if valid else "attention")
        return {"verified":valid, "identity_id":identity["id"],
                "reason":"valid_ed25519_signature" if valid else "invalid_signature",
                "physical_track_bound":False, "hardware_protection_verified":False,
                "note":"Proof of enrolled key possession only; neither PUF origin nor aircraft position is proven."}

@app.post("/api/missions", dependencies=[Depends(authorized)], status_code=201)
def create_mission(inp: MissionIn):
    if inp.end_time <= inp.start_time:
        raise HTTPException(422,"End time must follow start time")
    with LOCK, connect() as db:
        mid = "MIS-" + secrets.token_hex(4).upper()
        db.execute("""INSERT INTO missions VALUES (?,?,?,?,?,?,?,0)""", (
            mid, inp.title, inp.identity_id, inp.location,
            inp.start_time.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            inp.end_time.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),"pending"))
        audit(db,"MISSION_CREATED", f"Mission {mid} created as pending (no automatic authorization)")
    return {"id":mid,"status":"pending"}

@app.post("/api/missions/{mission_id}/approve", dependencies=[Depends(authorized)])
def approve_mission(mission_id: str):
    with LOCK, connect() as db:
        cur = db.execute("UPDATE missions SET status='approved' WHERE id=? AND status='pending'", (mission_id,))
        if not cur.rowcount:
            raise HTTPException(404, "Pending mission not found")
        audit(db,"MISSION_APPROVED", f"Operator approved mission {mission_id}")
    return {"id":mission_id,"status":"approved"}

@app.post("/api/observations", dependencies=[Depends(authorized)], status_code=201)
def add_observation(inp: ObservationIn):
    # Adapter ingestion is authenticated by deployment access policy. NO automatic track binding.
    with LOCK, connect() as db:
        db.execute("""INSERT INTO tracks
          (id,label,source,aircraft_type,lat,lon,alt_m,heading,speed_ms,claimed_identity,identity_state,association_state,authorization_state,observed_at,is_demo)
          VALUES (?,?,?,?,?,?,?,?,?,NULL,'unavailable','ambiguous','not_established',?,0)
          ON CONFLICT(id) DO UPDATE SET label=excluded.label,source=excluded.source,
          aircraft_type=excluded.aircraft_type,lat=excluded.lat,lon=excluded.lon,
          alt_m=excluded.alt_m,heading=excluded.heading,speed_ms=excluded.speed_ms,observed_at=excluded.observed_at""",
          (inp.id,inp.label,inp.source,inp.aircraft_type,inp.lat,inp.lon,inp.alt_m,inp.heading,inp.speed_ms,now_iso()))
        audit(db, "OBSERVATION_INGESTED", f"Observation {inp.id} received from {inp.source}", source=inp.source)
    return {"track_id":inp.id,"identity_state":"unavailable","association_state":"ambiguous"}

@app.post("/api/incidents/{incident_id}/ack", dependencies=[Depends(authorized)])
def ack_incident(incident_id: str):
    with LOCK, connect() as db:
        cur=db.execute("UPDATE incidents SET status='acknowledged' WHERE id=? AND status='open'", (incident_id,))
        if not cur.rowcount:
            raise HTTPException(404,"Open incident not found")
        audit(db,"INCIDENT_ACK", f"Operator acknowledged incident {incident_id}")
    return {"id":incident_id,"status":"acknowledged"}

@app.post("/api/demo/scenario", dependencies=[Depends(authorized)])
def demo_scenario(inp: ScenarioIn):
    if MODE != "demo":
        raise HTTPException(403,"Scenario fixtures are only permitted in demo mode")
    with LOCK, connect() as db:
        if inp.scenario == "reset":
            db.execute("DELETE FROM incidents WHERE is_demo=1")
            db.execute("DELETE FROM tracks WHERE is_demo=1")
            db.execute("DELETE FROM missions WHERE is_demo=1")
            demo_seed(db)
            db.execute("INSERT INTO incidents VALUES (?,?,?,?,?,?,?,1)",
                       ("INC-001","Unidentified aircraft observation",
                        "Unresolved training camera track","attention","open",now_iso(),"TRK-043"))
        elif inp.scenario == "unknown":
            db.execute("UPDATE tracks SET identity_state='unavailable',association_state='ambiguous',authorization_state='not_established' WHERE id='TRK-043'")
            db.execute("INSERT OR REPLACE INTO incidents VALUES (?,?,?,?,?,?,?,1)",
                       ("INC-003","Unknown target — demonstration","No credential or Remote ID available","attention","open",now_iso(),"TRK-043"))
        elif inp.scenario == "conflict":
            db.execute("UPDATE tracks SET association_state='contradicted',authorization_state='not_established' WHERE id='TRK-041'")
            db.execute("INSERT OR REPLACE INTO incidents VALUES (?,?,?,?,?,?,?,1)",
                       ("INC-004","Identity-to-track conflict — demonstration","Synthetic track conflicts with declared identity association","critical","open",now_iso(),"TRK-041"))
        elif inp.scenario == "clear":
            db.execute("UPDATE tracks SET association_state='corroborated',identity_state='verified',authorization_state='permitted' WHERE id='TRK-041'")
        audit(db,"DEMO_SCENARIO", f"Operator selected synthetic scenario: {inp.scenario}",source="demo")
    return {"scenario":inp.scenario,"note":"Synthetic fixture only; no live sensor or cryptographic evidence was created."}

@app.get("/api/evidence/check", dependencies=[Depends(read_authorized)])
def check_evidence():
    with LOCK, connect() as db:
        data=rows(db,"SELECT * FROM evidence ORDER BY seq ASC")
    previous="0"*64
    for item in data:
        entry={"time":item["timestamp"],"kind":item["kind"],"detail":item["detail"],
               "severity":item["severity"],"source":item["source"],"prev_hash":item["prev_hash"]}
        digest=hashlib.sha256(json.dumps(entry,sort_keys=True,separators=(",",":")).encode()).hexdigest()
        if item["prev_hash"] != previous or item["hash"] != digest:
            return {"valid":False,"first_invalid_seq":item["seq"],"entries_checked":len(data),
                    "note":"Local chain validation does not protect against full-database rewrite."}
        previous=digest
    return {"valid":True,"entries_checked":len(data),"head_hash":previous,
            "note":"Local integrity only; signed off-box checkpoints are not implemented."}

@app.get("/api/evidence/export", dependencies=[Depends(read_authorized)])
def evidence_export():
    with LOCK, connect() as db:
        return {"exported_at":now_iso(),"mode":MODE,"entries":rows(db,"SELECT * FROM evidence ORDER BY seq")}

app.mount("/assets",StaticFiles(directory=str(WEB)),name="assets")

@app.get("/")
def home():
    return FileResponse(WEB / "index.html")
