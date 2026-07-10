"""
src/scraper/html_parser.py
===========================
HTML Parsing and cleaning utilities using BeautifulSoup4.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class ParsedHTML(BaseModel):
    """
    Standardized parsed output of an HTML document.
    """
    title: str = Field(default="", description="The HTML page title.")
    meta_description: str = Field(default="", description="The meta description of the page.")
    visible_text: str = Field(default="", description="Cleaned visible plain text.")
    mailto_links: List[str] = Field(default_factory=list, description="Extracted mailto: links.")
    tel_links: List[str] = Field(default_factory=list, description="Extracted tel: links.")
    all_links: List[Dict[str, str]] = Field(default_factory=list, description="All anchor links with their text.")
    footer_text: str = Field(default="", description="Text content within footer tags.")
    json_ld: List[Dict[str, Any]] = Field(default_factory=list, description="Parsed JSON-LD structured data blocks.")


class HTMLParser:
    """
    Parses raw HTML using BeautifulSoup4 to extract contact indicators and metadata.
    """

    @staticmethod
    def parse(html: str, base_url: str) -> ParsedHTML:
        """
        Parses raw HTML and extracts key elements.
        """
        if not html:
            return ParsedHTML()

        soup = BeautifulSoup(html, "html.parser")
        
        # 1. Title & Meta description
        title = ""
        if soup.title and soup.title.string:
            title = soup.title.string.strip()
        
        meta_desc = ""
        meta_desc_tag = (
            soup.find("meta", attrs={"name": "description"}) or 
            soup.find("meta", attrs={"property": "og:description"})
        )
        if meta_desc_tag and isinstance(meta_desc_tag.get("content"), str):
            meta_desc = meta_desc_tag.get("content").strip()

        # 2. Links: mailto, tel, and generic
        mailto_links: List[str] = []
        tel_links: List[str] = []
        all_links: List[Dict[str, str]] = []

        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            text = a.get_text(strip=True) or ""
            
            if href.lower().startswith("mailto:"):
                email = href[7:].split("?")[0].strip()
                if email:
                    mailto_links.append(email)
            elif href.lower().startswith("tel:"):
                phone = href[4:].split("?")[0].strip()
                if phone:
                    tel_links.append(phone)
            else:
                # Convert relative links to absolute
                try:
                    absolute_url = urljoin(base_url, href)
                    all_links.append({"url": absolute_url, "text": text})
                except Exception:
                    pass

        # 3. Footer text
        footer_text = ""
        footer_tag = soup.find("footer") or soup.find(class_=lambda x: x and "footer" in x.lower()) or soup.find(id=lambda x: x and "footer" in x.lower())
        if footer_tag:
            footer_text = footer_tag.get_text(separator=" ", strip=True)

        # 4. JSON-LD Structured Data
        json_ld_blocks: List[Dict[str, Any]] = []
        for script in soup.find_all("script", type="application/ld+json"):
            if script.string:
                try:
                    data = json.loads(script.string.strip())
                    if isinstance(data, dict):
                        json_ld_blocks.append(data)
                    elif isinstance(data, list):
                        for item in data:
                            if isinstance(item, dict):
                                json_ld_blocks.append(item)
                except Exception as e:
                    logger.debug(f"Failed to parse JSON-LD: {e}")

        # 5. Clean Visible Text
        # Copy soup so we don't destroy original for later extractions
        text_soup = BeautifulSoup(html, "html.parser")
        
        # Remove script and style elements
        for script in text_soup(["script", "style", "noscript", "iframe", "header", "footer"]):
            script.decompose()
            
        visible_text = text_soup.get_text(separator=" ", strip=True)

        return ParsedHTML(
            title=title,
            meta_description=meta_desc,
            visible_text=visible_text,
            mailto_links=list(set(mailto_links)),
            tel_links=list(set(tel_links)),
            all_links=all_links,
            footer_text=footer_text,
            json_ld=json_ld_blocks
        )
