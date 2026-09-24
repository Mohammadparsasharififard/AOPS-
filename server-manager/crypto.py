"""Encryption layer for SSH credentials.

Design:
1. On first run, generate an asymmetric keypair (PyNaCl sealed box).
2. The private key is encrypted with the master password (symmetric, via
   PyNaCl SecretBox — the key is derived from the master password via
   Argon2 / scrypt).
3. SSH passwords / private keys are encrypted with the PUBLIC key (sealed
   box) — only the private key can decrypt them.
4. The private key is only loaded into memory after the user enters the
   master password. The private key is NEVER written to disk in plaintext.

This means: even if someone steals the DB or the keypair.json, they cannot
decrypt the SSH credentials without the master password.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
from typing import Optional

import bcrypt
import nacl.secret
import nacl.utils
from nacl.public import PrivateKey, PublicKey, SealedBox

from config import get_settings


# --- Master password hashing (verification) ------------------------------------

def hash_master_password(plain: str) -> str:
    """Bcrypt hash of the master password — stored in DB / .env for verification."""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_master_password(plain: str, hash_str: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hash_str.encode("utf-8"))
    except Exception:
        return False


# --- Master password derivation for symmetric encryption of the private key ----

def _derive_symmetric_key(master_password: str, salt: bytes) -> bytes:
    """Derive a 32-byte symmetric key from the master password.

    Using hashlib.scrypt (built-in, no extra deps) — N=2^15, r=8, p=1.
    Memory usage: roughly 128 * r * N = ~32 MB. maxmem is set to 128 MB
    to give plenty of headroom.
    """
    return hashlib.scrypt(
        master_password.encode("utf-8"),
        salt=salt,
        n=2 ** 15,
        r=8,
        p=1,
        maxmem=128 * 1024 * 1024,
        dklen=32,
    )


# --- Keypair management -------------------------------------------------------

def generate_keypair(master_password: str) -> tuple[bytes, bytes]:
    """Generate a new asymmetric keypair.

    Returns (private_key_bytes, public_key_bytes) — but the private key is
    encrypted with the master password before being saved.
    """
    sk = PrivateKey.generate()
    pk = sk.public_key
    return bytes(sk), bytes(pk)


def save_keypair(private_key_bytes: bytes, public_key_bytes: bytes, master_password: str) -> None:
    """Save the keypair to disk. The private key is encrypted with the master password."""
    settings = get_settings()
    salt = nacl.utils.random(16)
    sym_key = _derive_symmetric_key(master_password, salt)
    box = nacl.secret.SecretBox(sym_key)
    encrypted_private = box.encrypt(private_key_bytes)
    payload = {
        "version": 1,
        "salt_b64": base64.b64encode(salt).decode("ascii"),
        "encrypted_private_b64": base64.b64encode(encrypted_private).decode("ascii"),
        "public_b64": base64.b64encode(public_key_bytes).decode("ascii"),
    }
    settings.keypair_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    # Restrict file permissions
    os.chmod(settings.keypair_path, 0o600)


def load_public_key() -> Optional[bytes]:
    """Load only the public key — no master password needed."""
    settings = get_settings()
    if not settings.keypair_path.is_file():
        return None
    payload = json.loads(settings.keypair_path.read_text(encoding="utf-8"))
    return base64.b64decode(payload["public_b64"])


def load_private_key(master_password: str) -> Optional[bytes]:
    """Load and decrypt the private key with the master password.

    Returns None if keypair file missing or password wrong.
    """
    settings = get_settings()
    if not settings.keypair_path.is_file():
        return None
    payload = json.loads(settings.keypair_path.read_text(encoding="utf-8"))
    salt = base64.b64decode(payload["salt_b64"])
    encrypted_private = base64.b64decode(payload["encrypted_private_b64"])
    sym_key = _derive_symmetric_key(master_password, salt)
    box = nacl.secret.SecretBox(sym_key)
    try:
        return box.decrypt(encrypted_private)
    except Exception:
        return None


# --- Credential encryption (sealed box) --------------------------------------

def encrypt_credential(plaintext: str) -> str:
    """Encrypt an SSH password / private key string with the public key.

    Returns base64 ciphertext. Can only be decrypted with the private key,
    which is only available while the master password is in memory.
    """
    public_key_bytes = load_public_key()
    if public_key_bytes is None:
        raise RuntimeError("Keypair not initialized. Run `server-manager init` first.")
    pk = PublicKey(public_key_bytes)
    box = SealedBox(pk)
    encrypted = box.encrypt(plaintext.encode("utf-8"))
    return base64.b64encode(encrypted).decode("ascii")


def decrypt_credential(ciphertext_b64: str, master_password: str) -> Optional[str]:
    """Decrypt an encrypted credential. Returns None on failure (wrong password, etc)."""
    private_key_bytes = load_private_key(master_password)
    if private_key_bytes is None:
        return None
    sk = PrivateKey(private_key_bytes)
    box = SealedBox(sk)
    try:
        decrypted = box.decrypt(base64.b64decode(ciphertext_b64))
        return decrypted.decode("utf-8")
    except Exception:
        return None
