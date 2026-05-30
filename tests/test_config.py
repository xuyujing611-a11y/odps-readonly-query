import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from report_doctor.config import load_dataworks_settings, load_settings


class LoadSettingsTests(unittest.TestCase):
    def test_loads_required_values_from_env_file_without_overwriting_process_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text(
                "\n".join(
                    [
                        "ALIBABA_CLOUD_ACCESS_KEY_ID=file-ak",
                        "ALIBABA_CLOUD_ACCESS_KEY_SECRET=file-sk",
                        "ODPS_PROJECT=file-project",
                        "ODPS_ENDPOINT=https://example.aliyun.com/api",
                    ]
                ),
                encoding="utf-8",
            )

            with patch.dict(
                os.environ,
                {"ODPS_PROJECT": "process-project"},
                clear=False,
            ):
                settings = load_settings(env_path)

        self.assertEqual(settings.access_id, "file-ak")
        self.assertEqual(settings.secret_access_key, "file-sk")
        self.assertEqual(settings.project, "process-project")
        self.assertEqual(settings.endpoint, "https://example.aliyun.com/api")

    def test_missing_required_values_are_reported_together(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text("ODPS_PROJECT=p\n", encoding="utf-8")

            with patch.dict(os.environ, {}, clear=True):
                with self.assertRaisesRegex(ValueError, "ALIBABA_CLOUD_ACCESS_KEY_ID.*ODPS_ENDPOINT"):
                    load_settings(env_path)

    def test_load_dataworks_settings_defaults_to_user_region_and_prod(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text(
                "\n".join(
                    [
                        "ALIBABA_CLOUD_ACCESS_KEY_ID=file-ak",
                        "ALIBABA_CLOUD_ACCESS_KEY_SECRET=file-sk",
                        "ODPS_PROJECT=yh_doc_cdm",
                        "ODPS_ENDPOINT=https://example.aliyun.com/api",
                    ]
                ),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {}, clear=True):
                settings = load_dataworks_settings(env_path)

        self.assertEqual(settings.access_id, "file-ak")
        self.assertEqual(settings.secret_access_key, "file-sk")
        self.assertEqual(settings.region, "cn-beijing")
        self.assertEqual(settings.project_env, "PROD")
        self.assertEqual(settings.endpoint, "dataworks.cn-beijing.aliyuncs.com")
        self.assertEqual(settings.api_version, "2020-05-18")


if __name__ == "__main__":
    unittest.main()
