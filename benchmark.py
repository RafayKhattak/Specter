"""Benchmark Playwright browser automation vs Ghost-Net request-based API."""

from __future__ import annotations

import asyncio
import contextlib
import io
import statistics
import sys
import threading
import time
from dataclasses import dataclass
from typing import Callable

import psutil
from playwright.async_api import Page, async_playwright

from generated_api import run_login_flow

ITERATIONS = 3
LOGIN_URL = "https://github.com/login"
DUMMY_USERNAME = "specter_benchmark_user"
DUMMY_PASSWORD = "specter_benchmark_pass_12345"

# ANSI styling
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
MAGENTA = "\033[95m"
BLUE = "\033[94m"


@dataclass(frozen=True)
class BenchmarkResult:
    label: str
    latencies_ms: list[float]
    peak_memory_mb: list[float]

    @property
    def avg_latency_ms(self) -> float:
        return statistics.mean(self.latencies_ms)

    @property
    def avg_memory_mb(self) -> float:
        return statistics.mean(self.peak_memory_mb)


class PeakMemoryMonitor:
    """Track peak RSS for the current process and all child processes."""

    def __init__(self) -> None:
        self._process = psutil.Process()
        self._peak_bytes = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _sample(self) -> int:
        total = self._process.memory_info().rss
        for child in self._process.children(recursive=True):
            try:
                total += child.memory_info().rss
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return total

    def _run(self) -> None:
        while not self._stop.is_set():
            self._peak_bytes = max(self._peak_bytes, self._sample())
            time.sleep(0.01)

    def start(self) -> None:
        self._peak_bytes = self._sample()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> float:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        self._peak_bytes = max(self._peak_bytes, self._sample())
        return self._peak_bytes / (1024 * 1024)


def _measure_sync(run: Callable[[], object]) -> tuple[float, float]:
    monitor = PeakMemoryMonitor()
    monitor.start()
    start = time.perf_counter()
    run()
    elapsed_ms = (time.perf_counter() - start) * 1000
    peak_mb = monitor.stop()
    return elapsed_ms, peak_mb


async def playwright_login(page: Page) -> None:
    await page.goto(LOGIN_URL, wait_until="networkidle")
    await page.wait_for_selector("#login_field", state="visible", timeout=30_000)
    await page.fill("#login_field", DUMMY_USERNAME)
    await page.evaluate(
        "document.querySelector('#password')?.removeAttribute('disabled')"
    )
    await page.fill("#password", DUMMY_PASSWORD)
    await page.click('input[type="submit"][name="commit"]')
    await page.wait_for_selector("div.flash-error", timeout=30_000)
    await page.wait_for_load_state("networkidle")


async def run_playwright_once() -> tuple[float, float]:
    monitor = PeakMemoryMonitor()
    monitor.start()
    start = time.perf_counter()

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await playwright_login(page)
        finally:
            await browser.close()

    elapsed_ms = (time.perf_counter() - start) * 1000
    peak_mb = monitor.stop()
    return elapsed_ms, peak_mb


def run_api_once() -> tuple[float, float]:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        return _measure_sync(run_login_flow)


async def benchmark_playwright(iterations: int = ITERATIONS) -> BenchmarkResult:
    latencies: list[float] = []
    memories: list[float] = []

    for _ in range(iterations):
        elapsed_ms, peak_mb = await run_playwright_once()
        latencies.append(elapsed_ms)
        memories.append(peak_mb)

    return BenchmarkResult("Playwright", latencies, memories)


def benchmark_api(iterations: int = ITERATIONS) -> BenchmarkResult:
    latencies: list[float] = []
    memories: list[float] = []

    for _ in range(iterations):
        elapsed_ms, peak_mb = run_api_once()
        latencies.append(elapsed_ms)
        memories.append(peak_mb)

    return BenchmarkResult("Ghost-Net (API)", latencies, memories)


def _bar(value: float, max_value: float, width: int = 28) -> str:
    if max_value <= 0:
        return " " * width
    filled = min(width, max(1, int((value / max_value) * width)))
    return "#" * filled + "-" * (width - filled)


def _format_ms(value: float) -> str:
    return f"{value:,.1f} ms"


def print_comparison(playwright: BenchmarkResult, ghost_net: BenchmarkResult) -> None:
    speedup = playwright.avg_latency_ms / ghost_net.avg_latency_ms
    winner = ghost_net.label
    slower = playwright.label

    pw_bar = _bar(playwright.avg_latency_ms, playwright.avg_latency_ms)
    gn_bar = _bar(ghost_net.avg_latency_ms, playwright.avg_latency_ms)

    width = 62
    print()
    print(f"{CYAN}{BOLD}{'=' * width}{RESET}")
    print(f"{CYAN}{BOLD}  ** SPECTER GHOST-NET BENCHMARK **{RESET}")
    print(f"{CYAN}{BOLD}{'=' * width}{RESET}")
    print(f"{DIM}  Target: GitHub login flow  |  Iterations: {ITERATIONS} each{RESET}")
    print(f"{CYAN}{'-' * width}{RESET}")
    print()
    print(f"  {BOLD}{'Method':<22}{'Avg Latency':>14}{'Avg Memory':>14}{RESET}")
    print(f"  {DIM}{'-' * 50}{RESET}")
    print(
        f"  {RED}{playwright.label:<22}{RESET}"
        f"{RED}{_format_ms(playwright.avg_latency_ms):>14}{RESET}"
        f"{RED}{playwright.avg_memory_mb:>12.1f} MB{RESET}"
    )
    print(f"  {DIM}  [{RED}{pw_bar}{RESET}{DIM}]{RESET}")
    print()
    print(
        f"  {GREEN}{ghost_net.label:<22}{RESET}"
        f"{GREEN}{_format_ms(ghost_net.avg_latency_ms):>14}{RESET}"
        f"{GREEN}{ghost_net.avg_memory_mb:>12.1f} MB{RESET}"
    )
    print(f"  {DIM}  [{GREEN}{gn_bar}{RESET}{DIM}]{RESET}")
    print()
    print(f"{CYAN}{'-' * width}{RESET}")
    print(f"{BOLD}  RESULT{RESET}")
    print(
        f"  {GREEN}{BOLD}Ghost-Net is {speedup:.1f}x faster{RESET} "
        f"than {slower} "
        f"({YELLOW}{_format_ms(playwright.avg_latency_ms - ghost_net.avg_latency_ms)}{RESET} saved per run)"
    )
    memory_ratio = playwright.avg_memory_mb / max(ghost_net.avg_memory_mb, 0.1)
    print(
        f"  {MAGENTA}Memory footprint:{RESET} Playwright uses ~{memory_ratio:.1f}x more RAM "
        f"({playwright.avg_memory_mb:.1f} MB vs {ghost_net.avg_memory_mb:.1f} MB)"
    )
    print(f"{CYAN}{BOLD}{'=' * width}{RESET}")
    print()


async def main() -> None:
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    print(f"{BLUE}{BOLD}Running benchmarks...{RESET}")
    print(f"{DIM}  [1/2] Playwright ({ITERATIONS} runs - this will take a minute)...{RESET}")
    playwright_result = await benchmark_playwright()

    print(f"{DIM}  [2/2] Ghost-Net API ({ITERATIONS} runs)...{RESET}")
    api_result = benchmark_api()

    print_comparison(playwright_result, api_result)


if __name__ == "__main__":
    asyncio.run(main())
