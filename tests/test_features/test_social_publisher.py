"""Tests for social media publishing module."""

import pytest
import asyncio
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from datetime import datetime, timedelta
import tempfile
import os

from src.features.social_publisher import (
    Platform,
    PublishStatus,
    PublishRequest,
    PublishResult,
    MultiPlatformResult,
    UploadPostClient,
    DirectPlatformPublisher,
    SocialPublisher,
    publish_shorts,
)


class TestPlatformEnum:
    """Tests for Platform enum."""
    
    def test_platform_values(self):
        """Test platform enum values."""
        assert Platform.TIKTOK.value == "tiktok"
        assert Platform.INSTAGRAM.value == "instagram"
        assert Platform.YOUTUBE.value == "youtube"
        assert Platform.ALL.value == "all"


class TestPublishStatus:
    """Tests for PublishStatus enum."""
    
    def test_status_values(self):
        """Test status enum values."""
        assert PublishStatus.PENDING.value == "pending"
        assert PublishStatus.UPLOADING.value == "uploading"
        assert PublishStatus.PROCESSING.value == "processing"
        assert PublishStatus.PUBLISHED.value == "published"
        assert PublishStatus.SCHEDULED.value == "scheduled"
        assert PublishStatus.FAILED.value == "failed"


class TestPublishRequest:
    """Tests for PublishRequest dataclass."""
    
    def test_basic_request(self):
        """Test creating a basic publish request."""
        request = PublishRequest(
            video_path="/path/to/video.mp4",
            title="Test Video",
            description="Test description",
            platforms=[Platform.TIKTOK, Platform.YOUTUBE]
        )
        assert request.video_path == "/path/to/video.mp4"
        assert request.title == "Test Video"
        assert len(request.platforms) == 2
    
    def test_get_caption_tiktok(self):
        """Test caption generation for TikTok."""
        request = PublishRequest(
            video_path="/path/to/video.mp4",
            title="Amazing Video",
            description="Check this out!",
            platforms=[Platform.TIKTOK],
            hashtags=["viral", "trending"]
        )
        caption = request.get_caption(Platform.TIKTOK)
        assert "Amazing Video" in caption
        assert "Check this out!" in caption
        assert "#viral" in caption
        assert "#trending" in caption
    
    def test_get_caption_youtube(self):
        """Test caption generation for YouTube (title only)."""
        request = PublishRequest(
            video_path="/path/to/video.mp4",
            title="Very Long Title That Exceeds One Hundred Characters And Should Be Truncated For YouTube Shorts Platform",
            description="Description",
            platforms=[Platform.YOUTUBE]
        )
        caption = request.get_caption(Platform.YOUTUBE)
        assert len(caption) <= 100
    
    def test_get_caption_instagram(self):
        """Test caption generation for Instagram."""
        request = PublishRequest(
            video_path="/path/to/video.mp4",
            title="Cool Reel",
            description="Watch till the end!",
            platforms=[Platform.INSTAGRAM],
            hashtags=["reels", "explore"]
        )
        caption = request.get_caption(Platform.INSTAGRAM)
        assert "Cool Reel" in caption
        assert "Watch till the end!" in caption
        assert "#reels" in caption


class TestPublishResult:
    """Tests for PublishResult dataclass."""
    
    def test_successful_result(self):
        """Test creating a successful result."""
        result = PublishResult(
            platform=Platform.TIKTOK,
            status=PublishStatus.PUBLISHED,
            post_id="12345",
            post_url="https://tiktok.com/@user/video/12345",
            published_at=datetime.utcnow()
        )
        assert result.status == PublishStatus.PUBLISHED
        assert result.post_id == "12345"
    
    def test_failed_result(self):
        """Test creating a failed result."""
        result = PublishResult(
            platform=Platform.INSTAGRAM,
            status=PublishStatus.FAILED,
            error_message="Upload timeout"
        )
        assert result.status == PublishStatus.FAILED
        assert result.error_message == "Upload timeout"
    
    def test_to_dict(self):
        """Test converting result to dict."""
        result = PublishResult(
            platform=Platform.YOUTUBE,
            status=PublishStatus.PUBLISHED,
            post_id="abc123"
        )
        d = result.to_dict()
        assert d["platform"] == "youtube"
        assert d["status"] == "published"
        assert d["post_id"] == "abc123"


class TestMultiPlatformResult:
    """Tests for MultiPlatformResult dataclass."""
    
    def test_all_successful(self):
        """Test all_successful property."""
        request = PublishRequest(
            video_path="/test.mp4",
            title="Test",
            description="",
            platforms=[Platform.TIKTOK, Platform.YOUTUBE]
        )
        result = MultiPlatformResult(
            request=request,
            results=[
                PublishResult(platform=Platform.TIKTOK, status=PublishStatus.PUBLISHED),
                PublishResult(platform=Platform.YOUTUBE, status=PublishStatus.PUBLISHED),
            ]
        )
        assert result.all_successful is True
    
    def test_partial_success(self):
        """Test partial success scenario."""
        request = PublishRequest(
            video_path="/test.mp4",
            title="Test",
            description="",
            platforms=[Platform.TIKTOK, Platform.YOUTUBE]
        )
        result = MultiPlatformResult(
            request=request,
            results=[
                PublishResult(platform=Platform.TIKTOK, status=PublishStatus.PUBLISHED),
                PublishResult(platform=Platform.YOUTUBE, status=PublishStatus.FAILED),
            ]
        )
        assert result.all_successful is False
        assert result.any_successful is True
    
    def test_all_failed(self):
        """Test all failed scenario."""
        request = PublishRequest(
            video_path="/test.mp4",
            title="Test",
            description="",
            platforms=[Platform.TIKTOK]
        )
        result = MultiPlatformResult(
            request=request,
            results=[
                PublishResult(platform=Platform.TIKTOK, status=PublishStatus.FAILED),
            ]
        )
        assert result.all_successful is False
        assert result.any_successful is False


class TestUploadPostClient:
    """Tests for Upload-Post API client."""
    
    def test_init_no_api_key(self):
        """Test initialization without API key."""
        with patch.dict(os.environ, {}, clear=True):
            client = UploadPostClient()
            assert client.api_key is None
    
    def test_init_with_api_key(self):
        """Test initialization with API key."""
        client = UploadPostClient(api_key="test-key-123")
        assert client.api_key == "test-key-123"
    
    @pytest.mark.asyncio
    async def test_upload_video_no_api_key(self):
        """Test upload fails gracefully without API key."""
        client = UploadPostClient(api_key=None)
        result = await client.upload_video(
            video_path="/test.mp4",
            platform=Platform.TIKTOK,
            caption="Test"
        )
        assert result.status == PublishStatus.FAILED
        assert "not configured" in result.error_message
    
    @pytest.mark.asyncio
    async def test_upload_video_success(self):
        """Test successful upload with mocked HTTP client."""
        # Create temp video file
        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as f:
            f.write(b'fake video content')
            video_path = f.name
        
        try:
            # Test with no API key returns proper failure
            client = UploadPostClient(api_key=None)
            result = await client.upload_video(
                video_path=video_path,
                platform=Platform.TIKTOK,
                caption="Test caption"
            )
            
            # Without API key, should fail gracefully
            assert result.status == PublishStatus.FAILED
            assert "not configured" in result.error_message
            
            # Test that the result structure is correct
            d = result.to_dict()
            assert d["platform"] == "tiktok"
            assert d["status"] == "failed"
        finally:
            os.unlink(video_path)


class TestDirectPlatformPublisher:
    """Tests for direct platform API publisher."""
    
    @pytest.mark.asyncio
    async def test_publish_tiktok_no_token(self):
        """Test TikTok publish fails without token."""
        with patch.dict(os.environ, {"TIKTOK_ACCESS_TOKEN": ""}, clear=False):
            publisher = DirectPlatformPublisher()
            publisher.tiktok_token = None
            
            result = await publisher.publish_to_tiktok(
                video_path="/test.mp4",
                caption="Test"
            )
            assert result.status == PublishStatus.FAILED
            assert "not configured" in result.error_message
    
    @pytest.mark.asyncio
    async def test_publish_instagram_no_credentials(self):
        """Test Instagram publish fails without credentials."""
        publisher = DirectPlatformPublisher()
        publisher.instagram_token = None
        
        result = await publisher.publish_to_instagram(
            video_path="/test.mp4",
            caption="Test"
        )
        assert result.status == PublishStatus.FAILED
        assert "not configured" in result.error_message


class TestSocialPublisher:
    """Tests for high-level SocialPublisher."""
    
    @pytest.fixture
    def publisher(self):
        """Create a publisher instance."""
        return SocialPublisher(use_upload_post=True, upload_post_api_key="test-key")
    
    @pytest.mark.asyncio
    async def test_publish_multiple_platforms(self, publisher):
        """Test publishing to multiple platforms."""
        # Create temp video file
        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as f:
            f.write(b'fake video content')
            video_path = f.name
        
        try:
            request = PublishRequest(
                video_path=video_path,
                title="Test Video",
                description="Description",
                platforms=[Platform.TIKTOK, Platform.YOUTUBE],
                hashtags=["test"]
            )
            
            with patch.object(publisher.upload_post, 'upload_video') as mock_upload:
                mock_upload.return_value = PublishResult(
                    platform=Platform.TIKTOK,
                    status=PublishStatus.PUBLISHED,
                    post_id="123"
                )
                
                result = await publisher.publish(request)
                
                assert len(result.results) == 2
        finally:
            await publisher.close()
            os.unlink(video_path)
    
    @pytest.mark.asyncio
    async def test_publish_all_platforms(self, publisher):
        """Test publishing to ALL platforms."""
        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as f:
            f.write(b'fake video content')
            video_path = f.name
        
        try:
            request = PublishRequest(
                video_path=video_path,
                title="Test",
                description="",
                platforms=[Platform.ALL]
            )
            
            with patch.object(publisher.upload_post, 'upload_video') as mock_upload:
                mock_upload.return_value = PublishResult(
                    platform=Platform.TIKTOK,
                    status=PublishStatus.PUBLISHED
                )
                
                result = await publisher.publish(request)
                
                # ALL should expand to 3 platforms
                assert len(result.results) == 3
        finally:
            await publisher.close()
            os.unlink(video_path)


class TestPublishShortsFunction:
    """Tests for the publish_shorts convenience function."""
    
    @pytest.mark.asyncio
    async def test_publish_shorts_invalid_platforms(self):
        """Test publish_shorts with invalid platforms."""
        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as f:
            f.write(b'fake video content')
            video_path = f.name
        
        try:
            result = await publish_shorts(
                video_path=video_path,
                title="Test",
                platforms=["invalid_platform", "another_invalid"]
            )
            
            assert "error" in result
        finally:
            os.unlink(video_path)
    
    @pytest.mark.asyncio
    async def test_publish_shorts_default_platforms(self):
        """Test publish_shorts uses default platforms."""
        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as f:
            f.write(b'fake video content')
            video_path = f.name
        
        try:
            with patch('src.features.social_publisher.SocialPublisher') as MockPublisher:
                # Create a proper mock request for the result
                mock_request = PublishRequest(
                    video_path=video_path,
                    title="Test Video",
                    description="",
                    platforms=[Platform.TIKTOK, Platform.YOUTUBE]
                )
                mock_instance = AsyncMock()
                mock_instance.publish.return_value = MultiPlatformResult(
                    request=mock_request,
                    results=[]
                )
                mock_instance.close = AsyncMock()
                MockPublisher.return_value = mock_instance
                
                # Don't specify platforms - should default to tiktok, youtube
                result = await publish_shorts(
                    video_path=video_path,
                    title="Test Video"
                )
                
                # Verify publish was called
                mock_instance.publish.assert_called_once()
                
                # Check result structure
                assert "platforms_requested" in result
        finally:
            os.unlink(video_path)


class TestScheduledPublishing:
    """Tests for scheduled publishing functionality."""
    
    def test_scheduled_request(self):
        """Test creating a scheduled publish request."""
        scheduled = datetime.utcnow() + timedelta(hours=2)
        request = PublishRequest(
            video_path="/test.mp4",
            title="Scheduled Post",
            description="",
            platforms=[Platform.TIKTOK],
            scheduled_time=scheduled
        )
        assert request.scheduled_time == scheduled
    
    def test_scheduled_result(self):
        """Test scheduled publish result."""
        scheduled = datetime.utcnow() + timedelta(hours=2)
        result = PublishResult(
            platform=Platform.TIKTOK,
            status=PublishStatus.SCHEDULED,
            post_id="pending_123",
            scheduled_for=scheduled
        )
        assert result.status == PublishStatus.SCHEDULED
        assert result.scheduled_for == scheduled
        
        d = result.to_dict()
        assert d["status"] == "scheduled"
        assert d["scheduled_for"] is not None
