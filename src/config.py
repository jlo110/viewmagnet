"""Configuration management for ViewMagnet."""
from functools import lru_cache
from typing import List, Optional
from pydantic_settings import BaseSettings
from pydantic import Field, model_validator


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Environment (development, staging, production)
    environment: str = Field(default="development", alias="ENVIRONMENT")
    debug: bool = Field(default=False, alias="DEBUG")
    
    # Dev mode (NEVER true in production - hard-gated below)
    dev_mode: bool = Field(default=False, alias="DEV_MODE")
    
    # Frontend URL (used for OAuth callbacks, share links)
    frontend_url: str = Field(default="http://localhost:5173", alias="FRONTEND_URL")
    
    # YouTube API Keys (multiple for quota distribution)
    # Support both YOUTUBE_API_KEY_N and YOUTUBEX naming conventions
    youtube_api_key_1: Optional[str] = Field(default=None, alias="YOUTUBE_API_KEY_1")
    youtube_api_key_2: Optional[str] = Field(default=None, alias="YOUTUBE_API_KEY_2")
    youtube_api_key_3: Optional[str] = Field(default=None, alias="YOUTUBE_API_KEY_3")
    youtube_api_key_4: Optional[str] = Field(default=None, alias="YOUTUBE_API_KEY_4")
    
    # Alternative naming (YOUTUBE1, YOUTUBE2, etc.)
    youtube1: Optional[str] = Field(default=None, alias="YOUTUBE1")
    youtube2: Optional[str] = Field(default=None, alias="YOUTUBE2")
    youtube3: Optional[str] = Field(default=None, alias="YOUTUBE3")
    youtube4: Optional[str] = Field(default=None, alias="YOUTUBE4")
    youtube5: Optional[str] = Field(default=None, alias="YOUTUBE5")
    youtube6: Optional[str] = Field(default=None, alias="YOUTUBE6")
    youtube7: Optional[str] = Field(default=None, alias="YOUTUBE7")
    youtube8: Optional[str] = Field(default=None, alias="YOUTUBE8")
    youtube9: Optional[str] = Field(default=None, alias="YOUTUBE9")
    youtube10: Optional[str] = Field(default=None, alias="YOUTUBE10")
    youtube11: Optional[str] = Field(default=None, alias="YOUTUBE11")
    youtube12: Optional[str] = Field(default=None, alias="YOUTUBE12")
    youtube13: Optional[str] = Field(default=None, alias="YOUTUBE13")
    youtube14: Optional[str] = Field(default=None, alias="YOUTUBE14")
    youtube15: Optional[str] = Field(default=None, alias="YOUTUBE15")
    youtube16: Optional[str] = Field(default=None, alias="YOUTUBE16")
    youtube17: Optional[str] = Field(default=None, alias="YOUTUBE17")
    youtube18: Optional[str] = Field(default=None, alias="YOUTUBE18")
    youtube19: Optional[str] = Field(default=None, alias="YOUTUBE19")
    youtube20: Optional[str] = Field(default=None, alias="YOUTUBE20")
    youtube21: Optional[str] = Field(default=None, alias="YOUTUBE21")
    youtube22: Optional[str] = Field(default=None, alias="YOUTUBE22")
    youtube23: Optional[str] = Field(default=None, alias="YOUTUBE23")
    
    # Database - NO DEFAULT, must be set via environment
    database_url: Optional[str] = Field(default=None, alias="DATABASE_URL")
    
    # JWT Authentication - NO DEFAULT for secret, must be set via environment
    jwt_secret_key: Optional[str] = Field(default=None, alias="JWT_SECRET_KEY")
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    jwt_access_token_expire_minutes: int = Field(default=30, alias="JWT_ACCESS_TOKEN_EXPIRE_MINUTES")
    jwt_refresh_token_expire_days: int = Field(default=7, alias="JWT_REFRESH_TOKEN_EXPIRE_DAYS")
    
    # Cloudflare R2 Storage
    r2_account_id: Optional[str] = Field(default=None, alias="R2_ACCOUNT_ID")
    r2_access_key_id: Optional[str] = Field(default=None, alias="R2_ACCESS_KEY_ID")
    r2_secret_access_key: Optional[str] = Field(default=None, alias="R2_SECRET_ACCESS_KEY")
    r2_bucket_name: str = Field(default="viewmagnet-videos", alias="R2_BUCKET_NAME")
    
    # Anthropic Claude API
    anthropic_api_key: Optional[str] = Field(default=None, alias="ANTHROPIC_API_KEY")
    anthropic_model: str = Field(default="claude-sonnet-4-6", alias="ANTHROPIC_MODEL")
    
    # Groq API (fallback LLM)
    groq_api_key: Optional[str] = Field(default=None, alias="GROQ_API_KEY")
    groq_model: str = Field(default="llama-3.3-70b-versatile", alias="GROQ_MODEL")

    # Synthetic (https://synthetic.new) — subscription-based access to OSS LLMs
    # via an OpenAI-compatible endpoint. Used as a fallback between Anthropic
    # and Groq so we still produce LLM-grade output when Anthropic is out of
    # credits / rate-limited. Models are prefixed ``hf:<org>/<model>``.
    synthetic_api_key: Optional[str] = Field(default=None, alias="SYNTHETIC_API_KEY")
    synthetic_model: str = Field(
        # ``syn:large:text`` — Synthetic's always-current alias for the best large
        # text model (resolves to GLM-5.2 today). Use the alias, not a pinned
        # ``hf:...`` id: pinned ids get dropped by the proxy provider and 404
        # (Qwen3-Coder-480B did exactly that in ~2026-06, silently breaking the
        # whole Synthetic tier). Override via ``SYNTHETIC_MODEL`` env var. If
        # swapping, verify the candidate returns direct JSON — some reasoning
        # lines (e.g. Kimi K2.x) exhaust max_tokens on hidden chain-of-thought
        # and return empty content.
        default="syn:large:text",
        alias="SYNTHETIC_MODEL",
    )
    synthetic_base_url: str = Field(
        default="https://api.synthetic.new/openai/v1", alias="SYNTHETIC_BASE_URL"
    )
    
    # ElevenLabs API
    elevenlabs_api_key: Optional[str] = Field(default=None, alias="ELEVENLABS_API_KEY")
    
    # Replicate API
    replicate_api_token: Optional[str] = Field(default=None, alias="REPLICATE_API_TOKEN")
    
    # Google / YouTube OAuth client secrets file path
    google_client_secrets: Optional[str] = Field(default=None, alias="GOOGLE_CLIENT_SECRETS")
    
    # Stripe billing
    stripe_secret_key: Optional[str] = Field(default=None, alias="STRIPE_SECRET_KEY")
    stripe_webhook_secret: Optional[str] = Field(default=None, alias="STRIPE_WEBHOOK_SECRET")
    stripe_publishable_key: Optional[str] = Field(default=None, alias="STRIPE_PUBLISHABLE_KEY")
    
    # Encryption (Fernet key for at-rest token encryption)
    encryption_key: Optional[str] = Field(default=None, alias="ENCRYPTION_KEY")
    
    # Redis (cache + queue + rate-limit backend)
    redis_url: Optional[str] = Field(default=None, alias="REDIS_URL")
    
    # CORS origins (comma-separated)
    cors_origins: str = Field(
        default="http://localhost:3000,http://localhost:5173",
        alias="CORS_ORIGINS"
    )

    # Trusted Host allowlist (comma-separated host globs). Defaults to "*"
    # (accept any Host header) so existing deploys keep working; set to the
    # real domains in production to block Host-header attacks.
    allowed_hosts: str = Field(default="*", alias="ALLOWED_HOSTS")
    
    # Sentry DSN for error tracking (optional)
    sentry_dsn: Optional[str] = Field(default=None, alias="SENTRY_DSN")
    
    # Rate limiting
    rate_limit_requests: int = Field(default=100, alias="RATE_LIMIT_REQUESTS")
    rate_limit_period: int = Field(default=60, alias="RATE_LIMIT_PERIOD")

    # Background scheduler (APScheduler hourly metrics sweep). Must run in
    # EXACTLY ONE process — never in the API under multiple uvicorn workers,
    # or the job fires once per worker. Enable on a single dedicated process.
    run_scheduler: bool = Field(default=False, alias="RUN_SCHEDULER")

    # Velocity collection throughput caps (per scheduled run). Discovery costs
    # 1 quota unit/channel; with 22 keys (~220k units/day) sweeping ~3000
    # channels/hour = ~72k units/day, leaving headroom for the live app.
    velocity_discover_max_channels: int = Field(default=3000, alias="VELOCITY_DISCOVER_MAX_CHANNELS")
    # Raised 3000 -> 6000: denser trajectory sampling on spare quota (~1 unit/50
    # videos, so 6000 = ~120 units/cycle). Prod still has a SYNTHETIC-style env
    # override pinned at 3000 — set VELOCITY_COLLECT_MAX_VIDEOS=6000 to apply.
    velocity_collect_max_videos: int = Field(default=6000, alias="VELOCITY_COLLECT_MAX_VIDEOS")

    # Quota observability: warn when the fraction of daily YouTube quota still
    # remaining (across all keys) drops below this. 0.15 = alert at <15% left so
    # there's runway to cut discovery cadence before jobs actually starve.
    youtube_quota_alert_pct: float = Field(default=0.15, alias="YOUTUBE_QUOTA_ALERT_PCT")

    # Quota reserve: discovery is the dominant (and least time-critical) quota
    # spender, so it yields once today's *persisted* remaining quota drops below
    # this, leaving headroom for the cheap-but-irreplaceable capture jobs
    # (snapshots / channel time-series / comments). Skips the run, doesn't cut
    # cadence — full speed while there's headroom. Proper fix is WebSub (7.5).
    youtube_quota_discovery_reserve: int = Field(
        default=20000, alias="YOUTUBE_QUOTA_DISCOVERY_RESERVE"
    )

    # Collection QA: alert when a checkpoint's *recent* window hit-rate (windows
    # captured / eligible windows that closed in the last week) drops below this.
    # Catches silent dataset erosion (quota exhaustion / stalled scheduler) that
    # per-job success logs miss.
    collection_hit_rate_alert: float = Field(
        default=0.70, alias="COLLECTION_HIT_RATE_ALERT"
    )

    # WebSub push discovery (plan 7.5): YouTube pushes upload notifications to
    # our public callback — zero API quota (discovery polling is 99.5% of our
    # usage) and ~minutes latency. Disabled until the callback URL is set to
    # the API's public base (e.g. https://api.example.com — we append
    # /websub/youtube). The secret HMAC-signs notifications.
    websub_callback_url: Optional[str] = Field(default=None, alias="WEBSUB_CALLBACK_URL")
    websub_secret: Optional[str] = Field(default=None, alias="WEBSUB_SECRET")
    websub_lease_seconds: int = Field(default=828000, alias="WEBSUB_LEASE_SECONDS")  # ~9.6d max
    websub_subscribe_batch: int = Field(default=600, alias="WEBSUB_SUBSCRIBE_BATCH")

    # Collection targets
    target_channels: int = Field(default=5000, alias="TARGET_CHANNELS")
    daily_api_quota: int = Field(default=10000, alias="DAILY_API_QUOTA")
    
    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }
    
    @model_validator(mode="after")
    def validate_required_in_production(self) -> "Settings":
        """Validate that required secrets are set in production."""
        if self.environment == "production":
            if not self.database_url:
                raise ValueError("DATABASE_URL must be set in production")
            if not self.jwt_secret_key:
                raise ValueError("JWT_SECRET_KEY must be set in production")
            if self.jwt_secret_key and len(self.jwt_secret_key) < 32:
                raise ValueError("JWT_SECRET_KEY must be at least 32 characters in production")
            if self.dev_mode:
                raise ValueError(
                    "DEV_MODE must NOT be true in production. "
                    "DEV_MODE bypasses authentication and is for local development only."
                )
            if not self.encryption_key:
                raise ValueError(
                    "ENCRYPTION_KEY must be set in production (Fernet key for OAuth token encryption). "
                    "Generate one with: python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
                )
        
        # For development, use safe defaults
        if self.environment == "development":
            if not self.database_url:
                self.database_url = "sqlite:///./viewmagnet_dev.db"
            if not self.jwt_secret_key:
                self.jwt_secret_key = "dev-secret-key-not-for-production-use"
        
        return self
    
    @property
    def is_production(self) -> bool:
        """Check if running in production."""
        return self.environment == "production"
    
    @property
    def is_development(self) -> bool:
        """Check if running in development."""
        return self.environment == "development"
    
    @property
    def cors_origins_list(self) -> List[str]:
        """Return CORS origins as a list."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def allowed_hosts_list(self) -> List[str]:
        """Return the TrustedHost allowlist as a list (``['*']`` accepts any)."""
        return [h.strip() for h in self.allowed_hosts.split(",") if h.strip()] or ["*"]
    
    @property
    def youtube_api_keys(self) -> List[str]:
        """Return list of configured API keys."""
        keys = [
            self.youtube_api_key_1,
            self.youtube_api_key_2,
            self.youtube_api_key_3,
            self.youtube_api_key_4,
            self.youtube1,
            self.youtube2,
            self.youtube3,
            self.youtube4,
            self.youtube5,
            self.youtube6,
            self.youtube7,
            self.youtube8,
            self.youtube9,
            self.youtube10,
            self.youtube11,
            self.youtube12,
            self.youtube13,
            self.youtube14,
            self.youtube15,
            self.youtube16,
            self.youtube17,
            self.youtube18,
            self.youtube19,
            self.youtube20,
            self.youtube21,
            self.youtube22,
            self.youtube23,
        ]
        return [k for k in keys if k is not None]


# ============================================================
# HOISTED CONSTANTS (moved from individual modules)
# ============================================================

# Plan-based analysis & LLM-budget limits (per month/day)
#
# The four public tiers (Free / Starter / Pro / Agency) are the source of
# truth — they match the marketing Pricing page, the published /pricing.md
# and llms.txt copy, and the Stripe price set. ``enterprise`` is retained
# as a back-compat alias for ``agency`` (older rows + the DEV_MODE demo
# user historically used "pro"/"enterprise"); both resolve to unlimited.
PLAN_LIMITS = {
    "free": {
        "analyses_per_month": 5,
        "daily_llm_usd": 0.50,
    },
    "starter": {
        "analyses_per_month": 50,
        "daily_llm_usd": 5.00,
    },
    "pro": {
        "analyses_per_month": 500,
        "daily_llm_usd": 25.00,
    },
    "agency": {
        "analyses_per_month": -1,  # unlimited
        "daily_llm_usd": 100.00,
    },
    # Back-compat alias — treated identically to "agency".
    "enterprise": {
        "analyses_per_month": -1,  # unlimited
        "daily_llm_usd": 100.00,
    },
}

# Plans with no analysis / render cap. Used by enforcement helpers so the
# "unlimited" check stays in one place as tiers evolve.
UNLIMITED_PLANS = frozenset({"agency", "enterprise"})

# Predicted-tier thresholds used by analyze.py
TIER_THRESHOLDS = {
    "viral": 80,
    "high": 60,
    "medium": 40,
    "low": 0,
}

# Average YouTube video duration per category (used by metadata_analyzer)
CATEGORY_AVG_DURATIONS = {
    "gaming": 1200,            # 20 min
    "commentary_essay": 900,   # 15 min
    "entertainment_vlogs": 600,  # 10 min
    "education_howto": 900,    # 15 min
    "tech_reviews": 720,       # 12 min
    "music_creative": 240,     # 4 min
    "lifestyle": 600,          # 10 min
    "news_politics": 480,      # 8 min
    "other": 600,
}

# Pacing thresholds (loop_designer/pacing_analyzer)
PACING_TARGET_AVG_CUT_SECONDS = 3.0
PACING_MAX_DEAD_AIR_SECONDS = 2.0
PACING_SILENCE_THRESHOLD_DB = -35.0


# Category distribution targets from the guide
CATEGORY_DISTRIBUTION = {
    "gaming": 1200,
    "commentary_essay": 600,
    "entertainment_vlogs": 600,
    "education_howto": 600,
    "tech_reviews": 400,
    "music_creative": 300,
    "lifestyle": 500,  # cooking, fitness, fashion
    "news_politics": 300,
    "other": 500,
}

# Size distribution within each category (subscriber ranges)
SIZE_DISTRIBUTION = {
    "micro": {"range": (10_000, 50_000), "percentage": 0.25},
    "small": {"range": (50_000, 200_000), "percentage": 0.30},
    "medium": {"range": (200_000, 1_000_000), "percentage": 0.25},
    "large": {"range": (1_000_000, 5_000_000), "percentage": 0.15},
    "top": {"range": (5_000_000, float("inf")), "percentage": 0.05},
}

# YouTube category IDs mapping
YOUTUBE_CATEGORY_IDS = {
    "gaming": ["20"],  # Gaming
    "commentary_essay": ["24", "27"],  # Entertainment, Education
    "entertainment_vlogs": ["24", "22"],  # Entertainment, People & Blogs
    "education_howto": ["27", "26"],  # Education, Howto & Style
    "tech_reviews": ["28"],  # Science & Technology
    "music_creative": ["10"],  # Music
    "lifestyle": ["26", "19"],  # Howto & Style, Travel & Events
    "news_politics": ["25"],  # News & Politics
    "other": ["1", "2", "15", "17", "23"],  # Film, Autos, Pets, Sports, Comedy
}

# Search queries for channel discovery by category
DISCOVERY_QUERIES = {
    "gaming": [
        "gaming", "gameplay", "walkthrough", "let's play",
        "valorant", "fortnite", "minecraft", "gta", "call of duty",
        "apex legends", "league of legends", "elden ring", "gaming tips",
        "esports", "speedrun", "game review"
    ],
    "commentary_essay": [
        "video essay", "commentary", "analysis", "explained",
        "deep dive", "breakdown", "review essay", "media analysis",
        "film analysis", "social commentary"
    ],
    "entertainment_vlogs": [
        "vlog", "daily vlog", "lifestyle vlog", "day in my life",
        "challenge", "prank", "reaction", "storytime", "grwm"
    ],
    "education_howto": [
        "tutorial", "how to", "learn", "explained", "course",
        "tips and tricks", "beginner guide", "masterclass",
        "science explained", "history explained", "math tutorial"
    ],
    "tech_reviews": [
        "tech review", "smartphone review", "laptop review", "gadget",
        "unboxing", "tech news", "best tech", "comparison",
        "iphone", "samsung", "apple", "android"
    ],
    "music_creative": [
        "music", "cover", "original song", "music video",
        "producer", "beat making", "singing", "musician",
        "guitar tutorial", "piano cover", "songwriter", "indie artist",
        "bedroom producer", "music producer 2024", "remix", "acoustic cover",
        "lofi beats", "music channel", "singer songwriter", "music reaction"
    ],
    "lifestyle": [
        "cooking", "recipe", "fitness", "workout", "fashion",
        "haul", "home decor", "organization", "cleaning",
        "meal prep", "healthy lifestyle"
    ],
    "news_politics": [
        "news", "politics", "current events", "breaking news",
        "political analysis", "debate", "election", "policy",
        "political commentary", "news analysis", "geopolitics", "world news",
        "independent news", "political podcast", "news reaction", "daily news"
    ],
    "other": [
        "comedy", "funny", "pets", "animals", "sports highlights",
        "car review", "travel vlog", "documentary"
    ],
}


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()

