"""Website resolution — stage 2 of the category-first pipeline (module-local).

A company surfaced by discovery has a *candidate* URL (``https://<domain>/``).
This step confirms the CORRECT website cheaply with httpx (NO Apify spend):
follow redirects to the canonical URL (http→https, apex→www, a moved domain),
and report reachability. Deterministic + defensive: any failure keeps the
original candidate URL and flags it ``unverified`` — a row is NEVER blanked.

Pure-ish: the only side effect is a network GET, injected via the httpx client
so unit tests can pass a transport mock.
"""

from __future__ import annotations

import httpx

from app.competitors import config
from app.competitors.service import normalize_domain


def _is_reachable_status(code: int) -> bool:
    # 2xx/3xx → live; many B2B sites answer 403/405 to a bare GET but still exist,
    # so treat <500 as "reachable enough" (we keep the URL, never blank it).
    return 0 < code < 500


def resolve_result(final_url: str | None, status: int, original_url: str) -> dict:
    """Pure decision: given the final URL + status, return the row patch.

    Returns {"website", "domain", "reachable", "note"}. Deterministic — unit
    tested without network.
    """
    if final_url and _is_reachable_status(status):
        return {
            "website": final_url,
            "domain": normalize_domain(final_url),
            "reachable": True,
            "note": None,
        }
    return {
        "website": original_url,
        "domain": normalize_domain(original_url),
        "reachable": False,
        "note": "website unverified (could not confirm it resolves)",
    }


async def resolve_website(
    url: str, *, client: httpx.AsyncClient | None = None, timeout: float | None = None
) -> dict:
    """Follow redirects from ``url`` → canonical website patch (see resolve_result).

    Never raises: a transport error → unverified patch keeping the original URL.
    """
    original = url or ""
    if not original:
        return {"website": original, "domain": "", "reachable": False, "note": "no candidate URL"}
    # Some stored websites are schemeless/bare (e.g. LinkedIn 'www.zxaero.com') — httpx
    # raises ValueError("unknown url type") on those. Prefix a scheme so the request is
    # valid; the resolved patch still keeps the ORIGINAL on failure (never blanks a row).
    request_url = original if "://" in original else "https://" + original.lstrip("/")
    own = client is None
    cl = client or httpx.AsyncClient(
        follow_redirects=True,
        timeout=timeout or config.WEBRESOLVE_TIMEOUT,
        headers={"user-agent": "Mozilla/5.0 (compatible; mPowerBot/1.0)"},
    )
    try:
        resp = await cl.get(request_url)
        final_url = str(resp.url)
        return resolve_result(final_url, resp.status_code, original)
    except (httpx.HTTPError, ValueError, UnicodeError):
        # ANY transport/URL error → keep the candidate, flag unverified. A single bad
        # row must NEVER crash the whole sync (KI-31, ported from customers).
        return resolve_result(None, 0, original)
    finally:
        if own:
            await cl.aclose()
