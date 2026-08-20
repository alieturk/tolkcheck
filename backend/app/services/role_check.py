"""Role-assignment consistency check.

Speaker roles are assigned by hand: diarization returns anonymous SPEAKER_NN
labels and a user picks which is the interpreter and which the client. Nothing
verifies that choice, and nothing verifies that diarization put each speaker's
audio in the right cluster to begin with. Both failures are silent — scoring
proceeds and produces numbers that look ordinary.

The language Whisper detected per segment is independent evidence about who is
speaking, because an IND hearing constrains it:

    officer      Dutch only          (a Dutch civil servant conducting the hearing)
    client       source language only (why an interpreter is present at all)
    interpreter  both, in alternation (that is the job)

A speaker whose languages do not fit that shape is evidence of a misassignment
somewhere upstream. This module reports; it does not correct. Reassigning turns
on a language guess would fix some hearings and quietly corrupt others, and the
person reviewing a hearing needs to know the recording was ambiguous either way.
"""
from __future__ import annotations

import logging
from collections import defaultdict

log = logging.getLogger(__name__)

# A stray segment or two is normal — a Turkish place name inside a Dutch
# question, a "ja" from the client that decodes as Dutch. The threshold is a
# share of the speaker's own segments, so it scales with how much they talk.
CONTAMINATION_SHARE = 0.15
# Below this share of either language, a speaker is not really working
# bilingually and probably is not the interpreter.
BILINGUAL_MIN_SHARE = 0.20


def check_roles(
    transcript: list[dict],
    interpreter_speaker: str,
    client_speaker: str,
    client_lang: str,
) -> dict:
    """Compare detected languages against what each role should be speaking.

    Returns a JSON-serialisable dict::

        {
          "ok": bool,                      # False when any warning fired
          "client_lang": str,
          "distribution": {speaker: {"role": str, "total": int, "langs": {lang: n}}},
          "warnings": [{"code", "severity", "speaker", "message"}],
        }

    Severity is "high" when the finding invalidates scoring outright (roles
    swapped, interpreter not bilingual) and "medium" when it points at
    diarization leaking turns between speakers.
    """
    by_speaker: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for seg in transcript:
        by_speaker[seg.get("speaker", "?")][seg.get("language", "?")] += 1

    def role_of(spk: str) -> str:
        if spk == interpreter_speaker:
            return "interpreter"
        if spk == client_speaker:
            return "client"
        return "officer"

    distribution = {
        spk: {"role": role_of(spk), "total": sum(langs.values()), "langs": dict(langs)}
        for spk, langs in by_speaker.items()
    }

    def share(spk: str, lang: str) -> float:
        info = distribution.get(spk)
        if not info or not info["total"]:
            return 0.0
        return info["langs"].get(lang, 0) / info["total"]

    warnings: list[dict] = []

    def warn(code: str, severity: str, speaker: str | None, message: str) -> None:
        warnings.append({"code": code, "severity": severity,
                         "speaker": speaker, "message": message})

    # Nothing below is meaningful when the client speaks Dutch too.
    if client_lang != "nl":
        # 1. Officers speaking the client's language — client turns in the officer's cluster.
        for spk, info in distribution.items():
            if info["role"] != "officer":
                continue
            s = share(spk, client_lang)
            if s >= CONTAMINATION_SHARE:
                warn("officer_speaks_client_lang", "medium", spk,
                     f"{spk} is treated as the IND officer but {s:.0%} of their segments "
                     f"were detected as '{client_lang}'. Client speech is most likely "
                     f"assigned to the officer by diarization.")

        # 2. Client speaking Dutch — officer turns in the client's cluster.
        s = share(client_speaker, "nl")
        if s >= CONTAMINATION_SHARE:
            warn("client_speaks_dutch", "medium", client_speaker,
                 f"{client_speaker} is the client but {s:.0%} of their segments were "
                 f"detected as Dutch. Officer speech is most likely assigned to the "
                 f"client by diarization.")

        # 3. Interpreter not working in both languages — usually the wrong pick.
        i_client = share(interpreter_speaker, client_lang)
        i_dutch = share(interpreter_speaker, "nl")
        if min(i_client, i_dutch) < BILINGUAL_MIN_SHARE:
            warn("interpreter_not_bilingual", "high", interpreter_speaker,
                 f"{interpreter_speaker} is the interpreter but speaks "
                 f"{i_client:.0%} '{client_lang}' and {i_dutch:.0%} Dutch. An interpreter "
                 f"alternates between both; this speaker does not.")

        # 4. Roles swapped outright — each speaker looks like the other.
        if (share(client_speaker, "nl") > share(client_speaker, client_lang)
                and any(info["role"] == "officer" and share(spk, client_lang) > share(spk, "nl")
                        for spk, info in distribution.items())):
            warn("roles_possibly_swapped", "high", None,
                 "The speaker marked as the client speaks mostly Dutch while a speaker "
                 "treated as the officer speaks mostly the client's language. The role "
                 "assignment is probably reversed.")

    # Which speaker best fits the interpreter's profile, on the evidence.
    candidates = [(min(share(s, client_lang), share(s, "nl")), s) for s in distribution]
    best = max(candidates)[1] if candidates else None
    if best and best != interpreter_speaker and any(
        w["code"] in ("interpreter_not_bilingual", "roles_possibly_swapped") for w in warnings
    ):
        warn("interpreter_candidate", "high", best,
             f"On the language evidence {best} is the most bilingual speaker and is the "
             f"more likely interpreter.")

    result = {
        "ok": not warnings,
        "client_lang": client_lang,
        "distribution": distribution,
        "warnings": warnings,
    }

    for spk, info in sorted(distribution.items()):
        log.info("check_roles  %-12s role=%-11s n=%-3d langs=%s",
                 spk, info["role"], info["total"], info["langs"])
    for w in warnings:
        log.warning("check_roles  %s  [%s]  %s", w["code"], w["severity"], w["message"])
    if not warnings:
        log.info("check_roles  role assignment consistent with detected languages")

    return result
