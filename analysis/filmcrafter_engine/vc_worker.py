"""The one-shot worker that runs Chatterbox voice conversion. It runs in its own process with its own packages (see `revoice`), never inside the app's engine.

  python vc_worker.py check                     imports the packages and prints their versions
  python vc_worker.py install                   fetches the model files once (the only time this worker may use the network)
  python vc_worker.py convert <request.json>    request: {"source", "target", "out"} (paths); writes a WAV to `out`

It prints one JSON object on its last line. Nothing else is printed to stdout. It is started by `revoice` only after the person asked for it.
"""
from __future__ import annotations

import contextlib
import json
import os
import sys


def _say(**kw) -> None:
    sys.stdout.write(json.dumps(kw) + "\n")
    sys.stdout.flush()


def _device(torch) -> str:
    return "cuda" if torch.cuda.is_available() else "cpu"


def main(argv: list[str]) -> int:
    mode = argv[1] if len(argv) > 1 else ""
    try:
        with contextlib.redirect_stdout(sys.stderr):          # a library's own chatter must not reach the one line we print
            import torch
            import torchaudio
            from importlib import metadata
            versions = {}
            for p in ("torch", "torchaudio", "chatterbox-tts"):
                try:
                    versions[p] = metadata.version(p)
                except metadata.PackageNotFoundError:
                    versions[p] = None
            if mode == "check":
                from chatterbox.vc import ChatterboxVC  # noqa: F401
                result = {"ok": True, "versions": versions, "device": _device(torch)}
            elif mode == "install":
                from chatterbox.vc import ChatterboxVC
                ChatterboxVC.from_pretrained(_device(torch))
                result = {"ok": True, "versions": versions, "device": _device(torch)}
            elif mode == "convert":
                with open(argv[2], encoding="utf-8") as f:
                    req = json.load(f)
                from chatterbox.vc import ChatterboxVC
                model = ChatterboxVC.from_pretrained(_device(torch))
                with torch.inference_mode():
                    wav = model.generate(req["source"], target_voice_path=req["target"])
                torchaudio.save(req["out"], wav.cpu(), model.sr, format="wav")
                result = {"ok": True, "rate": int(model.sr), "versions": versions, "device": _device(torch)}
            else:
                result = {"ok": False, "why": "Unknown mode."}
    except Exception as e:                                    # reported plainly; the caller turns it into a message
        result = {"ok": False, "why": f"{type(e).__name__}: {e}"[:600]}
    _say(**result)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    sys.exit(main(sys.argv))
