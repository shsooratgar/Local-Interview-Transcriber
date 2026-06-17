#!/usr/bin/env python3
"""Smoke test: verify the local toolchain is ready.

Run inside the project's conda env:
    conda activate transcriber
    python src/check_setup.py
"""
import platform
import shutil
import sys


def ok(label, detail=""):
    print(f"  [ OK ] {label} {detail}".rstrip())


def fail(label, detail=""):
    print(f"  [FAIL] {label} {detail}".rstrip())


def check_ffmpeg():
    path = shutil.which("ffmpeg")
    if path:
        ok("ffmpeg", f"-> {path}")
        return True
    fail("ffmpeg", "not found on PATH  (brew install ffmpeg)")
    return False


def check_ollama():
    try:
        import requests
    except ImportError:
        fail("requests", "not installed  (pip install -r requirements.txt)")
        return False
    try:
        r = requests.get("http://localhost:11434/api/tags", timeout=5)
        r.raise_for_status()
        models = [m["name"] for m in r.json().get("models", [])]
        ok("ollama server", "reachable at localhost:11434")
        if models:
            ok("ollama models", ", ".join(models))
            return True
        fail("ollama models", "none pulled  (ollama pull qwen2.5:14b)")
        return False
    except Exception as e:  # noqa: BLE001
        fail("ollama server", f"unreachable ({e}).  Start: brew services start ollama")
        return False


def check_mlx_whisper():
    try:
        import mlx_whisper  # noqa: F401
        ok("mlx-whisper", "importable")
        return True
    except Exception as e:  # noqa: BLE001
        fail("mlx-whisper", f"import failed ({e})")
        return False


def main():
    print(f"Python : {platform.python_version()}  ({sys.executable})")
    print(f"System : {platform.platform()}")
    print("\nChecks:")
    results = [check_ffmpeg(), check_ollama(), check_mlx_whisper()]
    print()
    if all(results):
        print("All good — toolchain ready. ✅")
        return 0
    print("Some checks failed — see above. ❌")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
