# Specter

**Turn browser traffic into production-ready HTTP clients.**

Specter is a proof-of-concept pipeline that reverse-engineers web portal workflows from captured network traffic and compiles them into fast, stateful Python clients — no browser required at runtime.

> **Thesis:** UIs are for humans. The real API was always there in the network layer. Specter exposes it.

---

## Demo Video

<!-- Replace the placeholder below with your hosted demo link -->

[![Specter Demo](https://img.shields.io/badge/Demo-Video-red?style=for-the-badge&logo=google-drive)](https://drive.google.com/file/d/1xCpb6-gMVLl86aBFQImmMe4nxz4sZyV7/view?usp=sharing)

**Demo video:** [Zatanna PoC Demo (Google Drive)](https://drive.google.com/file/d/1xCpb6-gMVLl86aBFQImmMe4nxz4sZyV7/view?usp=sharing) 

---

## Table of Contents

- [The Problem](#the-problem)
- [The Solution](#the-solution)
- [Architecture](#architecture)
- [Project Structure](#project-structure)
- [Requirements](#requirements)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Detailed Usage](#detailed-usage)
  - [Step 1: Capture (`capture_har.py`)](#step-1-capture-capture_harpy)
  - [Step 2: Compile (`har_compiler.py`)](#step-2-compile-har_compilerpy)
  - [Step 3: Run (`generated_api.py`)](#step-3-run-generated_apipy)
  - [Step 4: Benchmark (`benchmark.py`)](#step-4-benchmark-benchmarkpy)
- [How It Works (Technical Deep Dive)](#how-it-works-technical-deep-dive)
  - [Why naive replay fails (HTTP 422)](#why-naive-replay-fails-http-422)
  - [The stateful two-step login flow](#the-stateful-two-step-login-flow)
  - [What the compiler extracts](#what-the-compiler-extracts)
  - [Browser impersonation with curl_cffi](#browser-impersonation-with-curl_cffi)
- [Benchmark Results](#benchmark-results)
- [End-to-End Pipeline Diagram](#end-to-end-pipeline-diagram)
- [Mapping to Production Portal Automation](#mapping-to-production-portal-automation)
- [Security & Credentials](#security--credentials)
- [Known Limitations](#known-limitations)
- [Roadmap](#roadmap)
- [Troubleshooting](#troubleshooting)
- [License](#license)

---

## The Problem

Many business-critical web portals (ERPs, payer portals, freight carriers, internal tools) **have no public API**. Teams are forced to automate them with browser bots:

```
Playwright / Selenium → open Chrome → click buttons → scrape HTML → repeat
```

This breaks in production:

| Issue | Impact |
|-------|--------|
| **Slow** | Full browser startup + page render for every action (seconds, not milliseconds) |
| **Heavy** | Hundreds of MB of RAM per browser instance |
| **Fragile** | UI redesigns break CSS selectors overnight |
| **Detectable** | Headless browsers trigger anti-bot systems |
| **Hard to scale** | 1,000 workflows × browsers = infrastructure nightmare |

**Example:** A logistics company needs freight quotes from 50 carrier portals, 500 times/day each. Browser automation means thousands of Chrome instances. The portals were never designed for that.

---

## The Solution

Specter implements a **Record → Generate → Run** pipeline:

1. **Record** — Capture real network traffic while a human (or script) completes a workflow once
2. **Generate** — Reverse-engineer the critical HTTP mutation request (e.g. `POST /session`) and compile a Python client
3. **Run** — Execute pure HTTP requests with session management, live CSRF tokens, and browser TLS impersonation

**No browser at runtime.** Direct API calls. Milliseconds, not seconds.

---

## Architecture

```
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│   1. CAPTURE     │ ──► │   2. COMPILE     │ ──► │   3. RUN         │ ──► │   4. PROVE       │
│  capture_har.py  │     │ har_compiler.py  │     │ generated_api.py │     │  benchmark.py    │
│                  │     │                  │     │                  │     │                  │
│  Playwright HAR  │     │  HAR → Python    │     │  curl_cffi HTTP  │     │  vs Playwright   │
│  recording       │     │  codegen         │     │  no browser      │     │  latency + RAM   │
└──────────────────┘     └──────────────────┘     └──────────────────┘     └──────────────────┘
        │                          │                          │
        ▼                          ▼                          ▼
 captures/*.har            generated_api.py            LoginResult JSON
```

---

## Project Structure

```
Specter/
├── capture_har.py       # Automated HAR capture (Playwright)
├── har_compiler.py      # HAR parser + Python code generator
├── generated_api.py     # Compiled stateful HTTP client (GitHub login)
├── benchmark.py         # Playwright vs Ghost-Net performance race
├── requirements.txt     # Python dependencies
├── .env.example         # Credential template (copy to .env — gitignored)
├── .gitignore
├── captures/            # HAR files (gitignored — may contain secrets)
│   └── github_login.har
└── README.md
```

---

## Requirements

- **Python 3.12+** (3.14 works; use `py` on Windows)
- **Chromium** (installed via Playwright for capture + benchmark only)
- Internet access (targets `github.com` in the demo)

---

## Installation

```powershell
# Clone / enter the project
cd Specter

# Install Python dependencies
py -m pip install -r requirements.txt

# Install Chromium for Playwright (capture + benchmark only)
py -m playwright install chromium

# Optional: copy credential template for capture / login scripts
copy .env.example .env
# Edit .env with your GitHub username and password
```

---

## Quick Start

Full pipeline in three commands:

```powershell
# 1. Capture traffic (opens browser — log in manually, then press Enter)
py capture_har.py --compile

# 2. Run the compiled API client (prompts for credentials)
py generated_api.py

# 3. Benchmark vs Playwright
py benchmark.py
```

---

## Detailed Usage

### Step 1: Capture (`capture_har.py`)

Automatically records network traffic to a HAR file. **No manual DevTools export.**

#### Interactive mode (default — recommended)

Opens a visible browser. You perform the workflow; Specter records everything.

```powershell
py capture_har.py
```

1. Chromium opens at `https://github.com/login`
2. Complete the login flow in the browser
3. Return to the terminal and press **Enter**
4. HAR saved to `captures/github_login.har`

#### Capture + compile in one step

```powershell
py capture_har.py --compile
```

Runs `har_compiler.py` immediately after capture → writes `generated_api.py`.

#### Automated mode (headless)

```powershell
py capture_har.py --auto --headless
```

Prompts for GitHub credentials (or uses env vars). Runs the login flow automatically without manual browser interaction.

#### All capture options

| Flag | Description |
|------|-------------|
| `--url URL` | Starting page (default: `https://github.com/login`) |
| `--output PATH` | HAR output path (default: `captures/github_login.har`) |
| `--auto` | Automated login instead of manual browser use |
| `--headless` | Hide browser window (usually with `--auto`) |
| `--username` | GitHub username (auto mode) |
| `--password` | GitHub password (auto mode) |
| `--compile` | Run compiler after capture |

---

### Step 2: Compile (`har_compiler.py`)

Parses a HAR file and generates a Python HTTP client.

```powershell
py har_compiler.py
```

Reads `captures/github_login.har` by default, writes `generated_api.py`.

#### What it extracts

From the HAR, the compiler finds the first **`POST`** request whose URL contains **`/session`** and extracts:

- **Request URL** — e.g. `https://github.com/session`
- **Headers** — browser headers (`accept`, `origin`, `referer`, `sec-ch-ua*`, `user-agent`, etc.)
- **Excluded headers** — HTTP/2 pseudo-headers (`:authority`, `:method`, …), `content-length`, `cookie` (managed by session)
- **Form payload** — all `application/x-www-form-urlencoded` fields from `postData`

#### Programmatic usage

```python
from pathlib import Path
from har_compiler import compile_har

compile_har(
    Path("captures/github_login.har"),
    Path("generated_api.py"),
    url_pattern="/session",
)
```

---

### Step 3: Run (`generated_api.py`)

Executes the compiled login flow using **pure HTTP** — no browser.

```powershell
py generated_api.py
```

Prompts for username and password (hidden input). Or use environment variables:

```powershell
$env:GITHUB_USERNAME = "your_username"
$env:GITHUB_PASSWORD = "your_password"
py generated_api.py
```

#### Expected output (success)

```
Freshly extracted tokens:
  authenticity_token: PQLV6CM1Gsllvgg0Cl6lIPBqqwG92KAYz0NT8JzRlfG+...
  timestamp: 1783506159578
  timestamp_secret: 43e383ae3110883d5126f3ec802a39a59284b31595fb5199ac0dffaba2ae6070
Response status code: 200
Login SUCCESS: Login succeeded — authenticated as YourUsername.
```

#### Python API

```python
from generated_api import run_login_flow

result = run_login_flow(username="you", password="secret", verbose=False)
print(result.success, result.message)
```

`run_login_flow()` returns a `LoginResult` dataclass:

| Field | Type | Description |
|-------|------|-------------|
| `status_code` | `int` | HTTP status from POST |
| `success` | `bool` | Whether login succeeded |
| `message` | `str` | Human-readable outcome |
| `redirect_url` | `str \| None` | Redirect URL if applicable |

---

### Step 4: Benchmark (`benchmark.py`)

Races **Playwright** (headless browser automation) against **Ghost-Net** (the compiled HTTP client).

```powershell
py benchmark.py
```

Runs each approach **3 times**, averages latency (ms) and peak memory (MB), prints a comparison table.

Uses dummy credentials (`specter_benchmark_user`) — measures infrastructure cost, not login success.

---

## How It Works (Technical Deep Dive)

### Why naive replay fails (HTTP 422)

If you replay the exact `POST /session` from a HAR file with hardcoded values:

```python
# This FAILS with HTTP 422
session.post("/session", data=HAR_FORM_PAYLOAD)
```

GitHub rejects it because:

1. **`authenticity_token`** — CSRF token bound to session cookies from `GET /login`; single-use
2. **`timestamp` / `timestamp_secret`** — time-bound anti-bot fields generated per page load
3. **No cookie chain** — POST expects cookies established by visiting the login page first

### The stateful two-step login flow

`generated_api.py` implements the fix:

```
┌─────────────────────────────────────────────────────────────┐
│  Step 1: GET https://github.com/login                       │
│          → establish session cookies                        │
├─────────────────────────────────────────────────────────────┤
│  Step 2: Parse HTML (BeautifulSoup)                         │
│          → extract authenticity_token                       │
│          → extract timestamp                                │
│          → extract timestamp_secret                         │
├─────────────────────────────────────────────────────────────┤
│  Step 3: POST https://github.com/session                    │
│          → inject fresh tokens into form payload            │
│          → inject runtime credentials                       │
│          → same session object (cookies preserved)          │
└─────────────────────────────────────────────────────────────┘
```

### What the compiler extracts

Example from a GitHub login capture:

| Category | Count | Examples |
|----------|-------|----------|
| Headers | 17 | `accept`, `origin`, `referer`, `sec-ch-ua`, `user-agent` |
| Form fields | 16 | `commit`, `login`, `password`, `authenticity_token`, `timestamp`, … |
| Dynamic fields (refreshed at runtime) | 3 | `authenticity_token`, `timestamp`, `timestamp_secret` |

### Browser impersonation with curl_cffi

```python
Session(impersonate="chrome120")
```

`curl_cffi` mimics real Chrome TLS/JA3 fingerprints and HTTP/2 behavior. Portals with anti-bot checks see a legitimate browser fingerprint — not Python `requests`.

---

## Benchmark Results

Measured on GitHub login flow (3 iterations each):

| Method | Avg Latency | Avg Memory | Notes |
|--------|-------------|------------|-------|
| **Playwright** | 4,502 ms | 440 MB | Headless Chromium, fill fields, click, wait |
| **Ghost-Net (API)** | 857 ms | 43 MB | Pure HTTP via `curl_cffi` |
| **Speedup** | **5.3× faster** | **~10× less RAM** | ~3,645 ms saved per run |

```
==============================================================
  ** SPECTER GHOST-NET BENCHMARK **
==============================================================
  Method                   Avg Latency    Avg Memory
  --------------------------------------------------
  Playwright                  4,502.0 ms       440.1 MB
  Ghost-Net (API)               856.9 ms        43.3 MB
--------------------------------------------------------------
  Ghost-Net is 5.3x faster than Playwright (3,645.2 ms saved per run)
==============================================================
```

*Results vary by network, machine, and portal. Re-run `benchmark.py` locally for fresh numbers.*

---

## End-to-End Pipeline Diagram

```
Human / Script                Specter                         Target Portal
     │                           │                                  │
     │  browse login page        │                                  │
     ├──────────────────────────►│  capture_har.py                  │
     │                           ├─────────────────────────────────►│
     │                           │◄─────────────────────────────────┤
     │                           │  saves captures/github_login.har │
     │                           │                                  │
     │                           │  har_compiler.py                 │
     │                           │  → generated_api.py              │
     │                           │                                  │
     │  py generated_api.py      │                                  │
     ├──────────────────────────►│  GET /login  (cookies)           │
     │                           ├─────────────────────────────────►│
     │                           │◄─────────────────────────────────┤
     │                           │  parse CSRF tokens               │
     │                           │  POST /session (credentials)     │
     │                           ├─────────────────────────────────►│
     │                           │◄─────────────────────────────────┤
     │◄──────────────────────────┤  LoginResult(success=True)       │
```

---

## Mapping to Production Portal Automation

Specter is an MVP of the **Record → Generate → Run** loop used by portal-to-API platforms:

| Production stage | Specter implementation | Status |
|------------------|------------------------|--------|
| **Record** — capture network traffic from a workflow | `capture_har.py` | ✅ Done |
| **Generate** — reconstruct auth, sessions, sequencing | `har_compiler.py` + dynamic token injection | ✅ Done |
| **Run** — direct HTTP, no UI | `generated_api.py` + `curl_cffi` | ✅ Done |
| **Prove** — faster than browser automation | `benchmark.py` | ✅ Done |
| **Integrate** — hosted API endpoint for agents | Not in scope (MVP) | 🔲 Future |
| **Reliability** — MFA, auto-repair, change detection | Not in scope (MVP) | 🔲 Future |

**Real-world use case this demo maps to:**

> A freight startup needs quotes from `carrier-portal.com` with no API. A human logs in once; Specter captures the underlying `POST /api/rates/calculate`. Production agents call that endpoint directly — 5× faster, no Chrome fleet.

GitHub login is the same pattern: auth tokens, session cookies, mutation POST — just a simpler portal.

---

## Security & Credentials

**Important:**

- HAR files in `captures/` may contain **plaintext passwords, cookies, and tokens**
- `captures/` and `*.har` are **gitignored** — do not commit them
- Never paste credentials into chat logs or issue trackers
- Use environment variables, a local `.env` file (see `.env.example`), or interactive `getpass` prompts at runtime
- `generated_api.py` stores **placeholder** credentials in `FORM_PAYLOAD`; runtime env/prompt values always override them

```powershell
# Clear env vars after use
Remove-Item Env:GITHUB_USERNAME -ErrorAction SilentlyContinue
Remove-Item Env:GITHUB_PASSWORD -ErrorAction SilentlyContinue
```

---

## Known Limitations

| Limitation | Details |
|------------|---------|
| **GitHub-specific compiler** | `har_compiler.py` targets `POST` + `/session`; other portals need different URL patterns |
| **2FA / MFA** | Accounts with two-factor authentication will not complete via this HTTP-only flow |
| **Account challenges** | GitHub may require CAPTCHA or email verification from new IPs |
| **Capture requires browser once** | Playwright used at compile/capture time only; not at runtime |
| **Portal changes** | If GitHub changes auth flow, re-capture and re-compile |

---

## Roadmap

- [ ] Generic flow compiler (manifest-driven, not hardcoded `/session`)
- [ ] FastAPI wrapper — single stable endpoint (`POST /v1/workflows/github/login`)
- [ ] Session persistence (save cookies to disk for follow-up requests)
- [ ] Health checks + golden replay tests (detect when portal changes)
- [ ] TOTP MFA support
- [ ] TLS proxy capture (any browser, not just Playwright)

---

## Troubleshooting

### `ModuleNotFoundError: curl_cffi`

```powershell
py -m pip install -r requirements.txt
```

### `playwright` browser not found

```powershell
py -m playwright install chromium
```

### `FileNotFoundError: captures/github_login.har`

Run capture first:

```powershell
py capture_har.py
```

### HTTP 422 on login

Stale CSRF tokens. Ensure `generated_api.py` uses the **two-step flow** (GET → parse → POST), not hardcoded HAR tokens alone.

### Playwright password field disabled

GitHub disables `#password` until client JS runs. `capture_har.py --auto` handles this; interactive mode works because you click manually.

### `IndentationError` in `generated_api.py`

Re-run compiler or check that function definitions and docstrings are on separate lines.

### Benchmark Unicode errors on Windows

Benchmark uses ASCII-safe table characters. Use Windows Terminal or PowerShell 7 for best ANSI color support.

---

## License

MIT 

---

<p align="center">
  <strong>Specter</strong> — UIs are for humans. Agents call HTTP.
</p>
