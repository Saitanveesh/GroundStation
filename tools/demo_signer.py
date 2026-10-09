"""Generate a software Ed25519 signer and exercise the HROT verification API.

LAB TOOL ONLY: a generated file-backed key is NOT a PUF or secure element.
Usage:
  python tools/demo_signer.py --url http://127.0.0.1:8765 --id LAB-KEY-01
Optional HROT_ADMIN_TOKEN is read from the environment.
"""
import argparse
import base64
import json
import os
import pathlib
import secrets
import urllib.error
import urllib.request

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def request(base, path, payload, token):
    headers={"Content-Type":"application/json"}
    if token:
        headers["X-HROT-Token"]=token
    req=urllib.request.Request(
        base.rstrip("/")+"/api"+path,
        data=json.dumps(payload).encode(),
        headers=headers,method="POST"
    )
    try:
        with urllib.request.urlopen(req,timeout=10) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"HTTP {error.code}: {error.read().decode()}") from error


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--url",default="http://127.0.0.1:8765")
    parser.add_argument("--id",default="LAB-SOFTWARE-01")
    parser.add_argument("--save-key",type=pathlib.Path,help="Optional private key file, outside repository")
    args=parser.parse_args()
    token=os.getenv("HROT_ADMIN_TOKEN","")
    key=Ed25519PrivateKey.generate()
    public=base64.b64encode(key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw
    )).decode()
    if args.save_key:
        path=args.save_key.expanduser().resolve()
        if path.exists():
            raise SystemExit("Refusing to overwrite an existing private key")
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,"wb") as output:
            output.write(key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption()
            ))
        print("LAB private key saved locally:",path)

    print("Enrolling lab SOFTWARE key (not PUF):",args.id)
    request(args.url,"/identities",{
        "id":args.id,"label":"Lab software signer","issuer":"Local lab operator",
        "public_key":public,"protection_claim":"software_declared"
    },token)
    challenge=request(args.url,"/verify/challenge",{"identity_id":args.id},token)
    signature=base64.b64encode(key.sign(challenge["transcript"].encode())).decode()
    proof=request(args.url,"/verify/complete",{
        "challenge_id":challenge["challenge_id"],
        "signature":signature
    },token)
    print(json.dumps(proof,indent=2))
    assert proof["verified"] and not proof["physical_track_bound"]
    print("PASS: real Ed25519 proof; physical aircraft identity remains unproven.")


if __name__=="__main__":
    main()
