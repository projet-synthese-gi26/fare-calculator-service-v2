"""Test désactivé : évite les appels HTTP externes en CI."""

import unittest


class DisabledApiTest(unittest.TestCase):
    @unittest.skip("Disabled network-dependent test")
    def test_disabled(self):
        self.assertTrue(True)


if __name__ == "__main__":
    unittest.main()
