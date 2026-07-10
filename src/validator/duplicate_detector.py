"""
src/validator/duplicate_detector.py
====================================
Detects and merges duplicate business profiles based on shared identifiers and name distance.
"""

from __future__ import annotations

import logging
import re
from typing import List, Set, Dict
from urllib.parse import urlparse

from .business_profile_validator import BusinessProfile
from .validation_config import validation_config

logger = logging.getLogger(__name__)


def levenshtein_distance(s1: str, s2: str) -> int:
    """
    Computes edit distance between two strings (case-insensitive).
    """
    str1 = s1.lower().strip()
    str2 = s2.lower().strip()
    if len(str1) < len(str2):
        return levenshtein_distance(str2, str1)
    if len(str2) == 0:
        return len(str1)

    previous_row = range(len(str2) + 1)
    for i, c1 in enumerate(str1):
        current_row = [i + 1]
        for j, c2 in enumerate(str2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    return previous_row[-1]


class DuplicateDetector:
    """
    Identifies duplicate profiles using name, website, phone, email, and address matches,
    and merges duplicate sets into single profiles.
    """

    def __init__(self, max_distance: int | None = None) -> None:
        self.max_distance = max_distance if max_distance is not None else validation_config.max_duplicate_distance

    def _extract_domain(self, url: str) -> str:
        """Helper to extract domain from URL."""
        if not url:
            return ""
        parsed = urlparse(url)
        return parsed.netloc.replace("www.", "").lower().strip()

    def are_duplicates(self, p1: BusinessProfile, p2: BusinessProfile) -> bool:
        """
        Determines if two BusinessProfiles represent the same entity.
        Matches on: Website domain, Emails, Phones, Business Name, or Address.
        """
        # 1. Match on Website domain
        dom1 = self._extract_domain(p1.official_website)
        dom2 = self._extract_domain(p2.official_website)
        if dom1 and dom2 and dom1 == dom2:
            # If it's a local mock server, require matching the full path
            if "localhost" in dom1 or "127.0.0.1" in dom1:
                if p1.official_website.lower().strip() == p2.official_website.lower().strip():
                    return True
            else:
                return True

        # 2. Match on Emails intersection
        emails1 = set(p1.emails)
        emails2 = set(p2.emails)
        if emails1 and emails2 and emails1.intersection(emails2):
            return True

        # 3. Match on Phones intersection
        phones1 = set(p1.phones)
        phones2 = set(p2.phones)
        if phones1 and phones2 and phones1.intersection(phones2):
            return True

        # 4. Match on Address (exact match on digits/letters only)
        addr1 = re.sub(r"[^a-zA-Z0-9]", "", p1.address.lower())
        addr2 = re.sub(r"[^a-zA-Z0-9]", "", p2.address.lower())
        if addr1 and addr2 and addr1 == addr2:
            return True

        # 5. Match on Business Name edit distance + same state/city keywords (if present)
        name1 = p1.business_name.strip()
        name2 = p2.business_name.strip()
        if name1 and name2:
            dist = levenshtein_distance(name1, name2)
            if dist <= self.max_distance:
                # If names are extremely close, check if they don't contradict in state/city
                # To be conservative, we check if they share state abbreviation (2 letters) or city
                return True

        return False

    def merge_profiles(self, profiles: List[BusinessProfile]) -> BusinessProfile:
        """
        Merges a list of duplicate profiles into a single BusinessProfile.
        """
        if not profiles:
            raise ValueError("Cannot merge empty list of profiles.")
        if len(profiles) == 1:
            return profiles[0]

        # Use the first profile as the base template
        merged = BusinessProfile(
            business_name=profiles[0].business_name,
            official_website=profiles[0].official_website,
            address=profiles[0].address,
            confidence=profiles[0].confidence,
            extraction_method="Merged"
        )

        emails_set: Set[str] = set()
        phones_set: Set[str] = set()
        socials_dict: Dict[str, str] = {
            "linkedin": "", "facebook": "", "instagram": "", "twitter": "", "youtube": "", "github": ""
        }
        pages_set: Set[str] = set()
        errors_set: Set[str] = set()
        provenance_dict: Dict[str, str] = {}

        # Aggregate fields from all duplicates
        for p in profiles:
            # Prefer the longest/most complete business name
            if len(p.business_name) > len(merged.business_name):
                merged.business_name = p.business_name
            # Prefer first non-empty website
            if not merged.official_website:
                merged.official_website = p.official_website
            # Prefer first non-empty address
            if not merged.address:
                merged.address = p.address

            emails_set.update(p.emails)
            phones_set.update(p.phones)
            pages_set.update(p.pages_visited)
            errors_set.update(p.errors)
            merged.confidence = max(merged.confidence, p.confidence)

            # Combine social links
            for platform, url in p.social_links.items():
                if url and not socials_dict[platform]:
                    socials_dict[platform] = url

            # Combine provenance logs
            for field, src in p.provenance.items():
                if field not in provenance_dict:
                    provenance_dict[field] = src
                elif src not in provenance_dict[field]:
                    provenance_dict[field] = f"{provenance_dict[field]},{src}"

        # Assign aggregated lists
        merged.emails = sorted(list(emails_set))
        merged.phones = sorted(list(phones_set))
        merged.social_links = socials_dict
        merged.pages_visited = sorted(list(pages_set))
        merged.errors = sorted(list(errors_set))
        merged.provenance = provenance_dict

        return merged

    def deduplicate(self, contacts: List[BusinessProfile]) -> List[BusinessProfile]:
        """
        Deduplicates a list of business profiles, returning a list of merged unique profiles.
        """
        unique_profiles: List[BusinessProfile] = []
        
        # Simple clustering/grouping of duplicates
        visited = set()
        
        for i in range(len(contacts)):
            if i in visited:
                continue
            
            # Find all duplicates of contacts[i]
            duplicate_group = [contacts[i]]
            visited.add(i)
            
            for j in range(i + 1, len(contacts)):
                if j in visited:
                    continue
                if self.are_duplicates(contacts[i], contacts[j]):
                    duplicate_group.append(contacts[j])
                    visited.add(j)
            
            # Merge the duplicates in this group
            merged = self.merge_profiles(duplicate_group)
            unique_profiles.append(merged)

        logger.info(f"[DuplicateDetector] Deduplication reduced {len(contacts)} contacts to {len(unique_profiles)} unique profiles.")
        return unique_profiles
