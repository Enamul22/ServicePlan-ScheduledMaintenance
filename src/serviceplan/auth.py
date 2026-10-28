"""Local demonstration credentials and opaque sessions; no editable role assertion is trusted."""

import argparse
import getpass
import hashlib
import hmac
import secrets
from pydantic import BaseModel, model_validator
from typing import Literal


class UserConfig(BaseModel):
    user_id: str
    email: str
    display_name: str
    role: Literal["admin", "customer"]
    customer_id: str | None = None
    password_hash: str

    @model_validator(mode="after")
    def check(self):
        if self.role == "customer" and not self.customer_id:
            raise ValueError("Customer identity requires an assigned customer ID")
        if not self.password_hash.startswith("pbkdf2_sha256$"):
            raise ValueError("Use a generated PBKDF2 password hash")
        return self


def hash_password(password):
    salt = secrets.token_hex(16)
    iterations = 210000
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), iterations).hex()
    return f"pbkdf2_sha256${iterations}${salt}${digest}"


def verify_password(password, encoded):
    try:
        algorithm, iterations, salt, digest = encoded.split("$")
        if algorithm != "pbkdf2_sha256" or not 100000 <= int(iterations) <= 2000000:
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iterations)).hex()
        return hmac.compare_digest(digest, actual)
    except (ValueError, TypeError):
        return False


if __name__ == "__main__":
    argparse.ArgumentParser(
        description="Generate a hash for private serviceplan user configuration"
    ).parse_args()
    print(hash_password(getpass.getpass("New local demo password: ")))
