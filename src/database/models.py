"""Database models for channel discovery."""
from datetime import datetime
from typing import Optional
from sqlalchemy import (
    String, Integer, BigInteger, Float, DateTime, Boolean, Text,
    Index, UniqueConstraint, ForeignKey
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from src.security.crypto import encrypt, decrypt


class Base(DeclarativeBase):
    """Base class for all models."""
    pass


def _encrypted_property(column_name: str):
    """Create a hybrid property pair (getter/setter) for at-rest encrypted columns."""
    def getter(self):
        return decrypt(getattr(self, column_name))

    def setter(self, value):
        setattr(self, column_name, encrypt(value))

    return property(getter, setter)


# ============================================================
# USER & AUTH MODELS
# ============================================================

class User(Base):
    """
    ViewMagnet user account.
    
    Stores user info and subscription status.
    """
    __tablename__ = "users"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    # Auth
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)  # Null for OAuth-only users
    
    # Profile
    name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    avatar_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    
    # Subscription
    plan: Mapped[str] = mapped_column(String(50), default="free", nullable=False)  # free, starter, pro, agency
    stripe_customer_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    stripe_subscription_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    subscription_status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # active, past_due, canceled, etc.
    subscription_expires: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    # Usage tracking
    analyses_today: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    analyses_this_month: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_analysis_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    usage_period_start: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Auth hardening
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    email_verification_token: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    password_reset_token: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    password_reset_expires: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    token_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # Bump to revoke all tokens
    totp_secret: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    
    # Referral system
    referral_code: Mapped[Optional[str]] = mapped_column(String(12), unique=True, nullable=True, index=True)
    referred_by_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    referral_bonus_analyses: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    referral_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    
    # Admin
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Email opt-out for watchlist breakout alerts (default on — they opted in by
    # adding channels; this is the unsubscribe). Checked by the alert job.
    watchlist_email_alerts: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Opt-in for the weekly digest (a low-frequency roundup of the week's biggest
    # breakouts on your watchlist — distinct from the real-time alerts above).
    weekly_digest: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # War-room delivery (2.2): a Slack/Discord incoming-webhook URL. When set,
    # watchlist breakout alerts are POSTed here too (for agency war rooms).
    alert_webhook_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    last_login: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    def __repr__(self) -> str:
        return f"<User {self.email}>"


class PersonalAccessToken(Base):
    """A long-lived API token a user can hand to an agent/script.

    Used by the MCP server (and any third-party automation) to call
    the API on behalf of a user without exchanging their password.

    Token format presented to the user once at creation:
        ``vm_pat_<8-char prefix>_<32-char secret>``

    Only the ``prefix`` is indexed and queryable — the secret half is
    sha256-hashed into ``token_hash`` so a database leak can't be
    replayed. ``prefix`` exists purely to give the validator a fast
    keyed lookup instead of scanning every hash in the table.

    ``scopes`` is stored as a JSON-encoded list of strings (e.g.
    ``["read", "write"]``). Per-endpoint scope enforcement is layered on
    in a later phase; v1 records what was asked for so future versions
    can grandfather existing tokens in safely.
    """

    __tablename__ = "personal_access_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Human-readable label the user chose when generating the token
    # ("MacBook Claude", "CI pipeline", etc.). Free-form, 1-120 chars.
    name: Mapped[str] = mapped_column(String(120), nullable=False)

    # First half of the token, indexed for fast lookup. Format:
    # ``vm_pat_<8 hex chars>``. Searchable but useless without the secret.
    prefix: Mapped[str] = mapped_column(String(20), nullable=False, index=True)

    # SHA-256 of the **secret** half (the bit after the prefix). Unique
    # so accidental collisions are loud, indexed because revocation
    # checks join on it.
    token_hash: Mapped[str] = mapped_column(
        String(128), nullable=False, unique=True, index=True
    )

    # JSON array of scope strings. Stored as Text rather than the
    # vendor-specific JSON type so SQLite-backed test fixtures keep
    # working alongside Postgres in production.
    scopes: Mapped[str] = mapped_column(Text, nullable=False, default="[]")

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    # Bumped on every successful auth so we can show "last seen 3 hours
    # ago" in the dashboard and detect dormant tokens.
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # Optional hard expiry. ``None`` = never expires.
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # Soft-delete: revoked tokens stay in the table for audit but stop
    # authenticating. Surfaces in the dashboard as "revoked" rows.
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_pat_user_active", "user_id", "revoked_at"),
    )

    def __repr__(self) -> str:
        status = "revoked" if self.revoked_at else "active"
        return f"<PersonalAccessToken {self.prefix} user={self.user_id} {status}>"


class YouTubeConnection(Base):
    """
    Stores OAuth tokens for connected YouTube channels.
    
    Allows access to user's YouTube Analytics.
    """
    __tablename__ = "youtube_connections"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    
    # Channel info
    channel_id: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    channel_name: Mapped[str] = mapped_column(String(255), nullable=False)
    subscriber_count: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    
    # OAuth tokens (encrypted at rest via Fernet; access through the
    # ``access_token`` / ``refresh_token`` / ``client_secret`` properties below)
    access_token_encrypted: Mapped[str] = mapped_column("access_token", Text, nullable=False)
    refresh_token_encrypted: Mapped[str] = mapped_column("refresh_token", Text, nullable=False)
    token_uri: Mapped[str] = mapped_column(String(500), nullable=False)
    client_id: Mapped[str] = mapped_column(String(255), nullable=False)
    client_secret_encrypted: Mapped[str] = mapped_column("client_secret", String(512), nullable=False)
    scopes: Mapped[str] = mapped_column(Text, nullable=False)  # JSON array
    token_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_synced: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    # Timestamps
    connected_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    
    __table_args__ = (
        UniqueConstraint("user_id", "channel_id", name="uq_user_channel"),
    )
    
    # Encrypted accessors -- read/write plaintext; persisted as ciphertext.
    access_token = _encrypted_property("access_token_encrypted")
    refresh_token = _encrypted_property("refresh_token_encrypted")
    client_secret = _encrypted_property("client_secret_encrypted")


class UserVideoAnalysis(Base):
    """
    Stores analysis results for videos analyzed by users.
    
    Tracks what users have analyzed and the predictions made.
    """
    __tablename__ = "user_video_analyses"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    
    # Video info
    video_id: Mapped[str] = mapped_column(String(11), nullable=False, index=True)
    video_url: Mapped[str] = mapped_column(String(500), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    channel_id: Mapped[Optional[str]] = mapped_column(String(24), nullable=True)
    
    # Prediction results
    prediction_score: Mapped[float] = mapped_column(Float, nullable=False)  # 0-100
    prediction_tier: Mapped[str] = mapped_column(String(20), nullable=False)  # low, medium, high, viral
    title_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    thumbnail_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    
    # SHAP explanations (JSON)
    shap_explanations: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    recommendations: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Actual outcome (filled in later if connected)
    actual_views_7d: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    actual_ctr: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    actual_avg_duration: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    
    # Timestamps
    analyzed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    outcome_checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    __table_args__ = (
        Index("idx_user_video", "user_id", "video_id"),
    )


# ============================================================
# CHANNEL DISCOVERY MODELS
# ============================================================

class Channel(Base):
    """
    YouTube channel with metadata for benchmarking.
    
    Stores all data needed for Week 1-2 channel discovery:
    - Channel ID and name
    - Subscriber count, total views, video count
    - Primary category classification
    - Size tier classification
    - Engagement metrics
    """
    __tablename__ = "channels"
    
    # Primary key
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    # YouTube identifiers
    channel_id: Mapped[str] = mapped_column(String(24), unique=True, nullable=False, index=True)
    channel_name: Mapped[str] = mapped_column(String(255), nullable=False)
    custom_url: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    
    # Channel statistics
    subscriber_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    total_views: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    video_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    
    # Classification
    primary_category: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    youtube_category_id: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    size_tier: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    
    # Derived metrics
    avg_views_per_video: Mapped[float] = mapped_column(Float, nullable=True)
    engagement_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    upload_frequency_days: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    
    # Channel metadata
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    country: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    default_language: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    created_at_yt: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    thumbnail_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    
    # Discovery metadata
    discovery_source: Mapped[str] = mapped_column(String(50), nullable=False, default="search")
    discovery_query: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    
    # Niche assignment (set after clustering)
    niche_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    
    # Tracking
    collected_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    last_updated: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    videos_collected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    
    # Indexes for efficient querying
    __table_args__ = (
        Index("idx_category_size", "primary_category", "size_tier"),
        Index("idx_subscriber_count", "subscriber_count"),
        Index("idx_active_category", "is_active", "primary_category"),
    )
    
    def __repr__(self) -> str:
        return f"<Channel {self.channel_name} ({self.channel_id})>"
    
    @property
    def profile_url(self) -> str:
        """Get the channel's YouTube URL."""
        if self.custom_url:
            return f"https://www.youtube.com/{self.custom_url}"
        return f"https://www.youtube.com/channel/{self.channel_id}"


class ChannelSnapshot(Base):
    """
    Historical snapshots of channel statistics.
    
    Allows tracking channel growth over time for momentum analysis.
    """
    __tablename__ = "channel_snapshots"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel_id: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    
    # Stats at snapshot time
    subscriber_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_views: Mapped[int] = mapped_column(BigInteger, nullable=False)
    video_count: Mapped[int] = mapped_column(Integer, nullable=False)
    
    snapshot_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    
    __table_args__ = (
        Index("idx_channel_snapshot_time", "channel_id", "snapshot_at"),
    )


class DiscoveryProgress(Base):
    """
    Tracks progress of channel discovery by category and size tier.
    
    Used to ensure we hit the target distribution.
    """
    __tablename__ = "discovery_progress"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    size_tier: Mapped[str] = mapped_column(String(20), nullable=False)
    
    target_count: Mapped[int] = mapped_column(Integer, nullable=False)
    current_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    
    last_updated: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (
        UniqueConstraint("category", "size_tier", name="uq_category_size"),
    )
    
    @property
    def is_complete(self) -> bool:
        return self.current_count >= self.target_count
    
    @property
    def progress_pct(self) -> float:
        if self.target_count == 0:
            return 100.0
        return (self.current_count / self.target_count) * 100


class Video(Base):
    """
    YouTube video with metadata for benchmarking.
    
    Week 2-3: Video Metadata Collection
    - Last 30 videos per channel (150K total)
    - Performance metrics vs channel baseline
    """
    __tablename__ = "videos"
    
    # Primary key
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    # YouTube identifiers
    video_id: Mapped[str] = mapped_column(String(11), unique=True, nullable=False, index=True)
    channel_id: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    
    # Basic metadata
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # First 1000 chars
    thumbnail_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    tags: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON array stored as text
    
    # Video properties
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    published_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    youtube_category_id: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    
    # Current statistics
    view_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    like_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    comment_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    
    # Calculated performance metrics
    performance_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # views / channel avg
    engagement_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # (likes + comments) / views
    age_adjusted_performance: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    
    # Collection metadata
    collected_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    features_extracted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    
    __table_args__ = (
        Index("idx_video_channel", "channel_id"),
        Index("idx_video_published", "published_at"),
        Index("idx_video_views", "view_count"),
        Index("idx_video_performance", "performance_ratio"),
    )
    
    def __repr__(self) -> str:
        return f"<Video {self.video_id}: {self.title[:50]}>"
    
    @property
    def url(self) -> str:
        """Get the video's YouTube URL."""
        return f"https://www.youtube.com/watch?v={self.video_id}"
    
    @property
    def age_days(self) -> float:
        """Get the age of the video in days."""
        return (datetime.utcnow() - self.published_at).total_seconds() / 86400


class APIKeyUsage(Base):
    """
    Track API key usage for quota management.
    
    YouTube API has 10K units/day quota per key.
    """
    __tablename__ = "api_key_usage"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    key_index: Mapped[int] = mapped_column(Integer, nullable=False)
    date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    units_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    
    __table_args__ = (
        UniqueConstraint("key_index", "date", name="uq_key_date"),
        Index("idx_key_date", "key_index", "date"),
    )


class VideoFeatures(Base):
    """
    Extracted features for ML training.
    
    Week 3-4: Benchmark Feature Extraction
    - Thumbnail features (image analysis)
    - Title features (text analysis)
    - Metadata features
    """
    __tablename__ = "video_features"
    
    # Primary key
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    video_id: Mapped[str] = mapped_column(String(11), unique=True, nullable=False, index=True)
    
    # ===== THUMBNAIL FEATURES =====
    # Face detection
    face_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    face_area_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # Face area / total area
    has_face: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    
    # Text detection
    has_text: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    text_word_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    text_area_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    text_readability: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    
    # Color analysis
    dominant_color_1: Mapped[Optional[str]] = mapped_column(String(7), nullable=True)  # Hex color
    dominant_color_2: Mapped[Optional[str]] = mapped_column(String(7), nullable=True)
    dominant_color_3: Mapped[Optional[str]] = mapped_column(String(7), nullable=True)
    brightness: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # 0-1
    saturation: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # 0-1
    contrast: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # 0-1
    
    # Composition
    visual_complexity: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # 0-1
    edge_density: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # 0-1
    composition_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # Rule of thirds, 0-1
    
    # Enhanced composition (rule of thirds)
    rule_of_thirds_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # 0-1
    focal_point_x: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # 0-1 normalized
    focal_point_y: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # 0-1 normalized
    focal_point_quadrant: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # top-left, center, etc
    on_power_point: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)  # near thirds intersection
    
    # Point-in-time channel trends (calculated at upload time, no data leakage)
    channel_momentum_at_upload: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    channel_engagement_trend_at_upload: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    channel_hit_rate_at_upload: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    channel_recent_avg_ratio_at_upload: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    
    # Face emotions (requires DeepFace)
    face_emotion_primary: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # happy, sad, angry, etc
    face_emotion_intensity: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # 0-1
    
    # ===== TITLE FEATURES =====
    title_char_length: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    title_word_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    title_has_number: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    title_number_position: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)  # start/middle/end
    title_has_question: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    title_has_exclamation: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    title_has_brackets: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    title_caps_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # 0-1
    title_hook_type: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)  # how-to, listicle, etc.
    title_emotional_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # -1 to 1
    title_sentiment: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # -1 to 1
    title_trending_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # Keyword relevance to trending, 0-1
    title_specificity_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # How specific vs vague, 0-1
    
    # ===== METADATA FEATURES =====
    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    duration_category_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # vs category avg
    posting_day_of_week: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # 0-6 (Mon-Sun)
    posting_hour: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # 0-23
    tags_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    
    # Processing metadata
    extracted_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    thumbnail_processed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    title_processed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    
    __table_args__ = (
        Index("idx_features_video", "video_id"),
        Index("idx_features_hook", "title_hook_type"),
    )


class TrackedChannel(Base):
    """
    Channels being tracked for temporal data collection.
    
    Part 4: Temporal Training Set Collection
    - Active channels (2+ videos in last 30 days)
    - Monitored daily for new uploads
    """
    __tablename__ = "tracked_channels"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel_id: Mapped[str] = mapped_column(String(24), unique=True, nullable=False, index=True)
    
    # Activity metrics at time of selection
    recent_video_count: Mapped[int] = mapped_column(Integer, nullable=False)  # Videos in last 30 days
    avg_upload_frequency_days: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    
    # Tracking status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_checked: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_video_found: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    # Metadata
    added_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    source: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, default=None)  # 'user' or 'auto'
    # Stratification (spec: docs/specs/stratified-expansion.md). subscriber_count
    # is enriched via get_channel_details; category is derived from the modal
    # youtube_category_id of the channel's tracked videos (no API call).
    subscriber_count: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(8), nullable=True, index=True)
    size_tier: Mapped[Optional[str]] = mapped_column(String(8), nullable=True, index=True)  # nano|micro|mid|large
    enrolled_via: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # chart|search|graph|user

    __table_args__ = (
        Index("idx_tracked_active", "is_active"),
        Index("idx_tracked_last_checked", "last_checked"),
    )


class TrackedVideo(Base):
    """
    Videos being tracked over time for performance prediction.
    
    Each new video from tracked channels gets added here.
    Performance is measured at: 1h, 6h, 24h, 3d, 7d, 14d, 30d
    """
    __tablename__ = "tracked_videos"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    video_id: Mapped[str] = mapped_column(String(11), unique=True, nullable=False, index=True)
    channel_id: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    
    # Video metadata (captured at discovery)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    thumbnail_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    
    # Tracking status
    tracking_started: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    tracking_complete: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    
    # Checkpoint flags
    checkpoint_1h: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    checkpoint_6h: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    checkpoint_24h: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    checkpoint_3d: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    checkpoint_7d: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    checkpoint_14d: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    checkpoint_30d: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    
    # Final metrics (after 30 days)
    final_views: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    final_likes: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    final_comments: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    
    __table_args__ = (
        Index("idx_tracked_video_channel", "channel_id"),
        Index("idx_tracked_video_published", "published_at"),
        Index("idx_tracked_video_complete", "tracking_complete"),
    )


class VideoSnapshot(Base):
    """
    Performance snapshot at a specific checkpoint.
    
    Captures views, likes, comments at each measurement point.
    Used to train early-performance prediction models.
    """
    __tablename__ = "video_snapshots"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    video_id: Mapped[str] = mapped_column(String(11), nullable=False, index=True)
    
    # Checkpoint identifier
    checkpoint: Mapped[str] = mapped_column(String(10), nullable=False)  # 1h, 6h, 24h, 3d, 7d, 14d, 30d
    hours_since_publish: Mapped[float] = mapped_column(Float, nullable=False)
    
    # Metrics at checkpoint
    view_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    like_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    comment_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    
    # Derived metrics
    views_per_hour: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    engagement_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Normalized early-engagement signals — best leading indicators of a breakout.
    like_view_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    comment_view_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Metadata snapshot (Phase 7.1). Captured per-checkpoint so we can detect
    # title/thumbnail swaps over a video's life (natural A/B experiments) and
    # separate Shorts from long-form. These come free in the videos.list call
    # the collector already makes.
    title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    thumbnail_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    youtube_category_id: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    tag_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    is_short: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)

    # Phase 8.5 capture-now additions — same videos.list call, previously
    # discarded. description (first ~1000 chars) → chapters/links/hashtags +
    # edit detection; tags (JSON array) → topic signal (8.2); live/premiere
    # videos follow different curves and contaminate training unlabeled.
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tags: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON list
    live_broadcast_content: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    default_audio_language: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)

    # Timestamp
    captured_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    
    __table_args__ = (
        Index("idx_snapshot_video_checkpoint", "video_id", "checkpoint"),
        UniqueConstraint("video_id", "checkpoint", name="uq_video_checkpoint"),
    )


class VideoComment(Base):
    """Phase 7.2: a sample of top comments captured ~24h after a tracked video
    publishes. Powers comment intelligence (viewer intent / FAQ / next-video
    ideas) and is a leading-signal source. One row per (video_id, comment_id)."""

    __tablename__ = "video_comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    video_id: Mapped[str] = mapped_column(String(11), nullable=False, index=True)
    comment_id: Mapped[str] = mapped_column(String(64), nullable=False)
    author_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    author_channel_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    like_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reply_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("video_id", "comment_id", name="uq_video_comment"),
    )


class TopicCluster(Base):
    """Phase 8.2: a topic cluster from recent tracked uploads (saturation index).

    One batch per ``computed_at`` (the 6-hourly job); each row is a topic =
    cluster of similar titles in the trailing window. ``size``/``channel_count``
    are the saturation signal; history across batches gives topic velocity.
    """

    __tablename__ = "topic_clusters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    window_hours: Mapped[float] = mapped_column(Float, nullable=False, default=48.0)
    label: Mapped[str] = mapped_column(String(500), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    total_views: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    channel_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    example_titles: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON
    video_ids: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON


class TopicMomentum(Base):
    """Phase 2.1: per-topic *breakout density* over time — the honest market-timing
    signal. Where ``TopicCluster`` measures upload supply (saturation), this measures
    how often a topic's videos are actually breaking out right now (demand), and
    whether that rate is rising/peaking/fading vs the prior snapshot. Not a packaging
    predictor — a descriptive read on which topics audiences are rewarding.
    """

    __tablename__ = "topic_momentum"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    window_hours: Mapped[float] = mapped_column(Float, nullable=False, default=48.0)
    label: Mapped[str] = mapped_column(String(500), nullable=False)
    topic_size: Mapped[int] = mapped_column(Integer, nullable=False)
    breakout_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    breakout_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    total_views: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    channel_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    trend: Mapped[str] = mapped_column(String(20), nullable=False, default="new")
    prev_breakout_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    example_titles: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON
    video_ids: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON


class OwnerVideoAnalytics(Base):
    """Phase 3.2 (display half): real owner-side analytics for a connected
    channel's video — pulled from the YouTube Analytics API with the user's OAuth.

    This is the *real* CTR + retention (not the dead packaging proxy): impressions,
    click-through rate, average view %, and the audience-retention curve. Stored
    as display data; the gated prediction model that trains on this is deferred
    until enough owner-CTR data accrues and the channel-grouped re-validation
    passes. One row per (user, video), upserted on each pull.
    """

    __tablename__ = "owner_video_analytics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    channel_id: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    video_id: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    title: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    views: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    impressions: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    ctr: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)  # 0-1
    avg_view_percentage: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    avg_view_duration_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    retention_curve: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON list

    __table_args__ = (
        UniqueConstraint("user_id", "video_id", name="uq_owner_video"),
    )


class NicheBenchmark(Base):
    """Measured view-trajectory percentiles per (niche, format, checkpoint).

    Replaces the old /benchmarks endpoint, which served invented constants
    (``pct_with_face: 78``, ``optimal_upload_hour: 14``) whenever its lookup
    failed. These rows are pure description of collected snapshots: at each
    checkpoint, what view counts the 10th..99th percentile video actually hit.
    Shorts and long-form are kept separate because their curves differ by an
    order of magnitude, and mixing them makes every percentile meaningless.

    Answers "how is my video doing, really?" with a measurement rather than a
    prediction — the same honest framing as detection and durability.
    """

    __tablename__ = "niche_benchmarks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    # YouTube category id ("20" = Gaming). NULL = all niches pooled.
    niche: Mapped[Optional[str]] = mapped_column(String(8), nullable=True, index=True)
    is_short: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    checkpoint: Mapped[str] = mapped_column(String(8), nullable=False)
    n_videos: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    p10: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    p25: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    p50: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    p75: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    p90: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    p95: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    p99: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    __table_args__ = (
        Index("idx_niche_benchmark_lookup", "niche", "is_short", "checkpoint"),
    )


class TimingBenchmark(Base):
    """Measured publish-timing hit rates per (dimension, bucket, niche, format).

    "Hit" = a video landing in the top 20% of its OWN channel by 24h views, so
    channel size cannot confound the comparison. ``dimension`` is 'hour' (0-23,
    UTC) or 'dow' (0=Sunday). Replaces the invented ``optimal_upload_hour: 14``
    the old benchmarks endpoint served; the real effect is ~5 points of spread,
    correlational, and much smaller than the usual "best time to post" claims.
    """

    __tablename__ = "timing_benchmarks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    dimension: Mapped[str] = mapped_column(String(8), nullable=False)  # hour | dow
    bucket: Mapped[int] = mapped_column(Integer, nullable=False)
    niche: Mapped[Optional[str]] = mapped_column(String(8), nullable=True, index=True)
    is_short: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    n_videos: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    hit_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    __table_args__ = (
        Index("idx_timing_benchmark_lookup", "dimension", "niche", "is_short"),
    )


class EmergingFormat(Base):
    """A title/packaging format mined from live breakouts (Format Radar).

    Unlike a static template archive, each row is recomputed daily over a rolling
    window of *breakout* videos. ``momentum`` (recent vs prior occurrences) and
    ``openness`` (how many distinct channels are on it) are the live signals that
    a static index can't produce — the whole point. One row per (slug, niche).
    """

    __tablename__ = "emerging_formats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    template: Mapped[str] = mapped_column(String(300), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    psychology_type: Mapped[str] = mapped_column(String(40), nullable=False, default="Pattern")
    niche: Mapped[Optional[str]] = mapped_column(String(60), nullable=True, index=True)  # category id; null=global
    # metrics
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    avg_outlier: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    median_outlier: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    avg_views: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    momentum: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    unique_channels: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    openness: Mapped[str] = mapped_column(String(12), nullable=False, default="open")  # open|warming|crowded
    reliability: Mapped[str] = mapped_column(String(8), nullable=False, default="low")  # high|medium|low
    examples: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON: top examples
    window_days: Mapped[int] = mapped_column(Integer, nullable=False, default=45)
    computed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)

    __table_args__ = (
        UniqueConstraint("slug", "niche", name="uq_emerging_format_slug_niche"),
    )


class NicheCoverage(Base):
    """Per-niche tracking coverage (spec: docs/specs/stratified-expansion.md).

    One row per niche per daily compute. Tells us — niche by niche, not globally —
    whether we track enough to surface live signal: channel count + tier mix vs a
    target, recent breakout volume, and active Format Radar patterns. ``starved``
    drives the next stratified-expansion sweep.
    """

    __tablename__ = "niche_coverage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    niche: Mapped[str] = mapped_column(String(8), nullable=False, index=True)  # category id
    tracked_channels: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tier_mix: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON {nano,micro,mid,large}
    breakouts_7d: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active_formats: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    target_channels: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deficit: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    starved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)


class WebSubSubscription(Base):
    """WebSub lease state per tracked channel (plan 7.5).

    YouTube's hub grants leases up to ~10 days; the renewal job re-subscribes
    channels whose lease is near expiry. ``last_notified_at`` doubles as the
    health signal (a channel that uploads but never notifies = broken sub).
    """

    __tablename__ = "websub_subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel_id: Mapped[str] = mapped_column(String(24), unique=True, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="pending")  # pending|verified|failed
    lease_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_subscribed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_notified_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    notification_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class VideoHeatmap(Base):
    """Phase 8.1: the public "Most Replayed" heatmap — a retention-shape proxy.

    ~100 normalized points per video showing where viewers rewatch vs bail; the
    closest publicly-available thing to owner-private retention curves. Appears
    only once a video is ~1-2 weeks old (verified 2026-06-12: present on every
    probed video >=13d, absent at 3d), so capture is scheduled off the 14d
    checkpoint with one retry after 30d. One row per video; ``has_heatmap``
    False records an exhausted probe so we don't re-fetch forever.
    """

    __tablename__ = "video_heatmaps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    video_id: Mapped[str] = mapped_column(String(11), unique=True, nullable=False, index=True)
    has_heatmap: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    points: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON [{start_time,end_time,value}]
    n_points: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    video_duration_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Opening transcript (first ~60s) from the caption tracks the same yt-dlp
    # probe exposes — zero API quota, no OAuth. Feeds the hook analyzer,
    # breakout explainers, and transcript-level topic clustering.
    opening_transcript: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    transcript_lang: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    transcript_source: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)  # manual|auto
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


class YouTubeQuotaUsage(Base):
    """Durable YouTube API quota accounting (observability).

    The in-process :class:`~src.youtube.quota.QuotaManager` only counts usage
    in memory, so it's wiped on every restart and can't be inspected from
    outside the process — meaning "are our jobs running out of quota?" was
    unanswerable. This table is the source of truth: each process flushes its
    accumulated usage here (increment-on-conflict) keyed by
    ``(usage_date, key_index, operation)``, so the per-day total is accurate
    across restarts and across processes.

    ``usage_date`` is an ISO ``YYYY-MM-DD`` string (UTC) — exact-match grouping,
    no dialect date-type quirks. One row per key per operation per day.
    """

    __tablename__ = "youtube_quota_usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    usage_date: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    key_index: Mapped[int] = mapped_column(Integer, nullable=False)
    operation: Mapped[str] = mapped_column(String(32), nullable=False)
    units: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("usage_date", "key_index", "operation", name="uq_quota_usage"),
    )


class Niche(Base):
    """
    Micro-niche cluster for comparing similar channels.
    
    Examples:
    - Gaming > FPS > Valorant > Commentary
    - Education > Science > Physics > Explainers
    - Lifestyle > Cooking > Quick Recipes
    """
    __tablename__ = "niches"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    # Niche identification
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    
    # Keywords that define this niche (comma-separated)
    keywords: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Statistics
    channel_count: Mapped[int] = mapped_column(Integer, default=0)
    avg_subscribers: Mapped[float] = mapped_column(Float, default=0)
    
    # Benchmark metrics (calculated from member channels)
    avg_views_per_video: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    avg_engagement_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    avg_video_duration: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    avg_upload_frequency: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    
    # Thumbnail benchmarks
    avg_face_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    avg_text_in_thumbnail: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    dominant_colors: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    
    # Title benchmarks
    avg_title_length: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    common_hook_types: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    
    # Description
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (
        Index("idx_niche_category", "category"),
    )
    
    def __repr__(self) -> str:
        return f"<Niche {self.name} ({self.channel_count} channels)>"


class VideoContentAnalysis(Base):
    """
    Features extracted from actual video content (not just metadata).
    
    Requires downloading and analyzing video files.
    Stored in R2 for reference.
    """
    __tablename__ = "video_content_analysis"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    video_id: Mapped[str] = mapped_column(String(11), unique=True, nullable=False, index=True)
    
    # R2 storage references
    r2_video_key: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    r2_audio_key: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    
    # ===== HOOK FEATURES (First 10-30 seconds) =====
    hook_face_appears_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    hook_text_appears_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    hook_scene_changes_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    hook_avg_motion: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    hook_words_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # Engaging words in first 10s
    
    # ===== VISUAL PACING =====
    total_scene_changes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    avg_scene_duration: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    scene_change_variance: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    
    # ===== VISUAL QUALITY =====
    avg_brightness: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    brightness_variance: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    avg_sharpness: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    
    # ===== FACE PRESENCE =====
    face_screen_time_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    face_size_consistency: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    
    # ===== AUDIO FEATURES =====
    audio_energy_mean: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    audio_energy_variance: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    audio_tempo: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # BPM
    loudness_range: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    energy_ramp_up: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    has_music_intro: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    intro_duration_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    
    # ===== TRANSCRIPT FEATURES =====
    transcript_word_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    words_per_minute: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    question_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    call_to_action_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    transcript_sentiment: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    
    # Full transcript (for advanced analysis)
    transcript: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # ===== PROCESSING METADATA =====
    video_duration_analyzed: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # How many seconds analyzed
    extracted_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    extraction_success: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    extraction_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    __table_args__ = (
        Index("idx_content_video", "video_id"),
        Index("idx_content_success", "extraction_success"),
    )


# ============================================================
# DISTRIBUTION HUB MODELS
# ============================================================

class ConnectedAccount(Base):
    """
    A social media account connected to a user for multi-account distribution.
    
    Supports multiple platforms (YouTube, TikTok, Instagram, Twitter/X) and
    multiple accounts per platform per user (e.g., 5 burner Instagram accounts
    for clipping workflows).
    """
    __tablename__ = "connected_accounts"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    
    platform: Mapped[str] = mapped_column(String(20), nullable=False, index=True)  # youtube | tiktok | instagram | twitter
    platform_account_id: Mapped[str] = mapped_column(String(255), nullable=False)  # remote ID (channel_id, user_id)
    handle: Mapped[str] = mapped_column(String(100), nullable=False)  # display @handle
    display_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    avatar_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    
    # OAuth credentials (encrypted at rest via Fernet)
    access_token_encrypted: Mapped[str] = mapped_column("access_token", Text, nullable=False)
    refresh_token_encrypted: Mapped[Optional[str]] = mapped_column("refresh_token", Text, nullable=True)
    token_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    scopes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON array
    
    # Account metadata
    follower_count: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    
    # Settings
    auto_publish: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    default_caption_variation: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    
    # Timestamps
    connected_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    __table_args__ = (
        UniqueConstraint("user_id", "platform", "platform_account_id", name="uq_user_platform_account"),
        Index("idx_connected_user_platform", "user_id", "platform"),
        Index("idx_connected_active", "user_id", "is_active"),
    )
    
    def __repr__(self) -> str:
        return f"<ConnectedAccount {self.platform}:@{self.handle}>"
    
    # Encrypted accessors
    access_token = _encrypted_property("access_token_encrypted")
    refresh_token = _encrypted_property("refresh_token_encrypted")


class DistributionJob(Base):
    """
    A job to distribute one piece of content (video/clip) to N accounts.
    
    A single click on "distribute to all" creates one DistributionJob plus N
    DistributionResult rows (one per target account).
    """
    __tablename__ = "distribution_jobs"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    
    # Content metadata
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    base_caption: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    video_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)  # External (R2/S3) or local URL
    video_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)  # Local path used for upload
    thumbnail_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    
    # Source video info (if from a clip)
    source_video_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    clip_start_sec: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    clip_end_sec: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    
    # Status
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)  # pending | running | completed | failed | partial
    target_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    success_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failure_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    
    # Settings used for this job
    vary_captions: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    __table_args__ = (
        Index("idx_distribution_user_created", "user_id", "created_at"),
        Index("idx_distribution_status", "status"),
    )


class DistributionResult(Base):
    """
    Per-account result for one DistributionJob.
    """
    __tablename__ = "distribution_results"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    account_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    
    # Status
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)  # pending | running | success | failed
    platform: Mapped[str] = mapped_column(String(20), nullable=False)
    
    # Output
    posted_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)  # Public link to the posted content
    posted_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)  # Remote post ID
    caption_used: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Error info
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    __table_args__ = (
        Index("idx_dist_result_job", "job_id"),
        Index("idx_dist_result_account", "account_id"),
    )


class PublishedMetricSnapshot(Base):
    """One point-in-time view of a published post's performance (Week 10).

    Each row captures the cumulative metrics (views, likes, comments,
    shares, watch_time_seconds, ctr, retention) for a single
    ``DistributionResult`` (i.e. one post to one platform) at a single
    sample window. The collector targets fixed windows — ``1h``,
    ``24h``, ``7d``, ``30d`` — so the dashboard can show "vs. T+24h
    baseline" comparisons without resampling the raw timeseries.

    Why one row per (result, window) instead of one growing JSON blob:

      * lets a missed window (worker outage, API rate-limited) gap
        gracefully — the next collection still writes the next window
        instead of having to backfill a JSON path
      * Postgres indexes ``(distribution_result_id, window_key)``
        make per-post lookups cheap even with millions of rows
      * exposes the timeseries to ad-hoc SQL for future analytics
        without inventing a JSON-traversal pattern

    The ``raw`` JSON column holds the unmodified platform response so
    we can re-derive any new metric later without re-querying.
    """
    __tablename__ = "published_metric_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    distribution_result_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("distribution_results.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    platform: Mapped[str] = mapped_column(String(20), nullable=False)
    posted_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Sample window: see ``src.features.publish_metrics.WINDOWS``. One
    # row per (result, window) — re-running the collector for the
    # same window UPSERTs into the same row.
    window_key: Mapped[str] = mapped_column(String(8), nullable=False)
    # When the post was published (mirrored from the DistributionResult
    # for cheap windowed queries without a join).
    published_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    # When the metrics in this row were captured.
    sampled_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    # The metrics themselves. All nullable because not every platform
    # exposes every metric (Instagram doesn't share retention, etc.)
    # and a partial sample is still useful.
    views: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    likes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    comments: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    shares: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    watch_time_seconds: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    avg_view_percentage: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    click_through_rate: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )

    # Unmodified platform response — keeps the door open for adding
    # new derived metrics without re-fetching history.
    raw: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        # Uniqueness is enforced at the application layer (UPSERT in
        # ``record_metric_snapshot``); we keep this as a regular
        # composite index instead of UNIQUE so a partial-sample retry
        # doesn't trip on a race with the next-window write.
        Index(
            "idx_pms_result_window", "distribution_result_id", "window_key"
        ),
        Index("idx_pms_user_sampled", "user_id", "sampled_at"),
        Index("idx_pms_platform_published", "platform", "published_at"),
    )


# ============================================================
# OBSERVABILITY / SPEND CONTROL / AUDIT
# ============================================================

class LLMUsageRecord(Base):
    """One row per LLM call. Used to enforce per-user daily $ budgets."""
    __tablename__ = "llm_usage_records"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    
    provider: Mapped[str] = mapped_column(String(32), nullable=False)  # anthropic | groq
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    feature: Mapped[str] = mapped_column(String(64), nullable=False, index=True)  # title_gen, hook_score, ...
    
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    
    success: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    
    __table_args__ = (
        Index("idx_llm_user_date", "user_id", "created_at"),
        Index("idx_llm_feature_date", "feature", "created_at"),
    )


class AuditEvent(Base):
    """Append-only security/audit log."""
    __tablename__ = "audit_events"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # login_success, login_failed, signup, password_reset, oauth_connect,
    # oauth_disconnect, plan_change, token_refresh, account_locked, ...
    
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    
    __table_args__ = (
        Index("idx_audit_user_date", "user_id", "created_at"),
        Index("idx_audit_event_date", "event_type", "created_at"),
    )


# ============================================================
# STUDIO / EDITOR MODELS
# ============================================================

class EditSession(Base):
    """A user's edit state for a single clip in the Studio editor.

    A single canonical JSON ``spec`` drives BOTH the in-browser Remotion
    preview AND the server-side ffmpeg/Remotion render — single source of
    truth so what users see is what they get. See ``src/features/studio``
    for the spec schema.
    """
    __tablename__ = "edit_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Source-clip identity. ``clip_key`` is a stable opaque id the frontend
    # generates (sha256 of source_url+start+end) so we can resume edits across
    # sessions without exposing internal IDs.
    clip_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_video_url: Mapped[str] = mapped_column(String(500), nullable=False)
    source_clip_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_clip_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    source_start_time: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    source_end_time: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Display title shown in the user's Studio drafts list
    title: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Full editor spec (caption style, aspect, B-roll picks, transcript edits,
    # brand kit, template, etc). JSON encoded as Text to match the project's
    # storage convention (works equally well on Postgres + SQLite tests).
    spec: Mapped[str] = mapped_column(Text, nullable=False, default="{}")

    # CTA provenance (Week 10): if the user landed in Studio via a
    # cross-tool deep link carrying a recommendation context
    # (``?cta=hook_lab&reason=start_bottleneck``), the frontend posts
    # that envelope here on session create. When the resulting render
    # is published and metrics flow back, we attribute the post-publish
    # performance to the originating recommendation so the dashboard
    # can answer "did acting on the Lead Magnet advice actually help?".
    # JSON-encoded dict; ``None`` for sessions opened directly.
    cta_provenance: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Last render status & output
    last_render_job_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    last_render_status: Mapped[str] = mapped_column(String(32), default="idle", nullable=False)
    # idle | queued | rendering | done | failed
    last_render_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    last_render_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_rendered_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # Live progress for the polling UI (0..100); paired with a short human-readable
    # message ("Downloading source", "Encoding 42%", ...). Both nullable so older
    # rows + idle sessions are fine.
    render_progress: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    render_progress_message: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    # Cached audio waveform peaks for the timeline. Stored as JSON-encoded
    # list of floats in [0,1]. Recomputed whenever the cached peaks_bins
    # doesn't match the requested resolution or the cached times don't match
    # the spec's current clip.start_time/end_time.
    peaks_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    peaks_bins: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    peaks_start_time: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    peaks_end_time: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Cached multi-subject tracking for the Camera lane (Week 4).
    # tracking_json shape:
    #   {"fps": float, "frame_w": int, "frame_h": int,
    #    "subjects": [{"id": int, "label": str, "color_hex": str,
    #                  "smoothed_crop_x": [int, ...],
    #                  "frames": [{"t": float, "x": int, "y": int,
    #                              "w": int, "h": int, "conf": float}, ...]}]}
    # Cache key = (tracking_subjects_n, tracking_start_time, tracking_end_time);
    # any mismatch (different N requested, clip trimmed) triggers recompute.
    tracking_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tracking_subjects_n: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    tracking_status: Mapped[str] = mapped_column(
        String(20), default="idle", nullable=False
    )
    tracking_progress: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    tracking_progress_message: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    tracking_start_time: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    tracking_end_time: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("user_id", "clip_key", name="uq_edit_session_user_clip"),
        Index("idx_edit_session_user_updated", "user_id", "updated_at"),
    )

    def __repr__(self) -> str:
        return f"<EditSession user={self.user_id} clip={self.clip_key[:8]} status={self.last_render_status}>"


class UserBrandKit(Base):
    """A user's reusable brand kit (logo + colors + font) auto-applied to
    every Studio render.

    One row per user. Mirrors the ``BrandKit`` Pydantic model in
    :mod:`src.features.studio.spec` exactly so the JSON cast in either
    direction is trivial. The logo lives in R2 — ``logo_r2_key`` is the
    canonical reference (we use it to re-presign or delete on overwrite)
    and ``logo_url`` is a denormalized public URL for the frontend.
    """
    __tablename__ = "user_brand_kits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )

    # Logo storage. ``logo_r2_key`` is the durable handle; ``logo_url`` is
    # the public URL the frontend / renderer fetches (presigned for 7 days
    # in dev when no public CDN is configured).
    logo_url: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    logo_r2_key: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    logo_position: Mapped[str] = mapped_column(String(2), default="br", nullable=False)
    logo_opacity: Mapped[float] = mapped_column(Float, default=0.85, nullable=False)

    primary_color: Mapped[Optional[str]] = mapped_column(String(7), nullable=True)
    accent_color: Mapped[Optional[str]] = mapped_column(String(7), nullable=True)
    font_family: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)

    # Brand *voice* — the things Distribution applies to every publish
    # so the user doesn't have to retype their sign-off and hashtags
    # for every platform. Together with the visual fields above, this
    # completes the "brand kit auto-applies through the whole loop"
    # story (and finishes the third leg of the deep-integration moat).
    #
    # ``caption_signature`` is the user's stock sign-off, e.g.
    #   "— Reps Daily · Subscribe for more 💪"
    # appended to the base caption before publish. Kept as a single
    # TEXT field so creators can use line breaks / emoji / links.
    #
    # ``default_hashtags`` is a comma-separated list of hashtags
    # always merged into the publish (deduped against whatever the
    # user typed in the caption box).
    caption_signature: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    default_hashtags: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    def __repr__(self) -> str:
        return f"<UserBrandKit user={self.user_id} logo={'y' if self.logo_url else 'n'}>"


class UserRenderUsage(Base):
    """Per-month render-minute accounting (Week 8).

    One row per ``(user_id, month_start)``. ``month_start`` is always the
    first instant of a UTC calendar month so rollover is just "create
    a fresh row on the 1st"; old rows stay around so the Renders page
    can show a usage history.

    Free plan = 30 minutes/month (see
    :mod:`src.features.billing.render_budget` for the plan table); Pro
    + Enterprise are unlimited and never insert rows here (the budget
    helper short-circuits on infinite plans).
    """
    __tablename__ = "user_render_usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Always the first instant of a UTC month (year, month, 1, 00:00:00).
    # Combined with user_id this is the unique key for the period.
    month_start: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    # Cumulative render minutes used in this period. Float because
    # individual renders can be fractional (15-second short = 0.25).
    minutes_used: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id", "month_start", name="uq_user_render_usage_period"
        ),
        Index("idx_user_render_usage_user_month", "user_id", "month_start"),
    )

    def __repr__(self) -> str:
        return (
            f"<UserRenderUsage user={self.user_id} "
            f"month={self.month_start.date()} used={self.minutes_used:.2f}>"
        )


class StudioProject(Base):
    """A long-form Studio project: an ordered list of ``EditSession`` clips
    stitched into a single render.

    Each clip in a project still has its full per-clip feature set (captions,
    B-roll, transitions, brand kit, camera lane) because clips are FKs to
    existing ``EditSession`` rows, not duplicates. The project just owns the
    ordering, the project-wide defaults (aspect, transition, brand kit), and
    the stitched output. See :mod:`src.features.studio.project_spec` for the
    Pydantic shape and ``src/features/studio/render_project.py`` for the
    render job.

    A clip can belong to multiple projects (we don't copy ``EditSession``s);
    re-rendering an underlying session invalidates the project's render
    cache via ``EditSession.updated_at`` comparison.
    """
    __tablename__ = "studio_projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Display + defaults that cascade to new clips. ``default_aspect`` is
    # the project's canonical aspect; the render job forces every clip
    # to this aspect so the stitched output has consistent dimensions
    # (a 9:16 clip stitched with a 16:9 clip would otherwise letterbox
    # in ways the user didn't ask for).
    title: Mapped[str] = mapped_column(String(500), nullable=False, default="Untitled project")
    # Long-form description used as the seed caption/post body when the
    # creator hands a rendered project off to the Distribution Hub
    # (Week 9 Connected Tools). Optional — older projects predate the
    # field and just fall back to the title.
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    default_aspect: Mapped[str] = mapped_column(String(8), nullable=False, default="9:16")

    # Project-level transition default — applied between consecutive clips
    # whenever a clip doesn't have its own ``transition_in_type`` set.
    default_transition_type: Mapped[str] = mapped_column(String(32), nullable=False, default="cut")
    default_transition_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=300)

    # Project-level Brand Kit overlay (serialized as JSON, matches the
    # Pydantic ``BrandKit`` shape so the renderer can load it directly).
    # Applied as the *final* overlay across the stitched output so the
    # logo lower-third stays consistent across all clips regardless of
    # per-clip brand kits.
    brand_kit_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Render state — same vocabulary as ``EditSession`` so the polling
    # endpoint logic is shared.
    last_render_job_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    last_render_status: Mapped[str] = mapped_column(String(32), default="idle", nullable=False)
    # idle | queued | rendering | done | failed
    last_render_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    last_render_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_rendered_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    render_progress: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    render_progress_message: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    __table_args__ = (
        Index("idx_studio_project_user_updated", "user_id", "updated_at"),
    )

    def __repr__(self) -> str:
        return f"<StudioProject user={self.user_id} title={self.title[:24]!r} status={self.last_render_status}>"


class StudioProjectClip(Base):
    """One ordered clip inside a :class:`StudioProject`.

    The ``position`` column is the canonical ordering — drag-to-reorder in
    the UI translates to renumbering this field. Ripple-delete renumbers
    the rows after the deleted one so positions are always a contiguous
    0-indexed sequence (the API enforces this; the unique index catches
    accidental races).

    ``trim_in_seconds`` / ``trim_out_seconds`` are an *additional* trim
    applied at project-stitch time on top of the underlying
    ``EditSession``'s own ``source_start_time`` / ``source_end_time``.
    This lets the user re-trim a clip for the project without mutating
    the underlying session (which might be referenced by other
    projects).

    ``transition_in_type`` / ``transition_in_ms`` are the transition
    applied *into* this clip (from the previous one). The first clip
    in a project ignores these (it has no predecessor). ``None`` falls
    back to the project's ``default_transition_*``.
    """
    __tablename__ = "studio_project_clips"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("studio_projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    edit_session_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("edit_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    position: Mapped[int] = mapped_column(Integer, nullable=False)
    trim_in_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    trim_out_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    transition_in_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    transition_in_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # When the project last rendered using this clip's underlying
    # session output — used by the project render job to decide
    # whether to re-render the clip or reuse its cached MP4.
    last_used_session_render_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("project_id", "position", name="uq_studio_project_clip_position"),
        Index("idx_studio_project_clip_project_position", "project_id", "position"),
    )

    def __repr__(self) -> str:
        return f"<StudioProjectClip project={self.project_id} pos={self.position} session={self.edit_session_id}>"


class BackfillVideo(Base):
    """Cross-sectional training row rebuilt from a channel's upload history.

    The historical scrape/time-series was lost (memory/ml-data-disconnected.md);
    this table reconstructs a fresh labelled dataset from the live API — one row
    per backfilled video, with the label being the video's ``outlier`` (final
    views vs the channel's own median, in log space). Channel-grouped by
    ``channel_id`` so model scripts can split without per-channel leakage.

    Idempotent: ``video_id`` is unique; a channel is "done" once it has rows.
    """
    __tablename__ = "backfill_videos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    video_id: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    channel_id: Mapped[str] = mapped_column(String(30), nullable=False, index=True)

    title: Mapped[str] = mapped_column(Text, nullable=False)
    thumbnail_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tags: Mapped[Optional[str]] = mapped_column(Text, nullable=True)            # JSON list
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    is_short: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    youtube_category_id: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    default_audio_language: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)

    view_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    like_count: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    comment_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Label: views relative to the channel's own median (removes channel scale).
    channel_median_views: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    outlier: Mapped[Optional[float]] = mapped_column(Float, nullable=True)        # views / median
    log_outlier: Mapped[Optional[float]] = mapped_column(Float, nullable=True)    # ln(outlier)

    collected_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<BackfillVideo {self.video_id} ch={self.channel_id} outlier={self.outlier}>"


class WatchlistChannel(Base):
    """A public channel a user is watching for breakouts (competitive intel).

    The product's wedge: detection works on ANY public channel (Studio is your-
    channel-only). Adding one enrolls it into collection (TrackedChannel + WebSub)
    so we sample its uploads going forward; this row is the per-user association.
    """
    __tablename__ = "watchlist_channels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    channel_id: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    channel_title: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    label: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)  # user's note/group
    added_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "channel_id", name="uq_watchlist_user_channel"),
    )

    def __repr__(self) -> str:
        return f"<WatchlistChannel user={self.user_id} channel={self.channel_id}>"


class WatchlistAlertSent(Base):
    """Dedup ledger: which watchlist breakout we've already emailed a user about,
    so the alert job never double-sends for the same video."""
    __tablename__ = "watchlist_alerts_sent"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    video_id: Mapped[str] = mapped_column(String(20), nullable=False)
    channel_id: Mapped[Optional[str]] = mapped_column(String(24), nullable=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "video_id", name="uq_watchlist_alert_user_video"),
    )
