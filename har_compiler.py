"""HAR file compiler — extracts a POST /session request and generates a curl_cffi client."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import unquote_plus

HAR_FILENAME = "captures/github_login.har"
OUTPUT_FILENAME = "generated_api.py"

PSEUDO_HEADERS = {":authority", ":method", ":path", ":scheme", ":status"}
SESSION_MANAGED_HEADERS = {"content-length", "cookie"}
SENSITIVE_PAYLOAD_FIELDS = frozenset({"login", "password"})
DYNAMIC_TOKEN_FIELDS = frozenset({"authenticity_token", "timestamp", "timestamp_secret"})
PLACEHOLDER_CREDENTIALS = {
    "login": "specter_benchmark_user",
    "password": "specter_benchmark_pass_12345",
}


def load_har(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def find_session_post(
    har: dict[str, Any],
    *,
    url_pattern: str = "/session",
    method: str = "POST",
) -> dict[str, Any]:
    """Return the first matching mutation request from the HAR."""
    entries = har.get("log", {}).get("entries", [])
    for entry in entries:
        request = entry.get("request", {})
        entry_method = request.get("method", "").upper()
        url = request.get("url", "")
        if entry_method == method.upper() and url_pattern in url:
            return request
    raise ValueError(
        f"No {method.upper()} request containing {url_pattern!r} found in HAR file."
    )


def extract_headers(request: dict[str, Any]) -> dict[str, str]:
    headers: dict[str, str] = {}
    for header in request.get("headers", []):
        name = header.get("name", "")
        value = header.get("value", "")
        normalized = name.lower()

        if normalized in PSEUDO_HEADERS or normalized in SESSION_MANAGED_HEADERS:
            continue
        if name.startswith(":"):
            continue

        headers[name] = value
    return headers


def extract_payload(request: dict[str, Any]) -> dict[str, str]:
    post_data = request.get("postData")
    if not post_data:
        raise ValueError("POST request has no postData payload.")

    params = post_data.get("params")
    if params:
        return {
            param["name"]: unquote_plus(param.get("value", ""))
            for param in params
            if "name" in param
        }

    raw_text = post_data.get("text", "")
    if not raw_text:
        raise ValueError("POST request postData contains neither params nor text.")

    payload: dict[str, str] = {}
    for pair in raw_text.split("&"):
        if "=" in pair:
            key, value = pair.split("=", 1)
            payload[unquote_plus(key)] = unquote_plus(value)
        elif pair:
            payload[unquote_plus(pair)] = ""
    return payload


def sanitize_payload(payload: dict[str, str]) -> dict[str, str]:
    """Remove captured secrets — credentials come from env/prompts at runtime."""
    sanitized = dict(payload)
    for field in SENSITIVE_PAYLOAD_FIELDS:
        sanitized[field] = PLACEHOLDER_CREDENTIALS[field]
    for field in DYNAMIC_TOKEN_FIELDS:
        if field in sanitized:
            sanitized[field] = ""
    return sanitized


def format_python_dict(data: dict[str, str]) -> str:
    if not data:
        return "{}"

    lines = ["{"]
    items = list(data.items())
    for index, (key, value) in enumerate(items):
        comma = "," if index < len(items) - 1 else ""
        lines.append(f"    {key!r}: {value!r}{comma}")
    lines.append("}")
    return "\n".join(lines)


def generate_api_script(url: str, headers: dict[str, str], payload: dict[str, str]) -> str:
    headers_block = format_python_dict(headers)
    payload_block = format_python_dict(payload)

    return f'''"""Auto-generated stateful API client from HAR capture.

Credentials in FORM_PAYLOAD are placeholders only. Set GITHUB_USERNAME and
GITHUB_PASSWORD environment variables, pass arguments to run_login_flow(), or
use the interactive prompts when running this script directly.
"""

from __future__ import annotations

import getpass
import os
from dataclasses import dataclass

from bs4 import BeautifulSoup
from curl_cffi.requests import Session

LOGIN_URL = "https://github.com/login"
REQUEST_URL = {url!r}

REQUEST_HEADERS: dict[str, str] = {headers_block}

FORM_PAYLOAD: dict[str, str] = {payload_block}

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
    tokens: dict[str, str] = {{}}

    for field_name in DYNAMIC_TOKEN_FIELDS:
        tag = soup.find("input", {{"name": field_name, "type": "hidden"}})
        if tag is None or not tag.get("value"):
            raise ValueError(f"Could not find hidden input: {{field_name}}")
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

    user_login = soup.find("meta", attrs={{"name": "user-login"}})
    username = (user_login.get("content") or "").strip() if user_login else ""
    if username:
        return LoginResult(status_code, True, f"Login succeeded — authenticated as {{username}}.")

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
                print(f"  {{name}}: {{value}}")

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
            print(f"Response status code: {{result.status_code}}")

        return result


def main() -> None:
    result = run_login_flow()
    status = "SUCCESS" if result.success else "FAILED"
    print(f"Login {{status}}: {{result.message}}")


if __name__ == "__main__":
    main()
'''


def compile_har(
    har_path: Path,
    output_path: Path,
    *,
    url_pattern: str = "/session",
) -> None:
    har = load_har(har_path)
    request = find_session_post(har, url_pattern=url_pattern)

    url = request["url"]
    headers = extract_headers(request)
    payload = sanitize_payload(extract_payload(request))

    generated_source = generate_api_script(url, headers, payload)
    output_path.write_text(generated_source, encoding="utf-8")

    print(f"Extracted POST {url}")
    print(f"  Headers: {len(headers)}")
    print(f"  Form fields: {len(payload)}")
    print(f"Wrote {output_path}")


def main() -> None:
    project_root = Path(__file__).resolve().parent
    har_path = project_root / HAR_FILENAME
    output_path = project_root / OUTPUT_FILENAME

    if not har_path.exists():
        raise FileNotFoundError(f"HAR file not found: {har_path}")

    compile_har(har_path, output_path)


if __name__ == "__main__":
    main()
