import os
from cryptography.fernet import Fernet

# Set up encryption key fallback
_key = os.getenv("ENCRYPTION_KEY")
if not _key:
    # Generate a consistent session key if none provided in environment
    _key = Fernet.generate_key().decode()

_fernet = Fernet(_key.encode())

def encrypt_token(token: str) -> str:
    """Encrypt a plain text token string."""
    if not token:
        return ""
    return _fernet.encrypt(token.encode()).decode()

def decrypt_token(encrypted_token: str) -> str:
    """Decrypt an encrypted token string."""
    if not encrypted_token:
        return ""
    return _fernet.decrypt(encrypted_token.encode()).decode()
