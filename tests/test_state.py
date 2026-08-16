import unittest

from scripts.state import decrypt_refresh_token, encrypt_refresh_token


class StateTests(unittest.TestCase):
    def test_authenticated_refresh_token_encryption_roundtrip(self):
        encrypted = encrypt_refresh_token("refresh-value", "client-secret")
        self.assertNotIn(b"refresh-value", encrypted)
        self.assertEqual(decrypt_refresh_token(encrypted, "client-secret"), "refresh-value")

    def test_wrong_secret_rejected(self):
        encrypted = encrypt_refresh_token("refresh-value", "client-secret")
        with self.assertRaisesRegex(ValueError, "cannot be decrypted"):
            decrypt_refresh_token(encrypted, "different-secret")


if __name__ == "__main__":
    unittest.main()
