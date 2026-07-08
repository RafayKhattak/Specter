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

    return f'''"""Auto-generated stateful API client from HAR capture."""

from __future__ import annotations

from bs4 import BeautifulSoup
from curl_cffi.requests import Session

LOGIN_URL = "https://github.com/login"
REQUEST_URL = {url!r}

REQUEST_HEADERS: dict[str, str] = {headers_block}

FORM_PAYLOAD: dict[str, str] = {payload_block}

DYNAMIC_TOKEN_FIELDS = ("authenticity_token", "timestamp", "timestamp_secret")


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


def run_login_flow() -> int:
    with Session(impersonate="chrome120") as session:
        login_response = session.get(LOGIN_URL)
        login_response.raise_for_status()

        fresh_tokens = extract_login_tokens(login_response.text)

        print("Freshly extracted tokens:")
        for name, value in fresh_tokens.items():
            print(f"  {{name}}: {{value}}")

        payload = FORM_PAYLOAD.copy()
        payload.update(fresh_tokens)

        post_response = session.post(
            REQUEST_URL,
            headers=REQUEST_HEADERS,
            data=payload,
        )
        return post_response.status_code


def main() -> None:
    status_code = run_login_flow()
    print(f"Response status code: {{status_code}}")


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
    payload = extract_payload(request)

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
