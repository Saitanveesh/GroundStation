# HROT AirTrust — Ground Station

**Standalone, local-first drone identity, authorization and observation console.**
Mission Planner-inspired operator UX; **not** a Mission Planner plugin.

> **Current release: v0.1 technical MVP.** Working HTTP API, persistent database, web console,
> real Ed25519 signature verification, pending/approved missions, incident acknowledgements,
> manually/adapter-ingested observations, and a locally verifiable evidence hash chain.
> Does **not** claim real radar/RF detection, true physical-track binding, PUF-origin verification,
> verified hardware key protection, DRIP interoperability, or production counter-UAS readiness.

## 1. Run on Windows (PowerShell)

Requires Python 3.11+ and internet access once to install Python dependencies.

\`\`\`powershell
git clone https://github.com/Saitanveesh/GroundStation.git
cd GroundStation
.\run.ps1
\`\`\`

If this work is still under review on a feature branch, first run:

\`\`\`powershell
git checkout feat/hrot-airtrust-mvp
.\run.ps1
\`\`\`

Open **http://127.0.0.1:8765**. Close PowerShell / press Ctrl+C to stop.

If PowerShell blocks the script, run:

\`\`\`powershell
powershell -ExecutionPolicy Bypass -File .\run.ps1
\`\`\`

Linux/macOS: \`bash run.sh\`.

Both scripts run **DEMO mode bound to 127.0.0.1**, deliberately inaccessible to other computers without changing the bind address.

## 2. What the console includes

| Screen | Implementation |
|---|---|
| Airspace Overview | Mission Planner-inspired map, inspector, status cards, event feed |
| Aircraft & Tracks | Timestamped observation records with source provenance |
| Mission Permits | Create pending permits, explicitly approve |
| Identity Registry | Enroll and revoke Ed25519 public keys; issue and check fresh challenges |
| Incident Desk | Open alerts and audit-backed operator acknowledgement |
| Sensor Inputs | Clearly labeled demo fixtures and adapter status |
| Evidence Ledger | SHA-256 hash-chain check and JSON export |
| Training scenarios | Unidentified aircraft, contradicted association, restore and reset |

The map is a **schematic relative-position view**, not a surveyed location model.
Starter aircraft tracks are **fabricated** for evaluating workflow and UX.
No artificial entry is represented as verified radar or RF evidence.

The three independently displayed decisions are:
- Identity: \`verified | unverified | unavailable\`
- Association: \`corroborated | ambiguous | contradicted\`
- Authorization: \`permitted | not_established | denied\`

Only one of these dimensions is ever cryptographically evaluated by the current verifier.
An enrolled key signature does **not** update a track's association automatically.

## 3. Real Ed25519 test — without any aircraft

With the console running in one terminal, use another PowerShell:

\`\`\`powershell
.\.venv\Scripts\python.exe tools\demo_signer.py --id BENCH-SOFTWARE-001
\`\`\`

This tool generates an ephemeral **software** Ed25519 key locally, enrolls its *public key*,
asks the running HROT service for a fresh 16-byte nonce, signs the exact canonical transcript,
and verifies the signature. The server never receives the private key.
It proves enrolled-key possession **only**; it is not a PUF demonstration.

To create a retained lab key outside the repository, use
\`--save-key C:\labkeys\bench-id.pem\`. Keep it away from source control.

## 4. Real observation ingestion API

An external, authenticated adapter can post a track:

\`\`\`powershell
$body = @{
  id="TRK-EXT-001"; label="External test observation"; source="camera-adapter-01"
  aircraft_type="unknown"; lat=12.915; lon=77.607
  alt_m=80; heading=90; speed_ms=5.2
} | ConvertTo-Json
Invoke-RestMethod http://127.0.0.1:8765/api/observations -Method Post -ContentType "application/json" -Body $body
\`\`\`

This is **not** a radar/camera driver. It accepts adapter-produced observations.
The resulting record stays \`identity_state=unavailable\`,
\`association_state=ambiguous\`, \`authorization_state=not_established\`.
HROT deliberately does not auto-bind an arbitrary sensor track to a certified key.

Available HTTP endpoints: browse **http://127.0.0.1:8765/api/docs**.
The schema and current interface limits are in [docs/REQUIREMENTS-v1.md](docs/REQUIREMENTS-v1.md).

## 5. Live mode and security scope

Demo mode enables fixture/scenario controls and does **not** require a token when running
locally. It is **insecure to publish a demo instance on a public interface**.

For an access-controlled local instance, run with an admin token:

\`\`\`powershell
$env:HROT_MODE="live"
$env:HROT_ADMIN_TOKEN="REPLACE_WITH_A_RANDOM_VALUE_AT_LEAST_24_CHARACTERS"
.\.venv\Scripts\python.exe -m uvicorn server:app --host 127.0.0.1 --port 8765
\`\`\`

In live mode:
- Demo tracks are not automatically seeded in a fresh database.
- Mutation and read APIs require the \`X-HROT-Token\` header.
- The UI prompts for the administrator token and retains it in page memory.
- HTTPS, user roles, sensor-device credentials, trusted PKI issuers, backend attestation,
  external audit anchors, key rotation and field resilience are **not implemented**.

**Important:** Never expose this prototype directly on an untrusted network. An admin
token is not a production operator authorization system. Use a dedicated local device
and controlled bench environment. Use a different \`HROT_DATA_DIR\` for live records;
otherwise pre-existing demo fixtures from a previous database can remain present.

The SHA-256 audit chain detects incomplete modification, not full compromise. No external
checkpoint signatures exist yet.

## 6. Tests

\`\`\`powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -v tests
\`\`\`

CI runs Python syntax, JavaScript syntax and functional tests on each push/PR.

## 7. Product roadmap / engineering gates

1. Confirm actual Indian Remote ID coverage and conduct approved receive-only RF surveys.
2. Replace manual observation input with validated Remote ID / optical adapters.
3. Add signed trust registries, certificate chain validation, authenticated adapter credentials
   and off-box audit checkpoints.
4. Build calibrated multi-camera/RTK test fixture; evaluate false associations, ambiguity,
   track time-sync and controlled relay scenarios on **physical targets**.
5. Evaluate ASTM Remote ID / DRIP interoperability and separated PUF signing lifecycle.
6. Test against real participating drones, then customer/site operational requirements.

Do not claim a specific radio range, detection probability, adversarial relay resistance or
airframe-binding guarantee until measured on physical equipment.

## Why no Mission Planner plugin?

Mission Planner controls supported aircraft through MAVLink. A campus security station
cannot assume it has MAVLink access to visiting contractors or unknown aircraft.
MAVLink can later serve as a **test ground-truth adapter**, not a core dependency.

## License and compliance

Prototype for controlled research, not an autonomous countermeasure. No jamming, takeovers,
navigation spoofing or interception functionality. Site permissions, radio licensing,
privacy retention policies and legal checks remain deployment responsibilities.
