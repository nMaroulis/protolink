"""Artifact handling for the A2A protocol.

This module defines the Artifact class and related components for managing
data artifacts that can be exchanged between agents in the Protolink system.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from pydantic import BaseModel, Field, validator


class ArtifactType(str, Enum):
    """Types of artifacts that can be exchanged between agents."""
    # Data formats
    JSON = "application/json"
    TEXT = "text/plain"
    BINARY = "application/octet-stream"
    
    # Common document formats
    PDF = "application/pdf"
    DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    
    # Images
    JPEG = "image/jpeg"
    PNG = "image/png"
    GIF = "image/gif"
    
    # Audio/Video
    MP3 = "audio/mpeg"
    MP4 = "video/mp4"
    
    # Archives
    ZIP = "application/zip"
    TAR = "application/x-tar"
    GZIP = "application/gzip"
    
    # Custom types (use with format: "x-application/your-custom-type")
    CUSTOM = "x-application/custom"


class ArtifactStorage(str, Enum):
    """Storage backends for artifacts."""
    INLINE = "inline"      # Small artifacts stored directly in the message
    FILESYSTEM = "fs"      # Stored on local filesystem
    S3 = "s3"              # Amazon S3
    GCS = "gcs"            # Google Cloud Storage
    AZURE = "azure"        # Azure Blob Storage
    MEMORY = "memory"      # In-memory storage (for testing)


class ArtifactMetadata(BaseModel):
    """Metadata for an artifact."""
    name: str | None = Field(
        default=None,
        description="Human-readable name for the artifact"
    )
    description: str | None = Field(
        default=None,
        description="Description of the artifact"
    )
    created_at: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat(),
        description="When the artifact was created"
    )
    size_bytes: int | None = Field(
        default=None,
        description="Size of the artifact in bytes"
    )
    checksum: str | None = Field(
        default=None,
        description="Checksum of the artifact content"
    )
    checksum_algorithm: str = Field(
        default="sha256",
        description="Algorithm used to compute the checksum"
    )
    encoding: str | None = Field(
        default=None,
        description="Content encoding (e.g., 'gzip', 'base64')"
    )
    labels: Dict[str, str] = Field(
        default_factory=dict,
        description="Key-value pairs for categorization and filtering"
    )


class ArtifactReference(BaseModel):
    """Reference to an artifact stored in a specific location."""
    artifact_id: str = Field(
        ...,
        description="Unique identifier for the artifact"
    )
    storage: ArtifactStorage = Field(
        default=ArtifactStorage.INLINE,
        description="Storage backend where the artifact is stored"
    )
    uri: Optional[str] = Field(
        default=None,
        description="URI for accessing the artifact"
    )
    access_token: Optional[str] = Field(
        default=None,
        description="Optional access token for the artifact"
    )
    expires_at: Optional[str] = Field(
        default=None,
        description="When the artifact reference expires (ISO 8601)"
    )


class Artifact(BaseModel):
    """A data artifact that can be exchanged between agents.
    
    Artifacts represent data that is too large to include directly in messages
    or needs to be referenced and shared between agents. They can be stored
    in various backends and support streaming for large files.
    """
    
    # Core fields
    id: str = Field(
        default_factory=lambda: f"art_{__import__('uuid').uuid4().hex}",
        description="Unique artifact identifier"
    )
    type: Union[str, ArtifactType] = Field(
        ...,
        description="MIME type of the artifact"
    )
    storage: ArtifactStorage = Field(
        default=ArtifactStorage.INLINE,
        description="Storage backend for this artifact"
    )
    
    # Content can be either inline or referenced
    content: Optional[Any] = Field(
        default=None,
        description="Inline content (for small artifacts)"
    )
    content_encoding: Optional[str] = Field(
        default=None,
        description="Encoding of the content (e.g., 'base64')"
    )
    
    # Reference to external storage
    reference: Optional[ArtifactReference] = Field(
        default=None,
        description="Reference to external storage"
    )
    
    # Metadata
    metadata: ArtifactMetadata = Field(
        default_factory=ArtifactMetadata,
        description="Metadata about the artifact"
    )
    
    # Validation
    @validator('type')
    def validate_artifact_type(cls, v):
        """Ensure artifact type is valid."""
        if isinstance(v, str):
            try:
                return ArtifactType(v.lower())
            except ValueError:
                # Allow custom MIME types
                return v
        return v
    
    # Factory methods
    @classmethod
    def from_text(
        cls,
        text: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        **kwargs
    ) -> Artifact:
        """Create a text artifact from a string."""
        return cls(
            type=ArtifactType.TEXT,
            content=text,
            metadata=ArtifactMetadata(
                name=name,
                description=description,
                size_bytes=len(text.encode('utf-8')),
            ),
            **kwargs
        )
    
    @classmethod
    def from_json(
        cls,
        data: Any,
        name: Optional[str] = None,
        description: Optional[str] = None,
        **kwargs
    ) -> Artifact:
        """Create a JSON artifact from a Python object."""
        json_str = json.dumps(data)
        return cls(
            type=ArtifactType.JSON,
            content=json_str,
            metadata=ArtifactMetadata(
                name=name,
                description=description,
                size_bytes=len(json_str.encode('utf-8')),
            ),
            **kwargs
        )
    
    @classmethod
    def from_file(
        cls,
        file_path: Union[str, Path],
        mime_type: Optional[str] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        **kwargs
    ) -> Artifact:
        """Create an artifact from a file."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        
        # Try to determine MIME type if not provided
        if mime_type is None:
            import mimetypes
            mime_type, _ = mimetypes.guess_type(path.name)
            if mime_type is None:
                mime_type = ArtifactType.BINARY
        
        # For small files, read content directly
        size = path.stat().st_size
        if size < 1024 * 1024:  # 1MB threshold
            with open(path, 'rb') as f:
                content = f.read()
            
            # For binary data, encode as base64
            if mime_type.startswith('text/'):
                content = content.decode('utf-8')
                encoding = None
            else:
                content = base64.b64encode(content).decode('ascii')
                encoding = 'base64'
            
            return cls(
                type=mime_type,
                content=content,
                content_encoding=encoding,
                metadata=ArtifactMetadata(
                    name=name or path.name,
                    description=description,
                    size_bytes=size,
                ),
                **kwargs
            )
        else:
            # For large files, create a reference
            return cls(
                type=mime_type,
                storage=ArtifactStorage.FILESYSTEM,
                reference=ArtifactReference(
                    artifact_id=f"art_{__import__('uuid').uuid4().hex}",
                    storage=ArtifactStorage.FILESYSTEM,
                    uri=str(path.absolute()),
                ),
                metadata=ArtifactMetadata(
                    name=name or path.name,
                    description=description,
                    size_bytes=size,
                ),
                **kwargs
            )
    
    # Content access methods
    def get_content(self) -> Any:
        """Get the content of the artifact."""
        if self.content is not None:
            if self.content_encoding == 'base64':
                return base64.b64decode(self.content)
            return self.content
        
        # TODO: Implement fetching from external storage
        raise NotImplementedError("Fetching from external storage not implemented")
    
    def get_text(self) -> str:
        """Get the content as text."""
        content = self.get_content()
        if isinstance(content, bytes):
            return content.decode('utf-8')
        return str(content)
    
    def get_json(self) -> Any:
        """Parse the content as JSON."""
        if self.type != ArtifactType.JSON:
            raise ValueError(f"Artifact is not JSON (type: {self.type})")
        return json.loads(self.get_text())
    
    def save_to_file(self, file_path: Union[str, Path]) -> Path:
        """Save the artifact content to a file."""
        path = Path(file_path)
        content = self.get_content()
        
        if isinstance(content, str):
            path.write_text(content, encoding='utf-8')
        else:
            path.write_bytes(content)
        
        return path
    
    # Utility methods
    def compute_checksum(self, algorithm: str = "sha256") -> str:
        """Compute a checksum of the artifact content."""
        content = self.get_content()
        if isinstance(content, str):
            content = content.encode('utf-8')
        
        hasher = hashlib.new(algorithm)
        hasher.update(content)
        return hasher.hexdigest()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert the artifact to a dictionary."""
        return self.dict()
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Artifact:
        """Create an artifact from a dictionary."""
        return cls(**data)
