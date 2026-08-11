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
    whisper_model: str = "turbo"
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

    # Logging
    log_level: str = "INFO"


settings = Settings()
