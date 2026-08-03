import socket
from urllib.parse import urlparse


def check_dns(url: str) -> dict:
    hostname = urlparse(url).hostname
    try:
        infos = socket.getaddrinfo(hostname, None)
        ip_addresses = sorted({info[4][0] for info in infos})
        return {"resolved": True, "hostname": hostname, "ip_addresses": ip_addresses, "error": None}
    except socket.gaierror as exc:
        return {"resolved": False, "hostname": hostname, "ip_addresses": [], "error": str(exc)}
