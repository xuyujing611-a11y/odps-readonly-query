from __future__ import annotations

from getpass import getpass
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from report_doctor.encrypted_config import encrypt_env_text


def main() -> int:
    env_path = ROOT / ".env"
    enc_path = ROOT / ".env.enc"
    if not env_path.exists():
        print(f"ERROR: {env_path} does not exist.", file=sys.stderr)
        return 1

    password = getpass("New password for .env.enc: ")
    confirm = getpass("Confirm password: ")
    if password != confirm:
        print("ERROR: passwords do not match.", file=sys.stderr)
        return 1

    encrypted = encrypt_env_text(env_path.read_text(encoding="utf-8"), password)
    enc_path.write_text(encrypted, encoding="utf-8")
    enc_path.chmod(0o400)
    print(f"Encrypted config written: {enc_path}")

    answer = input("Delete plaintext .env now? Type YES to delete: ").strip()
    if answer == "YES":
        env_path.unlink()
        print("Plaintext .env deleted.")
    else:
        print("Plaintext .env kept. Delete it manually when you have verified .env.enc works.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
