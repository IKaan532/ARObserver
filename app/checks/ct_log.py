import httpx

CRT_SH_URL = "https://crt.sh/"


def _extract_names(entry: dict) -> set[str]:
    names = set()
    for field in ("common_name", "name_value"):
        value = entry.get(field)
        if not value:
            continue
        for line in value.split("\n"):
            line = line.strip().lower()
            if line:
                names.add(line)
    return names


def check_certificate_transparency(hostname: str, known_names: set[str], timeout: float = 20.0) -> dict:
    known_lower = {name.lower() for name in known_names}
    try:
        response = httpx.get(
            CRT_SH_URL,
            params={"q": hostname, "output": "json"},
            timeout=timeout,
            headers={"User-Agent": "ARObserver-CT-Check/1.0"},
        )
        response.raise_for_status()
        entries = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        return {"discovered_names": [], "error": str(exc)}

    all_names: set[str] = set()
    for entry in entries:
        all_names |= _extract_names(entry)

    discovered = sorted(name for name in all_names if name not in known_lower and not name.startswith("*."))
    return {"discovered_names": discovered, "error": None}
