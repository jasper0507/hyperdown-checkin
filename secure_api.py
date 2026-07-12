"""Hyperdown secure request sealing (RE from client v1.1.3).

Verified against Hyperdown.exe secureapi symbols:

deriveKey:
  material = nonce_hex + ":" + fmt.Sprint(ts)
  salt     = SHA256(material)          # 32 bytes
  info     = "hyperdown-secure-api:v1:" + ToUpper(method) + ":" + normalize(path)
  key      = HKDF-SHA256(ikm=master_key, salt=salt, info=info, length=32)

associatedData (AAD for AEAD) — order is nonce BEFORE ts:
  ToUpper(method) + "\\n" + path + "\\n" + nonce_hex + "\\n" + fmt.Sprint(ts)

Seal:
  randomHex(16) -> nonce_hex (envelope anti-replay / KDF)
  randomBytes(24) -> XChaCha20-Poly1305 nonce
  ciphertext = XChaCha20-Poly1305.Seal(key, aead_nonce, body, aad)

Wire (RE + trial):
  Header: X-Hyperdown-Secure: v1
  Body: {ts, nonce, ciphertext, sign}
  nonce likely hex(16 random bytes)
  ciphertext likely base64(aead_nonce || sealed) or base64(sealed) / hex(sealed)
  sign = base64(HMAC-SHA256(key, sign_msg))
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
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

try:
    from nacl.bindings import crypto_aead_xchacha20poly1305_ietf_encrypt
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "缺少 PyNaCl，请先: pip install pynacl cryptography"
    ) from exc

_MASTER_KEY_HEX = (
    "dd85f63f107a32ce3def4835fe56c27865a1557fedad19adbd72ff81ea2e1025"
)
MASTER_KEY = bytes.fromhex(
    os.environ.get("HYPERDOWN_SECURE_MASTER_KEY", _MASTER_KEY_HEX)
)
SALT_PREFIX = b"hyperdown-secure-api:v1:"
SECURE_HEADER = "v1"

# Primary RE hypothesis; override via env for probes.
KDF_VARIANT = os.environ.get("HYPERDOWN_KDF_VARIANT", "re_primary")
WIRE_VARIANT = os.environ.get("HYPERDOWN_WIRE_VARIANT", "nonce_hex_ct_b64_n24ct")
SIGN_VARIANT = os.environ.get("HYPERDOWN_SIGN_VARIANT", "v1_nl_method_path_nonce_ts_ct")


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


def associated_data(method: str, path: str, ts: int, nonce_hex: str) -> bytes:
    """AAD bytes — RE order: method, path, nonce, ts (not ts before nonce)."""
    return (
        f"{method.upper()}\n{normalize_api_path(path)}\n{nonce_hex}\n{ts}"
    ).encode()


def derive_key(method: str, path: str, ts: int, nonce_hex: str) -> bytes:
    method_u = method.upper()
    path_n = normalize_api_path(path)
    material = f"{nonce_hex}:{ts}".encode()
    digest = hashlib.sha256(material).digest()
    info_primary = SALT_PREFIX + f"{method_u}:{path_n}".encode()

    variant = KDF_VARIANT
    if variant == "re_primary":
        salt, info = digest, info_primary
    elif variant == "salt_digest_info_method_path":
        salt, info = digest, f"{method_u}:{path_n}".encode()
    elif variant == "salt_prefix_info_digest":
        salt, info = SALT_PREFIX, digest
    elif variant == "salt_prefix_info_material":
        salt, info = SALT_PREFIX, material
    elif variant == "salt_prefix_info_method_path":
        salt, info = SALT_PREFIX, f"{method_u}:{path_n}".encode()
    elif variant == "salt_digest_info_empty":
        salt, info = digest, b""
    elif variant == "salt_prefix_info_empty":
        salt, info = SALT_PREFIX, b""
    else:
        raise ValueError(f"unknown KDF_VARIANT: {variant}")

    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        info=info,
    ).derive(MASTER_KEY)


def build_sign_message(
    method: str,
    path: str,
    ts: int,
    nonce_hex: str,
    ciphertext_field: str,
    *,
    aead_nonce_b64: str = "",
    nonce_field: str = "",
) -> bytes:
    method_u = method.upper()
    path_n = normalize_api_path(path)
    n_for_sign = nonce_field or nonce_hex
    v = SIGN_VARIANT
    if v == "v1_nl_method_path_nonce_ts_ct":
        # Match AAD field order after version prefix
        return f"v1\n{method_u}\n{path_n}\n{nonce_hex}\n{ts}\n{ciphertext_field}".encode()
    if v == "v1_nl_method_path_ts_nonce_ct":
        return f"v1\n{method_u}\n{path_n}\n{ts}\n{nonce_hex}\n{ciphertext_field}".encode()
    if v == "v1_nl_aad_ct":
        aad = associated_data(method_u, path_n, ts, nonce_hex)
        return b"v1\n" + aad + b"\n" + ciphertext_field.encode()
    if v == "v1_nl_method_path_nonce_ts_ct_aead":
        return (
            f"v1\n{method_u}\n{path_n}\n{nonce_hex}\n{ts}\n"
            f"{ciphertext_field}\n{aead_nonce_b64}"
        ).encode()
    if v == "v1_null_method_path_nonce_ts_ct":
        return (
            b"v1\x00"
            + method_u.encode()
            + b"\x00"
            + path_n.encode()
            + b"\x00"
            + nonce_hex.encode()
            + b"\x00"
            + str(ts).encode()
            + b"\x00"
            + ciphertext_field.encode()
        )
    if v == "v1_nl_method_path_nfield_ts_ct":
        return f"v1\n{method_u}\n{path_n}\n{n_for_sign}\n{ts}\n{ciphertext_field}".encode()
    raise ValueError(f"unknown SIGN_VARIANT: {v}")


def sign_envelope(key: bytes, msg: bytes) -> str:
    """HMAC-SHA256 then standard Base64 (client uses encoding/base64.EncodeToString)."""
    digest = hmac.new(key, msg, hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def seal_json(
    method: str,
    path: str,
    body: bytes | dict[str, Any] | None = None,
    *,
    ts: int | None = None,
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

    ts = int(time.time()) if ts is None else int(ts)
    nonce_hex = secrets.token_hex(16)
    aead_nonce = secrets.token_bytes(24)

    method_u = method.upper()
    path_n = normalize_api_path(path)
    key = derive_key(method_u, path_n, ts, nonce_hex)
    aad = associated_data(method_u, path_n, ts, nonce_hex)

    sealed = crypto_aead_xchacha20poly1305_ietf_encrypt(
        plaintext, aad, aead_nonce, key
    )
    aead_b64 = base64.b64encode(aead_nonce).decode()

    wire = WIRE_VARIANT
    if wire == "nonce_hex_ct_b64":
        nonce_field, ct_field = nonce_hex, base64.b64encode(sealed).decode()
    elif wire == "nonce_hex_ct_hex":
        nonce_field, ct_field = nonce_hex, sealed.hex()
    elif wire == "nonce_hex_ct_b64_n24ct":
        # AEAD nonce must reach the server somehow — prepend is the usual pattern
        nonce_field = nonce_hex
        ct_field = base64.b64encode(aead_nonce + sealed).decode()
    elif wire == "nonce_hex_ct_hex_n24ct":
        nonce_field = nonce_hex
        ct_field = (aead_nonce + sealed).hex()
    elif wire == "nonce_b64_ct_b64":
        nonce_field = aead_b64
        ct_field = base64.b64encode(sealed).decode()
    elif wire == "nonce_b64_ct_hex":
        nonce_field = aead_b64
        ct_field = sealed.hex()
    else:
        raise ValueError(f"unknown WIRE_VARIANT: {wire}")

    msg = build_sign_message(
        method_u,
        path_n,
        ts,
        nonce_hex,
        ct_field,
        aead_nonce_b64=aead_b64,
        nonce_field=nonce_field,
    )
    envelope = {
        "ts": ts,
        "nonce": nonce_field,
        "ciphertext": ct_field,
        "sign": sign_envelope(key, msg),
    }
    return envelope, {"X-Hyperdown-Secure": SECURE_HEADER}


def probe_matrix() -> list[tuple[str, str, str]]:
    """Return (kdf, wire, sign) combos worth trying."""
    kdfs = [
        "re_primary",
        "salt_digest_info_method_path",
        "salt_prefix_info_digest",
        "salt_prefix_info_material",
        "salt_prefix_info_method_path",
    ]
    wires = [
        "nonce_hex_ct_b64_n24ct",
        "nonce_hex_ct_b64",
        "nonce_hex_ct_hex",
        "nonce_b64_ct_b64",
        "nonce_hex_ct_hex_n24ct",
        "nonce_b64_ct_hex",
    ]
    signs = [
        "v1_nl_method_path_nonce_ts_ct",
        "v1_nl_method_path_ts_nonce_ct",
        "v1_nl_aad_ct",
        "v1_nl_method_path_nonce_ts_ct_aead",
        "v1_nl_method_path_nfield_ts_ct",
    ]
    # Prefer RE-primary combinations first
    out: list[tuple[str, str, str]] = []
    for k in kdfs:
        for w in wires:
            for s in signs:
                out.append((k, w, s))
    return out
