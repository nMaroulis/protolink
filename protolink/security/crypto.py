"""Cryptographic utilities for the A2A protocol."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, Optional, Tuple, Union

from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from pydantic import BaseModel, Field, validator


class KeyType(str, Enum):
    """Supported key types."""
    RSA = "rsa"
    EC = "ec"
    ED25519 = "ed25519"
    X25519 = "x25519"
    AES = "aes"
    CHACHA20 = "chacha20"


class KeyUsage(str, Enum):
    """Key usage flags."""
    ENCRYPT = "encrypt"
    DECRYPT = "decrypt"
    SIGN = "sign"
    VERIFY = "verify"
    DERIVE = "derive"
    WRAP = "wrap"
    UNWRAP = "unwrap"


class HashAlgorithm(str, Enum):
    """Supported hash algorithms."""
    SHA256 = "sha256"
    SHA384 = "sha384"
    SHA512 = "sha512"
    BLAKE2B = "blake2b"
    BLAKE2S = "blake2s"


class CryptoError(Exception):
    """Base exception for cryptographic operations."""
    pass


class KeyNotFoundError(CryptoError):
    """Raised when a key is not found."""
    pass


class InvalidKeyError(CryptoError):
    """Raised when a key is invalid."""
    pass


@dataclass
class KeyPair:
    """A pair of public and private keys."""
    
    public_key: bytes
    private_key: Optional[bytes] = None
    key_type: KeyType = KeyType.RSA
    key_size: int = 4096
    created_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def key_id(self) -> str:
        """Generate a unique key ID from the public key."""
        return hashlib.sha256(self.public_key).hexdigest()
    
    @property
    def is_expired(self) -> bool:
        """Check if the key is expired."""
        if not self.expires_at:
            return False
        return datetime.utcnow() >= self.expires_at
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert the key pair to a dictionary."""
        return {
            "public_key": base64.b64encode(self.public_key).decode("utf-8"),
            "private_key": base64.b64encode(self.private_key).decode("utf-8") if self.private_key else None,
            "key_type": self.key_type.value,
            "key_size": self.key_size,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "key_id": self.key_id,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> KeyPair:
        """Create a key pair from a dictionary."""
        return cls(
            public_key=base64.b64decode(data["public_key"]),
            private_key=base64.b64decode(data["private_key"]) if data.get("private_key") else None,
            key_type=KeyType(data.get("key_type", KeyType.RSA)),
            key_size=data.get("key_size", 4096),
            created_at=datetime.fromisoformat(data["created_at"]) if "created_at" in data else datetime.utcnow(),
            expires_at=datetime.fromisoformat(data["expires_at"]) if data.get("expires_at") else None,
            metadata=data.get("metadata", {}),
        )


def generate_key_pair(
    key_type: Union[KeyType, str] = KeyType.RSA,
    key_size: int = 4096,
    curve: Optional[str] = None,
    expires_in: Optional[int] = None,
    **metadata: Any,
) -> KeyPair:
    """Generate a new key pair.
    
    Args:
        key_type: Type of key to generate
        key_size: Size of the key in bits (for RSA)
        curve: Curve name for EC keys
        expires_in: Key expiration time in seconds
        **metadata: Additional metadata
        
    Returns:
        A new key pair
    """
    key_type = KeyType(key_type) if isinstance(key_type, str) else key_type
    
    if key_type == KeyType.RSA:
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=key_size,
            backend=default_backend()
        )
        public_key = private_key.public_key()
        
        private_bytes = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )
        
        public_bytes = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )
        
    elif key_type == KeyType.EC:
        if not curve:
            curve = "secp384r1"  # Default curve
            
        curve_obj = {
            "secp256r1": ec.SECP256R1,
            "secp384r1": ec.SECP384R1,
            "secp521r1": ec.SECP521R1,
        }.get(curve.lower())
        
        if not curve_obj:
            raise ValueError(f"Unsupported curve: {curve}")
            
        private_key = ec.generate_private_key(
            curve=curve_obj(),
            backend=default_backend()
        )
        public_key = private_key.public_key()
        
        private_bytes = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )
        
        public_bytes = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )
        
    else:
        raise ValueError(f"Unsupported key type: {key_type}")
    
    return KeyPair(
        public_key=public_bytes,
        private_key=private_bytes,
        key_type=key_type,
        key_size=key_size,
        expires_at=datetime.utcnow() + timedelta(seconds=expires_in) if expires_in else None,
        metadata=metadata,
    )


def sign_message(
    message: bytes,
    private_key: bytes,
    algorithm: Union[HashAlgorithm, str] = HashAlgorithm.SHA256,
) -> bytes:
    """Sign a message with a private key.
    
    Args:
        message: The message to sign
        private_key: The private key in PEM format
        algorithm: The hash algorithm to use
        
    Returns:
        The signature
    """
    try:
        # Try to load as RSA private key
        key = serialization.load_pem_private_key(
            private_key,
            password=None,
            backend=default_backend()
        )
        
        if isinstance(key, rsa.RSAPrivateKey):
            hasher = {
                HashAlgorithm.SHA256: hashes.SHA256(),
                HashAlgorithm.SHA384: hashes.SHA384(),
                HashAlgorithm.SHA512: hashes.SHA512(),
            }[HashAlgorithm(algorithm)]
            
            return key.sign(
                message,
                padding.PSS(
                    mgf=padding.MGF1(hasher),
                    salt_length=padding.PSS.MAX_LENGTH
                ),
                hasher
            )
            
        elif isinstance(key, ec.EllipticCurvePrivateKey):
            hasher = {
                HashAlgorithm.SHA256: hashes.SHA256(),
                HashAlgorithm.SHA384: hashes.SHA384(),
                HashAlgorithm.SHA512: hashes.SHA512(),
            }[HashAlgorithm(algorithm)]
            
            return key.sign(
                message,
                ec.ECDSA(hasher)
            )
            
        else:
            raise ValueError(f"Unsupported key type: {type(key).__name__}")
            
    except Exception as e:
        raise CryptoError(f"Failed to sign message: {e}") from e


def verify_signature(
    message: bytes,
    signature: bytes,
    public_key: bytes,
    algorithm: Union[HashAlgorithm, str] = HashAlgorithm.SHA256,
) -> bool:
    """Verify a message signature.
    
    Args:
        message: The original message
        signature: The signature to verify
        public_key: The public key in PEM format
        algorithm: The hash algorithm used for signing
        
    Returns:
        True if the signature is valid, False otherwise
    """
    try:
        # Try to load as public key
        key = serialization.load_pem_public_key(
            public_key,
            backend=default_backend()
        )
        
        if isinstance(key, rsa.RSAPublicKey):
            hasher = {
                HashAlgorithm.SHA256: hashes.SHA256(),
                HashAlgorithm.SHA384: hashes.SHA384(),
                HashAlgorithm.SHA512: hashes.SHA512(),
            }[HashAlgorithm(algorithm)]
            
            key.verify(
                signature,
                message,
                padding.PSS(
                    mgf=padding.MGF1(hasher),
                    salt_length=padding.PSS.MAX_LENGTH
                ),
                hasher
            )
            return True
            
        elif isinstance(key, ec.EllipticCurvePublicKey):
            hasher = {
                HashAlgorithm.SHA256: hashes.SHA256(),
                HashAlgorithm.SHA384: hashes.SHA384(),
                HashAlgorithm.SHA512: hashes.SHA512(),
            }[HashAlgorithm(algorithm)]
            
            key.verify(
                signature,
                message,
                ec.ECDSA(hasher)
            )
            return True
            
        else:
            raise ValueError(f"Unsupported key type: {type(key).__name__}")
            
    except (InvalidSignature, ValueError) as e:
        return False
    except Exception as e:
        raise CryptoError(f"Failed to verify signature: {e}") from e


def encrypt_message(
    message: bytes,
    key: bytes,
    algorithm: str = "AES-256-GCM",
    associated_data: Optional[bytes] = None,
) -> Tuple[bytes, bytes, bytes]:
    """Encrypt a message using symmetric encryption.
    
    Args:
        message: The message to encrypt
        key: The encryption key
        algorithm: The encryption algorithm to use
        associated_data: Optional associated data for AEAD modes
        
    Returns:
        A tuple of (ciphertext, iv, tag)
    """
    try:
        if algorithm.upper() == "AES-256-GCM":
            iv = os.urandom(12)  # 96 bits for GCM
            cipher = Cipher(
                algorithms.AES(key),
                modes.GCM(iv),
                backend=default_backend()
            )
            encryptor = cipher.encryptor()
            
            if associated_data:
                encryptor.authenticate_additional_data(associated_data)
                
            ciphertext = encryptor.update(message) + encryptor.finalize()
            return ciphertext, iv, encryptor.tag
            
        elif algorithm.upper() == "CHACHA20-POLY1305":
            nonce = os.urandom(12)  # 96 bits for ChaCha20-Poly1305
            cipher = Cipher(
                algorithms.ChaCha20(key, nonce),
                mode=None,
                backend=default_backend()
            )
            encryptor = cipher.encryptor()
            ciphertext = encryptor.update(message) + encryptor.finalize()
            
            # In a real implementation, you would also generate and verify a Poly1305 tag
            # This is a simplified version
            tag = hmac.new(
                key,
                nonce + ciphertext + (associated_data or b""),
                hashlib.sha256
            ).digest()[:16]  # Truncate to 128 bits
            
            return ciphertext, nonce, tag
            
        else:
            raise ValueError(f"Unsupported encryption algorithm: {algorithm}")
            
    except Exception as e:
        raise CryptoError(f"Failed to encrypt message: {e}") from e


def decrypt_message(
    ciphertext: bytes,
    key: bytes,
    iv: bytes,
    tag: Optional[bytes] = None,
    algorithm: str = "AES-256-GCM",
    associated_data: Optional[bytes] = None,
) -> bytes:
    """Decrypt a message using symmetric encryption.
    
    Args:
        ciphertext: The encrypted message
        key: The decryption key
        iv: The initialization vector
        tag: The authentication tag (for AEAD modes)
        algorithm: The encryption algorithm to use
        associated_data: Optional associated data for AEAD modes
        
    Returns:
        The decrypted message
        
    Raises:
        CryptoError: If decryption fails
    """
    try:
        if algorithm.upper() == "AES-256-GCM":
            if not tag:
                raise ValueError("Authentication tag is required for GCM mode")
                
            cipher = Cipher(
                algorithms.AES(key),
                modes.GCM(iv, tag),
                backend=default_backend()
            )
            decryptor = cipher.decryptor()
            
            if associated_data:
                decryptor.authenticate_additional_data(associated_data)
                
            return decryptor.update(ciphertext) + decryptor.finalize()
            
        elif algorithm.upper() == "CHACHA20-POLY1305":
            if not tag:
                raise ValueError("Authentication tag is required for ChaCha20-Poly1305")
                
            # Verify the tag first
            expected_tag = hmac.new(
                key,
                iv + ciphertext + (associated_data or b""),
                hashlib.sha256
            ).digest()[:16]  # Truncate to 128 bits
            
            if not hmac.compare_digest(tag, expected_tag):
                raise InvalidTag("Invalid authentication tag")
                
            cipher = Cipher(
                algorithms.ChaCha20(key, iv),
                mode=None,
                backend=default_backend()
            )
            decryptor = cipher.decryptor()
            return decryptor.update(ciphertext) + decryptor.finalize()
            
        else:
            raise ValueError(f"Unsupported encryption algorithm: {algorithm}")
            
    except Exception as e:
        raise CryptoError(f"Failed to decrypt message: {e}") from e


class KeyManager:
    """Key management for cryptographic operations."""
    
    def __init__(self, storage_backend=None):
        """Initialize the key manager.
        
        Args:
            storage_backend: Optional storage backend for key persistence
        """
        self._keys: Dict[str, KeyPair] = {}
        self._storage = storage_backend
    
    def generate_key(
        self,
        key_type: Union[KeyType, str] = KeyType.RSA,
        key_size: int = 4096,
        expires_in: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> KeyPair:
        """Generate a new key pair.
        
        Args:
            key_type: Type of key to generate
            key_size: Size of the key in bits
            expires_in: Key expiration time in seconds
            metadata: Additional metadata
            
        Returns:
            The generated key pair
        """
        key_pair = generate_key_pair(
            key_type=key_type,
            key_size=key_size,
            expires_in=expires_in,
            **(metadata or {})
        )
        
        self._keys[key_pair.key_id] = key_pair
        
        if self._storage:
            self._storage.store_key(key_pair)
            
        return key_pair
    
    def get_key(self, key_id: str) -> KeyPair:
        """Get a key by ID.
        
        Args:
            key_id: The key ID
            
        Returns:
            The key pair
            
        Raises:
            KeyNotFoundError: If the key is not found
        """
        if key_id in self._keys:
            return self._keys[key_id]
            
        if self._storage:
            key_pair = self._storage.get_key(key_id)
            if key_pair:
                self._keys[key_id] = key_pair
                return key_pair
                
        raise KeyNotFoundError(f"Key not found: {key_id}")
    
    def add_key(self, key_pair: KeyPair) -> None:
        """Add a key pair to the manager.
        
        Args:
            key_pair: The key pair to add
        """
        self._keys[key_pair.key_id] = key_pair
        
        if self._storage:
            self._storage.store_key(key_pair)
    
    def remove_key(self, key_id: str) -> None:
        """Remove a key pair from the manager.
        
        Args:
            key_id: The key ID to remove
            
        Raises:
            KeyNotFoundError: If the key is not found
        """
        if key_id not in self._keys:
            if not self._storage or not self._storage.has_key(key_id):
                raise KeyNotFoundError(f"Key not found: {key_id}")
                
        del self._keys[key_id]
        
        if self._storage:
            self._storage.delete_key(key_id)
    
    def list_keys(self) -> Dict[str, Dict[str, Any]]:
        """List all managed keys.
        
        Returns:
            A dictionary of key IDs to key metadata
        """
        keys = {}
        
        # Add in-memory keys
        for key_id, key_pair in self._keys.items():
            keys[key_id] = {
                "key_id": key_pair.key_id,
                "key_type": key_pair.key_type.value,
                "key_size": key_pair.key_size,
                "created_at": key_pair.created_at.isoformat(),
                "expires_at": key_pair.expires_at.isoformat() if key_pair.expires_at else None,
                "is_expired": key_pair.is_expired,
                "metadata": key_pair.metadata,
            }
            
        # Add storage keys if available
        if self._storage:
            for key_id in self._storage.list_keys():
                if key_id not in keys:
                    try:
                        key_pair = self._storage.get_key(key_id)
                        if key_pair:
                            keys[key_id] = {
                                "key_id": key_pair.key_id,
                                "key_type": key_pair.key_type.value,
                                "key_size": key_pair.key_size,
                                "created_at": key_pair.created_at.isoformat(),
                                "expires_at": key_pair.expires_at.isoformat() if key_pair.expires_at else None,
                                "is_expired": key_pair.is_expired,
                                "metadata": key_pair.metadata,
                            }
                    except Exception as e:
                        logger.warning(f"Failed to load key {key_id} from storage: {e}")
                        
        return keys
