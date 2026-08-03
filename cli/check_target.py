import argparse
import asyncio
import json

from app.checks.dns import check_dns
from app.checks.headers import check_headers
from app.checks.reachability import check_reachability
from app.checks.redirect import check_https_redirect
from app.checks.tls import check_tls
from app.scoring import calculate_score


async def run_checks(url: str) -> dict:
    reachability = await check_reachability(url)
    redirect = await check_https_redirect(url)
    dns = check_dns(url)
    tls = check_tls(url)
    headers = await check_headers(url)
    result = {
        "url": url,
        "reachability": reachability,
        "redirect": redirect,
        "dns": dns,
        "tls": tls,
        "headers": headers,
    }
    result["scoring"] = calculate_score(result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Bir hedefi elle yoklar")
    parser.add_argument("url", help="Kontrol edilecek hedef URL")
    args = parser.parse_args()
    result = asyncio.run(run_checks(args.url))
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
