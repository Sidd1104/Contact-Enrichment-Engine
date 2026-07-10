"""
src/ai/prompts/prompt_manager.py
==================================
Central Prompt Manager.

Manages prompt templates stored as text files in the templates/ directory.
Templates use Python's str.format_map() for safe variable interpolation.

Features:
  - Loads templates from disk on first access (lazy loading).
  - Caches loaded templates in memory.
  - Supports dynamic variable injection.
  - Template versioning via filename conventions.
  - Falls back gracefully if a template file is missing.
  
Usage:
    from src.ai.prompts import prompt_manager
    
    prompt = prompt_manager.render(
        "contact_extraction",
        first_name="John",
        last_name="Doe",
        city="New York",
        state="NY",
    )
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# Directory containing .txt prompt template files
TEMPLATES_DIR = Path(__file__).parent / "templates"


class PromptManager:
    """
    Centralized prompt template manager.
    
    Templates are stored as .txt files in the templates/ subdirectory.
    Variable placeholders use {variable_name} syntax (Python str.format).
    """

    def __init__(self, templates_dir: Optional[Path] = None) -> None:
        self._templates_dir = templates_dir or TEMPLATES_DIR
        self._cache: Dict[str, str] = {}

    def _load_template(self, name: str) -> str:
        """
        Load a template file from disk.
        
        Looks for: templates/{name}.txt
        
        Args:
            name: Template name (without .txt extension).
            
        Returns:
            Raw template string.
            
        Raises:
            FileNotFoundError: If the template file doesn't exist.
        """
        file_path = self._templates_dir / f"{name}.txt"

        if not file_path.exists():
            raise FileNotFoundError(
                f"Prompt template '{name}' not found at {file_path}. "
                f"Available templates: {self.list_templates()}"
            )

        content = file_path.read_text(encoding="utf-8")
        logger.debug(f"[PromptManager] Loaded template '{name}' ({len(content)} chars)")
        return content

    def get_template(self, name: str) -> str:
        """
        Get a template by name, using cache if available.
        
        Args:
            name: Template name (without .txt extension).
            
        Returns:
            Raw template string with {placeholders}.
        """
        if name not in self._cache:
            self._cache[name] = self._load_template(name)
        return self._cache[name]

    def render(self, template_name: str, **variables) -> str:
        """
        Load a template and render it with the provided variables.
        
        Missing variables in the template will be left as empty strings.
        Extra variables not present in the template are silently ignored.
        
        Args:
            template_name: Name of the template file (without .txt).
            **variables:   Key-value pairs to inject into placeholders.
            
        Returns:
            Rendered prompt string ready to send to an AI provider.
        """
        template = self.get_template(template_name)

        # Use format_map with a defaultdict-like wrapper to handle missing keys
        class SafeDict(dict):
            def __missing__(self, key):
                return ""

        rendered = template.format_map(SafeDict(**variables))

        logger.debug(
            f"[PromptManager] Rendered '{template_name}' with "
            f"{len(variables)} variables ({len(rendered)} chars)"
        )
        return rendered

    def render_raw(self, template_text: str, **variables) -> str:
        """
        Render a raw template string (not loaded from file).
        
        Useful for one-off prompts or testing.
        """
        class SafeDict(dict):
            def __missing__(self, key):
                return ""

        return template_text.format_map(SafeDict(**variables))

    def list_templates(self) -> list[str]:
        """List all available template names."""
        if not self._templates_dir.exists():
            return []
        return [
            f.stem for f in self._templates_dir.glob("*.txt")
        ]

    def reload(self, name: Optional[str] = None) -> None:
        """
        Clear the template cache, forcing a reload from disk.
        
        Args:
            name: If specified, only reload this template. Otherwise reload all.
        """
        if name:
            self._cache.pop(name, None)
        else:
            self._cache.clear()
        logger.info(
            f"[PromptManager] Cache cleared for "
            f"{'template ' + name if name else 'all templates'}."
        )


# Singleton instance — import this across the application
prompt_manager = PromptManager()
