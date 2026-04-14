"""WikiOracle ZIP encryption helpers.

Uses pyzipper to create and read AES-256 encrypted ZIP archives.
Each archive contains a single XML file (config.xml or state.xml).
"""

from __future__ import annotations

import io

import pyzipper


def build_encrypted_zip(inner_name: str, inner_bytes: bytes, password: str) -> bytes:
    """Create an AES-256 encrypted ZIP containing one file.

    Returns the ZIP archive as raw bytes (suitable for upload).
    """
    buf = io.BytesIO()
    with pyzipper.AESZipFile(
        buf, "w",
        compression=pyzipper.ZIP_DEFLATED,
        encryption=pyzipper.WZ_AES,
    ) as zf:
        zf.setpassword(password.encode("utf-8"))
        zf.setencryption(pyzipper.WZ_AES, nbits=256)
        zf.writestr(inner_name, inner_bytes)
    return buf.getvalue()


def read_encrypted_zip(zip_bytes: bytes, inner_name: str, password: str) -> bytes:
    """Decrypt an AES-256 encrypted ZIP and return the named member's bytes.

    Raises ``RuntimeError`` if the password is wrong.
    """
    buf = io.BytesIO(zip_bytes)
    with pyzipper.AESZipFile(buf, "r") as zf:
        zf.setpassword(password.encode("utf-8"))
        return zf.read(inner_name)
