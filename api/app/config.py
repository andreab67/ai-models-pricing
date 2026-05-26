"""Runtime configuration loaded from env vars."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- service ----------------------------------------------------------
    environment: str = Field(default="dev")
    log_level: str = Field(default="INFO")
    api_host: str = Field(default="0.0.0.0")  # noqa: S104 — intentional in container
    api_port: int = Field(default=8000, validation_alias="server_port")
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    # --- openrouter -------------------------------------------------------
    openrouter_base_url: str = Field(default="https://openrouter.ai/api/v1")
    openrouter_models_path: str = Field(default="/models")
    openrouter_timeout_s: float = Field(default=15.0)
    openrouter_refresh_seconds: int = Field(default=900)  # 15 min

    # --- kilo -------------------------------------------------------------
    kilo_plans_path: Path = Field(default=Path(__file__).parent / "data" / "kilo_plans.yaml")
    kilo_pricing_url: str = Field(default="https://kilo.ai/pricing")
    kilo_diff_user_agent: str = Field(default="model-pricing-bot/0.1 (+andrea-house.com)")

    # --- redis ------------------------------------------------------------
    redis_url: str = Field(default="redis://localhost:6379/0")
    cache_ttl_seconds: int = Field(default=900)

    # --- postgres ---------------------------------------------------------
    database_url: str = Field(
        default="postgresql+psycopg://pricing:pricing@localhost:5432/pricing"
    )
    db_pool_size: int = Field(default=5)
    db_max_overflow: int = Field(default=10)

    # --- mail -------------------------------------------------------------
    smtp_host: str = Field(default="")
    smtp_port: int = Field(default=465)
    smtp_username: str = Field(default="")
    smtp_password: str = Field(default="")
    smtp_use_tls: bool = Field(default=True)   # port 465 SSL wrapper (SES)
    smtp_starttls: bool = Field(default=False)  # port 587 STARTTLS — not used with SES/465
    smtp_from: str = Field(default="greenyogainc@greenyogainc.com")
    smtp_to: list[str] = Field(default_factory=list)

    # --- ranking ----------------------------------------------------------
    # weights used to score "best coding model" — pure cost is naive, so we
    # bias toward output cost (longer in coding) and require min context.
    rank_input_weight: float = Field(default=0.30)
    rank_output_weight: float = Field(default=0.70)
    rank_min_context_tokens: int = Field(default=64_000)
    rank_max_input_price: float = Field(default=10.0)   # USD / Mtok
    rank_max_output_price: float = Field(default=40.0)  # USD / Mtok
    rank_top_n: int = Field(default=10)

    # --- external account keys -------------------------------------------
    openrouter_api_key: str = Field(default="")
    kilo_api_key: str = Field(default="")
    openai_api_key: str = Field(default="")
    openai_admin_key: str = Field(default="")
    anthropic_api_key: str = Field(default="")
    anthropic_admin_key: str = Field(default="")

    # --- kilo plan (used for account widget) -----------------------------
    kilo_tier: str = Field(default="starter")

    # --- comparison wrappers ---------------------------------------------
    openrouter_payg_fee_pct: float = Field(default=0.055)
    openrouter_byok_fee_pct: float = Field(default=0.05)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
