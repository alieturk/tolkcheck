"""Shared plumbing for the evaluation scripts.

Not a test helper — these scripts are deliberately outside tests/ (see
evaluation/README.md). Logging follows the same `[step] key=val` convention as
pipeline.py and smoke_test.py so output reads consistently with the rest of the
codebase.
"""
from __future__ import annotations

import logging
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

# The scripts live in backend/evaluation/, the package lives in backend/app/.
# Put backend/ on sys.path so `import app...` resolves when a script is run
# directly (`python evaluation/wer_check.py`) rather than as a module.
BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

DATA = Path(__file__).resolve().parent / "data"
AUDIO_DIR = DATA / "audio"
SESSION_DIR = DATA / "session"
RESULTS_DIR = Path(__file__).resolve().parent / "results"

log = logging.getLogger("evaluation")


def neutralise_broken_torchcodec() -> None:
    """Make a half-installed torchcodec fail as ImportError rather than RuntimeError.

    torchcodec arrives as a torchaudio dependency but needs FFmpeg 4-7 shared
    libraries at import time. Without them `import torchcodec` raises RuntimeError.
    `sentence_transformers.base.modality_types` guards its optional torchcodec
    import with `except (ImportError, OSError)` — a RuntimeError sails straight
    through, so LaBSE cannot be imported at all, and the traceback blames audio
    decoding rather than the missing FFmpeg.

    Uninstalling torchcodec fixes it, but does not stay fixed: any `uv run` or
    `uv sync` reinstalls it from the lockfile, which silently re-breaks
    scoring_check between runs. So detect the unloadable state and swap in a stub
    whose submodule lookups raise ImportError, which the guard handles correctly.

    Nothing in app/ is patched — this only affects the importing eval process, and
    only when torchcodec is already broken. Audio decoding falls back to
    soundfile, which reads the 16 kHz WAV fixtures without FFmpeg.
    """
    import importlib
    import types

    if isinstance(sys.modules.get("torchcodec"), types.ModuleType) and \
            getattr(sys.modules["torchcodec"], "_tolkcheck_stub", False):
        return
    try:
        importlib.import_module("torchcodec")
        return                     # loads fine — leave it alone
    except ImportError:
        return                     # genuinely absent; the upstream guard handles it
    except Exception as exc:
        broken = type(exc).__name__

    # A failed import can leave partial submodule entries behind.
    for key in [k for k in sys.modules if k == "torchcodec" or k.startswith("torchcodec.")]:
        del sys.modules[key]

    from importlib.machinery import ModuleSpec

    # Emulate "installed but unusable": the module and its `decoders` submodule
    # exist, and the two names sentence_transformers wants are None — exactly the
    # state its own `except (ImportError, OSError)` branch produces. A bare
    # __path__-only stub is not enough: transformers calls
    # importlib.util.find_spec("torchcodec"), which raises ValueError on a
    # sys.modules entry whose __spec__ is None, so the spec has to be real.
    stub = types.ModuleType("torchcodec")
    stub.__spec__ = ModuleSpec("torchcodec", loader=None, is_package=True)
    stub.__path__ = []
    stub._tolkcheck_stub = True
    stub.__doc__ = f"stub installed by evaluation/_common.py (real import raised {broken})"

    decoders = types.ModuleType("torchcodec.decoders")
    decoders.__spec__ = ModuleSpec("torchcodec.decoders", loader=None)
    decoders.AudioDecoder = None
    decoders.VideoDecoder = None
    stub.decoders = decoders

    sys.modules["torchcodec"] = stub
    sys.modules["torchcodec.decoders"] = decoders
    # ASCII only: this fires at _common import time, before setup_logging() has had
    # a chance to switch stdout to UTF-8, so an em-dash here would be mangled on a
    # cp1252 console.
    log.warning("[env] torchcodec is installed but cannot load (%s) -- replaced with a "
                "stub so sentence-transformers can import. Audio decoding falls back to "
                "soundfile, which handles the WAV fixtures. Install FFmpeg 4-7 on PATH "
                "to use torchcodec for real.", broken)


def setup_logging(level: int = logging.INFO) -> None:
    # Turkish text (ı, ğ, ş) and the report's box-drawing characters are not
    # encodable in cp1252, which is still the default console codepage on Windows.
    # Without this every script dies with UnicodeEncodeError at print time — after
    # having done all the expensive work.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    logging.basicConfig(level=level, format="%(message)s", stream=sys.stdout)
    # pyannote and speechbrain are extremely chatty at INFO
    for noisy in ("pyannote", "speechbrain", "torio", "torchaudio", "httpx",
                  "urllib3", "filelock", "huggingface_hub", "sentence_transformers"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    # torchaudio 2.8 emits a multi-line UserWarning per load() call about the
    # TorchCodec migration. With 8 clips x 2 models that buries the actual results.
    # Suppressed here only — nothing in app/ is silenced.
    import warnings
    warnings.filterwarnings("ignore", category=UserWarning, module=r"torchaudio\..*")
    warnings.filterwarnings("ignore", message=r".*TorchCodec.*")
    warnings.filterwarnings("ignore", message=r".*has been deprecated.*")


# ── Result contract ───────────────────────────────────────────────────────────

SKIPPED = "skipped"
RAN = "ran"
FAILED = "failed"


@dataclass
class CheckResult:
    """One evaluation section's outcome.

    `status` is deliberately explicit: run_all.py must be able to say in the
    report which checks produced numbers, which were skipped and why, and which
    blew up — never silently omit one.
    """
    name: str
    status: str
    reason: str = ""
    markdown: str = ""
    numbers: dict = field(default_factory=dict)

    @classmethod
    def skipped(cls, name: str, reason: str) -> "CheckResult":
        log.warning("[%s] SKIPPED — %s", name, reason)
        return cls(name=name, status=SKIPPED, reason=reason)

    @classmethod
    def failed(cls, name: str, reason: str) -> "CheckResult":
        log.error("[%s] FAILED — %s", name, reason)
        return cls(name=name, status=FAILED, reason=reason)


# ── Text normalisation for WER / string comparison ────────────────────────────

# Whisper renders small cardinals as digits about as often as words, in both
# Turkish and Dutch. Without this map the WER figure partly measures number
# formatting rather than recognition. Only the number words actually present in
# the fixture references are listed — extend it if the fixtures change.
_NUMBER_WORDS = {
    # Turkish
    "bir": "1", "iki": "2", "üç": "3", "dört": "4", "beş": "5",
    "altı": "6", "yedi": "7", "sekiz": "8", "dokuz": "9", "on": "10",
    # Dutch
    "een": "1", "twee": "2", "drie": "3", "vier": "4", "vijf": "5",
    "zes": "6", "zeven": "7", "acht": "8", "negen": "9", "tien": "10",
    "twaalf": "12",
}

_PUNCT_RE = re.compile(r"[^\w\s]", flags=re.UNICODE)
_WS_RE = re.compile(r"\s+")


def normalise_text(text: str, map_numbers: bool = True) -> str:
    """Lowercase, strip punctuation/diacritic noise, optionally digitise numerals.

    Applied identically to reference and hypothesis. `map_numbers=False` gives the
    raw comparison so the report can show both and the reader can see how much of
    the WER is formatting.
    """
    text = unicodedata.normalize("NFC", text)
    text = text.replace("’", "'").replace("‘", "'").replace("`", "'")
    text = text.lower()
    text = _PUNCT_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text).strip()
    if map_numbers:
        text = " ".join(_NUMBER_WORDS.get(tok, tok) for tok in text.split())
    return text


# ── Markdown helpers ──────────────────────────────────────────────────────────

def md_table(headers: list[str], rows: list[list]) -> str:
    """Minimal GitHub-flavoured markdown table. Escapes pipes in cell text."""
    def cell(v) -> str:
        if isinstance(v, float):
            return f"{v:.3f}"
        return str(v).replace("|", "\\|").replace("\n", " ")

    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join("---" for _ in headers) + "|"]
    out += ["| " + " | ".join(cell(c) for c in row) + " |" for row in rows]
    return "\n".join(out)


def mean(xs) -> float:
    xs = list(xs)
    return sum(xs) / len(xs) if xs else 0.0


def env_missing(var: str) -> bool:
    """True when a settings value that gates a check is absent or a placeholder."""
    from app.config import settings

    val = getattr(settings, var, "") or ""
    val = val.strip().strip('"').strip("'")
    return not val or "your_token_here" in val or "your_key_here" in val


# Run at import time, not from setup_logging(): every eval script imports _common
# before it touches app.services, and the stub has to be in place before
# sentence_transformers is first imported anywhere in the process. No-op when
# torchcodec is absent or working.
neutralise_broken_torchcodec()
