from cryptography.fernet import Fernet

from personal_hermes.oauth.crypto import TokenCipher


def test_token_cipher_round_trips_without_plaintext_leakage():
    cipher = TokenCipher(Fernet.generate_key().decode("ascii"))

    encrypted = cipher.encrypt("refresh-token")

    assert encrypted != "refresh-token"
    assert cipher.decrypt(encrypted) == "refresh-token"
