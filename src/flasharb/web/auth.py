import hashlib
import hmac
import secrets


def password_hash(password):
    if len(password) < 12:
        raise ValueError("Use at least 12 characters")
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 600000).hex()
    return f"pbkdf2:600000:{salt}:{digest}"


def verify_password(password, stored):
    try:
        _, rounds, salt, expected = stored.split(":")
        result = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt), int(rounds)
        ).hex()
        return hmac.compare_digest(result, expected)
    except (ValueError, TypeError):
        return False
