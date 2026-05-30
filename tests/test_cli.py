import unittest

from report_doctor.cli import build_parser


class CliTests(unittest.TestCase):
    def test_script_style_global_options_are_accepted_after_subcommand(self):
        parser = build_parser()
        args = parser.parse_args(["test-connection", "--env", "local.env", "--json"])

        self.assertEqual(args.command, "test-connection")
        self.assertEqual(args.env, "local.env")
        self.assertTrue(args.json)


if __name__ == "__main__":
    unittest.main()
