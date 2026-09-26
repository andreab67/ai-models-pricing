"""Runtime configuration loaded from env vars."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
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
    # Expected interval between refresh-pricing runs; the models cache lives
    # 3x this long so it never expires between runs.
    openrouter_refresh_seconds: int = Field(default=900)  # 15 min
    # Hourly snapshots older than this are pruned by the refresh job (0 = keep).
    snapshot_retention_days: int = Field(default=90)

    # --- kilo -------------------------------------------------------------
    kilo_plans_path: Path = Field(default=Path(__file__).parent / "data" / "kilo_plans.yaml")
    # Gateway API host. On 2026-09-18 api.kilo.ai returned a bare edge 403 on
    # every path for ~3h (roughly 18:30-21:30 UTC) and api.kilocode.ai answered
    # instead; both then flipped back. That was a Kilo-side outage, NOT a host
    # migration -- kilo.ai/docs and the Kilo Code extension both still use
    # api.kilo.ai, which is the correct host. Kept settings-backed so the next
    # such outage can be ridden out with an env var instead of a redeploy.
    # NOTE: kilo_pricing_url below is the *marketing* site; not interchangeable.
    kilo_base_url: str = Field(default="https://api.kilo.ai/api/gateway")
    kilo_pricing_url: str = Field(default="https://kilo.ai/pricing")
    kilo_diff_user_agent: str = Field(default="model-pricing-bot/0.1 (+andrea-house.com)")
    kilo_extraction_model: str = Field(default="anthropic/claude-haiku-4.5")
    kilo_sanity_max_delta_pct: float = Field(default=0.50)

    # --- gitlab (kilo_diff auto-commit) ------------------------------------
    gitlab_api_url: str = Field(default="https://gitlab.andrea-house.com/api/v4")
    gitlab_project_id: int = Field(default=54)
    gitlab_project_path: str = Field(default="root/model-pricing")
    gitlab_token: str = Field(default="")

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
    rank_min_context_tokens: int = Field(default=1_000_000)
    rank_max_input_price: float = Field(default=10.0)   # USD / Mtok
    rank_max_output_price: float = Field(default=40.0)  # USD / Mtok
    rank_top_n: int = Field(default=10)
    rank_exclude_patterns: list[str] = Field(
        default=["flash-lite", "flash-8b", "learnlm"]
    )

    # --- external account keys -------------------------------------------
    openrouter_api_key: str = Field(default="")
    openrouter_admin_key: str = Field(default="")
    kilo_api_key: str = Field(default="")

    # --- kilo plan (account widget + daily report savings) ---------------
    # Must be a tier in kilo_plans.yaml; an unknown value fails fast at start.
    kilo_tier: Literal["starter", "pro", "expert"] = Field(default="starter")

    # --- comparison wrappers ---------------------------------------------
    openrouter_payg_fee_pct: float = Field(default=0.055)
    openrouter_byok_fee_pct: float = Field(default=0.05)

    @field_validator("kilo_tier", mode="before")
    @classmethod
    def _normalize_tier(cls, v: object) -> object:
        return v.strip().lower() if isinstance(v, str) else v


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
