"""
Tests for the three FitFindr tools.
Run with: pytest tests/test_tools.py
"""

from unittest.mock import MagicMock, patch

import pytest

from tools import create_fit_card, search_listings, suggest_outfit


# ── Test 1: search returns results for a broad query ─────────────────────────

def test_search_listings_returns_results():
    results = search_listings(description="vintage tee")
    assert isinstance(results, list)
    assert len(results) > 0
    assert all("title" in item for item in results)


# ── Test 2: search returns empty list when nothing matches ────────────────────

def test_search_listings_no_match():
    results = search_listings(description="zxqwerty nonexistent item xyzzy")
    assert results == []


# ── Test 3: price filter excludes items above max_price ───────────────────────

def test_search_listings_price_filter():
    max_price = 20.0
    results = search_listings(description="shirt jacket top", max_price=max_price)
    assert all(item["price"] <= max_price for item in results)


# ── Test 4: suggest_outfit with empty wardrobe returns a non-empty string ─────

def test_suggest_outfit_empty_wardrobe():
    mock_response = MagicMock()
    mock_response.choices[0].message.content = "Try pairing it with high-waisted jeans and white sneakers."

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_response

    new_item = {
        "title": "Vintage Graphic Tee",
        "category": "tops",
        "style_tags": ["vintage", "graphic"],
        "colors": ["black", "white"],
    }
    empty_wardrobe = {"items": []}

    with patch("tools._get_groq_client", return_value=mock_client):
        result = suggest_outfit(new_item, empty_wardrobe)

    assert isinstance(result, str)
    assert result.strip() != ""


# ── Test 5: create_fit_card with empty outfit returns the exact error string ──

def test_create_fit_card_empty_outfit():
    new_item = {
        "title": "Y2K Baby Tee",
        "price": 18.0,
        "platform": "depop",
    }

    result = create_fit_card("", new_item)
    assert result == "Could not generate fit card: no outfit suggestion provided."

    result_whitespace = create_fit_card("   ", new_item)
    assert result_whitespace == "Could not generate fit card: no outfit suggestion provided."
