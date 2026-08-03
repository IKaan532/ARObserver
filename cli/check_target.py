import argparse
import asyncio
import json

from app.checks.dns import check_dns
from app.checks.reachability import check_reachability
from app.checks.redirect import check_https_redirect


async def run_checks(url: str) -> dict:
    reachability = await check_reachability(url)
    redirect = await check_https_redirect(url)
    dns = check_dns(url)
    return {"url": url, "reachability": reachability, "redirect": redirect, "dns": dns}


def main() -> None:
    parser = argparse.ArgumentParser(description="Bir hedefi elle yoklar")
    parser.add_argument("url", help="Kontrol edilecek hedef URL")
    args = parser.parse_args()
    result = asyncio.run(run_checks(args.url))
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
