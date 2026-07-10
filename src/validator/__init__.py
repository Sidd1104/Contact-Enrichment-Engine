"""
src/validator/
==============
Validator layer for validating email syntax, normalizing phone numbers,
detecting duplicates, and calculating final confidence scores.
"""

from __future__ import annotations

from .validation_config import validation_config, ValidationConfig
from .email_validator import EmailValidator
from .phone_validator import PhoneValidator
from .business_profile_validator import BusinessProfile, BusinessProfileValidator
from .confidence_validator import ConfidenceValidator
from .duplicate_detector import DuplicateDetector, levenshtein_distance
from .validation_metrics import ValidationMetrics
from .validation_manager import ValidationManager

__all__ = [
    "validation_config",
    "ValidationConfig",
    "EmailValidator",
    "PhoneValidator",
    "BusinessProfile",
    "BusinessProfileValidator",
    "ConfidenceValidator",
    "DuplicateDetector",
    "levenshtein_distance",
    "ValidationMetrics",
    "ValidationManager"
]
