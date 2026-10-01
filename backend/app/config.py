from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@db:5432/tolkcheck"

    # CORS
    cors_origins: list[str] = ["http://localhost:3000"]

    # Whisper
    # large-v3 rather than "turbo", as a deliberately CONSERVATIVE choice — not a
    # measured one. Read this before "optimising" it either way.
    #
    # Why prefer large-v3: turbo is a distilled large-v3 whose decoder has 4 layers
    # instead of 32. It is several times faster, and distillation of that severity
    # carries a risk of quality loss that falls hardest on languages with the least
    # training data. Turkish is the client language this tool targets. Any
    # transcription error on the source side propagates into the LaBSE similarity
    # score and is indistinguishable there from an interpreter deviation — i.e. it
    # manufactures exactly the signal the tool exists to detect. So we pay the CPU
    # cost (whisper_device="cpu") to keep source-side noise down.
    #
    # What we actually measured: evaluation/wer_check.py, on the 8 gold clips, gives
    # turbo and large-v3 an IDENTICAL corpus WER. That fixture set is clean TTS read
    # speech and is too easy to separate them — a tie there is not evidence they are
    # equivalent, only that the benchmark is saturated. The turbo penalty, if it
    # exists, would show on accented, noisy or disfluent Turkish, which is precisely
    # what the fixtures lack. Switching to turbo would roughly halve CPU time and
    # may well be fine; it just is not yet evidenced. Get harder audio, re-run
    # wer_check.py, and decide on the numbers.
    whisper_model: str = "large-v3"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"

    # HuggingFace — required for pyannote.audio diarization
    hf_token: str = ""

    # Anthropic
    anthropic_api_key: str = ""
    llm_model: str = "claude-sonnet-4-6"

    # Redis / ARQ
    redis_url: str = "redis://redis:6379"

    # Auth
    secret_key: str  # required — no default; app must fail to start if unset
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 10  # 10 hours
    # Cookies must be sent over HTTPS in production. Default safe (True);
    # on-prem deployments without internal HTTPS must set COOKIE_SECURE=false
    # explicitly in .env, or the login cookie will silently fail to persist.
    cookie_secure: bool = True
    # Account lockout (BIO2 5.17): this many consecutive failed logins lock the
    # account for login_lockout_minutes. Per account, not per IP — rate
    # limiting by source address belongs in the reverse proxy.
    login_max_failures: int = 5
    login_lockout_minutes: int = 15
    # Minimum length for passwords set through the operator CLI.
    password_min_length: int = 12

    # Retention (EIS-5, AVG art. 5(1)(e)): sessions — with their transcript,
    # flags and feedback — and any remaining audio are deleted this many days
    # after upload by the daily job in app/services/retention.py.
    retention_days: int = 90

    # Logging
    log_level: str = "INFO"


settings = Settings()
