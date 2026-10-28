"""
Social Media Auto-Publishing Module

Integrates with Upload-Post API for one-click publishing to:
- TikTok
- Instagram Reels
- YouTube Shorts

Also supports scheduling and multi-platform publishing.

Upload-Post API: https://upload-post.com
Alternative: direct platform APIs with OAuth
"""

import os
import json
import asyncio
from datetime import datetime
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from enum import Enum
import logging

import httpx

logger = logging.getLogger(__name__)


class Platform(Enum):
    """Supported social media platforms."""
    TIKTOK = "tiktok"
    INSTAGRAM = "instagram"
    YOUTUBE = "youtube"
    ALL = "all"


class PublishStatus(Enum):
    """Status of a publish request."""
    PENDING = "pending"
    UPLOADING = "uploading"
    PROCESSING = "processing"
    PUBLISHED = "published"
    SCHEDULED = "scheduled"
    FAILED = "failed"


@dataclass
class PublishRequest:
    """Request to publish a video to social media."""
    video_path: str
    title: str
    description: str
    platforms: List[Platform]
    
    # Optional metadata
    hashtags: List[str] = field(default_factory=list)
    thumbnail_path: Optional[str] = None
    
    # Scheduling (None = publish immediately)
    scheduled_time: Optional[datetime] = None
    
    # Platform-specific settings
    tiktok_settings: Dict[str, Any] = field(default_factory=dict)
    instagram_settings: Dict[str, Any] = field(default_factory=dict)
    youtube_settings: Dict[str, Any] = field(default_factory=dict)
    
    def get_caption(self, platform: Platform) -> str:
        """Get formatted caption with hashtags for platform."""
        hashtag_str = " ".join(f"#{tag}" for tag in self.hashtags) if self.hashtags else ""
        
        if platform == Platform.TIKTOK:
            # TikTok: title + hashtags (max 2200 chars)
            caption = f"{self.title}\n\n{self.description}" if self.description else self.title
            if hashtag_str:
                caption += f"\n\n{hashtag_str}"
            return caption[:2200]
        
        elif platform == Platform.INSTAGRAM:
            # Instagram: title + description + hashtags (max 2200 chars)
            caption = self.title
            if self.description:
                caption += f"\n\n{self.description}"
            if hashtag_str:
                caption += f"\n\n{hashtag_str}"
            return caption[:2200]
        
        elif platform == Platform.YOUTUBE:
            # YouTube Shorts: title only (max 100 chars), description separate
            return self.title[:100]
        
        return self.title


@dataclass
class PublishResult:
    """Result of a publish attempt."""
    platform: Platform
    status: PublishStatus
    post_id: Optional[str] = None
    post_url: Optional[str] = None
    error_message: Optional[str] = None
    published_at: Optional[datetime] = None
    scheduled_for: Optional[datetime] = None
    
    def to_dict(self) -> Dict:
        return {
            "platform": self.platform.value,
            "status": self.status.value,
            "post_id": self.post_id,
            "post_url": self.post_url,
            "error_message": self.error_message,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "scheduled_for": self.scheduled_for.isoformat() if self.scheduled_for else None,
        }


@dataclass
class MultiPlatformResult:
    """Results from publishing to multiple platforms."""
    request: PublishRequest
    results: List[PublishResult] = field(default_factory=list)
    
    @property
    def all_successful(self) -> bool:
        return all(r.status == PublishStatus.PUBLISHED for r in self.results)
    
    @property
    def any_successful(self) -> bool:
        return any(r.status == PublishStatus.PUBLISHED for r in self.results)
    
    def to_dict(self) -> Dict:
        return {
            "video_path": self.request.video_path,
            "title": self.request.title,
            "platforms_requested": [p.value for p in self.request.platforms],
            "results": [r.to_dict() for r in self.results],
            "all_successful": self.all_successful,
            "any_successful": self.any_successful,
        }


class UploadPostClient:
    """
    Client for Upload-Post API (https://upload-post.com).
    
    Upload-Post provides a unified API for posting to TikTok, Instagram, and YouTube
    with OAuth token management.
    """
    
    BASE_URL = "https://api.upload-post.com/v1"
    
    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize Upload-Post client.
        
        Args:
            api_key: Upload-Post API key (or set UPLOAD_POST_API_KEY env var)
        """
        self.api_key = api_key or os.getenv("UPLOAD_POST_API_KEY")
        if not self.api_key:
            logger.warning("Upload-Post API key not configured")
        
        self._client = None
    
    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.BASE_URL,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=300.0  # 5 min timeout for video uploads
            )
        return self._client
    
    async def close(self):
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
    
    async def get_connected_accounts(self) -> Dict[str, List[Dict]]:
        """
        Get all connected social media accounts.
        
        Returns:
            Dict mapping platform to list of connected accounts
        """
        if not self.api_key:
            raise ValueError("Upload-Post API key not configured")
        
        try:
            response = await self.client.get("/accounts")
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            logger.error(f"Failed to get connected accounts: {e}")
            raise
    
    async def upload_video(
        self,
        video_path: str,
        platform: Platform,
        caption: str,
        account_id: Optional[str] = None,
        thumbnail_path: Optional[str] = None,
        scheduled_time: Optional[datetime] = None,
        **kwargs
    ) -> PublishResult:
        """
        Upload and publish a video to a specific platform.
        
        Args:
            video_path: Path to the video file
            platform: Target platform
            caption: Video caption/title
            account_id: Specific account ID (uses default if not specified)
            thumbnail_path: Optional custom thumbnail
            scheduled_time: Optional scheduling time
            **kwargs: Platform-specific options
        
        Returns:
            PublishResult with status and post details
        """
        if not self.api_key:
            return PublishResult(
                platform=platform,
                status=PublishStatus.FAILED,
                error_message="Upload-Post API key not configured"
            )
        
        try:
            # Prepare multipart form data
            files = {
                "video": (os.path.basename(video_path), open(video_path, "rb"), "video/mp4")
            }
            
            if thumbnail_path and os.path.exists(thumbnail_path):
                files["thumbnail"] = (
                    os.path.basename(thumbnail_path),
                    open(thumbnail_path, "rb"),
                    "image/jpeg"
                )
            
            data = {
                "platform": platform.value,
                "caption": caption,
            }
            
            if account_id:
                data["account_id"] = account_id
            
            if scheduled_time:
                data["scheduled_time"] = scheduled_time.isoformat()
            
            # Add platform-specific options
            data.update(kwargs)
            
            # Upload to Upload-Post API
            response = await self.client.post(
                "/upload",
                data=data,
                files=files
            )
            response.raise_for_status()
            
            result_data = response.json()
            
            return PublishResult(
                platform=platform,
                status=PublishStatus.SCHEDULED if scheduled_time else PublishStatus.PUBLISHED,
                post_id=result_data.get("post_id"),
                post_url=result_data.get("post_url"),
                published_at=datetime.utcnow() if not scheduled_time else None,
                scheduled_for=scheduled_time,
            )
            
        except httpx.HTTPStatusError as e:
            error_detail = e.response.text if e.response else str(e)
            logger.error(f"Upload failed for {platform.value}: {error_detail}")
            return PublishResult(
                platform=platform,
                status=PublishStatus.FAILED,
                error_message=f"API error: {error_detail}"
            )
        except Exception as e:
            logger.error(f"Upload failed for {platform.value}: {e}")
            return PublishResult(
                platform=platform,
                status=PublishStatus.FAILED,
                error_message=str(e)
            )
        finally:
            # Close file handles
            for f in files.values():
                if hasattr(f[1], 'close'):
                    f[1].close()
    
    async def get_post_status(self, post_id: str) -> Dict:
        """
        Check the status of a published/scheduled post.
        
        Args:
            post_id: The post ID from upload response
        
        Returns:
            Dict with post status and details
        """
        if not self.api_key:
            raise ValueError("Upload-Post API key not configured")
        
        try:
            response = await self.client.get(f"/posts/{post_id}")
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            logger.error(f"Failed to get post status: {e}")
            raise


class DirectPlatformPublisher:
    """
    Direct publishing using platform APIs (alternative to Upload-Post).
    
    Requires OAuth tokens for each platform:
    - TikTok: Content Posting API
    - Instagram: Graph API
    - YouTube: Data API v3
    """
    
    def __init__(self):
        self.tiktok_token = os.getenv("TIKTOK_ACCESS_TOKEN")
        self.instagram_token = os.getenv("INSTAGRAM_ACCESS_TOKEN")
        self.instagram_user_id = os.getenv("INSTAGRAM_USER_ID")
        self.youtube_credentials_path = os.getenv("YOUTUBE_OAUTH_CREDENTIALS")
        
        self._http_client = None
    
    @property
    def http_client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=300.0)
        return self._http_client
    
    async def close(self):
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
    
    async def publish_to_tiktok(
        self,
        video_path: str,
        caption: str,
        **kwargs
    ) -> PublishResult:
        """
        Publish video to TikTok using Content Posting API.
        
        Requires TikTok developer app with video.publish scope.
        """
        if not self.tiktok_token:
            return PublishResult(
                platform=Platform.TIKTOK,
                status=PublishStatus.FAILED,
                error_message="TikTok access token not configured"
            )
        
        try:
            # Step 1: Initialize upload
            init_response = await self.http_client.post(
                "https://open.tiktokapis.com/v2/post/publish/inbox/video/init/",
                headers={
                    "Authorization": f"Bearer {self.tiktok_token}",
                    "Content-Type": "application/json",
                },
                json={
                    "post_info": {
                        "title": caption[:150],
                        "privacy_level": kwargs.get("privacy_level", "PUBLIC_TO_EVERYONE"),
                        "disable_duet": kwargs.get("disable_duet", False),
                        "disable_comment": kwargs.get("disable_comment", False),
                        "disable_stitch": kwargs.get("disable_stitch", False),
                    },
                    "source_info": {
                        "source": "FILE_UPLOAD",
                        "video_size": os.path.getsize(video_path),
                    }
                }
            )
            init_response.raise_for_status()
            init_data = init_response.json()
            
            upload_url = init_data["data"]["upload_url"]
            publish_id = init_data["data"]["publish_id"]
            
            # Step 2: Upload video to provided URL
            with open(video_path, "rb") as f:
                upload_response = await self.http_client.put(
                    upload_url,
                    content=f.read(),
                    headers={"Content-Type": "video/mp4"}
                )
                upload_response.raise_for_status()
            
            # Step 3: Poll for completion
            for _ in range(30):  # Max 5 minutes
                status_response = await self.http_client.post(
                    "https://open.tiktokapis.com/v2/post/publish/status/fetch/",
                    headers={
                        "Authorization": f"Bearer {self.tiktok_token}",
                        "Content-Type": "application/json",
                    },
                    json={"publish_id": publish_id}
                )
                status_data = status_response.json()
                status = status_data["data"]["status"]
                
                if status == "PUBLISH_COMPLETE":
                    return PublishResult(
                        platform=Platform.TIKTOK,
                        status=PublishStatus.PUBLISHED,
                        post_id=publish_id,
                        post_url=status_data["data"].get("video_url"),
                        published_at=datetime.utcnow(),
                    )
                elif status in ["FAILED", "EXPIRED"]:
                    return PublishResult(
                        platform=Platform.TIKTOK,
                        status=PublishStatus.FAILED,
                        error_message=status_data["data"].get("fail_reason", status),
                    )
                
                await asyncio.sleep(10)
            
            return PublishResult(
                platform=Platform.TIKTOK,
                status=PublishStatus.FAILED,
                error_message="Upload timed out",
            )
            
        except Exception as e:
            logger.error(f"TikTok publish failed: {e}")
            return PublishResult(
                platform=Platform.TIKTOK,
                status=PublishStatus.FAILED,
                error_message=str(e),
            )
    
    async def publish_to_instagram(
        self,
        video_path: str,
        caption: str,
        **kwargs
    ) -> PublishResult:
        """
        Publish video to Instagram Reels using Graph API.
        
        Requires Instagram Business/Creator account connected to Facebook.
        """
        if not self.instagram_token or not self.instagram_user_id:
            return PublishResult(
                platform=Platform.INSTAGRAM,
                status=PublishStatus.FAILED,
                error_message="Instagram credentials not configured"
            )
        
        try:
            # Step 1: Upload video to hosting (Instagram requires URL)
            # For production, upload to CDN/S3 first
            # Here we'll use a placeholder for the video URL
            video_url = kwargs.get("video_url")
            if not video_url:
                return PublishResult(
                    platform=Platform.INSTAGRAM,
                    status=PublishStatus.FAILED,
                    error_message="Instagram requires video URL (upload to CDN first)"
                )
            
            # Step 2: Create media container
            container_response = await self.http_client.post(
                f"https://graph.facebook.com/v18.0/{self.instagram_user_id}/media",
                params={
                    "access_token": self.instagram_token,
                    "media_type": "REELS",
                    "video_url": video_url,
                    "caption": caption,
                    "share_to_feed": kwargs.get("share_to_feed", True),
                }
            )
            container_response.raise_for_status()
            container_data = container_response.json()
            container_id = container_data["id"]
            
            # Step 3: Wait for processing
            for _ in range(60):  # Max 10 minutes
                status_response = await self.http_client.get(
                    f"https://graph.facebook.com/v18.0/{container_id}",
                    params={
                        "access_token": self.instagram_token,
                        "fields": "status_code",
                    }
                )
                status_data = status_response.json()
                status = status_data.get("status_code")
                
                if status == "FINISHED":
                    break
                elif status == "ERROR":
                    return PublishResult(
                        platform=Platform.INSTAGRAM,
                        status=PublishStatus.FAILED,
                        error_message="Video processing failed",
                    )
                
                await asyncio.sleep(10)
            
            # Step 4: Publish the container
            publish_response = await self.http_client.post(
                f"https://graph.facebook.com/v18.0/{self.instagram_user_id}/media_publish",
                params={
                    "access_token": self.instagram_token,
                    "creation_id": container_id,
                }
            )
            publish_response.raise_for_status()
            publish_data = publish_response.json()
            
            return PublishResult(
                platform=Platform.INSTAGRAM,
                status=PublishStatus.PUBLISHED,
                post_id=publish_data["id"],
                post_url=f"https://www.instagram.com/reel/{publish_data['id']}/",
                published_at=datetime.utcnow(),
            )
            
        except Exception as e:
            logger.error(f"Instagram publish failed: {e}")
            return PublishResult(
                platform=Platform.INSTAGRAM,
                status=PublishStatus.FAILED,
                error_message=str(e),
            )
    
    async def publish_to_youtube(
        self,
        video_path: str,
        title: str,
        description: str = "",
        **kwargs
    ) -> PublishResult:
        """
        Publish video to YouTube Shorts using Data API v3.
        
        Requires OAuth credentials with youtube.upload scope.
        """
        try:
            from googleapiclient.discovery import build
            from googleapiclient.http import MediaFileUpload
            from google.oauth2.credentials import Credentials  # noqa: F401  (availability probe)
            from google.auth.transport.requests import Request
            import pickle
            
            # Load credentials
            credentials = None
            token_path = self.youtube_credentials_path or "youtube_token.pickle"
            
            if os.path.exists(token_path):
                with open(token_path, "rb") as token:
                    credentials = pickle.load(token)
            
            if not credentials or not credentials.valid:
                if credentials and credentials.expired and credentials.refresh_token:
                    credentials.refresh(Request())
                else:
                    return PublishResult(
                        platform=Platform.YOUTUBE,
                        status=PublishStatus.FAILED,
                        error_message="YouTube OAuth credentials not configured"
                    )
            
            # Build YouTube client
            youtube = build("youtube", "v3", credentials=credentials)
            
            # Prepare video metadata
            body = {
                "snippet": {
                    "title": title[:100],  # YouTube title max 100 chars
                    "description": description,
                    "tags": kwargs.get("tags", []),
                    "categoryId": kwargs.get("category_id", "22"),  # People & Blogs
                },
                "status": {
                    "privacyStatus": kwargs.get("privacy", "public"),
                    "selfDeclaredMadeForKids": kwargs.get("made_for_kids", False),
                }
            }
            
            # Shorts indicator (video < 60s and vertical)
            if kwargs.get("is_shorts", True):
                body["snippet"]["title"] = f"{title[:90]} #Shorts"
            
            # Upload video
            media = MediaFileUpload(
                video_path,
                mimetype="video/mp4",
                resumable=True,
                chunksize=1024 * 1024  # 1MB chunks
            )
            
            request = youtube.videos().insert(
                part=",".join(body.keys()),
                body=body,
                media_body=media
            )
            
            response = None
            while response is None:
                status, response = request.next_chunk()
                if status:
                    logger.info(f"YouTube upload progress: {int(status.progress() * 100)}%")
            
            video_id = response["id"]
            
            return PublishResult(
                platform=Platform.YOUTUBE,
                status=PublishStatus.PUBLISHED,
                post_id=video_id,
                post_url=f"https://youtube.com/shorts/{video_id}",
                published_at=datetime.utcnow(),
            )
            
        except ImportError:
            return PublishResult(
                platform=Platform.YOUTUBE,
                status=PublishStatus.FAILED,
                error_message="google-api-python-client not installed"
            )
        except Exception as e:
            logger.error(f"YouTube publish failed: {e}")
            return PublishResult(
                platform=Platform.YOUTUBE,
                status=PublishStatus.FAILED,
                error_message=str(e),
            )


class SocialPublisher:
    """
    High-level social media publisher with support for multiple platforms.
    
    Can use either Upload-Post API (simpler) or direct platform APIs.
    """
    
    def __init__(
        self,
        use_upload_post: bool = True,
        upload_post_api_key: Optional[str] = None
    ):
        """
        Initialize social publisher.
        
        Args:
            use_upload_post: Use Upload-Post API (True) or direct APIs (False)
            upload_post_api_key: Upload-Post API key
        """
        self.use_upload_post = use_upload_post
        
        if use_upload_post:
            self.upload_post = UploadPostClient(upload_post_api_key)
            self.direct = None
        else:
            self.upload_post = None
            self.direct = DirectPlatformPublisher()
    
    async def close(self):
        """Close HTTP clients."""
        if self.upload_post:
            await self.upload_post.close()
        if self.direct:
            await self.direct.close()
    
    async def publish(
        self,
        request: PublishRequest
    ) -> MultiPlatformResult:
        """
        Publish video to multiple platforms.
        
        Args:
            request: PublishRequest with video and metadata
        
        Returns:
            MultiPlatformResult with results for each platform
        """
        result = MultiPlatformResult(request=request)
        
        # Determine which platforms to publish to
        platforms = request.platforms
        if Platform.ALL in platforms:
            platforms = [Platform.TIKTOK, Platform.INSTAGRAM, Platform.YOUTUBE]
        
        # Publish to each platform concurrently
        tasks = []
        for platform in platforms:
            if platform == Platform.ALL:
                continue
            tasks.append(self._publish_to_platform(request, platform))
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for res in results:
            if isinstance(res, PublishResult):
                result.results.append(res)
            elif isinstance(res, Exception):
                logger.error(f"Publish failed with exception: {res}")
                result.results.append(PublishResult(
                    platform=Platform.TIKTOK,  # Unknown platform
                    status=PublishStatus.FAILED,
                    error_message=str(res)
                ))
        
        return result
    
    async def _publish_to_platform(
        self,
        request: PublishRequest,
        platform: Platform
    ) -> PublishResult:
        """Publish to a single platform."""
        caption = request.get_caption(platform)
        
        if self.use_upload_post and self.upload_post:
            # Use Upload-Post API
            platform_settings = {}
            if platform == Platform.TIKTOK:
                platform_settings = request.tiktok_settings
            elif platform == Platform.INSTAGRAM:
                platform_settings = request.instagram_settings
            elif platform == Platform.YOUTUBE:
                platform_settings = request.youtube_settings
            
            return await self.upload_post.upload_video(
                video_path=request.video_path,
                platform=platform,
                caption=caption,
                thumbnail_path=request.thumbnail_path,
                scheduled_time=request.scheduled_time,
                **platform_settings
            )
        
        elif self.direct:
            # Use direct platform APIs
            if platform == Platform.TIKTOK:
                return await self.direct.publish_to_tiktok(
                    request.video_path, caption, **request.tiktok_settings
                )
            elif platform == Platform.INSTAGRAM:
                return await self.direct.publish_to_instagram(
                    request.video_path, caption, **request.instagram_settings
                )
            elif platform == Platform.YOUTUBE:
                return await self.direct.publish_to_youtube(
                    request.video_path,
                    request.title,
                    request.description,
                    tags=request.hashtags,
                    **request.youtube_settings
                )
        
        return PublishResult(
            platform=platform,
            status=PublishStatus.FAILED,
            error_message="No publishing method configured"
        )
    
    async def publish_to_accounts(
        self,
        video_path: str,
        title: str,
        base_caption: str,
        accounts: List[Dict[str, Any]],
        thumbnail_path: Optional[str] = None,
        hashtags: Optional[List[str]] = None,
        vary_captions: bool = True,
        llm_client=None,
        # Budget attribution for the caption-variant LLM call. The
        # distribution worker has this from the DistributionJob row.
        user_id: Optional[int] = None,
        plan: str = "free",
    ) -> List[Dict[str, Any]]:
        """
        Publish one piece of content to N specific connected accounts.
        
        Each account in `accounts` is a dict like:
            {"id": int, "platform": str, "handle": str, "access_token": str}
        
        If `vary_captions` is True and an LLM client is available, this will
        generate a slightly different caption variant per account so the posts
        don't look automated/batched.
        
        Returns a list of result dicts:
            {"account_id": int, "platform": str, "status": "success"|"failed",
             "posted_url": str|None, "posted_id": str|None,
             "caption_used": str, "error_message": str|None}
        """
        if not accounts:
            return []
        
        hashtags = hashtags or []
        results: List[Dict[str, Any]] = []
        
        # Generate caption variants if requested
        captions: Dict[int, str] = {}
        if vary_captions and llm_client is not None and len(accounts) > 1:
            try:
                captions = await self._generate_caption_variants(
                    base_caption=base_caption,
                    accounts=accounts,
                    llm_client=llm_client,
                    user_id=user_id,
                    plan=plan,
                )
            except Exception as e:
                logger.warning(f"Caption variation failed: {e}")
                captions = {}
        
        for acct in accounts:
            account_id = acct["id"]
            platform_str = acct["platform"]
            caption = captions.get(account_id, base_caption)
            
            # Map platform string to Platform enum
            try:
                platform = Platform(platform_str)
            except ValueError:
                results.append({
                    "account_id": account_id,
                    "platform": platform_str,
                    "status": "failed",
                    "posted_url": None,
                    "posted_id": None,
                    "caption_used": caption,
                    "error_message": f"Unsupported platform: {platform_str}",
                })
                continue
            
            # Build per-account PublishRequest
            request = PublishRequest(
                video_path=video_path,
                title=title,
                description=caption,
                platforms=[platform],
                hashtags=hashtags,
                thumbnail_path=thumbnail_path,
            )
            
            try:
                publish_result = await self._publish_to_platform(request, platform)
                
                results.append({
                    "account_id": account_id,
                    "platform": platform_str,
                    "status": "success" if publish_result.status == PublishStatus.PUBLISHED else "failed",
                    "posted_url": getattr(publish_result, "post_url", None) or getattr(publish_result, "url", None),
                    "posted_id": getattr(publish_result, "post_id", None),
                    "caption_used": caption,
                    "error_message": publish_result.error_message,
                })
            except Exception as e:
                logger.error(f"Failed to publish to account {account_id} ({platform_str}): {e}")
                results.append({
                    "account_id": account_id,
                    "platform": platform_str,
                    "status": "failed",
                    "posted_url": None,
                    "posted_id": None,
                    "caption_used": caption,
                    "error_message": str(e),
                })
        
        return results
    
    async def _generate_caption_variants(
        self,
        base_caption: str,
        accounts: List[Dict[str, Any]],
        llm_client,
        # Budget attribution. This runs inside the distribution background
        # job; the job has the user_id in its closure but historically
        # never forwarded it to the LLM call below.
        user_id: Optional[int] = None,
        plan: str = "free",
    ) -> Dict[int, str]:
        """Generate one caption variant per account using the LLM."""
        if not base_caption.strip():
            return {}
        
        n = len(accounts)
        platforms = [a["platform"] for a in accounts]
        
        system_prompt = (
            "You are a social media manager. Given a base caption, generate "
            "subtly-different variants for the same content posted to multiple "
            "accounts. Vary wording and emphasis but keep the core message and "
            "hashtags. Each variant should feel native to its platform."
        )
        
        user_prompt = f"""Generate {n} caption variants of this base caption.

BASE CAPTION:
{base_caption}

TARGET PLATFORMS (in order): {', '.join(platforms)}

Rules:
- Same core message, same hashtags
- Vary the opening line, word choice, and emphasis
- Match each platform's style (TikTok = casual, Instagram = aesthetic, YouTube = direct, Twitter = concise)
- Stay within the platform's character limits

Respond with ONLY a JSON array of {n} strings (one per variant, in target-platform order):
["variant 1", "variant 2", ...]"""
        
        # llm_client may be sync or async - we use sync interface here since
        # our LLMClient is sync
        try:
            response = llm_client.generate(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=2000,
                temperature=0.8,
                user_id=user_id,
                plan=plan,
                feature="social_publisher.caption_variants",
            )

            if not response.success:
                return {}
            
            text = response.text.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]
            
            start = text.find('[')
            end = text.rfind(']') + 1
            if start >= 0 and end > start:
                variants = json.loads(text[start:end])
                if isinstance(variants, list):
                    return {
                        accounts[i]["id"]: str(variants[i]).strip()
                        for i in range(min(len(variants), n))
                        if str(variants[i]).strip()
                    }
        except Exception as e:
            logger.warning(f"LLM caption variation failed: {e}")
        
        return {}
    
    async def get_connected_accounts(self) -> Dict[str, Any]:
        """Get all connected social media accounts."""
        if self.upload_post:
            return await self.upload_post.get_connected_accounts()
        return {
            "tiktok": [{"connected": bool(os.getenv("TIKTOK_ACCESS_TOKEN"))}],
            "instagram": [{"connected": bool(os.getenv("INSTAGRAM_ACCESS_TOKEN"))}],
            "youtube": [{"connected": bool(os.getenv("YOUTUBE_OAUTH_CREDENTIALS"))}],
        }


async def publish_shorts(
    video_path: str,
    title: str,
    description: str = "",
    platforms: List[str] = None,
    hashtags: List[str] = None,
    scheduled_time: Optional[datetime] = None,
    use_upload_post: bool = True,
) -> Dict:
    """
    Convenience function to publish a short video to social platforms.
    
    Args:
        video_path: Path to the video file (should be vertical 9:16)
        title: Video title
        description: Video description
        platforms: List of platform names ("tiktok", "instagram", "youtube", "all")
        hashtags: List of hashtags (without #)
        scheduled_time: Optional scheduling time (None = publish now)
        use_upload_post: Use Upload-Post API (requires UPLOAD_POST_API_KEY)
    
    Returns:
        Dict with publishing results
    
    Example:
        result = await publish_shorts(
            video_path="clip_1_vertical.mp4",
            title="This hack changed everything",
            hashtags=["viral", "lifehack", "productivity"],
            platforms=["tiktok", "youtube"]
        )
    """
    if platforms is None:
        platforms = ["tiktok", "youtube"]
    
    if hashtags is None:
        hashtags = []
    
    # Convert platform strings to enum
    platform_enums = []
    for p in platforms:
        try:
            platform_enums.append(Platform(p.lower()))
        except ValueError:
            logger.warning(f"Unknown platform: {p}")
    
    if not platform_enums:
        return {"error": "No valid platforms specified"}
    
    # Create publish request
    request = PublishRequest(
        video_path=video_path,
        title=title,
        description=description,
        platforms=platform_enums,
        hashtags=hashtags,
        scheduled_time=scheduled_time,
    )
    
    # Publish
    publisher = SocialPublisher(use_upload_post=use_upload_post)
    try:
        result = await publisher.publish(request)
        return result.to_dict()
    finally:
        await publisher.close()
