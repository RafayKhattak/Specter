"""Auto-generated stateful API client from HAR capture."""

from __future__ import annotations

import getpass
import os
from dataclasses import dataclass

from bs4 import BeautifulSoup
from curl_cffi.requests import Session

LOGIN_URL = "https://github.com/login"
REQUEST_URL = 'https://github.com/session'

REQUEST_HEADERS: dict[str, str] = {
    'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
    'accept-encoding': 'gzip, deflate, br, zstd',
    'cache-control': 'max-age=0',
    'content-type': 'application/x-www-form-urlencoded',
    'origin': 'https://github.com',
    'priority': 'u=0, i',
    'referer': 'https://github.com/login',
    'sec-ch-ua': '"HeadlessChrome";v="149", "Chromium";v="149", "Not)A;Brand";v="24"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"Windows"',
    'sec-fetch-dest': 'document',
    'sec-fetch-mode': 'navigate',
    'sec-fetch-site': 'same-origin',
    'sec-fetch-user': '?1',
    'upgrade-insecure-requests': '1',
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/149.0.7827.55 Safari/537.36'
}

FORM_PAYLOAD: dict[str, str] = {
    'commit': 'Sign in with your identity provider',
    'authenticity_token': '7yCcOZX3q5WZY805dx9 OWj7il/c4JRQ7X13FM4pjiNNIGl3LOLIw4mA0AnBj2qPz ljHOv8/FhPqr6nYZRlZQ==',
    'add_account': '',
    'login': 'specter_benchmark_user',
    'password': 'specter_benchmark_pass_12345',
    'webauthn-conditional': 'undefined',
    'javascript-support': 'true',
    'webauthn-support': 'supported',
    'webauthn-iuvpaa-support': 'supported',
    'return_to': 'https://github.com/login',
    'allow_signup': '',
    'client_id': '',
    'integration': '',
    'required_field_28ef': '',
    'timestamp': '1783508458253',
    'timestamp_secret': '0e0afcfab7f638f2d61f695f9daa2f2a989d38d6b195276b485fc35e48dec4f7'
}

DYNAMIC_TOKEN_FIELDS = ("authenticity_token", "timestamp", "timestamp_secret")


@dataclass(frozen=True)
class LoginResult:
    status_code: int
    success: bool
    message: str
    redirect_url: str | None = None


def extract_login_tokens(html: str) -> dict[str, str]:
    """Parse the login page and extract CSRF / anti-bot hidden fields."""
    soup = BeautifulSoup(html, "html.parser")
    tokens: dict[str, str] = {}

    for field_name in DYNAMIC_TOKEN_FIELDS:
        tag = soup.find("input", {"name": field_name, "type": "hidden"})
        if tag is None or not tag.get("value"):
            raise ValueError(f"Could not find hidden input: {field_name}")
        tokens[field_name] = tag["value"]

    return tokens


def evaluate_login_response(response) -> LoginResult:
    status_code = response.status_code
    redirect_url = response.headers.get("location")
    html = response.text

    if status_code in (301, 302, 303, 307, 308) and redirect_url:
        if "/login" not in redirect_url and "/session" not in redirect_url:
            return LoginResult(status_code, True, "Login succeeded — redirect.", redirect_url)

    soup = BeautifulSoup(html, "html.parser")
    error_banner = soup.select_one("div.flash-error .js-flash-alert")
    if error_banner:
        return LoginResult(status_code, False, error_banner.get_text(strip=True) or "Login failed.")

    user_login = soup.find("meta", attrs={"name": "user-login"})
    username = (user_login.get("content") or "").strip() if user_login else ""
    if username:
        return LoginResult(status_code, True, f"Login succeeded — authenticated as {username}.")

    if "Sign in to GitHub" in html and 'name="password"' in html:
        return LoginResult(status_code, False, "Login failed — still on the sign-in page.")

    return LoginResult(status_code, False, "Login outcome unclear.")


def resolve_credentials(username: str | None = None, password: str | None = None) -> tuple[str, str]:
    resolved_username = username or os.environ.get("GITHUB_USERNAME", "").strip()
    resolved_password = password or os.environ.get("GITHUB_PASSWORD", "")

    if not resolved_username:
        resolved_username = input("GitHub username or email: ").strip()
    if not resolved_password:
        resolved_password = getpass.getpass("GitHub password: ")

    if not resolved_username or not resolved_password:
        raise ValueError("Username and password are required.")

    return resolved_username, resolved_password


def run_login_flow(
    username: str | None = None,
    password: str | None = None,
    *,
    verbose: bool = True,
) -> LoginResult:
    login_username, login_password = resolve_credentials(username, password)

    with Session(impersonate="chrome120") as session:
        login_response = session.get(LOGIN_URL)
        login_response.raise_for_status()

        fresh_tokens = extract_login_tokens(login_response.text)

        if verbose:
            print("Freshly extracted tokens:")
            for name, value in fresh_tokens.items():
                print(f"  {name}: {value}")

        payload = FORM_PAYLOAD.copy()
        payload.update(fresh_tokens)
        payload["login"] = login_username
        payload["password"] = login_password

        post_response = session.post(
            REQUEST_URL,
            headers=REQUEST_HEADERS,
            data=payload,
        )
        result = evaluate_login_response(post_response)

        if verbose:
            print(f"Response status code: {result.status_code}")

        return result


def main() -> None:
    result = run_login_flow()
    status = "SUCCESS" if result.success else "FAILED"
    print(f"Login {status}: {result.message}")


if __name__ == "__main__":
    main()
