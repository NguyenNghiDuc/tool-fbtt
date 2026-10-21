import hashlib
import hmac
import os
import secrets


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def hash_password(password):
    salt = os.urandom(16)
    value = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)
    return salt.hex() + ':' + value.hex()


def check_password(password, stored):
    salt, value = stored.split(':')
    candidate = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1)
    return hmac.compare_digest(candidate.hex(), value)


def random_token():
    return secrets.token_urlsafe(32)


def totp(secret, at=None):
    import base64
    import struct
    import time
    counter = int(time.time() if at is None else at) // 30
    key = base64.b32decode(secret)
    value = hmac.new(key, struct.pack('>Q', counter), hashlib.sha1).digest()
    offset = value[-1] & 15
    number = (struct.unpack('>I', value[offset:offset + 4])[0] & 0x7fffffff) % 1000000
    return f'{number:06d}'


def verify_totp(secret, code, last_counter=-1):
    import time
    if not code or len(code) != 6 or not code.isdigit():
        return None
    now = int(time.time()) // 30
    for delta in (-1, 0, 1):
        counter = now + delta
        if counter > last_counter and hmac.compare_digest(totp(secret, counter * 30), code):
            return counter
    return None
