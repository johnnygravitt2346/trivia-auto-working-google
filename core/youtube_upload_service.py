#!/usr/bin/env python3
"""
YouTube Upload Service
Handles uploading videos to YouTube using OAuth credentials
"""

import os
import json
import time
import tempfile
from datetime import datetime
from typing import Optional, Dict, Any

from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError
from google.cloud import storage


class YouTubeUploadService:
    """Service for uploading videos to YouTube"""
    
    def __init__(self, tokens_path: str = './secrets/youtube_tokens.json'):
        self.tokens_path = tokens_path
        self.youtube_service = None
        self.credentials = None
        
    def _load_credentials(self) -> Optional[Credentials]:
        """Load and refresh YouTube OAuth credentials"""
        try:
            if not os.path.exists(self.tokens_path):
                print("❌ YouTube tokens not found. Please complete OAuth setup first.")
                return None
            
            with open(self.tokens_path, 'r') as f:
                tokens_data = json.load(f)
            
            # Create credentials object
            credentials = Credentials(
                token=tokens_data.get('token'),
                refresh_token=tokens_data.get('refresh_token'),
                token_uri=tokens_data.get('token_uri'),
                client_id=tokens_data.get('client_id'),
                client_secret=tokens_data.get('client_secret'),
                scopes=tokens_data.get('scopes')
            )
            
            # Refresh token if needed
            if credentials.expired:
                print("🔄 Refreshing YouTube OAuth token...")
                credentials.refresh(Request())
                
                # Save updated tokens
                tokens_data['token'] = credentials.token
                tokens_data['expiry'] = credentials.expiry.isoformat() if credentials.expiry else None
                
                with open(self.tokens_path, 'w') as f:
                    json.dump(tokens_data, f, indent=2)
                
                print("✅ YouTube OAuth token refreshed and saved")
            
            return credentials
            
        except Exception as e:
            print(f"❌ Error loading YouTube credentials: {str(e)}")
            return None
    
    def _get_youtube_service(self):
        """Get authenticated YouTube service"""
        if self.youtube_service is None:
            self.credentials = self._load_credentials()
            if self.credentials is None:
                return None
            
            try:
                self.youtube_service = build('youtube', 'v3', credentials=self.credentials)
                print("✅ YouTube service authenticated successfully")
            except Exception as e:
                print(f"❌ Error building YouTube service: {str(e)}")
                return None
        
        return self.youtube_service
    
    def upload_video_from_job(self,
                              job_data: Dict[str, Any],
                              video_path: str,
                              tags: list = None,
                              category_id: str = "22",
                              privacy_status: str = "private",
                              thumbnail_path: str = None) -> Dict[str, Any]:
        """
        Upload video using metadata from job data (with manifest support)
        
        STRICT: Requires youtube_title and youtube_description from manifest.
        Will fail if these fields are missing - no fallback to auto-generated titles.
        
        Args:
            job_data: Job data dict containing youtube_title and youtube_description
            video_path: Path to the video file
            tags: List of tags (optional)
            category_id: YouTube category ID
            privacy_status: Privacy status
            thumbnail_path: Path to thumbnail (optional)
            
        Returns:
            Dict with upload result or error information
        """
        # STRICT VALIDATION: Require YouTube metadata from manifest
        if not job_data.get('youtube_title'):
            return {
                'success': False,
                'error': '❌ Missing youtube_title - manifest metadata is required. Job must have been created with a manifest.',
                'error_code': 'MISSING_YOUTUBE_TITLE'
            }
        
        if not job_data.get('youtube_description'):
            return {
                'success': False,
                'error': '❌ Missing youtube_description - manifest metadata is required. Job must have been created with a manifest.',
                'error_code': 'MISSING_YOUTUBE_DESCRIPTION'
            }
        
        # Extract metadata from job
        title = job_data['youtube_title']
        description = job_data['youtube_description']
        
        # Add manifest info to logs
        manifest_index = job_data.get('manifest_index', 'unknown')
        print(f"📹 Uploading video with manifest metadata (index: {manifest_index})")
        print(f"   Title: {title}")
        print(f"   Description: {description[:100]}...")
        
        # Use the standard upload_video method
        return self.upload_video(
            video_path=video_path,
            title=title,
            description=description,
            tags=tags,
            category_id=category_id,
            privacy_status=privacy_status,
            thumbnail_path=thumbnail_path
        )
    
    def upload_video(self, 
                    video_path: str,
                    title: str,
                    description: str,
                    tags: list = None,
                    category_id: str = "22",  # People & Blogs
                    privacy_status: str = "private",  # Start as private for review
                    thumbnail_path: str = None) -> Dict[str, Any]:
        """
        Upload a video to YouTube
        
        Args:
            video_path: Path to the video file
            title: Video title
            description: Video description
            tags: List of tags
            category_id: YouTube category ID (22 = People & Blogs)
            privacy_status: Privacy status (private, unlisted, public)
            thumbnail_path: Path to thumbnail image
            
        Returns:
            Dict with upload result or error information
        """
        try:
            # Get YouTube service
            youtube = self._get_youtube_service()
            if youtube is None:
                return {
                    'success': False,
                    'error': 'Failed to authenticate with YouTube',
                    'error_code': 'AUTH_FAILED'
                }
            
            # Handle GCS paths - download to local temp file if needed
            local_video_path = video_path
            temp_file_created = False
            
            if video_path.startswith('videos/') or video_path.startswith('gs://'):
                # This is a GCS path, download to local temp file
                print(f"📥 Downloading video from GCS: {video_path}")
                try:
                    from google.cloud import storage
                    import tempfile
                    
                    # Initialize GCS client
                    storage_client = storage.Client()
                    bucket_name = 'trivia-dev-assets'  # Your bucket name
                    bucket = storage_client.bucket(bucket_name)
                    
                    # Download to temp file
                    blob = bucket.blob(video_path)
                    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.mp4')
                    local_video_path = temp_file.name
                    temp_file.close()
                    
                    blob.download_to_filename(local_video_path)
                    temp_file_created = True
                    print(f"✅ Downloaded video to: {local_video_path}")
                    
                except Exception as e:
                    return {
                        'success': False,
                        'error': f'Failed to download video from GCS: {str(e)}',
                        'error_code': 'GCS_DOWNLOAD_FAILED'
                    }
            else:
                # Validate local video file
                if not os.path.exists(video_path):
                    return {
                        'success': False,
                        'error': f'Video file not found: {video_path}',
                        'error_code': 'FILE_NOT_FOUND'
                    }
            
            # Prepare video metadata
            video_metadata = {
                'snippet': {
                    'title': title,
                    'description': description,
                    'tags': tags or [],
                    'categoryId': category_id
                },
                'status': {
                    'privacyStatus': privacy_status
                }
            }
            
            print(f"🎬 Starting upload: {title}")
            print(f"📁 Video file: {local_video_path}")
            print(f"🔒 Privacy: {privacy_status}")
            
            # Create media upload
            media = MediaFileUpload(
                local_video_path,
                chunksize=-1,
                resumable=True,
                mimetype='video/mp4'
            )
            
            # Start upload
            insert_request = youtube.videos().insert(
                part=','.join(video_metadata.keys()),
                body=video_metadata,
                media_body=media
            )
            
            # Execute upload with progress tracking
            response = None
            error = None
            retry = 0
            
            while response is None:
                try:
                    status, response = insert_request.next_chunk()
                    if status:
                        progress = int(status.progress() * 100)
                        print(f"📤 Upload progress: {progress}%")
                except HttpError as e:
                    if e.resp.status in [500, 502, 503, 504]:
                        # Retryable error
                        error = f"Retryable error: {e}"
                        retry += 1
                        if retry > 3:
                            return {
                                'success': False,
                                'error': f'Upload failed after retries: {error}',
                                'error_code': 'UPLOAD_FAILED'
                            }
                        print(f"⚠️ Retryable error, retrying ({retry}/3): {e}")
                        time.sleep(2 ** retry)  # Exponential backoff
                    else:
                        # Non-retryable error
                        return {
                            'success': False,
                            'error': f'Upload failed: {e}',
                            'error_code': 'UPLOAD_ERROR'
                        }
            
            # Upload successful
            video_id = response['id']
            video_url = f"https://www.youtube.com/watch?v={video_id}"
            
            print(f"✅ Upload successful!")
            print(f"🎥 Video ID: {video_id}")
            print(f"🔗 URL: {video_url}")
            
            # Upload thumbnail if provided
            if thumbnail_path and os.path.exists(thumbnail_path):
                try:
                    self._upload_thumbnail(youtube, video_id, thumbnail_path)
                except Exception as e:
                    print(f"⚠️ Thumbnail upload failed: {e}")
            
            return {
                'success': True,
                'video_id': video_id,
                'video_url': video_url,
                'title': title,
                'privacy_status': privacy_status,
                'upload_time': datetime.utcnow().isoformat() + "Z"
            }
            
        except Exception as e:
            print(f"❌ Upload error: {str(e)}")
            return {
                'success': False,
                'error': str(e),
                'error_code': 'UNKNOWN_ERROR'
            }
        finally:
            # Clean up temp file if we created one
            if temp_file_created and os.path.exists(local_video_path):
                try:
                    os.unlink(local_video_path)
                    print(f"🗑️ Cleaned up temp file: {local_video_path}")
                except Exception as e:
                    print(f"⚠️ Failed to clean up temp file: {e}")
    
    def _upload_thumbnail(self, youtube, video_id: str, thumbnail_path: str):
        """Upload thumbnail for a video"""
        try:
            youtube.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(thumbnail_path)
            ).execute()
            print(f"✅ Thumbnail uploaded for video {video_id}")
        except Exception as e:
            print(f"❌ Thumbnail upload failed: {e}")
            raise
    
    def get_channel_info(self) -> Dict[str, Any]:
        """Get information about the authenticated channel"""
        try:
            youtube = self._get_youtube_service()
            if youtube is None:
                return {'success': False, 'error': 'Authentication failed'}
            
            # Get channel information
            response = youtube.channels().list(
                part='snippet,statistics',
                mine=True
            ).execute()
            
            if not response['items']:
                return {'success': False, 'error': 'No channel found'}
            
            channel = response['items'][0]
            return {
                'success': True,
                'channel_id': channel['id'],
                'title': channel['snippet']['title'],
                'description': channel['snippet']['description'],
                'custom_url': channel['snippet'].get('customUrl', ''),
                'subscriber_count': channel['statistics'].get('subscriberCount', '0'),
                'video_count': channel['statistics'].get('videoCount', '0'),
                'view_count': channel['statistics'].get('viewCount', '0')
            }
            
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def update_video_privacy(self, video_id: str, privacy_status: str) -> Dict[str, Any]:
        """Update video privacy status"""
        try:
            youtube = self._get_youtube_service()
            if youtube is None:
                return {'success': False, 'error': 'Authentication failed'}
            
            youtube.videos().update(
                part='status',
                body={
                    'id': video_id,
                    'status': {
                        'privacyStatus': privacy_status
                    }
                }
            ).execute()
            
            return {
                'success': True,
                'video_id': video_id,
                'privacy_status': privacy_status
            }
            
        except Exception as e:
            return {'success': False, 'error': str(e)}


# Convenience function for easy import
def get_youtube_upload_service() -> YouTubeUploadService:
    """Get a YouTube upload service instance"""
    return YouTubeUploadService()
