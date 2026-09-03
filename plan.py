"""Encrypt plan.data.json into plan.html. Run: python plan.py [password]

The blob is AES-GCM with a PBKDF2 key, so the page holds no readable transcript and
no password to compare against — a wrong password just fails to decrypt.
Re-run with a new password any time; it rewrites the same line.
"""
import base64, getpass, json, os, re, sys
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

ITER = 200_000                                  # must match the iterations in plan.html
b64 = lambda b: base64.b64encode(b).decode()

pw = sys.argv[1] if len(sys.argv) > 1 else getpass.getpass("password: ")
data = json.dumps(json.load(open("plan.data.json", encoding="utf-8")), separators=(",", ":")).encode()

salt, iv = os.urandom(16), os.urandom(12)
key = PBKDF2HMAC(algorithm=SHA256(), length=32, salt=salt, iterations=ITER).derive(pw.encode())
blob = ".".join(map(b64, (salt, iv, AESGCM(key).encrypt(iv, data, None))))

html = open("plan.html", encoding="utf-8").read()
html, n = re.subn(r'(const ENC=")[^"]*(")', lambda m: m.group(1) + blob + m.group(2), html, count=1)
assert n == 1, "plan.html has no `const ENC=\"...\"` line to write into"
open("plan.html", "w", encoding="utf-8", newline="\n").write(html)
print(f"encrypted {len(data)} bytes -> plan.html ({len(blob)} b64 chars)")
