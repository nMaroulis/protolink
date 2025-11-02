"""Unit tests for the security module in the Protolink A2A library."""

import base64
import json
import time
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from protolink.security import (
    APIKeyAuthenticator,
    AuthToken,
    CryptoError,
    KeyManager,
    KeyPair,
    KeyType,
    KeyUsage,
    sign_message,
    verify_signature,
    encrypt_message,
    decrypt_message,
)


class TestKeyManager:
    """Tests for the KeyManager class."""
    
    def test_create_key_manager(self):
        """Test creating a KeyManager instance."""
        key_manager = KeyManager()
        assert key_manager is not None
    
    def test_generate_rsa_key_pair(self):
        """Test generating an RSA key pair."""
        key_manager = KeyManager()
        key_pair = key_manager.generate_key(
            key_id="test-rsa-key",
            key_type=KeyType.RSA,
            key_size=2048,
            metadata={"purpose": "test"},
        )
        
        assert key_pair.key_id == "test-rsa-key"
        assert key_pair.key_type == KeyType.RSA
        assert key_pair.public_key is not None
        assert key_pair.private_key is not None
        assert key_pair.metadata == {"purpose": "test"}
        
        # Check that the keys are valid
        public_key = key_pair.public_key
        private_key = key_pair.private_key
        
        # Try to use the keys for signing/verification
        message = b"Test message"
        signature = private_key.sign(
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH
            ),
            hashes.SHA256()
        )
        
        # Verify the signature
        public_key.verify(
            signature,
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH
            ),
            hashes.SHA256()
        )
    
    def test_generate_ec_key_pair(self):
        """Test generating an EC key pair."""
        key_manager = KeyManager()
        key_pair = key_manager.generate_key(
            key_id="test-ec-key",
            key_type=KeyType.EC,
            curve="secp256r1",
        )
        
        assert key_pair.key_id == "test-ec-key"
        assert key_pair.key_type == KeyType.EC
        assert key_pair.public_key is not None
        assert key_pair.private_key is not None
        
        # Check that the keys are valid
        public_key = key_pair.public_key
        private_key = key_pair.private_key
        
        # Try to use the keys for signing/verification
        message = b"Test message"
        signature = private_key.sign(
            message,
            ec.ECDSA(hashes.SHA256())
        )
        
        # Verify the signature
        public_key.verify(
            signature,
            message,
            ec.ECDSA(hashes.SHA256())
        )
    
    def test_get_key(self):
        """Test getting a key by ID."""
        key_manager = KeyManager()
        key_pair = key_manager.generate_key("test-key")
        
        # Get the key
        retrieved = key_manager.get_key("test-key")
        assert retrieved is not None
        assert retrieved.key_id == "test-key"
        
        # Try to get a non-existent key
        with pytest.raises(KeyError):
            key_manager.get_key("non-existent-key")
    
    def test_list_keys(self):
        """Test listing all keys."""
        key_manager = KeyManager()
        
        # Add some test keys
        key_manager.generate_key("key1")
        key_manager.generate_key("key2")
        
        # List keys
        keys = key_manager.list_keys()
        assert len(keys) >= 2  # May include default keys
        assert any(k.key_id == "key1" for k in keys)
        assert any(k.key_id == "key2" for k in keys)
    
    def test_delete_key(self):
        """Test deleting a key."""
        key_manager = KeyManager()
        key_manager.generate_key("key-to-delete")
        
        # Delete the key
        key_manager.delete_key("key-to-delete")
        
        # Verify it's gone
        with pytest.raises(KeyError):
            key_manager.get_key("key-to-delete")
        
        # Try to delete a non-existent key
        with pytest.raises(KeyError):
            key_manager.delete_key("non-existent-key")


class TestAuthToken:
    """Tests for the AuthToken class."""
    
    def test_create_token(self):
        """Test creating an AuthToken."""
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(hours=1)
        
        token = AuthToken(
            token_id="test-token",
            user_id="user-123",
            expires_at=expires_at,
            issued_at=now,
            metadata={"role": "admin"},
        )
        
        assert token.token_id == "test-token"
        assert token.user_id == "user-123"
        assert token.expires_at == expires_at
        assert token.issued_at == now
        assert token.metadata == {"role": "admin"}
        assert not token.is_expired()
    
    def test_token_expiration(self):
        """Test token expiration."""
        now = datetime.now(timezone.utc)
        
        # Not expired
        token = AuthToken(
            token_id="test-token",
            user_id="user-123",
            expires_at=now + timedelta(hours=1),
        )
        assert not token.is_expired()
        
        # Expired
        token = AuthToken(
            token_id="test-token",
            user_id="user-123",
            expires_at=now - timedelta(seconds=1),
        )
        assert token.is_expired()
    
    def test_token_serialization(self):
        """Test serializing and deserializing a token."""
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(hours=1)
        
        token = AuthToken(
            token_id="test-token",
            user_id="user-123",
            expires_at=expires_at,
            issued_at=now,
            metadata={"role": "admin"},
        )
        
        # Serialize to dict
        data = token.model_dump()
        
        # Check serialized fields
        assert data["token_id"] == "test-token"
        assert data["user_id"] == "user-123"
        assert data["expires_at"] == expires_at.isoformat()
        assert data["issued_at"] == now.isoformat()
        assert data["metadata"] == {"role": "admin"}
        
        # Deserialize back to AuthToken
        new_token = AuthToken.model_validate(data)
        assert new_token.token_id == token.token_id
        assert new_token.user_id == token.user_id
        assert new_token.expires_at == token.expires_at
        assert new_token.issued_at == token.issued_at
        assert new_token.metadata == token.metadata


class TestAPIKeyAuthenticator:
    """Tests for the APIKeyAuthenticator class."""
    
    def test_authenticate_valid_key(self):
        """Test authenticating with a valid API key."""
        authenticator = APIKeyAuthenticator(api_key="test-key")
        
        # Valid key
        request = {
            "headers": {
                "Authorization": "Bearer test-key"
            }
        }
        
        result = authenticator.authenticate(request)
        assert result.is_authenticated
        assert result.user_id == "api-client"
        
        # Valid key with different case
        request = {
            "headers": {
                "Authorization": "bearer test-key"
            }
        }
        
        result = authenticator.authenticate(request)
        assert result.is_authenticated
    
    def test_authenticate_invalid_key(self):
        """Test authenticating with an invalid API key."""
        authenticator = APIKeyAuthenticator(api_key="test-key")
        
        # Wrong key
        request = {
            "headers": {
                "Authorization": "Bearer wrong-key"
            }
        }
        
        result = authenticator.authenticate(request)
        assert not result.is_authenticated
        
        # Missing header
        request = {}
        result = authenticator.authenticate(request)
        assert not result.is_authenticated
        
        # Malformed header
        request = {
            "headers": {
                "Authorization": "InvalidFormat"
            }
        }
        result = authenticator.authenticate(request)
        assert not result.is_authenticated
    
    def test_get_auth_headers(self):
        """Test getting authentication headers."""
        authenticator = APIKeyAuthenticator(api_key="test-key")
        headers = authenticator.get_auth_headers()
        
        assert headers == {"Authorization": "Bearer test-key"}


class TestCryptoUtils:
    """Tests for the cryptographic utility functions."""
    
    def test_sign_and_verify_rsa(self, tmp_path):
        """Test signing and verifying with RSA keys."""
        # Generate a test key pair
        key_manager = KeyManager()
        key_pair = key_manager.generate_key("test-rsa", KeyType.RSA, 2048)
        
        # Test data
        message = b"Test message to sign"
        
        # Sign the message
        signature = sign_message(
            message=message,
            private_key=key_pair.private_key,
            algorithm="RS256"
        )
        
        # Verify the signature
        result = verify_signature(
            message=message,
            signature=signature,
            public_key=key_pair.public_key,
            algorithm="RS256"
        )
        
        assert result is True
        
        # Test with wrong message
        result = verify_signature(
            message=b"Wrong message",
            signature=signature,
            public_key=key_pair.public_key,
            algorithm="RS256"
        )
        
        assert result is False
    
    def test_encrypt_decrypt_message(self, tmp_path):
        """Test encrypting and decrypting a message."""
        # Generate a test key
        key = os.urandom(32)  # 256-bit key for AES-256
        
        # Test data
        message = b"Test message to encrypt"
        
        # Encrypt the message
        ciphertext, iv, tag = encrypt_message(
            message=message,
            key=key,
            algorithm="AES-256-GCM"
        )
        
        # Decrypt the message
        decrypted = decrypt_message(
            ciphertext=ciphertext,
            key=key,
            iv=iv,
            tag=tag,
            algorithm="AES-256-GCM"
        )
        
        assert decrypted == message
        
        # Test with wrong key
        wrong_key = os.urandom(32)
        with pytest.raises(CryptoError):
            decrypt_message(
                ciphertext=ciphertext,
                key=wrong_key,
                iv=iv,
                tag=tag,
                algorithm="AES-256-GCM"
            )
        
        # Test with wrong tag
        wrong_tag = os.urandom(16)
        with pytest.raises(CryptoError):
            decrypt_message(
                ciphertext=ciphertext,
                key=key,
                iv=iv,
                tag=wrong_tag,
                algorithm="AES-256-GCM"
            )
