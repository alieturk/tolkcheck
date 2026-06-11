"""HTTP API integration test — verifies the REST layer responds correctly.

Does NOT trigger the AI pipeline (no real audio processing).
Run against the live backend:

    uv run python api_test.py [--base-url http://localhost:8000]
"""
from __future__ import annotations

import argparse
import io
import struct
import sys
import urllib.error
import urllib.parse
import urllib.request


def _ok(label: str) -> None:
    print(f"  \033[32m✓\033[0m  {label}")


def _fail(label: str, detail: str) -> None:
    print(f"  \033[31m✗\033[0m  {label}: {detail}")
    sys.exit(1)


def _get(base: str, path: str) -> tuple[int, dict]:
    url = base.rstrip("/") + path
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req) as resp:
            import json
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        import json
        try:
            body = json.loads(e.read())
        except Exception:
            body = {}
        return e.code, body


def _minimal_wav() -> bytes:
    """Return the smallest valid PCM WAV file (44-byte header + 1 silent sample)."""
    sample_rate = 16000
    num_channels = 1
    bits_per_sample = 16
    num_samples = 1
    byte_rate = sample_rate * num_channels * bits_per_sample // 8
    block_align = num_channels * bits_per_sample // 8
    data_size = num_samples * block_align

    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + data_size,
        b"WAVE",
        b"fmt ",
        16,                  # chunk size
        1,                   # PCM
        num_channels,
        sample_rate,
        byte_rate,
        block_align,
        bits_per_sample,
        b"data",
        data_size,
    )
    return header + b"\x00\x00"   # 1 silent 16-bit sample


def _post_multipart(base: str, path: str, fields: dict, files: dict) -> tuple[int, dict]:
    boundary = b"----TestBoundary12345"
    body = b""
    for name, value in fields.items():
        body += b"--" + boundary + b"\r\n"
        body += f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
        body += value.encode() + b"\r\n"
    for name, (filename, data, content_type) in files.items():
        body += b"--" + boundary + b"\r\n"
        body += f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode()
        body += f"Content-Type: {content_type}\r\n\r\n".encode()
        body += data + b"\r\n"
    body += b"--" + boundary + b"--\r\n"

    url = base.rstrip("/") + path
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary.decode()}"},
        method="POST",
    )
    import json
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, {}


def run(base: str) -> None:
    print(f"\nAPI integration test  →  {base}\n")

    # 1. Health check
    status, body = _get(base, "/health")
    if status == 200 and body.get("status") == "ok":
        _ok("GET /health  →  200 {status: ok}")
    else:
        _fail("GET /health", f"got {status} {body}")

    # 2. List sessions (empty or list)
    status, body = _get(base, "/sessions")
    if status == 200 and isinstance(body, list):
        _ok(f"GET /sessions  →  200  [{len(body)} sessions]")
    else:
        _fail("GET /sessions", f"got {status} {body}")

    # 3. Unknown session → 404
    fake_id = "00000000-0000-0000-0000-000000000000"
    status, _ = _get(base, f"/sessions/{fake_id}")
    if status == 404:
        _ok(f"GET /sessions/<bad-uuid>  →  404")
    else:
        _fail("GET /sessions/<bad-uuid>", f"expected 404, got {status}")

    # 4. Upload a minimal WAV
    status, body = _post_multipart(
        base, "/sessions",
        fields={"language": "nl"},
        files={"audio": ("test.wav", _minimal_wav(), "audio/wav")},
    )
    if status == 202 and "session_id" in body:
        session_id = body["session_id"]
        _ok(f"POST /sessions  →  202  session_id={session_id[:8]}…")
    else:
        _fail("POST /sessions", f"got {status} {body}")
        return  # can't proceed

    # 5. Fetch the created session
    status, body = _get(base, f"/sessions/{session_id}")
    if status == 200 and body.get("id") == session_id:
        _ok(f"GET /sessions/<id>  →  200  status={body.get('status')}")
    else:
        _fail("GET /sessions/<id>", f"got {status} {body}")

    print("\nAll checks passed.\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    args = parser.parse_args()
    run(args.base_url)
