"""Evidentia's Cloudinary integration kit.

Independent of the rest of the codebase (no Evidentia imports) so it can be tested in isolation and
reused. Everything Cloudinary-specific lives here: credentials, signed upload parameters, webhook
verification, delivery URLs, Admin API helpers, the Analyze API client and account bootstrap.
"""

from evidentia_cloudinary.config import CloudinaryCredentials, configure
from evidentia_cloudinary.errors import (
    CloudinaryError,
    CloudinaryNotFound,
    CloudinaryPermanentError,
    CloudinaryRetryableError,
)

__all__ = [
    "CloudinaryCredentials",
    "CloudinaryError",
    "CloudinaryNotFound",
    "CloudinaryPermanentError",
    "CloudinaryRetryableError",
    "configure",
]
