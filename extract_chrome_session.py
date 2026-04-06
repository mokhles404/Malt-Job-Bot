"""
Extract Malt session cookies from a running Chrome browser.

Reads the Cookies SQLite database, decrypts values using the macOS Keychain
key, and writes malt_state.json — no new browser window required.

Usage:
    python extract_chrome_session.py          # creates malt_state.json
    python extract_chrome_session.py --force  # overwrite existing file
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

STATE_FILE = "malt_state.json"


# --------------------------------------------------------------------------- #
# macOS Chrome cookie decryption
# --------------------------------------------------------------------------- #

def _get_macos_chrome_key() -> bytes:
    """Retrieve the Chrome Safe Storage password from the macOS Keychain."""
    result = subprocess.run(
        ["security", "find-generic-password", "-ga", "Chrome", "-w"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "Could not read 'Chrome Safe Storage' from Keychain. "
            "Make sure Chrome has been launched at least once.\n"
            f"stderr: {result.stderr.strip()}"
        )
    return result.stdout.strip().encode("utf-8")


def _derive_aes_key(password: bytes) -> bytes:
    return hashlib.pbkdf2_hmac(
        "sha1",
        password,
        b"saltysalt",
        1003,
        dklen=16,
    )


_CHROME_INTERNAL_HEADER_LEN = 32


def _decrypt_cookie_value(encrypted: bytes, aes_key: bytes) -> str:
    if not encrypted:
        return ""
    if encrypted[:3] in (b"v10", b"v11"):
        encrypted = encrypted[3:]
    else:
        return encrypted.decode("utf-8", errors="replace")

    iv = b" " * 16
    cipher = Cipher(algorithms.AES(aes_key), modes.CBC(iv))
    decryptor = cipher.decryptor()
    decrypted = decryptor.update(encrypted) + decryptor.finalize()
    padding_len = decrypted[-1]
    if 1 <= padding_len <= 16:
        decrypted = decrypted[:-padding_len]
    # Chrome wraps values in a fixed-length internal header before encrypting.
    if len(decrypted) > _CHROME_INTERNAL_HEADER_LEN:
        decrypted = decrypted[_CHROME_INTERNAL_HEADER_LEN:]
    return decrypted.decode("utf-8", errors="replace")


# --------------------------------------------------------------------------- #
# Cookie extraction
# --------------------------------------------------------------------------- #

_CHROME_PROFILE = os.path.expanduser(
    "~/Library/Application Support/Google/Chrome/Default"
)

_MALT_DOMAINS = (".malt.fr", "www.malt.fr", "malt.fr")


def _chrome_epoch_to_unix(chrome_ts: int) -> float:
    """Chrome stores timestamps as microseconds since 1601-01-01."""
    if chrome_ts == 0:
        return -1
    return (chrome_ts / 1_000_000) - 11644473600


def extract_malt_cookies() -> list[dict]:
    if platform.system() != "Darwin":
        raise RuntimeError("Automatic cookie extraction is only supported on macOS.")

    cookies_db = os.path.join(_CHROME_PROFILE, "Cookies")
    if not os.path.isfile(cookies_db):
        raise FileNotFoundError(
            f"Chrome cookies database not found at {cookies_db}. "
            "Is Chrome installed and has been launched at least once?"
        )

    password = _get_macos_chrome_key()
    aes_key = _derive_aes_key(password)

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    tmp.close()
    try:
        shutil.copy2(cookies_db, tmp.name)
        conn = sqlite3.connect(tmp.name)
        rows = conn.execute(
            "SELECT host_key, name, encrypted_value, path, "
            "       is_secure, is_httponly, expires_utc, samesite "
            "FROM cookies WHERE host_key LIKE '%malt%'"
        ).fetchall()
        conn.close()
    finally:
        os.unlink(tmp.name)

    if not rows:
        raise RuntimeError(
            "No Malt cookies found in Chrome. "
            "Open Chrome, log in to https://www.malt.fr, then run this again."
        )

    cookies = []
    for host, name, enc_val, path, secure, httponly, expires_utc, samesite in rows:
        if not any(host.endswith(d) or host == d for d in _MALT_DOMAINS):
            continue

        value = _decrypt_cookie_value(enc_val, aes_key)

        domain = host if host.startswith(".") else host
        sameSite = {0: "None", 1: "Lax", 2: "Strict"}.get(samesite, "None")

        cookie: dict = {
            "name": name,
            "value": value,
            "domain": domain,
            "path": path,
            "secure": bool(secure),
            "httpOnly": bool(httponly),
            "sameSite": sameSite,
        }
        exp = _chrome_epoch_to_unix(expires_utc)
        if exp > 0:
            cookie["expires"] = exp

        cookies.append(cookie)

    return cookies


def build_storage_state(cookies: list[dict]) -> dict:
    return {
        "cookies": cookies,
        "origins": [],
    }


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract Malt session from your running Chrome."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=f"Overwrite {STATE_FILE} if it already exists.",
    )
    args = parser.parse_args()

    state_path = Path(STATE_FILE)
    if state_path.exists() and not args.force:
        print(
            f"{STATE_FILE} already exists. Use --force to overwrite.",
            file=sys.stderr,
        )
        sys.exit(0)

    print("Reading Chrome cookies for malt.fr ...")
    cookies = extract_malt_cookies()
    print(f"Found {len(cookies)} Malt cookies.")

    state = build_storage_state(cookies)
    state_path.write_text(json.dumps(state, indent=2))
    print(f"Saved to {state_path.resolve()}")
    print("You can now run: python malt_bot.py")


if __name__ == "__main__":
    main()
