"""Utility functions for computing tokens for feedback links."""

from hashlib import sha256


def compute_feedback_token(inp: str, out: str, salt: str) -> str:
    """Compute a per-link token from input, output, and a secret salt.

    The token is SHA256 over the UTF-8 bytes of "{inp}|{out}|{salt}".
    """
    base = f"{inp}|{out}|{salt}".encode("utf-8")
    return sha256(base).hexdigest()
