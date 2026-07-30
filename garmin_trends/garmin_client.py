"""Garmin Connect auth: loads a cached session token if present, otherwise
logs in with the credentials in .env (prompting for an MFA code if Garmin
asks for one) and caches the resulting token for next time.
"""
import os
from pathlib import Path

from dotenv import load_dotenv
import garminconnect

BASE_DIR = Path(__file__).resolve().parent
TOKEN_DIR = BASE_DIR / ".garmin_tokens"
ENV_PATH = BASE_DIR / ".env"


def _prompt_mfa() -> str:
    return input("Garmin requested an MFA code - enter it here: ").strip()


def get_client() -> garminconnect.Garmin:
    load_dotenv(ENV_PATH)
    email = os.getenv("GARMIN_EMAIL")
    password = os.getenv("GARMIN_PASSWORD")

    client = garminconnect.Garmin(
        email=email,
        password=password,
        prompt_mfa=_prompt_mfa,
    )
    try:
        client.login(tokenstore=str(TOKEN_DIR))
    except Exception as exc:
        raise SystemExit(
            f"Garmin login failed: {exc}\n"
            f"Check {ENV_PATH} has GARMIN_EMAIL / GARMIN_PASSWORD set correctly, "
            f"or delete {TOKEN_DIR} and try again if a cached session went stale."
        ) from exc
    return client


if __name__ == "__main__":
    c = get_client()
    print(f"Logged in as: {c.get_full_name()}")
    print(f"Session cached at: {TOKEN_DIR}")
