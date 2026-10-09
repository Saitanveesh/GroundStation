# HROT-GCS Requirements v1 — implementation boundary

**Version:** v1 / 2026-10-09. **Product:** HROT AirTrust. **Status:** working MVP + open experiments.

## 1. Mission and exclusions

An independent airspace identity-and-trust console for institutional security teams.
Accept observations from supported sensors, verify enrolled cryptographic identities,
evaluate separately recorded operating permission, and retain incident evidence.

The core MUST NOT depend on Mission Planner or MAVLink. Mission Planner may be an
optional telemetry/reference adapter for consenting research aircraft.

No automated classification of unresponsive aircraft as hostile. No jamming,
spoofing, forced control or interdiction.

## 2. Observation schema

\`TrackObservation\`:
- \`id\` (sensor-scoped track ID), \`source\`, \`observed_at\` (UTC)
- \`lat\`, \`lon\`, \`alt_m\`, \`heading\`, \`speed_ms\`, \`aircraft_type\`
- \`is_demo\` source flag; data is explicitly provenance-marked
- \`claimed_identity\` optional, NEVER trusted as binding by itself

Production-grade ingestion additionally requires: measurement clock/time uncertainty,
source device attestation/authorization, geospatial uncertainty and sensor-specific
metadata. **Open — not in v0.1.**

## 3. Three-field state model

Identity = \`verified | unverified | unavailable\`
Association = \`corroborated | ambiguous | contradicted\`
Authorization = \`permitted | not_established | denied\`

All three dimensions apply to PUF, secure-element and software credentials.
Never infer authorization from valid cryptographic signatures.
Never infer track binding from authentication alone.
One identity may be confidently associated with at most one independently resolved
physical aircraft track at a decision instant. Split/duplicate sensors must be
resolved upstream; any ambiguous match must remain inconclusive.

v0.1 stores these states, but DOES NOT implement automatic sensor fusion
or credible physical correlation. Demo states are synthetic.

## 4. Cryptographic identity protocol (implemented)

- Ed25519 registered raw 32-byte public key; private key never sent to GCS.
- Challenge: 16 bytes from OS CSPRNG, per identity, expires after 90 seconds.
- Domain-separated UTF-8 message:
  \`HROT-AirTrust/v1/identity-proof|{challenge_id}|{identity_id}|{nonce_base64}\`
- Verifier checks Ed25519 over exact transcript.
- Challenge consumed before verification; replays rejected.
- Revoked identity cannot start new sessions.
- Result is key-possession proof ONLY, without airframe/position assertion.
- Enrollment authority string and key-protection type are operator-declared,
  not X.509-validated or hardware-attested in v0.1.

v0.2 design must introduce verifier/operator authorization, rate limiting, formal
credential and issuer trust, canonical structured transcripts, batch concurrency
tests, stricter expiry semantics, and request tracing.

## 5. Beacon nonce and DRIP — OPEN, not implemented

Hypothesis: a site-signed rolling nonce broadcast can provide freshness input to
compatible participating drones, but cannot prove proximity, defeat relay, or
make unsupported third-party drones accept requests.

Study ASTM F3411, RFC 9374 DET, RFC 9575 DRIP authentication formats and actual
device compatibility before deciding whether the nonce can be standardized or
must be an explicitly documented HROT extension.
Continuous signing is incompatible with the earlier NUCLEO limited-signature
lifecycle unless a separate signing architecture is demonstrated.

No invented claims such as "100 drones supported" before airtime/load tests.

## 6. Evidence schema and controls (partial implementation)

\`EvidenceEntry\`:
\`seq, timestamp, kind, detail, severity, source, prev_hash, hash\`.
SHA-256 over canonical sorted JSON event fields, prev_hash included.

v0.1: append-only application workflow and local verify/export implemented.
Outstanding: external signed hash anchors, independent host, secure clock,
privilege separation, append-only storage and incident chain of custody.

## 7. Real physical correlation — EXPERIMENT, not product feature

Candidate onboard evidence: credential module with its own GNSS, IMU, barometer
and key, signing timestamps/position/motion. Compare to calibrated independent
camera/radar trajectories with uncertainty. Signed kinematics are still vulnerable
to compromised sensors, GNSS spoofing and module transfer.

Design test fixture using 2 calibrated cameras, 2 moving physical targets,
independent RTK-quality reference, controlled relays and measured time synchronization.
No simulated tracks may count toward physical-validation claims.
No ground-truth antenna sharing with the test module; do not hand-label tracks;
score every ambiguous result and failure.

Metrics: correct/false association, inconclusive rate, relay detection by
separation, latency and sensor conditions. No fixed % targets before trials.

## 8. Workstream gates

G0: Customer/security workflow interview; Indian Remote ID passive survey;
receive-only spectrum survey; sensor API inventory.
G1: Core verification, API, evidence, operator UX. **v0.1 implemented**.
G2: Real sensors and physically tracked association experiment.
G3: DRIP/nonce/PUF hardware lifecycle and RF channel qualification.
G4: Authorized site pilots, uptime, false alarms, operator and buyer validation.

At each stage, new data decides architecture. Industry product/defense readiness
MUST NOT be inferred from G1.

## 9. Nonfunctional quality

- Local-first, standalone browser UI; no mandatory external CDNs for function.
- Seeded fixtures visibly marked, entirely absent from fresh live databases.
- Fixed-dimensional identity/association/authorization statuses.
- Explicit source provenance on every observation.
- Fail closed on untrusted cryptographic proof, invalid key and revocation.
- Dedicated authentication and least-privilege operations required before deployment.
- No auto-arming/control links to a flight controller.
