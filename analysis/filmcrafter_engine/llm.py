"""The AI "brain" behind the Director, Director Command, creative directions, the Choreography Engine and take
review: OpenAI (cloud), OpenRouter (cloud, one key for hundreds of cheaper models) or a local model served by Ollama or LM Studio (all speak the OpenAI chat API).

Settings live in ~/.filmcrafter/llm.json (no secrets):
  {"provider": "openai" | "openrouter" | "ollama" | "lmstudio", "base_url": "...", "model": "...", "vision_model": "..."}
The OpenRouter key lives in the OS keychain (service "filmcrafter", account "openrouter"), never in this file.

Every module calls `client()` and `client.responses.create(model=…, input=[…], text={"format": json_schema})`.
For local servers that call is translated to chat completions with a JSON-schema response format, falling back to
plain JSON mode (schema in the prompt) for models/servers without schema support, and reasoning traces
(<think>…</think>, as DeepSeek-R1 prints) are stripped before parsing.

  python -m filmcrafter_engine.llm get | set '<json>' | models '<json>' | test '<json>'
"""
from __future__ import annotations

import json
import os
import re
import sys
import types

CONFIG = os.path.join(os.path.expanduser("~"), ".filmcrafter", "llm.json")
DEFAULT_URLS = {"ollama": "http://127.0.0.1:11434/v1", "lmstudio": "http://127.0.0.1:1234/v1", "openrouter": "https://openrouter.ai/api/v1", "gemini": "https://generativelanguage.googleapis.com/v1beta/openai", "anthropic": "https://api.anthropic.com/v1"}
NAMES = {"openai": "OpenAI", "anthropic": "Anthropic Claude", "openrouter": "OpenRouter", "gemini": "Google Gemini", "ollama": "Ollama", "lmstudio": "LM Studio"}
LOCAL = ("ollama", "lmstudio")        # run on this computer: free
MODELS_CACHE = os.path.join(os.path.expanduser("~"), ".filmcrafter", "openrouter_models.json")


def config() -> dict:
    try:
        with open(CONFIG, encoding="utf-8") as f:
            c = json.load(f)
    except (OSError, ValueError):
        c = {}
    prov = c.get("provider") if c.get("provider") in NAMES else "openai"
    return {"provider": prov, "base_url": (c.get("base_url") or DEFAULT_URLS.get(prov, "")).rstrip("/"),
            "model": c.get("model") or "", "vision_model": c.get("vision_model") or ""}


def save(c: dict) -> dict:
    prov = c.get("provider")
    if prov not in NAMES:
        raise SystemExit("Choose OpenAI, OpenRouter, Ollama or LM Studio, or Google Gemini.")
    url = (c.get("base_url") or DEFAULT_URLS.get(prov, "")).strip().rstrip("/")
    if prov != "openai":
        if not re.match(r"^https?://[^\s/]+(:\d+)?(/.*)?$", url):
            raise SystemExit("Enter the server address, e.g. http://127.0.0.1:11434/v1")
        if prov not in {"gemini", "anthropic"} and not url.endswith("/v1"):
            url += "/v1"   # both servers expose the OpenAI API under /v1
        if prov in {"openrouter", "gemini", "anthropic"} and not url.startswith("https://"):
            raise SystemExit(f"{NAMES[prov]} is reached over https.")
        if not (c.get("model") or "").strip():
            raise SystemExit("Choose which model to use." if prov == "openrouter" else "Choose which local model to use.")
    out = {"provider": prov, "base_url": url if prov != "openai" else "", "model": (c.get("model") or "").strip(),
           "vision_model": (c.get("vision_model") or "").strip()}
    os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
    with open(CONFIG, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    return config()


def is_local() -> bool:
    """A model on this computer (Ollama, LM Studio): free. OpenRouter is a cloud service and is paid, though cheaper."""
    return config()["provider"] in LOCAL


def uses_openai() -> bool:
    return config()["provider"] == "openai"


def visual_ready() -> bool:
    """Can the brain look at pictures right now (take review)? OpenAI needs its key; OpenRouter needs its key and a vision model chosen; a local brain needs a vision model chosen."""
    cfg = config()
    if cfg["provider"] == "openai":
        return bool(os.environ.get("FILMCRAFTER_OPENAI_KEY"))
    if cfg["provider"] == "openrouter":
        return bool(os.environ.get("FILMCRAFTER_OPENROUTER_KEY")) and bool(cfg["vision_model"])
    if cfg["provider"] == "gemini":
        return bool(os.environ.get("GEMINI_API_KEY")) and bool(cfg["vision_model"])
    return True                       # a local brain says plainly in local_model() when no vision model is chosen


# ---------------------------------------------------------------- client

class _LocalResponses:
    """responses.create(...) → chat.completions on an OpenAI-compatible local server."""

    def __init__(self, chat):
        self.chat = chat

    @staticmethod
    def _messages(inp) -> list[dict]:
        msgs = []
        for m in inp:
            c = m["content"]
            if isinstance(c, list):  # multimodal parts (review)
                parts = []
                for p in c:
                    if p.get("type") in ("input_text", "text"):
                        parts.append({"type": "text", "text": p["text"]})
                    elif p.get("type") in ("input_image", "image_url"):
                        url = p["image_url"] if isinstance(p["image_url"], str) else p["image_url"]["url"]
                        parts.append({"type": "image_url", "image_url": {"url": url}})
                c = parts
            msgs.append({"role": m["role"], "content": c})
        return msgs

    def create(self, model: str, input, text: dict | None = None, **_):
        msgs = self._messages(input)
        fmt = (text or {}).get("format") or {}
        schema = fmt.get("schema")
        raw = None
        if schema:
            try:  # 1) native JSON-schema structured output (LM Studio, recent Ollama)
                r = self.chat.completions.create(model=model, messages=msgs, response_format={
                    "type": "json_schema", "json_schema": {"name": fmt.get("name", "result"), "schema": schema, "strict": True}})
                raw = _json_text(r.choices[0].message.content or "")
                json.loads(raw)
            except Exception:
                raw = None
            if raw is None:  # 2) JSON mode with the schema spelled out
                hint = {"role": "system", "content": "Reply with ONLY a JSON object (no prose, no code fences) that matches "
                                                     "this JSON Schema exactly:\n" + json.dumps(schema)}
                try:
                    r = self.chat.completions.create(model=model, messages=[hint] + msgs, response_format={"type": "json_object"})
                except Exception:
                    r = self.chat.completions.create(model=model, messages=[hint] + msgs)
                raw = _json_text(r.choices[0].message.content or "")
                try:
                    json.loads(raw)
                except ValueError as e:
                    raise RuntimeError(f"The local model didn't return valid JSON ({e}). Try a larger or instruction-tuned model.")
        else:
            r = self.chat.completions.create(model=model, messages=msgs)
            raw = _json_text(r.choices[0].message.content or "")
        return types.SimpleNamespace(output_text=raw)


def _json_text(s: str) -> str:
    """Strip reasoning traces and code fences; return the outermost JSON object text."""
    s = re.sub(r"<think>.*?</think>", "", s, flags=re.S).strip()
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s.strip(), flags=re.S)
    a, b = s.find("{"), s.rfind("}")
    return s[a:b + 1] if a >= 0 and b > a else s


def _openrouter_key() -> str:
    key = os.environ.get("FILMCRAFTER_OPENROUTER_KEY")
    if not key:
        try:
            import keyring
            key = keyring.get_password("filmcrafter", "openrouter")
        except Exception:
            key = None
    if not key:
        raise SystemExit("Add your OpenRouter key in Settings, or choose another AI brain.")
    return key


def _gemini_key() -> str:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        try:
            import keyring
            key = keyring.get_password("filmcrafter", "google")
        except Exception:
            key = None
    if not key:
        raise SystemExit("Add your Google Gemini key in Settings, or choose another AI brain.")
    return key


def _anthropic_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        try:
            import keyring
            key = keyring.get_password("filmcrafter", "anthropic")
        except Exception:
            key = None
    if not key:
        raise SystemExit("Add your Anthropic Claude API key in Settings, or choose another AI brain.")
    return key


class _AnthropicResponses:
    def __init__(self, cfg): self.cfg = cfg
    def create(self, model: str, input, text: dict | None = None, **_):
        import requests
        system = "\n\n".join(str(m.get("content") or "") for m in input if m.get("role") == "system")
        messages = [{"role": m["role"], "content": m["content"]} for m in input if m.get("role") in {"user", "assistant"}]
        schema = ((text or {}).get("format") or {}).get("schema")
        if schema:
            system += "\nReply with ONLY JSON matching this schema exactly:\n" + json.dumps(schema)
        r = requests.post(self.cfg["base_url"].rstrip("/") + "/messages", timeout=180, headers={
            "x-api-key": _anthropic_key(), "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": model, "max_tokens": 4096, "system": system, "messages": messages})
        r.raise_for_status(); body = r.json(); raw = "".join(x.get("text", "") for x in body.get("content", []) if x.get("type") == "text")
        raw = _json_text(raw) if schema else raw
        if schema: json.loads(raw)
        return types.SimpleNamespace(output_text=raw)


class _Anthropic:
    def __init__(self, cfg): self.cfg = cfg; self.responses = _AnthropicResponses(cfg); self.local = False; self.routed = False


class _Local:
    """Any chat-completions server behind the same interface: Ollama / LM Studio on this computer, or OpenRouter in the cloud."""

    def __init__(self, cfg: dict):
        from openai import OpenAI
        self.cfg = cfg
        routed = cfg["provider"] == "openrouter"
        key = _openrouter_key() if routed else _gemini_key() if cfg["provider"] == "gemini" else (os.environ.get("FILMCRAFTER_LOCAL_KEY") or "local")
        self._oa = OpenAI(base_url=cfg["base_url"], api_key=key,
                          default_headers={"HTTP-Referer": "https://github.com/Olusegune/FilmCrafterCode", "X-Title": "FilmCrafter"} if routed else None)
        self.responses = _LocalResponses(self._oa.chat)
        self.models = self._oa.models
        self.local = cfg["provider"] in LOCAL
        self.routed = routed


def client():
    """The configured brain: an OpenAI client, or a local server behind the same interface."""
    cfg = config()
    if cfg["provider"] == "anthropic":
        _anthropic_key()
        return _Anthropic(cfg)
    if cfg["provider"] != "openai":
        return _Local(cfg)             # OpenRouter, Ollama or LM Studio
    import keyring
    from openai import OpenAI
    key = os.environ.get("FILMCRAFTER_OPENAI_KEY") or keyring.get_password("filmcrafter", "openai")
    if not key:
        raise SystemExit("Add your OpenAI key in Settings, or choose a local model (Ollama or LM Studio).")
    return OpenAI(api_key=key)


def local_model(c, vision: bool = False) -> str | None:
    """For a brain other than OpenAI: the configured model (vision model for review). None for OpenAI."""
    if not hasattr(c, "cfg"):
        return None
    cfg = c.cfg
    if vision:
        if not cfg["vision_model"]:
            hint = "(for example google/gemini-2.5-flash)" if cfg["provider"] == "openrouter" else "(for example gemini-2.5-flash)" if cfg["provider"] == "gemini" else "(e.g. llava, qwen2.5-vl, gemma3)"
            raise SystemExit(f"Visual review needs a {NAMES[cfg['provider']]} model that can see images {hint}. Choose one in Settings, or use OpenAI.")
        return cfg["vision_model"]
    return cfg["model"]


# ---------------------------------------------------------------- settings helpers

def _usd_per_mtok(v) -> float | None:
    try:
        f = float(v) * 1_000_000
        return round(f, 4) if f >= 0 and f == f else None
    except (TypeError, ValueError):
        return None


def openrouter_models(fetch=None) -> dict:
    """OpenRouter's public model list with prices: {models: ids cheapest first, vision_capable, prices: {id: {in, out}} in USD per million tokens, structured: ids that can answer in JSON}.
    Saved to ~/.filmcrafter so a cost estimate can use the real price of the model chosen."""
    import requests
    r = (fetch or (lambda: requests.get(DEFAULT_URLS["openrouter"] + "/models", timeout=20)))()
    r.raise_for_status()
    rows, prices, vision, structured = [], {}, [], []
    for m in r.json().get("data", []):
        mid = m.get("id")
        if not isinstance(mid, str) or not mid:
            continue
        pr = m.get("pricing") or {}
        a, b = _usd_per_mtok(pr.get("prompt")), _usd_per_mtok(pr.get("completion"))
        if a is None:
            continue
        prices[mid] = {"in": a, "out": b if b is not None else a}
        rows.append((a + (b or 0), mid))
        if "image" in ((m.get("architecture") or {}).get("input_modalities") or []):
            vision.append(mid)
        sp = m.get("supported_parameters") or []
        if "structured_outputs" in sp or "response_format" in sp:
            structured.append(mid)
    ids = [mid for _, mid in sorted(rows)]
    out = {"base_url": DEFAULT_URLS["openrouter"], "models": ids, "vision_capable": [x for x in ids if x in set(vision)], "structured": [x for x in ids if x in set(structured)], "prices": prices}
    try:
        os.makedirs(os.path.dirname(MODELS_CACHE), exist_ok=True)
        with open(MODELS_CACHE, "w", encoding="utf-8") as f:
            json.dump({"at": int(__import__("time").time()), "prices": prices}, f)
    except OSError:
        pass
    return out


def price_per_mtok() -> tuple[float, float] | None:
    """(input, output) USD per million tokens of the model chosen on OpenRouter, from the last list fetched; None for any other brain or an unknown model."""
    cfg = config()
    if cfg["provider"] != "openrouter" or not cfg["model"]:
        return None
    try:
        with open(MODELS_CACHE, encoding="utf-8") as f:
            p = (json.load(f).get("prices") or {}).get(cfg["model"])
    except (OSError, ValueError):
        return None
    return (float(p["in"]), float(p["out"])) if isinstance(p, dict) and "in" in p and "out" in p else None


def list_models(c: dict) -> dict:
    """Models the chosen server has (for the Settings picker): the local server's own list, or OpenRouter's public list with prices."""
    import requests
    prov = c.get("provider")
    if prov == "openrouter":
        try:
            return openrouter_models()
        except Exception as e:
            raise SystemExit(f"Couldn't reach OpenRouter ({type(e).__name__}). Check your internet connection and try again.")
    if prov == "gemini":
        try:
            cfg = {**config(), **c, "provider": "gemini", "base_url": (c.get("base_url") or DEFAULT_URLS["gemini"]).rstrip("/")}
            ids = sorted(m.id for m in _Local(cfg).models.list().data)
            return {"base_url": cfg["base_url"], "models": ids, "vision_capable": ids}
        except SystemExit: raise
        except Exception as e:
            raise SystemExit(f"Couldn't reach Google Gemini ({type(e).__name__}). Check the key and internet connection.")
    if prov == "anthropic":
        import requests
        try:
            url = (c.get("base_url") or DEFAULT_URLS["anthropic"]).rstrip("/")
            r = requests.get(url + "/models", timeout=20, headers={"x-api-key": _anthropic_key(), "anthropic-version": "2023-06-01"}); r.raise_for_status()
            ids = sorted(x["id"] for x in r.json().get("data", []) if isinstance(x.get("id"), str))
            return {"base_url": url, "models": ids, "vision_capable": ids}
        except SystemExit: raise
        except Exception as e: raise SystemExit(f"Couldn't reach Anthropic Claude ({type(e).__name__}). Check the key and internet connection.")
    url = (c.get("base_url") or DEFAULT_URLS.get(prov, "")).rstrip("/")
    if prov in LOCAL and not url.endswith("/v1"):
        url += "/v1"
    try:
        r = requests.get(url + "/models", timeout=4)
        r.raise_for_status()
        ids = sorted(m["id"] for m in r.json().get("data", []))
    except Exception as e:
        raise SystemExit(f"No {NAMES.get(prov, 'server')} at {url} ({type(e).__name__}). Start it"
                         f"{' (ollama serve)' if prov == 'ollama' else ' and turn on its local server (Developer tab)' if prov == 'lmstudio' else ''}, then try again.")
    vision_hint = re.compile(r"llava|vision|-vl|vl-|qwen2\.5vl|gemma3|minicpm-v|moondream|pixtral|llama3\.2-vision|bakllava", re.I)
    return {"base_url": url, "models": ids, "vision_capable": [m for m in ids if vision_hint.search(m)]}


def test(c: dict) -> dict:
    """A tiny structured request through exactly the path the app uses."""
    import time
    cfg = {**config(), **{k: v for k, v in c.items() if v}}
    if cfg["provider"] in {"openrouter", "gemini"} and not cfg.get("base_url"):
        cfg["base_url"] = DEFAULT_URLS[cfg["provider"]]
    if cfg["provider"] == "openai":
        cl = client()
        model = "gpt-5"
        from .director import resolve_model
        model = resolve_model(cl, model)
    else:
        if cfg["provider"] in LOCAL and not cfg["base_url"].endswith("/v1"):
            cfg["base_url"] = cfg["base_url"].rstrip("/") + "/v1"
        cl = _Local(cfg)
        model = cfg["model"]
    schema = {"type": "object", "additionalProperties": False, "required": ["shot", "energy"],
              "properties": {"shot": {"type": "string"}, "energy": {"type": "integer"}}}
    t = time.time()
    r = cl.responses.create(model=model, input=[{"role": "system", "content": "You direct music videos. Be brief."},
                                                {"role": "user", "content": "Describe one opening shot for a hopeful Afrobeats song in one sentence, and rate its energy 1-10."}],
                            text={"format": {"type": "json_schema", "name": "probe", "schema": schema, "strict": True}})
    out = json.loads(r.output_text)
    return {"ok": True, "model": model, "seconds": round(time.time() - t, 1), "sample": out}


def main(argv: list[str]) -> int:
    action = argv[0] if argv else "get"
    data = json.loads(argv[1]) if len(argv) > 1 else {}
    try:
        res = {"get": lambda: config(), "set": lambda: save(data), "models": lambda: list_models(data),
               "test": lambda: test(data)}[action]()
        print(json.dumps({"event": "result", "data": res}, ensure_ascii=False), flush=True)
        return 0
    except SystemExit as e:
        print(json.dumps({"event": "error", "message": str(e)}), flush=True)
    except Exception as e:
        from .director import openai_error
        print(json.dumps({"event": "error", "message": openai_error(e)}), flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
