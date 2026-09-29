from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import cloudinary

SignatureAlgorithm = Literal["sha1", "sha256"]


@dataclass(frozen=True)
class CloudinaryCredentials:
    cloud_name: str
    api_key: str
    api_secret: str
    signature_algorithm: SignatureAlgorithm = "sha1"

    def __repr__(self) -> str:  # never leak the secret into logs
        return f"CloudinaryCredentials(cloud_name={self.cloud_name!r}, api_key={self.api_key!r})"


def configure(creds: CloudinaryCredentials) -> None:
    """Configure the global Cloudinary SDK. Call once per process at startup."""
    cloudinary.config(
        cloud_name=creds.cloud_name,
        api_key=creds.api_key,
        api_secret=creds.api_secret,
        secure=True,
        signature_algorithm=creds.signature_algorithm,
    )
