"""Unit tests for services/transcription.py.

_get_model / faster-whisper are mocked throughout — no model weights loaded
in CI (same approach as test_scoring_and_translation.py mocking LaBSE). What's
under test here is the kwargs assembly into model.transcribe(): specifically
that `initial_prompt` (the per-session known_terms glossary, see
Session.known_terms) is passed through when given and omitted when not —
mirroring the existing "only include `language` when truthy" pattern rather
than introducing a different convention for the new parameter.

transcribe_chunk() does real tensor work (mono-mixing, optional resample)
before ever reaching the mocked model, so tests use a tiny fake waveform
object instead of pulling in torch as a test dependency — see _FakeWaveform.
_transcribe_chunk_sync also unconditionally imports torchaudio.functional even
on the fixed-16kHz path these tests take (where it's never called) — see the
_fake_torchaudio fixture below for why that import is stubbed rather than
making every test here depend on the real (multi-GB) torch/torchaudio install.
"""
from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from app.services import transcription


@pytest.fixture(autouse=True)
def _fake_torchaudio(monkeypatch):
    """Stub out torchaudio.functional so `import torchaudio.functional as F`
    inside _transcribe_chunk_sync succeeds without the real package installed.
    Safe here because every test in this module keeps sample_rate == 16000,
    so the real resample() is never called — only the import needs to work."""
    fake_torchaudio = types.ModuleType("torchaudio")
    fake_functional = types.ModuleType("torchaudio.functional")
    fake_functional.resample = MagicMock()
    fake_torchaudio.functional = fake_functional
    monkeypatch.setitem(sys.modules, "torchaudio", fake_torchaudio)
    monkeypatch.setitem(sys.modules, "torchaudio.functional", fake_functional)


class _FakeWaveform:
    """Stands in for a mono torch.Tensor: only .dim() and .numpy() are used
    by _transcribe_chunk_sync when sample_rate is already 16000 (no resample,
    no stereo-to-mono mean)."""

    def __init__(self, arr: np.ndarray):
        self._arr = arr

    def dim(self) -> int:
        return 1

    def numpy(self) -> np.ndarray:
        return self._arr


def _fake_waveform() -> _FakeWaveform:
    return _FakeWaveform(np.zeros(16000, dtype=np.float32))


def _make_mock_model(language: str = "nl") -> MagicMock:
    """A fake faster-whisper WhisperModel whose .transcribe() records kwargs
    and returns no segments (segment shape isn't what these tests check)."""
    model = MagicMock()
    info = MagicMock(language=language, language_probability=0.95, duration=1.0)
    model.transcribe = MagicMock(return_value=([], info))
    return model


# ── transcribe_chunk / _transcribe_chunk_sync ─────────────────────────────────

class TestTranscribeChunk:
    @pytest.mark.asyncio
    async def test_initial_prompt_passed_when_given(self):
        model = _make_mock_model()
        with patch("app.services.transcription._get_model", return_value=model):
            await transcription.transcribe_chunk(
                _fake_waveform(), 16000, language="tr", initial_prompt="Ahmad, Kabul"
            )
        _, kwargs = model.transcribe.call_args
        assert kwargs["initial_prompt"] == "Ahmad, Kabul"

    @pytest.mark.asyncio
    async def test_initial_prompt_omitted_when_not_given(self):
        model = _make_mock_model()
        with patch("app.services.transcription._get_model", return_value=model):
            await transcription.transcribe_chunk(_fake_waveform(), 16000, language="tr")
        _, kwargs = model.transcribe.call_args
        assert "initial_prompt" not in kwargs

    @pytest.mark.asyncio
    async def test_initial_prompt_omitted_when_empty_string(self):
        """Empty string is falsy — same convention as `language` already uses."""
        model = _make_mock_model()
        with patch("app.services.transcription._get_model", return_value=model):
            await transcription.transcribe_chunk(
                _fake_waveform(), 16000, language="tr", initial_prompt=""
            )
        _, kwargs = model.transcribe.call_args
        assert "initial_prompt" not in kwargs

    @pytest.mark.asyncio
    async def test_language_and_initial_prompt_coexist(self):
        model = _make_mock_model()
        with patch("app.services.transcription._get_model", return_value=model):
            await transcription.transcribe_chunk(
                _fake_waveform(), 16000, language="tr", initial_prompt="Ahmad"
            )
        _, kwargs = model.transcribe.call_args
        assert kwargs["language"] == "tr"
        assert kwargs["initial_prompt"] == "Ahmad"

    @pytest.mark.asyncio
    async def test_neither_language_nor_initial_prompt_by_default(self):
        """No regressions to the pre-existing auto-detect-language behaviour."""
        model = _make_mock_model()
        with patch("app.services.transcription._get_model", return_value=model):
            await transcription.transcribe_chunk(_fake_waveform(), 16000)
        _, kwargs = model.transcribe.call_args
        assert "language" not in kwargs
        assert "initial_prompt" not in kwargs


# ── transcribe / _transcribe_sync ─────────────────────────────────────────────

class TestTranscribe:
    @pytest.mark.asyncio
    async def test_initial_prompt_passed_when_given(self, tmp_path):
        model = _make_mock_model()
        audio_path = tmp_path / "audio.wav"
        audio_path.write_bytes(b"")
        with patch("app.services.transcription._get_model", return_value=model):
            await transcription.transcribe(audio_path, initial_prompt="Ahmad, Kabul")
        _, kwargs = model.transcribe.call_args
        assert kwargs["initial_prompt"] == "Ahmad, Kabul"

    @pytest.mark.asyncio
    async def test_initial_prompt_omitted_when_not_given(self, tmp_path):
        model = _make_mock_model()
        audio_path = tmp_path / "audio.wav"
        audio_path.write_bytes(b"")
        with patch("app.services.transcription._get_model", return_value=model):
            await transcription.transcribe(audio_path)
        _, kwargs = model.transcribe.call_args
        assert "initial_prompt" not in kwargs
