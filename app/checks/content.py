import hashlib

import httpx


async def check_content(url: str, expected_keyword: str | None, timeout: float = 10.0) -> dict:
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(url)
    except httpx.HTTPError as exc:
        return {"content_hash": None, "keyword_found": None, "error": str(exc)}

    body = response.text
    content_hash = hashlib.sha256(body.encode("utf-8", errors="ignore")).hexdigest()
    keyword_found = expected_keyword.lower() in body.lower() if expected_keyword else None
    return {"content_hash": content_hash, "keyword_found": keyword_found, "error": None}
