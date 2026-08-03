import time

import httpx


async def check_reachability(url: str, timeout: float = 10.0) -> dict:
    start = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(url)
        return {
            "reachable": True,
            "status_code": response.status_code,
            "response_time_ms": round((time.perf_counter() - start) * 1000, 2),
            "timeout": False,
            "error": None,
        }
    except httpx.TimeoutException:
        return {
            "reachable": False,
            "status_code": None,
            "response_time_ms": round((time.perf_counter() - start) * 1000, 2),
            "timeout": True,
            "error": "timeout",
        }
    except httpx.HTTPError as exc:
        return {
            "reachable": False,
            "status_code": None,
            "response_time_ms": round((time.perf_counter() - start) * 1000, 2),
            "timeout": False,
            "error": str(exc),
        }
