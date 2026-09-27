"""Groq/OpenRouter transport and local configuration; never expose API keys."""
import json
import os
import re
import shlex
import time
from pathlib import Path
from urllib import error, request

PROVIDERS = {
    "groq": {"url": "https://api.groq.com/openai/v1/chat/completions", "keys": ("GROQ_API_KEY",)},
    "openrouter": {"url": "https://openrouter.ai/api/v1/chat/completions", "keys": ("OPEN_ROUTER_API_KEY", "OPENROUTER_API_KEY")},
}
GROQ_MODELS = {"planner": "openai/gpt-oss-20b", "writer": "openai/gpt-oss-120b",
               "skeptic": "openai/gpt-oss-20b", "evidence": "openai/gpt-oss-20b", "methodology": "openai/gpt-oss-20b"}
OPENROUTER_MODELS = {"planner": "meta-llama/llama-3.3-70b-instruct", "writer": "openai/gpt-oss-120b",
                     "skeptic": "meta-llama/llama-3.3-70b-instruct", "evidence": "meta-llama/llama-3.3-70b-instruct", "methodology": "openai/gpt-oss-20b"}


def usable(value):
    return bool(value and value.strip() and value.strip().lower() not in
                {"your_actual_key_here", "your_api_key_here", "your_key_here", "changeme"})


def load_env(path=None):
    path = Path(path) if path else Path(__file__).with_name(".env")
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line.startswith("export "):
            line = line[7:].lstrip()
        name, separator, raw = line.partition("=")
        name = name.strip()
        if not separator or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            continue
        try:
            values = shlex.split(raw, comments=True)
        except ValueError:
            raise ValueError(f"Invalid quoting for {name} in .env") from None
        # Parse as data: no shell execution or variable expansion.
        os.environ.setdefault(name, " ".join(values))


def api_key(provider):
    return next((os.environ[name].strip() for name in PROVIDERS[provider]["keys"]
                 if usable(os.environ.get(name))), None)


def status():
    return [{"id": name, "configured": bool(api_key(name))} for name in PROVIDERS]


def model_for(provider, role):
    defaults = GROQ_MODELS if provider == "groq" else OPENROUTER_MODELS
    # Legacy DPR_MODEL_* remains Groq-only; provider model IDs are not interchangeable.
    return (os.environ.get(f"DPR_{provider.upper()}_MODEL_{role.upper()}")
            or (os.environ.get("DPR_MODEL_" + role.upper()) if provider == "groq" else None)
            or defaults[role])


def provider_order(role):
    preferred = os.environ.get("DPR_PROVIDER_" + role.upper(), os.environ.get("DPR_PROVIDER", "auto")).lower()
    if preferred not in ("auto", *PROVIDERS):
        raise ValueError("DPR_PROVIDER must be auto, groq, or openrouter")
    # Use both services when configured; otherwise use the available one.
    first = ("openrouter" if role in ("skeptic", "methodology") else "groq") if preferred == "auto" else preferred
    return [name for name in (first, *[p for p in PROVIDERS if p != first]) if api_key(name)]


def redact(message):
    message = str(message)
    for name, value in os.environ.items():
        if "API_KEY" in name and value:
            message = message.replace(value, "[redacted]")
    return re.sub(r"\b(?:gsk_|sk-or-|sk-)[A-Za-z0-9_-]+", "[redacted]", message)[:800]


class ProviderError(RuntimeError):
    def __init__(self, message, retryable=False, delay=1):
        super().__init__(message)
        self.retryable = retryable
        self.delay = delay


def response_error(provider, model, code, body, retry_after=None):
    detail = ""
    try:
        parsed = json.loads(body)
        detail = parsed.get("error", parsed)
        if isinstance(detail, dict):
            detail = detail.get("message") or detail.get("code") or "Request rejected"
    except (ValueError, AttributeError):
        # Cloudflare can return plain-text/HTML access-denied responses.
        if "1010" in body:
            detail = "Access denied by the provider's edge security (code 1010)."
    hints = {401: "Check the API key.", 402: "Check provider credits/billing.",
             403: "Check account/model permissions and network or region restrictions.",
             404: "Check the configured model ID.", 429: "Rate limit or quota reached; try again later."}
    retryable = code in (408, 429, 500, 502, 503, 504) or (code == 400 and "json" in str(detail).lower())
    try:
        delay = min(5, max(0, float(retry_after or 1)))
    except ValueError:
        delay = 1
    return ProviderError(redact(f"{provider} / {model}: HTTP {code}. {detail} {hints.get(code, '')}"), retryable, delay)


def complete(provider, role, system, payload, max_tokens=4096, model_override=None, usage_callback=None):
    model = model_override or model_for(provider, role)
    data = {"model": model, "temperature": 0.2, "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system + " Return one valid JSON object, no markdown fences."},
                         {"role": "user", "content": json.dumps(payload)}],
            "response_format": {"type": "json_object"}}
    req = request.Request(PROVIDERS[provider]["url"], json.dumps(data).encode(),
                          {"Authorization": "Bearer " + api_key(provider), "Content-Type": "application/json",
                           "Accept": "application/json", "User-Agent": "DPR-Workspace/0.2"})
    try:
        with request.urlopen(req, timeout=90) as response:
            result = json.load(response)
    except error.HTTPError as exc:
        body = exc.read(16000).decode("utf-8", errors="replace")
        raise response_error(provider, model, exc.code, body, exc.headers.get("Retry-After")) from None
    except (error.URLError, TimeoutError, OSError):
        raise ProviderError(f"{provider} / {model}: Connection failed or timed out. Check network access.", True) from None
    except ValueError:
        raise ProviderError(f"{provider} / {model}: Invalid API response.", True) from None
    if isinstance(result, dict) and result.get("error"):
        raw_code = result["error"].get("code", 502) if isinstance(result["error"], dict) else 502
        code = int(raw_code) if str(raw_code).isdigit() else 502
        raise response_error(provider, model, code, json.dumps(result))
    try:
        choice = result["choices"][0]
        if usage_callback:
            usage_callback(result.get("usage"))
        if choice.get("finish_reason") == "length":
            raise ProviderError(f"{provider} / {model}: Output exceeded the token limit. Request a smaller revision.")
        content = choice["message"]["content"].strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content)
        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            raise ValueError("Expected an object")
        return parsed
    except (KeyError, IndexError, TypeError, AttributeError, ValueError):
        raise ProviderError(f"{provider} / {model}: Model did not return a valid JSON object.", True) from None


def llm(role, system, payload, report=None):
    order = provider_order(role)
    if not order:
        raise ValueError("Set a real GROQ_API_KEY or OPEN_ROUTER_API_KEY in .env, then restart the server. Placeholder values are not API keys.")
    failures = []
    for provider in order:
        for attempt in range(2):
            if report:
                report(f"Calling {provider} / {model_for(provider, role)}" + (" (retry)" if attempt else ""))
            try:
                return complete(provider, role, system, payload)
            except ProviderError as exc:
                failures.append(str(exc))
                if report:
                    report(str(exc))
                if not exc.retryable or attempt:
                    break
                time.sleep(exc.delay)
    raise RuntimeError("All configured providers failed. " + " | ".join(dict.fromkeys(failures)))
