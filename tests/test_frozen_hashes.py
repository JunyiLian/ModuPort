from __future__ import annotations

import hashlib
from pathlib import Path
import unittest


class FrozenSourceHashTests(unittest.TestCase):
    def test_all_authoritative_sources_match(self):
        root = Path(__file__).resolve().parents[1]
        records = []
        for line in (root / "provenance" / "FROZEN_SOURCE_SHA256.txt").read_text(encoding="utf-8").splitlines():
            if not line or line.startswith("#"):
                continue
            expected, relative = line.split(maxsplit=1)
            source = root / relative
            actual = hashlib.sha256(source.read_bytes()).hexdigest()
            records.append(relative)
            self.assertEqual(actual, expected, relative)
        self.assertEqual(len(records), 26)


if __name__ == "__main__":
    unittest.main()
