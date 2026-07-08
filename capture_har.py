"""Automatically capture a HAR file — no manual DevTools export needed.

Usage:
    py capture_har.py              # opens browser, record your flow, press Enter
    py capture_har.py --compile    # same, then runs har_compiler.py
    py capture_har.py --auto       # fully automated GitHub login capture
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys
from pathlib import Path

from playwright.async_api import BrowserContext, Page, async_playwright

DEFAULT_OUTPUT = "captures/github_login.har"
DEFAULT_START_URL = "https://github.com/login"


async def _github_automated_flow(page: Page, username: str, password: str) -> None:
    await page.goto(DEFAULT_START_URL, wait_until="domcontentloaded")
    await page.wait_for_selector("#login_field", state="visible", timeout=30_000)
    await page.fill("#login_field", username)
    await page.evaluate(
        "document.querySelector('#password')?.removeAttribute('disabled')"
    )
    await page.fill("#password", password)
    await page.click('input[type="submit"][name="commit"]')
    # GitHub keeps background requests open — networkidle often never fires.
    await page.wait_for_function(
        "() => !location.pathname.includes('/login') || document.querySelector('div.flash-error')",
        timeout=30_000,
    )
    await page.wait_for_load_state("domcontentloaded")


async def capture_har(
    *,
    start_url: str,
    output_path: Path,
    headless: bool,
    interactive: bool,
    username: str | None,
    password: str | None,
) -> Path:
    async with async_playwright() as playwright:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        browser = await playwright.chromium.launch(headless=headless)
        context: BrowserContext = await browser.new_context(
            record_har_path=str(output_path),
            record_har_content="embed",
            record_har_mode="full",
        )
        page = await context.new_page()

        try:
            if interactive:
                await page.goto(start_url, wait_until="domcontentloaded")
                print()
                print("Recording network traffic...")
                print(f"  URL:   {start_url}")
                print(f"  Output: {output_path}")
                print()
                print("  1. Use the browser window to complete the flow (login, checkout, etc.).")
                print("  2. Come back here and press Enter to save the HAR.")
                print()
                await asyncio.to_thread(input, "Press Enter when done... ")
            else:
                if not username or not password:
                    raise ValueError("Automated mode requires credentials.")
                print(f"Recording automated flow -> {output_path}")
                await _github_automated_flow(page, username, password)

            await context.close()
            await browser.close()
        except Exception:
            await context.close()
            await browser.close()
            raise

    if not output_path.exists():
        raise RuntimeError(f"HAR file was not written: {output_path}")

    return output_path


def resolve_credentials(args: argparse.Namespace) -> tuple[str | None, str | None]:
    if args.interactive:
        return None, None

    username = args.username or os.environ.get("GITHUB_USERNAME", "").strip() or None
    password = args.password or os.environ.get("GITHUB_PASSWORD") or None

    if not username:
        username = input("GitHub username or email: ").strip() or None
    if not password:
        password = getpass.getpass("GitHub password: ")

    return username, password


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Automatically capture a HAR file (no manual DevTools export).",
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_START_URL,
        help=f"Page to open (default: {DEFAULT_START_URL})",
    )
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT,
        help=f"HAR file to write (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Automate the GitHub login flow instead of manual browser use.",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Hide the browser window (usually paired with --auto).",
    )
    parser.add_argument("--username", help="GitHub username for --auto mode.")
    parser.add_argument("--password", help="GitHub password for --auto mode.")
    parser.add_argument(
        "--compile",
        action="store_true",
        help="Run har_compiler.py after capture.",
    )
    return parser.parse_args()


def maybe_compile(output_path: Path) -> None:
    from har_compiler import compile_har

    project_root = Path(__file__).resolve().parent
    compile_har(output_path, project_root / "generated_api.py")


async def main() -> None:
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    args = parse_args()
    output_path = Path(args.output).resolve()
    interactive = not args.auto
    username, password = resolve_credentials(
        argparse.Namespace(
            interactive=interactive,
            username=args.username,
            password=args.password,
        )
    )

    saved_path = await capture_har(
        start_url=args.url,
        output_path=output_path,
        headless=args.headless,
        interactive=interactive,
        username=username,
        password=password,
    )

    size_kb = saved_path.stat().st_size / 1024
    print(f"\nHAR saved: {saved_path} ({size_kb:.1f} KB)")

    if args.compile:
        print("Compiling -> generated_api.py ...")
        maybe_compile(saved_path)
        print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
