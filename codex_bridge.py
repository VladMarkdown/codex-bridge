"""codex-bridge — call OpenAI Codex (GPT-5.x, "Sign in with ChatGPT") from the
command line or from another tool/agent.

This is a thin BRIDGE: it authenticates once via the Codex OAuth device flow and
then lets you send a prompt to Codex and read the answer back. Nothing else —
build whatever you need (code review, second opinion, image generation, ...) on
top of `ask()` / `respond()`.

The token lives ONLY on this machine in ~/.codex-bridge/auth.json
(override with $CODEX_BRIDGE_HOME). It is never printed and never committed.

CLI:
  codex-bridge login                 # one-time browser login
  codex-bridge ask "your prompt"     # print Codex's text answer
  echo "long prompt" | codex-bridge ask -    # read the prompt from stdin
  codex-bridge ask "..." --model gpt-5.5

Library:
  from codex_bridge import ask, respond
  text = ask("Explain this stack trace ...")
  # respond() is the low-level primitive — pass `tools=[...]` to use Codex
  # tools (e.g. image_generation). See respond() docstring.

Requires Python 3.9+. Standard library only.
"""

from __future__ import annotations

import argparse
import base64
import http.client
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# ── Endpoints / client ────────────────────────────────────────────────────────
AUTH_BASE = "https://auth.openai.com"
CODEX_BASE = "https://chatgpt.com/backend-api/codex"
# OpenAI's Codex OAuth client id (the "Sign in with ChatGPT" flow). Public value.
CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
# Client identifier sent to the API. Override with $CODEX_BRIDGE_ORIGINATOR.
ORIGINATOR = os.environ.get("CODEX_BRIDGE_ORIGINATOR", "codex-bridge")
DEFAULT_MODEL = os.environ.get("CODEX_BRIDGE_MODEL", "gpt-5.5")

HOME = os.environ.get("CODEX_BRIDGE_HOME") or os.path.join(os.path.expanduser("~"), ".codex-bridge")
TOKEN_PATH = os.path.join(HOME, "auth.json")


# ── HTTP helpers ───────────────────────────────────────────────────────────────
def _base_headers(content_type: str | None = None) -> dict[str, str]:
    h = {"originator": ORIGINATOR, "User-Agent": ORIGINATOR}
    if content_type:
        h["Content-Type"] = content_type
    return h


def _post(url: str, *, headers: dict[str, str], data: bytes, timeout: int = 60):
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        return resp.getcode(), resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def _post_json(url: str, payload: dict, *, timeout: int = 60):
    return _post(url, headers=_base_headers("application/json"),
                 data=json.dumps(payload).encode("utf-8"), timeout=timeout)


def _post_form(url: str, payload: dict, *, timeout: int = 60):
    return _post(url, headers=_base_headers("application/x-www-form-urlencoded"),
                 data=urllib.parse.urlencode(payload).encode("utf-8"), timeout=timeout)


# ── Token store + refresh ───────────────────────────────────────────────────────
def _decode_jwt(access_token: str) -> dict:
    parts = access_token.split(".")
    if len(parts) != 3:
        return {}
    pad = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(pad).decode("utf-8"))
    except Exception:
        return {}


def _account_id(access_token: str) -> str | None:
    auth = _decode_jwt(access_token).get("https://api.openai.com/auth") or {}
    acc = auth.get("chatgpt_account_id")
    return acc if isinstance(acc, str) and acc else None


def _jwt_exp_ms(access_token: str) -> int | None:
    exp = _decode_jwt(access_token).get("exp")
    return int(exp) * 1000 if isinstance(exp, (int, float)) and exp > 0 else None


def _expires_ms(access_token: str, expires_in) -> int:
    if isinstance(expires_in, (int, float)) and expires_in > 0:
        return int(time.time() * 1000 + expires_in * 1000)
    return _jwt_exp_ms(access_token) or int(time.time() * 1000)


def save_tokens(access: str, refresh: str, expires_ms: int) -> None:
    os.makedirs(HOME, exist_ok=True)
    payload = _decode_jwt(access)
    profile = payload.get("https://api.openai.com/profile") or {}
    auth = payload.get("https://api.openai.com/auth") or {}
    data = {
        "access": access,
        "refresh": refresh,
        "expires": expires_ms,
        "accountId": _account_id(access),
        "email": profile.get("email"),
        "plan": auth.get("chatgpt_plan_type"),
    }
    with open(TOKEN_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    try:
        os.chmod(TOKEN_PATH, 0o600)
    except Exception:
        pass


def load_tokens() -> dict | None:
    if not os.path.exists(TOKEN_PATH):
        return None
    with open(TOKEN_PATH, encoding="utf-8") as f:
        return json.load(f)


def _refresh(refresh_token: str) -> dict:
    code, body = _post_form(f"{AUTH_BASE}/oauth/token", {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": CLIENT_ID,
    })
    if code != 200:
        raise RuntimeError(f"token refresh failed ({code}): {body[:300]}")
    j = json.loads(body)
    access = j.get("access_token")
    if not access:
        raise RuntimeError("token refresh response missing access_token")
    new_refresh = j.get("refresh_token") or refresh_token
    save_tokens(access, new_refresh, _expires_ms(access, j.get("expires_in")))
    return {"access": access, "accountId": _account_id(access)}


def get_valid_access() -> tuple[str, str]:
    """Return (access_token, account_id), refreshing if near expiry.
    Raises if not logged in (run `codex-bridge login` first)."""
    tok = load_tokens()
    if not tok:
        raise RuntimeError("Not logged in. Run: codex-bridge login")
    if int(tok.get("expires", 0)) - 60_000 < int(time.time() * 1000):
        tok = {**tok, **_refresh(tok["refresh"])}
    access = tok["access"]
    acc = tok.get("accountId") or _account_id(access)
    if not acc:
        raise RuntimeError("Could not resolve chatgpt_account_id from token")
    return access, acc


# ── One-time device-code login ──────────────────────────────────────────────────
def login() -> int:
    import webbrowser
    print("Requesting device code from OpenAI...")
    code, body = _post_json(f"{AUTH_BASE}/api/accounts/deviceauth/usercode",
                            {"client_id": CLIENT_ID})
    if code != 200:
        print(f"usercode request failed ({code}): {body[:400]}", file=sys.stderr)
        return 1
    j = json.loads(body)
    device_auth_id = j.get("device_auth_id")
    user_code = j.get("user_code") or j.get("usercode")
    interval = max(1, int(j.get("interval") or 5))
    if not device_auth_id or not user_code:
        print(f"missing device/user code: {body[:400]}", file=sys.stderr)
        return 1

    verify_url = f"{AUTH_BASE}/codex/device"
    print("\n" + "=" * 56)
    print("  1) Open:  " + verify_url)
    print("  2) Enter code:  " + user_code)
    print("  3) Approve in your ChatGPT account.")
    print("=" * 56 + "\n")
    try:
        webbrowser.open(verify_url)
    except Exception:
        pass

    print("Waiting for authorization (up to 15 min)...")
    deadline = time.time() + 15 * 60
    authorization_code = code_verifier = None
    while time.time() < deadline:
        c, b = _post_json(f"{AUTH_BASE}/api/accounts/deviceauth/token",
                          {"device_auth_id": device_auth_id, "user_code": user_code})
        if c == 200:
            tj = json.loads(b)
            authorization_code = tj.get("authorization_code")
            code_verifier = tj.get("code_verifier")
            if authorization_code and code_verifier:
                break
            print(f"unexpected token payload: {b[:300]}", file=sys.stderr)
            return 1
        if c in (403, 404):
            time.sleep(interval)
            continue
        print(f"device token poll failed ({c}): {b[:300]}", file=sys.stderr)
        return 1
    if not authorization_code:
        print("Authorization timed out.", file=sys.stderr)
        return 1

    print("Exchanging code for tokens...")
    c, b = _post_form(f"{AUTH_BASE}/oauth/token", {
        "grant_type": "authorization_code",
        "code": authorization_code,
        "redirect_uri": f"{AUTH_BASE}/deviceauth/callback",
        "client_id": CLIENT_ID,
        "code_verifier": code_verifier,
    })
    if c != 200:
        print(f"token exchange failed ({c}): {b[:400]}", file=sys.stderr)
        return 1
    ej = json.loads(b)
    access, refresh = ej.get("access_token"), ej.get("refresh_token")
    if not access or not refresh:
        print(f"exchange missing tokens: {b[:300]}", file=sys.stderr)
        return 1
    save_tokens(access, refresh, _expires_ms(access, ej.get("expires_in")))
    tok = load_tokens() or {}
    print(f"\nLogged in and saved to {TOKEN_PATH}")
    print(f"  account: {tok.get('email') or tok.get('accountId')}  plan: {tok.get('plan')}")
    return 0


# ── The bridge call ───────────────────────────────────────────────────────────
def _request_once(body: dict, timeout: int) -> str:
    access, account_id = get_valid_access()
    headers = {
        "Authorization": f"Bearer {access}",
        "chatgpt-account-id": account_id,
        "Accept": "text/event-stream",
        "Content-Type": "application/json",
        "originator": ORIGINATOR,
        "User-Agent": ORIGINATOR,
    }
    req = urllib.request.Request(f"{CODEX_BASE}/responses",
                                data=json.dumps(body).encode("utf-8"),
                                headers=headers, method="POST")
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        return resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:600]
        raise RuntimeError(f"HTTP {e.code}: {detail}") from None


def respond(prompt: str, *, model: str | None = None, instructions: str | None = None,
            tools: list[dict] | None = None, tool_choice=None,
            timeout: int = 240, retries: int = 3) -> str:
    """Low-level bridge primitive: send one prompt to Codex and return the RAW
    SSE response text. This is what everything else is built on.

    For plain text/code, use ask(). To use Codex tools (e.g. image generation),
    pass tools=[{"type": "image_generation", "model": "gpt-image-1.5",
    "size": "1024x1024", "output_format": "png"}] and parse the result yourself.
    """
    body: dict = {
        "model": model or DEFAULT_MODEL,
        "input": [{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
        "instructions": instructions or "You are a helpful assistant.",
        "stream": True,
        "store": False,
    }
    if tools:
        body["tools"] = tools
    if tool_choice is not None:
        body["tool_choice"] = tool_choice

    last_err = None
    for attempt in range(1, retries + 1):
        try:
            return _request_once(body, timeout)
        except (http.client.IncompleteRead, urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last_err = e
            time.sleep(5 * attempt)
        except RuntimeError as e:
            msg = str(e)
            if "HTTP 429" in msg or "HTTP 5" in msg:
                last_err = e
                time.sleep(15 * attempt)
            else:
                raise
    raise RuntimeError(f"failed after {retries} attempts: {last_err}")


def extract_text(sse_text: str) -> str:
    """Pull the assistant's text out of a Responses-API SSE stream."""
    deltas: list[str] = []
    completed_text: list[str] = []
    failure = None
    for line in sse_text.split("\n"):
        line = line.strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if not data or data == "[DONE]":
            continue
        try:
            ev = json.loads(data)
        except Exception:
            continue
        t = ev.get("type")
        if t == "response.output_text.delta" and isinstance(ev.get("delta"), str):
            deltas.append(ev["delta"])
        elif t in ("response.failed", "error"):
            err = ev.get("error") or {}
            failure = err.get("message") or ev.get("message") or err.get("code") or "failed"
        elif t == "response.completed":
            for item in (ev.get("response") or {}).get("output") or []:
                for c in item.get("content") or []:
                    if c.get("type") in ("output_text", "text") and c.get("text"):
                        completed_text.append(c["text"])
    if deltas:
        return "".join(deltas).strip()
    if completed_text:
        return "\n".join(completed_text).strip()
    if failure:
        raise RuntimeError(f"Codex error: {failure}")
    return ""


def ask(prompt: str, *, model: str | None = None, instructions: str | None = None,
        timeout: int = 240) -> str:
    """Send a prompt to Codex and return its text answer."""
    return extract_text(respond(prompt, model=model, instructions=instructions, timeout=timeout))


# ── CLI ──────────────────────────────────────────────────────────────────────
def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(prog="codex-bridge", description="Bridge to OpenAI Codex (GPT-5.x).")
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("login", help="one-time browser login (Sign in with ChatGPT)")

    a = sub.add_parser("ask", help="send a prompt, print the answer")
    a.add_argument("prompt", help="prompt text, or '-' to read from stdin")
    a.add_argument("--model", default=None, help=f"model id (default {DEFAULT_MODEL})")
    a.add_argument("--instructions", default=None, help="optional system instructions")

    sub.add_parser("whoami", help="show the logged-in account")

    args = ap.parse_args()
    if args.cmd == "login":
        return login()
    if args.cmd == "whoami":
        tok = load_tokens()
        if not tok:
            print("Not logged in. Run: codex-bridge login", file=sys.stderr)
            return 1
        print(f"{tok.get('email') or tok.get('accountId')}  plan: {tok.get('plan')}")
        return 0
    if args.cmd == "ask":
        prompt = sys.stdin.read() if args.prompt == "-" else args.prompt
        if not prompt.strip():
            print("empty prompt", file=sys.stderr)
            return 1
        print(ask(prompt, model=args.model, instructions=args.instructions))
        return 0
    ap.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
