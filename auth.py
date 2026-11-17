import hashlib
import hmac
import os
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).with_name("users.db")
ITERASI = 200_000
USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,20}$")


@contextmanager
def _db():
    conn = sqlite3.connect(DB_PATH)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with _db() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                nama_lengkap TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                dibuat TEXT DEFAULT CURRENT_TIMESTAMP
            )"""
        )


def _hash_password(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERASI).hex()


def register_user(username, nama, password, konfirmasi):
    """Return (berhasil: bool, pesan: str)."""
    username, nama = (username or "").strip(), (nama or "").strip()

    if not USERNAME_RE.match(username):
        return False, "Username harus 3-20 karakter: huruf, angka, atau underscore."
    if not nama:
        return False, "Nama lengkap wajib diisi."
    if len(password or "") < 6:
        return False, "Password minimal 6 karakter."
    if password != konfirmasi:
        return False, "Konfirmasi password tidak sama."

    salt = os.urandom(16)
    try:
        with _db() as conn:
            conn.execute(
                "INSERT INTO users (username, nama_lengkap, password_hash, salt) VALUES (?, ?, ?, ?)",
                (username, nama, _hash_password(password, salt), salt.hex()),
            )
    except sqlite3.IntegrityError:
        return False, "Username sudah dipakai, coba yang lain."
    return True, "Pendaftaran berhasil! Silakan login di tab Login."


def login_user(username, password):
    """Return (berhasil: bool, data_user: dict | None)."""
    with _db() as conn:
        row = conn.execute(
            "SELECT username, nama_lengkap, password_hash, salt FROM users WHERE username = ?",
            ((username or "").strip(),),
        ).fetchone()

    if row is None:
        _hash_password(password or "", bytes(16))  # samakan waktu proses
        return False, None

    uname, nama, hash_tersimpan, salt_hex = row
    hash_input = _hash_password(password or "", bytes.fromhex(salt_hex))
    if hmac.compare_digest(hash_input, hash_tersimpan):
        return True, {"username": uname, "nama": nama}
    return False, None


init_db()
