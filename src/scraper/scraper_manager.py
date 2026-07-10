"""
src/scraper/scraper_manager.py
===============================
Orchestrator for the Website Acquisition, Scraping & Contact Extraction Pipeline.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Set, Tuple
from urllib.parse import urlparse

from .http_scraper import HTTPScraper
from .browser_scraper import BrowserScraper
from .page_discovery import PageDiscovery
from .html_parser import HTMLParser, ParsedHTML
from .robots_handler import RobotsHandler
from .scraper_metrics import ScraperMetrics
from .scraper_result import ScrapedPage

from ..extractor.structured_contact import StructuredContact
from ..extractor.email_extractor import EmailExtractor
from ..extractor.phone_extractor import PhoneExtractor
from ..extractor.social_extractor import SocialExtractor
from ..extractor.confidence_engine import ConfidenceEngine

logger = logging.getLogger(__name__)


class ScraperManager:
    """
    Main manager coordinating robots.txt parsing, HTTP scraping, page discovery,
    Playwright fallbacks, contact extraction, and metrics writing.
    """

    def __init__(
        self,
        strict_robots: bool = False,
        max_contact_pages: int = 3,
        metrics_file: str = "logs/scraper_metrics.json",
        headless_browser: bool = True
    ) -> None:
        self.strict_robots = strict_robots
        self.max_contact_pages = max_contact_pages
        
        self.robots_handler = RobotsHandler()
        self.http_scraper = HTTPScraper()
        self.browser_scraper = BrowserScraper(headless=headless_browser)
        self.page_discovery = PageDiscovery(max_candidates=max_contact_pages)
        self.metrics = ScraperMetrics(metrics_file)
        
        self._browser_started = False

    async def close(self) -> None:
        """Closes any underlying scraper clients and browser instances."""
        await self.http_scraper.close()
        await self.robots_handler._client.aclose()
        if self._browser_started:
            await self.browser_scraper.close()
            self._browser_started = False

    async def __aenter__(self) -> ScraperManager:
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()

    def _normalize_url(self, url: str) -> str:
        """Ensures the URL has a valid scheme prefix."""
        cleaned = url.strip()
        if not cleaned:
            return ""
        if not (cleaned.startswith("http://") or cleaned.startswith("https://")):
            return "https://" + cleaned
        return cleaned

    def _extract_business_name(self, parsed_htmls: List[ParsedHTML]) -> str:
        """
        Attempts to find a representative business name from parsed HTML metadata.
        """
        # 1. Look in JSON-LD blocks
        for parsed in parsed_htmls:
            for item in parsed.json_ld:
                if "@type" in item and any(t in str(item["@type"]).lower() for t in ["organization", "localbusiness", "medicalbusiness"]):
                    if "name" in item and isinstance(item["name"], str):
                        return item["name"].strip()

        # 2. Look at first non-empty page title (clean up common suffixes like Home, Contact)
        for parsed in parsed_htmls:
            if parsed.title:
                title = parsed.title
                # Clean up title by splitting on common dividers
                for divider in ["|", "-", "–"]:
                    if divider in title:
                        parts = title.split(divider)
                        # Often the business name is the second or first part
                        if len(parts[0]) > 2:
                            return parts[0].strip()
                return title

        # 3. Fall back to meta description if found
        for parsed in parsed_htmls:
            if parsed.meta_description:
                return parsed.meta_description[:50].strip()

        return ""

    async def scrape_website(self, website_url: str) -> StructuredContact:
        """
        Scrapes a business website to extract structured contact details.
        Uses HTTP scraping first, then falls back to Playwright if needed.
        """
        start_time = time.perf_counter()
        normalized_url = self._normalize_url(website_url)
        
        errors: List[str] = []
        pages_visited: List[str] = []
        method_used = "HTTP"

        # Initialize extraction state
        emails_with_scores: Dict[str, float] = {}
        phones_with_scores: Dict[str, float] = {}
        social_links: Dict[str, str] = {
            "linkedin": "", "facebook": "", "instagram": "", "twitter": "", "youtube": "", "github": ""
        }
        parsed_pages: List[ParsedHTML] = []

        if not normalized_url:
            self.metrics.increment_failures()
            self.metrics.record_session(time.perf_counter() - start_time)
            self.metrics.save()
            return StructuredContact(
                official_website=website_url,
                errors=["Empty or invalid website URL provided."]
            )

        # 1. Robots.txt check
        is_allowed = await self.robots_handler.is_allowed(normalized_url)
        if not is_allowed:
            warning_msg = f"Robots.txt restricts crawling on {normalized_url}."
            logger.warning(warning_msg)
            errors.append(warning_msg)
            if self.strict_robots:
                self.metrics.increment_failures()
                self.metrics.record_session(time.perf_counter() - start_time)
                self.metrics.save()
                return StructuredContact(
                    official_website=normalized_url,
                    errors=errors
                )

        # 2. HTTP Scraping of Homepage
        homepage_scraped = await self.http_scraper.scrape_page(normalized_url)
        pages_visited.append(normalized_url)

        # Track HTTP success / fail
        if homepage_scraped.status_code > 0 and homepage_scraped.status_code < 400:
            self.metrics.increment_http_success()
            self.metrics.increment_pages_crawled()
            
            # Parse Homepage
            homepage_parsed = HTMLParser.parse(homepage_scraped.html, normalized_url)
            parsed_pages.append(homepage_parsed)
            
            # Extract basic contacts
            homepage_emails = EmailExtractor.extract(homepage_parsed.visible_text, homepage_parsed.mailto_links)
            homepage_phones = PhoneExtractor.extract(homepage_parsed.visible_text, homepage_parsed.tel_links)
            homepage_socials = SocialExtractor.extract(homepage_parsed.all_links)
            
            # Record confidence scores
            for email, base_score in homepage_emails.items():
                is_mailto = email in homepage_parsed.mailto_links
                is_footer = email in homepage_parsed.footer_text.lower()
                emails_with_scores[email] = ConfidenceEngine.compute_email_confidence(
                    email, normalized_url, is_mailto, is_footer, normalized_url
                )

            for phone, base_score in homepage_phones.items():
                is_tel = any(phone in t for t in homepage_parsed.tel_links)
                is_footer = phone in homepage_parsed.footer_text
                phones_with_scores[phone] = ConfidenceEngine.compute_phone_confidence(
                    phone, normalized_url, is_tel, is_footer, normalized_url
                )

            for platform, url in homepage_socials.items():
                if url:
                    social_links[platform] = url

            # Check if we should crawl subpages
            # We crawl subpages if email or phone is missing
            if not emails_with_scores or not phones_with_scores:
                # Discover contact pages
                candidates = self.page_discovery.discover_pages(homepage_parsed, normalized_url)
                
                # Fetch candidate pages via HTTP
                for page_url, score in candidates:
                    # Check robots.txt for subpage
                    if not await self.robots_handler.is_allowed(page_url):
                        logger.warning(f"Robots.txt restricts subpage crawl: {page_url}")
                        continue

                    subpage_scraped = await self.http_scraper.scrape_page(page_url)
                    pages_visited.append(page_url)

                    if subpage_scraped.status_code > 0 and subpage_scraped.status_code < 400:
                        self.metrics.increment_http_success()
                        self.metrics.increment_pages_crawled()

                        sub_parsed = HTMLParser.parse(subpage_scraped.html, page_url)
                        parsed_pages.append(sub_parsed)

                        # Extract subpage contacts
                        sub_emails = EmailExtractor.extract(sub_parsed.visible_text, sub_parsed.mailto_links)
                        sub_phones = PhoneExtractor.extract(sub_parsed.visible_text, sub_parsed.tel_links)
                        sub_socials = SocialExtractor.extract(sub_parsed.all_links)

                        for email, _ in sub_emails.items():
                            is_mailto = email in sub_parsed.mailto_links
                            is_footer = email in sub_parsed.footer_text.lower()
                            score_val = ConfidenceEngine.compute_email_confidence(
                                email, page_url, is_mailto, is_footer, normalized_url
                            )
                            if email not in emails_with_scores or score_val > emails_with_scores[email]:
                                emails_with_scores[email] = score_val

                        for phone, _ in sub_phones.items():
                            is_tel = any(phone in t for t in sub_parsed.tel_links)
                            is_footer = phone in sub_parsed.footer_text
                            score_val = ConfidenceEngine.compute_phone_confidence(
                                phone, page_url, is_tel, is_footer, normalized_url
                            )
                            if phone not in phones_with_scores or score_val > phones_with_scores[phone]:
                                phones_with_scores[phone] = score_val

                        for platform, url in sub_socials.items():
                            if url and not social_links[platform]:
                                social_links[platform] = url
                    else:
                        self.metrics.increment_http_fail()
                        if subpage_scraped.error_message:
                            errors.append(f"HTTP subpage failed: {page_url} - {subpage_scraped.error_message}")
        else:
            self.metrics.increment_http_fail()
            if homepage_scraped.error_message:
                errors.append(f"HTTP homepage failed: {homepage_scraped.error_message}")

        # 3. Playwright Fallback
        # Triggered if HTTP homepage scrape failed, OR contact details are still missing after subpage crawl
        needs_browser = (len(parsed_pages) == 0) or (not emails_with_scores and not phones_with_scores)
        
        if needs_browser:
            method_used = "Browser"
            logger.info(f"[Orchestrator] Falling back to Browser Scraper for {normalized_url}")
            
            # Start browser if not already running
            if not self._browser_started:
                await self.browser_scraper.start()
                self._browser_started = True
                self.metrics.increment_browser_launches()

            # Scrape homepage using Playwright
            browser_homepage = await self.browser_scraper.scrape_page(normalized_url)
            if browser_homepage.status_code > 0 and browser_homepage.status_code < 400:
                self.metrics.increment_browser_success()
                self.metrics.increment_pages_crawled()

                homepage_parsed = HTMLParser.parse(browser_homepage.html, normalized_url)
                if not any(p.title == homepage_parsed.title for p in parsed_pages):
                    parsed_pages.append(homepage_parsed)

                # Extract
                homepage_emails = EmailExtractor.extract(homepage_parsed.visible_text, homepage_parsed.mailto_links)
                homepage_phones = PhoneExtractor.extract(homepage_parsed.visible_text, homepage_parsed.tel_links)
                homepage_socials = SocialExtractor.extract(homepage_parsed.all_links)

                for email, _ in homepage_emails.items():
                    is_mailto = email in homepage_parsed.mailto_links
                    is_footer = email in homepage_parsed.footer_text.lower()
                    score_val = ConfidenceEngine.compute_email_confidence(
                        email, normalized_url, is_mailto, is_footer, normalized_url
                    )
                    if email not in emails_with_scores or score_val > emails_with_scores[email]:
                        emails_with_scores[email] = score_val

                for phone, _ in homepage_phones.items():
                    is_tel = any(phone in t for t in homepage_parsed.tel_links)
                    is_footer = phone in homepage_parsed.footer_text
                    score_val = ConfidenceEngine.compute_phone_confidence(
                        phone, normalized_url, is_tel, is_footer, normalized_url
                    )
                    if phone not in phones_with_scores or score_val > phones_with_scores[phone]:
                        phones_with_scores[phone] = score_val

                for platform, url in homepage_socials.items():
                    if url and not social_links[platform]:
                        social_links[platform] = url

                # Discover and crawl contact pages if still empty
                if not emails_with_scores and not phones_with_scores:
                    candidates = self.page_discovery.discover_pages(homepage_parsed, normalized_url)
                    for page_url, score in candidates:
                        if page_url in pages_visited:
                            continue

                        if not await self.robots_handler.is_allowed(page_url):
                            continue

                        browser_subpage = await self.browser_scraper.scrape_page(page_url)
                        pages_visited.append(page_url)

                        if browser_subpage.status_code > 0 and browser_subpage.status_code < 400:
                            self.metrics.increment_browser_success()
                            self.metrics.increment_pages_crawled()

                            sub_parsed = HTMLParser.parse(browser_subpage.html, page_url)
                            parsed_pages.append(sub_parsed)

                            # Extract subpage contacts
                            sub_emails = EmailExtractor.extract(sub_parsed.visible_text, sub_parsed.mailto_links)
                            sub_phones = PhoneExtractor.extract(sub_parsed.visible_text, sub_parsed.tel_links)
                            sub_socials = SocialExtractor.extract(sub_parsed.all_links)

                            for email, _ in sub_emails.items():
                                is_mailto = email in sub_parsed.mailto_links
                                is_footer = email in sub_parsed.footer_text.lower()
                                score_val = ConfidenceEngine.compute_email_confidence(
                                    email, page_url, is_mailto, is_footer, normalized_url
                                )
                                if email not in emails_with_scores or score_val > emails_with_scores[email]:
                                    emails_with_scores[email] = score_val

                            for phone, _ in sub_phones.items():
                                is_tel = any(phone in t for t in sub_parsed.tel_links)
                                is_footer = phone in sub_parsed.footer_text
                                score_val = ConfidenceEngine.compute_phone_confidence(
                                    phone, page_url, is_tel, is_footer, normalized_url
                                )
                                if phone not in phones_with_scores or score_val > phones_with_scores[phone]:
                                    phones_with_scores[phone] = score_val

                            for platform, url in sub_socials.items():
                                if url and not social_links[platform]:
                                    social_links[platform] = url
                        else:
                            self.metrics.increment_browser_fail()
                            if browser_subpage.error_message:
                                errors.append(f"Browser subpage failed: {page_url} - {browser_subpage.error_message}")
            else:
                self.metrics.increment_browser_fail()
                if browser_homepage.error_message:
                    errors.append(f"Browser homepage failed: {browser_homepage.error_message}")

        # 4. Synthesize structured outputs
        # Sort extracted emails and phones by confidence score descending
        sorted_emails = sorted(emails_with_scores.items(), key=lambda x: x[1], reverse=True)
        sorted_phones = sorted(phones_with_scores.items(), key=lambda x: x[1], reverse=True)

        final_emails = [email for email, score in sorted_emails]
        final_phones = [phone for phone, score in sorted_phones]

        # Extract business name
        business_name = self._extract_business_name(parsed_pages)

        # Aggregate profile confidence
        email_scores = list(emails_with_scores.values())
        phone_scores = list(phones_with_scores.values())
        aggregate_confidence = ConfidenceEngine.get_aggregate_confidence(email_scores, phone_scores)

        processing_time = time.perf_counter() - start_time

        # Update metrics counts
        self.metrics.add_extracted_counts(len(final_emails), len(final_phones))
        self.metrics.record_session(processing_time)
        if not final_emails and not final_phones:
            self.metrics.increment_failures()
        self.metrics.save()

        # Build contact output
        return StructuredContact(
            business_name=business_name,
            official_website=normalized_url,
            emails=final_emails,
            phones=final_phones,
            social_links=social_links,
            pages_visited=pages_visited,
            extraction_method=method_used,
            confidence=aggregate_confidence,
            processing_time=round(processing_time, 2),
            errors=errors
        )
