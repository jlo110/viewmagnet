"""R2 storage integration for video files."""

import os
import boto3
from botocore.config import Config
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class R2Storage:
    """Cloudflare R2 storage for video clips."""
    
    def __init__(
        self,
        account_id: Optional[str] = None,
        access_key_id: Optional[str] = None,
        secret_access_key: Optional[str] = None,
        bucket_name: str = "ViewMagnet-videos"
    ):
        """
        Initialize R2 storage client.
        
        Args:
            account_id: Cloudflare account ID
            access_key_id: R2 access key ID
            secret_access_key: R2 secret access key
            bucket_name: Name of the R2 bucket
        """
        self.account_id = account_id or os.getenv("R2_ACCOUNT_ID")
        self.access_key_id = access_key_id or os.getenv("R2_ACCESS_KEY_ID")
        self.secret_access_key = secret_access_key or os.getenv("R2_SECRET_ACCESS_KEY")
        self.bucket_name = bucket_name or os.getenv("R2_BUCKET_NAME", "ViewMagnet-videos")
        
        self._client = None
    
    @property
    def client(self):
        """Lazy initialize S3-compatible client for R2."""
        if self._client is None:
            if not all([self.account_id, self.access_key_id, self.secret_access_key]):
                raise ValueError(
                    "R2 credentials not configured. Set R2_ACCOUNT_ID, "
                    "R2_ACCESS_KEY_ID, and R2_SECRET_ACCESS_KEY environment variables."
                )
            
            self._client = boto3.client(
                's3',
                endpoint_url=f"https://{self.account_id}.r2.cloudflarestorage.com",
                aws_access_key_id=self.access_key_id,
                aws_secret_access_key=self.secret_access_key,
                config=Config(
                    signature_version='s3v4',
                    retries={'max_attempts': 3}
                )
            )
        return self._client
    
    def upload_video(self, video_id: str, file_path: str, content_type: str = "video/mp4") -> str:
        """
        Upload a video file to R2.
        
        Args:
            video_id: YouTube video ID (used as key)
            file_path: Local path to video file
            content_type: MIME type of the file
            
        Returns:
            R2 object key
        """
        key = f"videos/{video_id}.mp4"
        
        try:
            with open(file_path, 'rb') as f:
                self.client.upload_fileobj(
                    f,
                    self.bucket_name,
                    key,
                    ExtraArgs={'ContentType': content_type}
                )
            logger.info(f"Uploaded video to R2: {key}")
            return key
        except Exception as e:
            logger.error(f"Failed to upload video to R2: {e}")
            raise
    
    def object_exists(self, key: str) -> bool:
        """True if an object already exists at ``key`` (cheap HEAD)."""
        try:
            self.client.head_object(Bucket=self.bucket_name, Key=key)
            return True
        except Exception:
            return False

    def upload_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        """Upload raw bytes to ``key``. Used for thumbnail archiving (Phase 7.2)."""
        self.client.put_object(
            Bucket=self.bucket_name, Key=key, Body=data, ContentType=content_type
        )
        return key

    def upload_audio(self, video_id: str, file_path: str) -> str:
        """
        Upload an audio file to R2.
        
        Args:
            video_id: YouTube video ID
            file_path: Local path to audio file
            
        Returns:
            R2 object key
        """
        key = f"audio/{video_id}.mp3"
        
        try:
            with open(file_path, 'rb') as f:
                self.client.upload_fileobj(
                    f,
                    self.bucket_name,
                    key,
                    ExtraArgs={'ContentType': 'audio/mpeg'}
                )
            logger.info(f"Uploaded audio to R2: {key}")
            return key
        except Exception as e:
            logger.error(f"Failed to upload audio to R2: {e}")
            raise
    
    def download_video(self, video_id: str, output_path: str) -> bool:
        """
        Download a video from R2.
        
        Args:
            video_id: YouTube video ID
            output_path: Local path to save the file
            
        Returns:
            True if successful
        """
        key = f"videos/{video_id}.mp4"
        
        try:
            self.client.download_file(self.bucket_name, key, output_path)
            logger.info(f"Downloaded video from R2: {key}")
            return True
        except Exception as e:
            logger.error(f"Failed to download video from R2: {e}")
            return False
    
    def video_exists(self, video_id: str) -> bool:
        """Check if a video exists in R2."""
        key = f"videos/{video_id}.mp4"
        try:
            self.client.head_object(Bucket=self.bucket_name, Key=key)
            return True
        except:
            return False
    
    def delete_video(self, video_id: str):
        """Delete a video and its audio from R2."""
        try:
            self.client.delete_object(Bucket=self.bucket_name, Key=f"videos/{video_id}.mp4")
            self.client.delete_object(Bucket=self.bucket_name, Key=f"audio/{video_id}.mp3")
            logger.info(f"Deleted video {video_id} from R2")
        except Exception as e:
            logger.error(f"Failed to delete video from R2: {e}")
    
    def get_presigned_url(self, video_id: str, expiration: int = 3600) -> str:
        """
        Get a presigned URL for video playback.
        
        Args:
            video_id: YouTube video ID
            expiration: URL expiration time in seconds
            
        Returns:
            Presigned URL string
        """
        key = f"videos/{video_id}.mp4"
        try:
            url = self.client.generate_presigned_url(
                'get_object',
                Params={'Bucket': self.bucket_name, 'Key': key},
                ExpiresIn=expiration
            )
            return url
        except Exception as e:
            logger.error(f"Failed to generate presigned URL: {e}")
            raise
    
    def list_videos(self, prefix: str = "videos/", max_keys: int = 1000) -> list:
        """List all videos in the bucket."""
        try:
            response = self.client.list_objects_v2(
                Bucket=self.bucket_name,
                Prefix=prefix,
                MaxKeys=max_keys
            )
            return [obj['Key'] for obj in response.get('Contents', [])]
        except Exception as e:
            logger.error(f"Failed to list videos: {e}")
            return []
    
    def get_storage_stats(self) -> dict:
        """Get storage usage statistics."""
        try:
            videos = self.list_videos("videos/")
            audio = self.list_videos("audio/")
            
            total_size = 0
            for key in videos + audio:
                try:
                    response = self.client.head_object(Bucket=self.bucket_name, Key=key)
                    total_size += response.get('ContentLength', 0)
                except:
                    pass
            
            return {
                'video_count': len(videos),
                'audio_count': len(audio),
                'total_size_mb': total_size / (1024 * 1024),
                'total_size_gb': total_size / (1024 * 1024 * 1024)
            }
        except Exception as e:
            logger.error(f"Failed to get storage stats: {e}")
            return {}

