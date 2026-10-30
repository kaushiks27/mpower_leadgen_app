"""Apify scraping feature (S-5).

Campaign-driven lead generation: build a people-search query from a campaign's
target-category + geography + decision-maker roles, run it through Apify, dedup
every result against the central leads table (global contact-once), and write
survivors into the lead spine tagged with the campaign.

One-way dependencies (OP #11): scraping -> leads (dedup + write), -> campaigns
(read campaign), -> config (read role catalog), -> settings (resolve_api_key),
-> infra. None of those modules import scraping.
"""

from __future__ import annotations

from app.scraping.router import router

__all__ = ["router"]
