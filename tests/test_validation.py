"""
tests/test_validation.py
=========================
Unit tests for the validator and deduplication layer (Phase 2F).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import pytest

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.validator.email_validator import EmailValidator
from src.validator.phone_validator import PhoneValidator
from src.validator.business_profile_validator import BusinessProfile
from src.validator.duplicate_detector import DuplicateDetector, levenshtein_distance
from src.validator.confidence_validator import ConfidenceValidator
from src.validator.validation_metrics import ValidationMetrics
from src.validator.validation_manager import ValidationManager
from src.extractor.structured_contact import StructuredContact


# =============================================================================
# Test: EmailValidator
# =============================================================================

def test_email_validator_rules():
    emails = [
        "info@mycompany.com",          # valid
        "INFO@mycompany.com",          # duplicate (different casing)
        "malformed_email",             # syntax error
        "user@disposable.mailinator.com", # disposable domain (fails because of mailinator.com inside)
        "john@yopmail.com",            # disposable domain
        "test@company.x",              # invalid TLD (1 letter)
        "office@company.toolongtldtoolongtldtoolongtldtoolongtldtoolongtldtoolongtldtoolongtld", # too long TLD (>63 chars)
    ]
    
    validated = EmailValidator.validate(emails)
    
    assert "info@mycompany.com" in validated
    assert len(validated) == 1  # only one valid, cleaned email survives
    assert "malformed_email" not in validated
    assert "john@yopmail.com" not in validated
    assert "test@company.x" not in validated


# =============================================================================
# Test: PhoneValidator
# =============================================================================

def test_phone_validator_rules():
    phones = [
        "(212) 456-7890",              # valid US local
        "+1 212 456 7890",             # duplicate normalized
        "123-45",                      # impossible length
        "tel:+12124567891",            # has tel prefix
        "+44 20 7946 0958",            # valid UK
    ]
    
    validated = PhoneValidator.validate(phones)
    
    assert "+12124567890" in validated
    assert "+12124567891" in validated
    assert "+442079460958" in validated
    assert len(validated) == 3


# =============================================================================
# Test: DuplicateDetector & Levenshtein
# =============================================================================

def test_levenshtein_distance():
    assert levenshtein_distance("Clinic", "clinic") == 0
    assert levenshtein_distance("Super Clinic", "Supr Clinic") == 1
    assert levenshtein_distance("Super Clinic", "Clinic") == 6


def test_duplicate_detector():
    p1 = BusinessProfile(
        business_name="Super Clinic",
        official_website="https://superclinic.com",
        emails=["info@superclinic.com"],
        phones=["+12124567890"],
        address="123 Main St, New York, NY 10001"
    )
    p2 = BusinessProfile(
        business_name="Supr Clinic",    # Levenshtein distance = 1
        official_website="",            # empty
        emails=[],                      # empty
        phones=[],
        address=""
    )
    p3 = BusinessProfile(
        business_name="Unrelated Tech",
        official_website="https://unrelatedtech.com",
        emails=["support@unrelatedtech.com"],
        phones=["+12125559999"],
        address="456 Broadway, New York, NY 10012"
    )

    detector = DuplicateDetector(max_distance=2)
    
    # p1 and p2 are duplicates because name distance is 1 (<= 2)
    assert detector.are_duplicates(p1, p2) is True
    
    # p1 and p3 are NOT duplicates
    assert detector.are_duplicates(p1, p3) is False

    # Merge p1 and p2
    merged = detector.merge_profiles([p1, p2])
    assert merged.business_name == "Super Clinic"
    assert merged.official_website == "https://superclinic.com"
    assert "+12124567890" in merged.phones
    assert merged.address == "123 Main St, New York, NY 10001"


# =============================================================================
# Test: ConfidenceValidator
# =============================================================================

def test_confidence_validator():
    p = BusinessProfile(
        business_name="Test Clinic",
        official_website="https://testclinic.com",
        emails=["info@testclinic.com"],
        phones=["+12124567890"],
        confidence=0.7
    )
    
    conf = ConfidenceValidator.calculate(p, has_contact_page=True, has_footer=True)
    
    # Base = 0.70
    # + 0.05 (emails) + 0.05 (phones) + 0.05 (contact_page) + 0.05 (footer) = 0.90
    assert conf == 0.90


# =============================================================================
# Test: ValidationManager and Metrics
# =============================================================================

def test_validation_manager_flow():
    with TemporaryDirectory() as temp_dir:
        metrics_file = Path(temp_dir) / "val_metrics.json"
        manager = ValidationManager(metrics_file=str(metrics_file))
        
        # Scraper contact with valid data
        contact = StructuredContact(
            business_name="Local Doc",
            official_website="https://local-doc.com",
            emails=["contact@local-doc.com"],
            phones=["(212) 456-7890"],
            social_links={"linkedin": "https://linkedin.com/in/local-doc"},
            pages_visited=["https://local-doc.com/contact"],
            confidence=0.8
        )
        
        raw_rec = {
            "address_line_1": "123 Doc Road",
            "city": "Dallas",
            "state": "TX",
            "postal_code": "75201",
            "country": "US"
        }
        
        profile, needs_ai = manager.validate_contact(contact, raw_rec)
        
        assert profile.business_name == "Local Doc"
        assert "+12124567890" in profile.phones
        assert "123 Doc Road, Dallas, TX 75201, US" == profile.address
        assert profile.confidence > 0.85
        
        # Since we have both email and phone, and confidence is high, it should not need AI
        assert needs_ai is False
        
        # Check metrics file exists
        assert metrics_file.exists()
        with open(metrics_file, "r") as f:
            data = json.load(f)
        assert data["counts"]["validated_emails"] == 1
        assert data["counts"]["validated_phones"] == 1
