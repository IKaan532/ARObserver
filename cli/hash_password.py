import argparse
import getpass

from app.auth import hash_password


def main() -> None:
    parser = argparse.ArgumentParser(description="ADMIN_PASSWORD_HASH için bir şifre hash'i üretir")
    parser.add_argument("password", nargs="?", help="Hash'lenecek şifre (verilmezse gizli olarak sorulur)")
    args = parser.parse_args()
    password = args.password or getpass.getpass("Şifre: ")
    print(hash_password(password))


if __name__ == "__main__":
    main()
