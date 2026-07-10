"""
scripts/test_gemini_live.py
=============================
Live verification test for the Gemini API provider.
Sends a real request to the Gemini API to confirm connectivity and response parsing.
"""

import asyncio
import sys
import os
import json
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ai.providers.gemini import GeminiProvider
from src.ai.models.response import EnrichedContact
from src.ai.prompts import prompt_manager
from src.ai.router import AIRouter


async def test_basic_query():
    """Test 1: Basic text query to Gemini."""
    print("\n" + "=" * 60)
    print("TEST 1: Basic Gemini Text Query")
    print("=" * 60)
    
    provider = GeminiProvider()
    try:
        response = await provider.query("What is 2 + 2? Reply with just the number.")
        print(f"  Provider: {response.provider_name}")
        print(f"  Model:    {response.model}")
        print(f"  Latency:  {response.latency:.2f}s")
        print(f"  Retries:  {response.retry_count}")
        print(f"  Response: {response.text.strip()[:200]}")
        print(f"  Usage:    {response.metadata.get('usage', {})}")
        print("  [PASS] Basic query succeeded!")
        return True
    except Exception as e:
        print(f"  [FAIL] {type(e).__name__}: {e}")
        return False
    finally:
        await provider.close()


async def test_structured_query():
    """Test 2: Structured JSON output using Pydantic schema."""
    print("\n" + "=" * 60)
    print("TEST 2: Structured JSON Query (EnrichedContact)")
    print("=" * 60)
    
    provider = GeminiProvider()
    try:
        prompt = (
            "Return a sample contact entry for a fictitious doctor named "
            "Dr. Jane Smith in Chicago, IL with email jane.smith@example.com "
            "and phone (312) 555-0100. She is an MD specializing in Cardiology."
        )
        result = await provider.query_structured(
            prompt, EnrichedContact, timeout=30.0
        )
        print(f"  Parsed Model: {type(result).__name__}")
        print(f"  First Name:   {result.first_name}")
        print(f"  Last Name:    {result.last_name}")
        print(f"  Email:        {result.email}")
        print(f"  Phone:        {result.phone}")
        print(f"  City:         {result.city}")
        print(f"  State:        {result.state}")
        print(f"  Specialty:    {result.specialty}")
        print(f"  Credential:   {result.credential}")
        print("  [PASS] Structured query succeeded!")
        return True
    except Exception as e:
        print(f"  [FAIL] {type(e).__name__}: {e}")
        return False
    finally:
        await provider.close()


async def test_prompt_manager_with_gemini():
    """Test 3: Render a prompt template and send to Gemini."""
    print("\n" + "=" * 60)
    print("TEST 3: Prompt Template + Gemini Query")
    print("=" * 60)
    
    provider = GeminiProvider()
    try:
        rendered = prompt_manager.render(
            "contact_extraction",
            first_name="John",
            last_name="Doe",
            npi="1234567890",
            address="100 Main Street",
            city="Boston",
            state="MA",
            country="US",
        )
        print(f"  Rendered prompt length: {len(rendered)} chars")
        
        result = await provider.query_structured(
            rendered, EnrichedContact, timeout=30.0
        )
        print(f"  Email:     {result.email}")
        print(f"  Phone:     {result.phone}")
        print(f"  Specialty: {result.specialty}")
        print(f"  Source:    {result.source_website}")
        print("  [PASS] Template + structured query succeeded!")
        return True
    except Exception as e:
        print(f"  [FAIL] {type(e).__name__}: {e}")
        return False
    finally:
        await provider.close()


async def test_router_integration():
    """Test 4: Router routes to Gemini provider."""
    print("\n" + "=" * 60)
    print("TEST 4: Router Integration")
    print("=" * 60)
    
    router = AIRouter()
    router.register_provider(GeminiProvider())
    
    try:
        response = await router.query("Reply with: Router test successful")
        print(f"  Routed to: {response.provider_name}")
        print(f"  Response:  {response.text.strip()[:200]}")
        
        stats = router.provider_stats()
        print(f"  Stats:     {json.dumps(stats, indent=2)}")
        print("  [PASS] Router integration succeeded!")
        return True
    except Exception as e:
        print(f"  [FAIL] {type(e).__name__}: {e}")
        return False
    finally:
        await router.stop()


async def main():
    print("=" * 60)
    print("LIVE GEMINI API VERIFICATION")
    print("=" * 60)
    
    results = []
    results.append(await test_basic_query())
    results.append(await test_structured_query())
    results.append(await test_prompt_manager_with_gemini())
    results.append(await test_router_integration())
    
    print("\n" + "=" * 60)
    print(f"RESULTS: {sum(results)}/{len(results)} tests passed")
    print("=" * 60)
    
    if all(results):
        print("\nAll live Gemini API tests PASSED!")
    else:
        print("\nSome tests FAILED. Check the output above.")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
