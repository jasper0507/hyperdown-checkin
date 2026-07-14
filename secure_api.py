"""Hyperdown secure sealing — RE + capture 2026-07-14 + caller arg map.

Wire (official capture):
  v, request_id, ts, nonce, pub, ciphertext, sign
  nonce/ciphertext/sign = base64.RawURLEncoding (no padding)
  ciphertext len for {} = 18 bytes (no AEAD nonce prepended)
  pub = ephemeral X25519 public key (hex)

Crypto (SealJSON):
  eph = X25519.GenerateKey()
  shared = eph.ECDH(NewPublicKey(embedded_32B))  # embedded hex = peer PUBLIC key
  request_id = randomHex(16)
  key = HKDF-SHA256(shared, salt=SHA256(request_id+":"+ts),
                    info="hyperdown-secure-api:v1:"+METHOD+":"+path)
  aad = METHOD+"\\n"+path+"\\n"+request_id+"\\n"+ts
  sealed = XChaCha20-Poly1305.Seal(key, n24, body, aad)

Sign (signEnvelope + HTTP caller):
  SealJSON(method, path, accessToken, body)
  HMAC-SHA256(key, join_nul(
    "v1", METHOD, path, request_id, ts, nonce, pub, ciphertext, accessToken
  )) then RawURLEncoding
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

try:
    from nacl.bindings import (
        crypto_aead_xchacha20poly1305_ietf_encrypt,
        crypto_scalarmult,
    )
except ImportError as exc:  # pragma: no cover
    raise SystemExit("缺少 PyNaCl: pip install pynacl cryptography") from exc

# Client-embedded 32-byte peer public key (NewPublicKey), not a private seed
# and not an account credential. Override via HYPERDOWN_SECURE_PEER_PUB
# (legacy alias: HYPERDOWN_SECURE_MASTER_KEY).
_PEER_PUB_HEX = (
    "dd85f63f107a32ce3def4835fe56c27865a1557fedad19adbd72ff81ea2e1025"
)
PEER_PUBLIC_KEY = bytes.fromhex(
    os.environ.get("HYPERDOWN_SECURE_PEER_PUB")
    or os.environ.get("HYPERDOWN_SECURE_MASTER_KEY")
    or _PEER_PUB_HEX
)
SALT_PREFIX = b"hyperdown-secure-api:v1:"
SECURE_HEADER = "v1"

# Production defaults (verified 2026-07-14). Env overrides are debug-only.
KDF_VARIANT = os.environ.get("HYPERDOWN_KDF_VARIANT", "ecdh_re_primary")
SIGN_VARIANT = os.environ.get("HYPERDOWN_SIGN_VARIANT", "v3_token_nul")
B64_VARIANT = os.environ.get("HYPERDOWN_B64_VARIANT", "rawurl")
SIGN_SEP = os.environ.get("HYPERDOWN_SIGN_SEP", "nul")  # nul|nl


def b64encode_field(data: bytes) -> str:
    if B64_VARIANT == "rawurl":
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()
    if B64_VARIANT == "std":
        return base64.standard_b64encode(data).decode()
    if B64_VARIANT == "rawstd":
        return base64.standard_b64encode(data).rstrip(b"=").decode()
    raise ValueError(B64_VARIANT)


def is_sensitive_path(method: str, path: str) -> bool:
    if method.upper() != "POST":
        return False
    p = normalize_api_path(path)
    return p in {
        "/api/v1/me/checkins",
        "/api/v1/redemptions/redeem",
        "/api/v1/shares/parse",
        "/api/v1/shares/downloads/resolve",
        "/api/v1/downloads/resolve",
        "/api/code/redeem",
    }


def normalize_api_path(path: str) -> str:
    path = (path or "").split("?", 1)[0]
    if not path:
        return "/"
    if not path.startswith("/"):
        path = "/" + path
    return path


def associated_data(method: str, path: str, ts: int, request_id: str) -> bytes:
    return f"{method.upper()}\n{normalize_api_path(path)}\n{request_id}\n{ts}".encode()


def _ecdh_shared() -> tuple[bytes, str]:
    eph = x25519.X25519PrivateKey.generate()
    eph_priv = eph.private_bytes_raw()
    eph_pub = eph.public_key().public_bytes_raw()
    shared = crypto_scalarmult(eph_priv, PEER_PUBLIC_KEY)
    return shared, eph_pub.hex()


def derive_key(ikm: bytes, method: str, path: str, ts: int, request_id: str) -> bytes:
    method_u = method.upper()
    path_n = normalize_api_path(path)
    v = KDF_VARIANT
    if v in ("ecdh_re_primary", "re_primary"):
        material = f"{request_id}:{ts}".encode()
        salt = hashlib.sha256(material).digest()
        info = SALT_PREFIX + f"{method_u}:{path_n}".encode()
        return HKDF(hashes.SHA256(), 32, salt, info).derive(ikm)
    if v == "ecdh_raw":
        return ikm if len(ikm) == 32 else hashlib.sha256(ikm).digest()
    if v == "ecdh_sha256":
        return hashlib.sha256(ikm).digest()
    if v == "ecdh_ts_first":
        material = f"{ts}:{request_id}".encode()
        salt = hashlib.sha256(material).digest()
        info = SALT_PREFIX + f"{method_u}:{path_n}".encode()
        return HKDF(hashes.SHA256(), 32, salt, info).derive(ikm)
    raise ValueError(v)


def _sep() -> bytes:
    return b"\x00" if SIGN_SEP == "nul" else b"\n"


def build_sign_message(
    method: str,
    path: str,
    ts: int,
    request_id: str,
    nonce_field: str,
    pub: str,
    ciphertext: str,
    access_token: str = "",
) -> bytes:
    method_u = method.upper()
    path_n = normalize_api_path(path)
    sep = _sep()
    v = SIGN_VARIANT

    def join(parts: list[str]) -> bytes:
        return sep.join(p.encode() for p in parts)

    if v == "v3_token_nul":
        # method, path, envelope fields, then access token (SealJSON 3rd arg).
        # Always append the token field (may be empty) to match join(..., token).
        return join(
            [
                "v1",
                method_u,
                path_n,
                request_id,
                str(ts),
                nonce_field,
                pub,
                ciphertext,
                access_token or "",
            ]
        )
    if v == "v3_token_bearer":
        parts = [
            "v1",
            method_u,
            path_n,
            request_id,
            str(ts),
            nonce_field,
            pub,
            ciphertext,
            f"Bearer {access_token}" if access_token else "",
        ]
        return join(parts)
    if v == "v3_token_early":
        parts = [
            "v1",
            method_u,
            path_n,
            access_token or "",
            request_id,
            str(ts),
            nonce_field,
            pub,
            ciphertext,
        ]
        return join(parts)
    if v == "v2_nul_full":
        return join(
            ["v1", method_u, path_n, request_id, str(ts), nonce_field, pub, ciphertext]
        )
    if v == "v2_nl_full":
        return "\n".join(
            ["v1", method_u, path_n, request_id, str(ts), nonce_field, pub, ciphertext]
        ).encode()
    raise ValueError(v)


def seal_json(
    method: str,
    path: str,
    body: bytes | dict[str, Any] | None = None,
    *,
    ts: int | None = None,
    access_token: str = "",
) -> tuple[dict[str, Any], dict[str, str]]:
    if body is None:
        plaintext = b"{}"
    elif isinstance(body, (dict, list)):
        plaintext = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode()
    elif isinstance(body, str):
        plaintext = body.encode()
    else:
        plaintext = body
    if not plaintext:
        plaintext = b"{}"

    # Allow token from env for probes / systemd if not passed
    if not access_token:
        access_token = os.environ.get("HYPERDOWN_ACCESS_TOKEN", "")

    ts = int(time.time()) if ts is None else int(ts)
    request_id = secrets.token_hex(16)
    aead_nonce = secrets.token_bytes(24)

    method_u = method.upper()
    path_n = normalize_api_path(path)

    shared, pub_hex = _ecdh_shared()
    key = derive_key(shared, method_u, path_n, ts, request_id)
    aad = associated_data(method_u, path_n, ts, request_id)
    sealed = crypto_aead_xchacha20poly1305_ietf_encrypt(
        plaintext, aad, aead_nonce, key
    )

    nonce_field = b64encode_field(aead_nonce)
    ct_field = b64encode_field(sealed)
    msg = build_sign_message(
        method_u,
        path_n,
        ts,
        request_id,
        nonce_field,
        pub_hex,
        ct_field,
        access_token=access_token,
    )
    sig = b64encode_field(hmac.new(key, msg, hashlib.sha256).digest())

    envelope = {
        "v": "v1",
        "request_id": request_id,
        "ts": ts,
        "nonce": nonce_field,
        "pub": pub_hex,
        "ciphertext": ct_field,
        "sign": sig,
    }
    return envelope, {"X-Hyperdown-Secure": SECURE_HEADER}
