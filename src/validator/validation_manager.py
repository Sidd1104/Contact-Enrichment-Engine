"""
src/validator/validation_manager.py
====================================
Orchestrator for the validation and quality check pipeline stages.
"""

from __future__ import annotations

import logging
import time
from typing import Dict, Any, List, Tuple

from .business_profile_validator import BusinessProfile
from .email_validator import EmailValidator
from .phone_validator import PhoneValidator
from .duplicate_detector import DuplicateDetector
from .confidence_validator import ConfidenceValidator
from .validation_metrics import ValidationMetrics
from .validation_config import validation_config

# Import StructuredContact to ensure types match
from ..extractor.structured_contact import StructuredContact

logger = logging.getLogger(__name__)


class ValidationManager:
    """
    Coordinates email/phone checkers, duplicate detection, and final confidence scores.
    Determines if AI enrichment fallbacks must trigger.
    """

    def __init__(self, metrics_file: str = "logs/validation_metrics.json") -> None:
        self.metrics = ValidationMetrics(metrics_file)
        self.duplicate_detector = DuplicateDetector()

    def _assemble_address(self, raw_record: Dict[str, Any] | None) -> str:
        """Assembles a readable single-line address string from raw Import Engine fields."""
        if not raw_record:
            return ""
        
        addr_line = raw_record.get("address_line_1", "").strip()
        city = raw_record.get("city", "").strip()
        state = raw_record.get("state", "").strip()
        zip_code = raw_record.get("postal_code", "").strip()
        country = raw_record.get("country", "").strip()

        parts = []
        if addr_line:
            parts.append(addr_line)
        if city:
            parts.append(city)
        if state:
            if zip_code:
                parts.append(f"{state} {zip_code}")
            else:
                parts.append(state)
        elif zip_code:
            parts.append(zip_code)
        if country:
            parts.append(country)

        return ", ".join(parts)

    def validate_contact(
        self,
        contact: StructuredContact,
        raw_record: Dict[str, Any] | None = None
    ) -> Tuple[BusinessProfile, bool]:
        """
        Validates syntax, normalizes phones, maps to BusinessProfile,
        calculates confidence, and decides if AI fallback is required.
        """
        start_time = time.perf_counter()
        logger.info(f"[Validation] Starting validation for: {contact.official_website}")

        # 1. Validate Emails & Phones
        validated_emails = EmailValidator.validate(contact.emails)
        validated_phones = PhoneValidator.validate(contact.phones)

        # 2. Assemble address
        address = self._assemble_address(raw_record)

        # 3. Create BusinessProfile base
        profile = BusinessProfile(
            business_name=contact.business_name,
            official_website=contact.official_website,
            emails=validated_emails,
            phones=validated_phones,
            social_links=contact.social_links,
            address=address,
            pages_visited=contact.pages_visited,
            extraction_method=contact.extraction_method,
            confidence=contact.confidence,
            errors=contact.errors,
            provenance={
                "business_name": "scraper",
                "emails": "scraper" if validated_emails else "",
                "phones": "scraper" if validated_phones else "",
                "address": "importer" if address else ""
            }
        )

        # 4. Calculate Final Confidence Score
        # Check if scraper visited contact page or footer
        has_contact_page = any("contact" in p.lower() or "about" in p.lower() for p in contact.pages_visited)
        has_footer = "footer" in "".join(contact.errors).lower()  # heuristic fallback indicator

        final_conf = ConfidenceValidator.calculate(
            profile=profile,
            has_contact_page=has_contact_page,
            has_footer=has_footer
        )
        profile.confidence = final_conf

        # 5. Check AI fallback execution criteria
        # AI triggers if emails or phones are missing, OR if confidence is too low
        has_email = len(profile.emails) > 0
        has_phone = len(profile.phones) > 0
        conf_below_threshold = final_conf < validation_config.validation_confidence_threshold
        
        needs_ai = False
        if validation_config.enable_ai_fallback:
            if not has_email or not has_phone or conf_below_threshold:
                needs_ai = True
                logger.info(
                    f"[Validation] AI enrichment required. Reason: "
                    f"has_email={has_email}, has_phone={has_phone}, confidence={final_conf} "
                    f"(threshold={validation_config.validation_confidence_threshold})"
                )
            else:
                logger.info(f"[Validation] AI skipped. Criteria met. Confidence={final_conf}")
        else:
            logger.info("[Validation] AI skipped. Fallback disabled in config.")

        # Save Metrics
        latency = time.perf_counter() - start_time
        self.metrics.record_validated(len(validated_emails), len(validated_phones))
        self.metrics.record_session(latency)
        self.metrics.save()

        return profile, needs_ai

    def deduplicate_profiles(self, profiles: List[BusinessProfile]) -> List[BusinessProfile]:
        """
        Finds duplicates, merges them, and updates metric counts.
        """
        orig_count = len(profiles)
        unique_profiles = self.duplicate_detector.deduplicate(profiles)
        removed_count = orig_count - len(unique_profiles)
        
        self.metrics.record_duplicates_removed(removed_count)
        self.metrics.save()
        return unique_profiles
