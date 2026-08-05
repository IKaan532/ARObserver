import asyncio
import socket
import time
from urllib.parse import urlparse

import httpx


def _resolve_dns_timing(hostname: str) -> float | None:
    start = time.perf_counter()
    try:
        socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return None
    return round((time.perf_counter() - start) * 1000, 2)


def _span_ms(timings: dict, key_start: str, key_end: str) -> float | None:
    if key_start in timings and key_end in timings:
        return round((timings[key_end] - timings[key_start]) * 1000, 2)
    return None


async def check_reachability(url: str, timeout: float = 10.0) -> dict:
    hostname = urlparse(url).hostname
    dns_ms = await asyncio.to_thread(_resolve_dns_timing, hostname) if hostname else None

    timings: dict = {}

    async def tracer(name: str, info: dict) -> None:
        now = time.perf_counter()
        if name == "connection.connect_tcp.started":
            timings["tcp_start"] = now
        elif name == "connection.connect_tcp.complete":
            timings["tcp_end"] = now
        elif name == "connection.start_tls.started":
            timings["tls_start"] = now
        elif name == "connection.start_tls.complete":
            timings["tls_end"] = now
        elif name == "http11.send_request_headers.started":
            timings["request_start"] = now
        elif name == "http11.receive_response_headers.complete":
            timings["headers_end"] = now
        elif name == "http11.receive_response_body.complete":
            timings["body_end"] = now

    start = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            request = client.build_request("GET", url)
            request.extensions["trace"] = tracer
            response = await client.send(request)

        timing_result = {
            "dns_ms": dns_ms,
            "tcp_ms": _span_ms(timings, "tcp_start", "tcp_end"),
            "tls_ms": _span_ms(timings, "tls_start", "tls_end"),
            "ttfb_ms": _span_ms(timings, "request_start", "headers_end"),
            "download_ms": _span_ms(timings, "headers_end", "body_end"),
            "body_size_bytes": len(response.content),
            "content_encoding": response.headers.get("content-encoding"),
        }

        return {
            "reachable": True,
            "status_code": response.status_code,
            "response_time_ms": round((time.perf_counter() - start) * 1000, 2),
            "timeout": False,
            "error": None,
            "timing": timing_result,
        }
    except httpx.TimeoutException:
        return {
            "reachable": False,
            "status_code": None,
            "response_time_ms": round((time.perf_counter() - start) * 1000, 2),
            "timeout": True,
            "error": "timeout",
            "timing": None,
        }
    except httpx.HTTPError as exc:
        return {
            "reachable": False,
            "status_code": None,
            "response_time_ms": round((time.perf_counter() - start) * 1000, 2),
            "timeout": False,
            "error": str(exc),
            "timing": None,
        }
