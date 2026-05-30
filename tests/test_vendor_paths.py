import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from report_doctor.vendor_paths import iter_vendor_paths


class VendorPathsTests(unittest.TestCase):
    def test_vendor_runtime_is_preferred_before_legacy_vendor(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "vendor").mkdir()
            (root / "vendor_runtime").mkdir()

            with patch("report_doctor.vendor_paths.project_root", return_value=root):
                paths = list(iter_vendor_paths())

        self.assertEqual(paths, [root / "vendor_runtime", root / "vendor"])


if __name__ == "__main__":
    unittest.main()
