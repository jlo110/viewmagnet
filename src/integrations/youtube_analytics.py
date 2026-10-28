"""
YouTube Analytics API Integration

Allows users to connect their YouTube channel and access:
- CTR (Click-Through Rate)
- Average View Duration
- Retention curves
- Traffic sources
- Impressions and reach

Requires OAuth2 authentication with user consent.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta

# Google OAuth libraries
try:
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import Flow
    from googleapiclient.discovery import build
    GOOGLE_AUTH_AVAILABLE = True
except ImportError:
    GOOGLE_AUTH_AVAILABLE = False


@dataclass
class VideoAnalytics:
    """Analytics for a single video."""
    video_id: str
    title: str
    
    # Core metrics
    views: int
    watch_time_minutes: float
    avg_view_duration_seconds: float
    avg_view_percentage: float  # % of video watched
    
    # CTR metrics
    impressions: int
    ctr: float  # Click-through rate (0-1)
    
    # Engagement
    likes: int
    dislikes: int
    comments: int
    shares: int
    
    # Traffic sources
    traffic_sources: Dict[str, float]  # source -> percentage
    
    # Audience retention (optional, for detailed analysis)
    retention_curve: Optional[List[float]] = None  # [0-100] at each % of video


@dataclass
class ChannelAnalytics:
    """Overall channel analytics."""
    channel_id: str
    channel_name: str
    
    # Overall metrics (last 28 days)
    total_views: int
    total_watch_time_hours: float
    subscribers_gained: int
    subscribers_lost: int
    
    # Averages
    avg_ctr: float
    avg_view_duration_seconds: float
    avg_views_per_video: float
    
    # Top performing videos
    top_videos: List[VideoAnalytics]
    
    # Best posting times (based on performance)
    best_days: List[str]
    best_hours: List[int]


class YouTubeAnalyticsClient:
    """
    Client for accessing YouTube Analytics API.
    
    Requires OAuth2 credentials from Google Cloud Console.
    """
    
    # Required OAuth scopes
    SCOPES = [
        'https://www.googleapis.com/auth/youtube.readonly',
        'https://www.googleapis.com/auth/yt-analytics.readonly',
    ]
    
    def __init__(
        self,
        client_secrets_file: str = None,
        credentials: Credentials = None
    ):
        """
        Initialize the client.
        
        Args:
            client_secrets_file: Path to OAuth client secrets JSON
            credentials: Pre-existing credentials (for returning users)
        """
        if not GOOGLE_AUTH_AVAILABLE:
            raise ImportError(
                "Google auth libraries not installed. Run:\n"
                "pip install google-auth google-auth-oauthlib google-api-python-client"
            )
        
        self.client_secrets_file = client_secrets_file
        self.credentials = credentials
        self.youtube = None
        self.youtube_analytics = None
    
    def get_authorization_url(self, redirect_uri: str) -> Tuple[str, str]:
        """
        Get the OAuth authorization URL for user consent.
        
        Args:
            redirect_uri: Where to redirect after auth (your callback URL)
            
        Returns:
            Tuple of (authorization_url, state)
        """
        flow = Flow.from_client_secrets_file(
            self.client_secrets_file,
            scopes=self.SCOPES,
            redirect_uri=redirect_uri
        )
        
        authorization_url, state = flow.authorization_url(
            access_type='offline',  # Get refresh token
            include_granted_scopes='true',
            prompt='consent'  # Force consent screen
        )
        
        return authorization_url, state
    
    def handle_callback(self, authorization_response: str, redirect_uri: str) -> Credentials:
        """
        Handle the OAuth callback and get credentials.
        
        Args:
            authorization_response: Full callback URL with code
            redirect_uri: Same redirect URI used in authorization
            
        Returns:
            Credentials object (store the refresh token!)
        """
        flow = Flow.from_client_secrets_file(
            self.client_secrets_file,
            scopes=self.SCOPES,
            redirect_uri=redirect_uri
        )
        
        flow.fetch_token(authorization_response=authorization_response)
        self.credentials = flow.credentials
        
        return self.credentials
    
    def credentials_to_dict(self) -> dict:
        """Convert credentials to dict for storage."""
        return {
            'token': self.credentials.token,
            'refresh_token': self.credentials.refresh_token,
            'token_uri': self.credentials.token_uri,
            'client_id': self.credentials.client_id,
            'client_secret': self.credentials.client_secret,
            'scopes': self.credentials.scopes
        }
    
    def credentials_from_dict(self, creds_dict: dict) -> Credentials:
        """Restore credentials from stored dict."""
        self.credentials = Credentials(**creds_dict)
        return self.credentials
    
    def _build_services(self):
        """Build YouTube API service objects."""
        if not self.credentials:
            raise ValueError("No credentials. User must authorize first.")
        
        self.youtube = build('youtube', 'v3', credentials=self.credentials)
        self.youtube_analytics = build('youtubeAnalytics', 'v2', credentials=self.credentials)
    
    def get_channel_info(self) -> dict:
        """Get basic channel info for the authenticated user."""
        if not self.youtube:
            self._build_services()
        
        response = self.youtube.channels().list(
            part='snippet,statistics',
            mine=True
        ).execute()
        
        if not response.get('items'):
            raise ValueError("No channel found for this user")
        
        channel = response['items'][0]
        return {
            'channel_id': channel['id'],
            'channel_name': channel['snippet']['title'],
            'subscriber_count': int(channel['statistics'].get('subscriberCount', 0)),
            'video_count': int(channel['statistics'].get('videoCount', 0)),
            'view_count': int(channel['statistics'].get('viewCount', 0)),
        }
    
    def get_video_analytics(
        self,
        video_id: str,
        start_date: str = None,
        end_date: str = None
    ) -> VideoAnalytics:
        """
        Get detailed analytics for a specific video.
        
        Args:
            video_id: YouTube video ID
            start_date: Start date (YYYY-MM-DD), default 28 days ago
            end_date: End date (YYYY-MM-DD), default today
        """
        if not self.youtube_analytics:
            self._build_services()
        
        # Default to last 28 days
        if not end_date:
            end_date = datetime.now().strftime('%Y-%m-%d')
        if not start_date:
            start_date = (datetime.now() - timedelta(days=28)).strftime('%Y-%m-%d')
        
        # Get video title first
        video_response = self.youtube.videos().list(
            part='snippet',
            id=video_id
        ).execute()
        
        title = video_response['items'][0]['snippet']['title'] if video_response.get('items') else ''
        
        # Get analytics
        response = self.youtube_analytics.reports().query(
            ids='channel==MINE',
            startDate=start_date,
            endDate=end_date,
            metrics='views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,impressions,impressionClickThroughRate,likes,dislikes,comments,shares',
            filters=f'video=={video_id}'
        ).execute()
        
        # Parse response
        row = response.get('rows', [[0]*10])[0]
        
        # Get traffic sources
        traffic_response = self.youtube_analytics.reports().query(
            ids='channel==MINE',
            startDate=start_date,
            endDate=end_date,
            metrics='views',
            dimensions='insightTrafficSourceType',
            filters=f'video=={video_id}',
            sort='-views'
        ).execute()
        
        traffic_sources = {}
        total_views = sum(r[1] for r in traffic_response.get('rows', []))
        for src_row in traffic_response.get('rows', []):
            source = src_row[0]
            views = src_row[1]
            traffic_sources[source] = views / max(total_views, 1)
        
        return VideoAnalytics(
            video_id=video_id,
            title=title,
            views=int(row[0]),
            watch_time_minutes=float(row[1]),
            avg_view_duration_seconds=float(row[2]),
            avg_view_percentage=float(row[3]),
            impressions=int(row[4]),
            ctr=float(row[5]),
            likes=int(row[6]),
            dislikes=int(row[7]),
            comments=int(row[8]),
            shares=int(row[9]),
            traffic_sources=traffic_sources
        )
    
    def get_retention_curve(
        self,
        video_id: str,
        start_date: str = None,
        end_date: str = None,
    ) -> Optional[List[float]]:
        """Audience-retention curve: audienceWatchRatio at each elapsed-time ratio.

        Returns a list of ratios (1.0 = the whole audience still watching) sampled
        across the video, or None if the API has no retention data (common for
        very new or small videos). Best-effort — the caller treats None as 'no
        curve yet'."""
        if not self.youtube_analytics:
            self._build_services()
        if not end_date:
            end_date = datetime.now().strftime('%Y-%m-%d')
        if not start_date:
            start_date = (datetime.now() - timedelta(days=90)).strftime('%Y-%m-%d')
        try:
            resp = self.youtube_analytics.reports().query(
                ids='channel==MINE',
                startDate=start_date,
                endDate=end_date,
                metrics='audienceWatchRatio',
                dimensions='elapsedVideoTimeRatio',
                filters=f'video=={video_id}',
                sort='elapsedVideoTimeRatio',
            ).execute()
        except Exception:  # noqa: BLE001 — retention unavailable for this video
            return None
        rows = resp.get('rows', [])
        if not rows:
            return None
        return [float(r[1]) for r in rows]

    def get_channel_analytics(self, days: int = 28) -> ChannelAnalytics:
        """
        Get overall channel analytics.
        
        Args:
            days: Number of days to analyze
        """
        if not self.youtube_analytics:
            self._build_services()
        
        channel_info = self.get_channel_info()
        
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        
        # Overall metrics
        response = self.youtube_analytics.reports().query(
            ids='channel==MINE',
            startDate=start_date,
            endDate=end_date,
            metrics='views,estimatedMinutesWatched,subscribersGained,subscribersLost,impressionClickThroughRate,averageViewDuration'
        ).execute()
        
        row = response.get('rows', [[0]*6])[0]
        
        # Get top videos
        top_videos_response = self.youtube_analytics.reports().query(
            ids='channel==MINE',
            startDate=start_date,
            endDate=end_date,
            metrics='views,impressionClickThroughRate,averageViewDuration',
            dimensions='video',
            sort='-views',
            maxResults=10
        ).execute()
        
        top_videos = []
        for vid_row in top_videos_response.get('rows', []):
            video_id = vid_row[0]
            try:
                analytics = self.get_video_analytics(video_id, start_date, end_date)
                top_videos.append(analytics)
            except:
                continue
        
        return ChannelAnalytics(
            channel_id=channel_info['channel_id'],
            channel_name=channel_info['channel_name'],
            total_views=int(row[0]),
            total_watch_time_hours=float(row[1]) / 60,
            subscribers_gained=int(row[2]),
            subscribers_lost=int(row[3]),
            avg_ctr=float(row[4]),
            avg_view_duration_seconds=float(row[5]),
            avg_views_per_video=int(row[0]) / max(len(top_videos), 1),
            top_videos=top_videos,
            best_days=[],  # Would need additional query
            best_hours=[]
        )
    
    def get_ctr_comparison(self, video_id: str) -> dict:
        """
        Compare a video's CTR to channel average.
        
        Returns dict with comparison data.
        """
        video = self.get_video_analytics(video_id)
        channel = self.get_channel_analytics()
        
        ctr_diff = video.ctr - channel.avg_ctr
        ctr_pct_diff = (ctr_diff / max(channel.avg_ctr, 0.001)) * 100
        
        return {
            'video_ctr': video.ctr,
            'channel_avg_ctr': channel.avg_ctr,
            'difference': ctr_diff,
            'percent_difference': ctr_pct_diff,
            'verdict': 'above_average' if ctr_diff > 0 else 'below_average',
            'recommendation': self._ctr_recommendation(video.ctr, channel.avg_ctr)
        }
    
    def _ctr_recommendation(self, video_ctr: float, channel_ctr: float) -> str:
        """Generate CTR recommendation."""
        diff_pct = ((video_ctr - channel_ctr) / max(channel_ctr, 0.001)) * 100
        
        if diff_pct > 20:
            return "🔥 Excellent CTR! This thumbnail/title combo is working great."
        elif diff_pct > 0:
            return "✅ Above average CTR. Solid thumbnail/title."
        elif diff_pct > -20:
            return "⚠️ Slightly below average. Consider A/B testing thumbnail."
        else:
            return "❌ Low CTR. Thumbnail or title needs work."


# ============================================================
# OAUTH SETUP INSTRUCTIONS
# ============================================================
"""
To set up YouTube Analytics OAuth:

1. Go to Google Cloud Console: https://console.cloud.google.com/

2. Create a new project (or select existing)

3. Enable APIs:
   - YouTube Data API v3
   - YouTube Analytics API

4. Create OAuth 2.0 credentials:
   - Go to "Credentials"
   - Click "Create Credentials" > "OAuth client ID"
   - Application type: "Web application"
   - Add authorized redirect URIs:
     - http://localhost:8000/callback (for development)
     - https://yourdomain.com/callback (for production)

5. Download the client secrets JSON file

6. Store securely (never commit to git!)

7. Usage example:

```python
from src.integrations.youtube_analytics import YouTubeAnalyticsClient

# Initialize client
client = YouTubeAnalyticsClient(
    client_secrets_file='path/to/client_secrets.json'
)

# Get authorization URL (show to user)
auth_url, state = client.get_authorization_url(
    redirect_uri='http://localhost:8000/callback'
)
print(f"Please authorize: {auth_url}")

# After user authorizes and is redirected back
# (in your callback handler):
credentials = client.handle_callback(
    authorization_response=request.url,
    redirect_uri='http://localhost:8000/callback'
)

# Store the credentials for this user
user_creds = client.credentials_to_dict()
save_to_database(user_id, user_creds)

# Later, restore credentials for returning user
client.credentials_from_dict(stored_creds)

# Now you can fetch analytics!
video_analytics = client.get_video_analytics('dQw4w9WgXcQ')
print(f"CTR: {video_analytics.ctr:.2%}")
print(f"Avg View Duration: {video_analytics.avg_view_duration_seconds}s")
```
"""

