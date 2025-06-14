from curl_cffi import requests
import re
from typing import Optional

ep = "https://www.airbnb.com"

# ────────────────────────────────────────────────────────────────────────────
# Compiled with DOTALL so it works whether the page is pretty printed or all
# on one line.  The named capture group “key” lets us extract safely.
# ────────────────────────────────────────────────────────────────────────────
regx_api_key = re.compile(
    r'"api_config"\s*:\s*\{\s*"key"\s*:\s*"(?P<key>[^"]+)"',
    re.DOTALL,
)

def get(proxy_url: str) -> str:
    """
    Return the public API key that Airbnb drops into their HTML.

    Parameters
    ----------
    proxy_url : str
        Full http(s) proxy URL or empty string for direct connection.

    Raises
    ------
    RuntimeError
        If the key cannot be found in Airbnb’s landing page.
    requests.RequestError
        If curl_cffi fails to fetch the page (network, timeout, etc.).
    """
    headers = {
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,image/apng,*/*;q=0.8,"
            "application/signed-exchange;v=b3;q=0.7"
        ),
        "Accept-Language": "en",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Sec-Ch-Ua": (
            '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"'
        ),
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
    }

    # Build proxies dict only if a proxy was supplied
    proxies: Optional[dict[str, str]] = (
        {"http": proxy_url, "https": proxy_url} if proxy_url else {}
    )

    # ── 1. fetch landing page ──────────────────────────────────────────────
    resp = requests.get(ep, headers=headers, proxies=proxies, timeout=60)
    resp.raise_for_status()
    body = resp.text

    # ── 2. pull the API key out of the HTML/JS blob ────────────────────────
    m = regx_api_key.search(body)
    if not m:
        raise RuntimeError(
            "Airbnb API key not found – the front-page markup may have changed."
        )

    api_key = m.group("key")          # ← safer than string-replace
    return api_key
