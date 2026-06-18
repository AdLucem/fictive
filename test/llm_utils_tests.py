import argparse
from pathlib import Path
import unittest

from llm_utils import RequestConfig, args_to_request_config


def make_args(**overrides):
    defaults = {
        "model": "demo-model",
        "host": "localhost",
        "port": 30000,
        "temperature": 0.25,
        "max_tokens": 512,
        "timeout": 60,
        "log_level": "INFO",
        "prompt_file": Path("/tmp/prompt.txt"),
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class ArgsToRequestConfigTests(unittest.TestCase):
    def test_builds_request_config(self):
        args = make_args()

        cfg = args_to_request_config(args)

        self.assertEqual(
            cfg,
            RequestConfig(
                model="demo-model",
                host="localhost",
                port=30000,
                temperature=0.25,
                max_new_tokens=512,
                timeout=60,
                log_level="INFO",
                prompt_file=Path("/tmp/prompt.txt"),
            ),
        )

    def test_rejects_invalid_values(self):
        cases = [
            ({"port": 0}, "--port must be between 1 and 65535."),
            ({"port": 65536}, "--port must be between 1 and 65535."),
            ({"max_tokens": 0}, "--max-tokens must be > 0."),
            ({"timeout": 0}, "--timeout must be > 0."),
        ]

        for overrides, message in cases:
            with self.subTest(overrides=overrides):
                args = make_args(**overrides)
                with self.assertRaisesRegex(ValueError, message):
                    args_to_request_config(args)
