import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from report_doctor.config import load_settings
from report_doctor.encrypted_config import ConfigDecryptError, decrypt_env_text, encrypt_env_text


class EncryptedConfigTests(unittest.TestCase):
    def test_encrypts_and_decrypts_env_text_with_password(self):
        plaintext = "ALIBABA_CLOUD_ACCESS_KEY_ID=ak\nODPS_PROJECT=p\n"

        encrypted = encrypt_env_text(plaintext, "correct horse battery staple")
        decrypted = decrypt_env_text(encrypted, "correct horse battery staple")

        self.assertNotIn("ALIBABA_CLOUD_ACCESS_KEY_ID", encrypted)
        self.assertEqual(decrypted, plaintext)

    def test_wrong_password_fails_without_plaintext(self):
        encrypted = encrypt_env_text("ALIBABA_CLOUD_ACCESS_KEY_SECRET=sk\n", "right-password")

        with self.assertRaises(ConfigDecryptError):
            decrypt_env_text(encrypted, "wrong-password")

    def test_load_settings_uses_encrypted_env_when_plain_env_is_absent(self):
        env_text = "\n".join(
            [
                "ALIBABA_CLOUD_ACCESS_KEY_ID=ak",
                "ALIBABA_CLOUD_ACCESS_KEY_SECRET=sk",
                "ODPS_PROJECT=p",
                "ODPS_ENDPOINT=https://example.aliyun.com/api",
            ]
        )

        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            enc_path = Path(tmp) / ".env.enc"
            enc_path.write_text(encrypt_env_text(env_text, "pw"), encoding="utf-8")

            with patch.dict("os.environ", {}, clear=True):
                settings = load_settings(env_path, password_provider=lambda: "pw")

        self.assertEqual(settings.access_id, "ak")
        self.assertEqual(settings.secret_access_key, "sk")
        self.assertEqual(settings.project, "p")
        self.assertEqual(settings.endpoint, "https://example.aliyun.com/api")


if __name__ == "__main__":
    unittest.main()
