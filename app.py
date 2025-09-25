# app.py - Main Flask application
from flask import Flask, request, jsonify
from flask_cors import CORS
import yt_dlp
import re
import os
from functools import wraps
import logging
import requests
from urllib.parse import unquote

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# Configuration
API_KEY = "AAYUSEXDOWNLOADER"  # Change this to your preferred API key
MAX_DURATION = 3600  # Maximum video duration in seconds (1 hour)

def require_api_key(f):
    """Decorator to require API key authentication"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.args.get('apikey')
        if not api_key or api_key != API_KEY:
            return jsonify({
                'error': 'Invalid or missing API key',
                'status': 'failed'
            }), 401
        return f(*args, **kwargs)
    return decorated_function

def extract_video_id(url):
    """Extract YouTube video ID from various URL formats"""
    patterns = [
        r'(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/)([^&\n?#]+)',
        r'youtube\.com/v/([^&\n?#]+)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

def get_video_info(url):
    """Get video information without downloading"""
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extractaudio': False,
            'format': 'best',
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            # Check duration limit
            duration = info.get('duration', 0)
            if duration > MAX_DURATION:
                return None, f"Video too long ({duration}s). Maximum allowed: {MAX_DURATION}s"
            
            return info, None
    except Exception as e:
        return None, str(e)

@app.route('/')
def home():
    """API documentation endpoint"""
    return jsonify({
        'service': 'YouTube Downloader API',
        'version': '1.0.0',
        'endpoints': {
            'download': '/api/youtube-downloader',
            'info': '/api/video-info'
        },
        'usage': {
            'download': '/api/youtube-downloader?url=YOUTUBE_URL&apikey=YOUR_API_KEY&format=mp4&quality=720p',
            'info': '/api/video-info?url=YOUTUBE_URL&apikey=YOUR_API_KEY'
        },
        'parameters': {
            'url': 'YouTube video URL (required)',
            'apikey': 'API authentication key (required)',
            'format': 'Output format: mp4, mp3, webm (optional, default: mp4)',
            'quality': 'Video quality: 144p, 240p, 360p, 480p, 720p, 1080p, best (optional, default: best)'
        }
    })

@app.route('/api/youtube-downloader', methods=['GET'])
@require_api_key
def youtube_downloader():
    """Main YouTube downloader endpoint"""
    try:
        # Get parameters
        url = request.args.get('url')
        format_type = request.args.get('format', 'mp4').lower()
        quality = request.args.get('quality', 'best').lower()
        
        # Validate URL
        if not url:
            return jsonify({
                'error': 'URL parameter is required',
                'status': 'failed'
            }), 400
        
        # URL decode if needed
        url = unquote(url)
        
        # Validate YouTube URL
        video_id = extract_video_id(url)
        if not video_id:
            return jsonify({
                'error': 'Invalid YouTube URL',
                'status': 'failed'
            }), 400
        
        # Get video info first
        info, error = get_video_info(url)
        if error:
            return jsonify({
                'error': error,
                'status': 'failed'
            }), 400
        
        # Configure yt-dlp options based on format
        if format_type == 'mp3':
            ydl_opts = {
                'format': 'bestaudio/best',
                'extractaudio': True,
                'audioformat': 'mp3',
                'quiet': True,
                'no_warnings': True,
            }
        else:
            # Video formats
            if quality == 'best':
                format_selector = 'best'
            elif quality in ['144p', '240p', '360p', '480p', '720p', '1080p']:
                height = quality[:-1]  # Remove 'p'
                format_selector = f'best[height<={height}]'
            else:
                format_selector = 'best'
            
            ydl_opts = {
                'format': format_selector,
                'quiet': True,
                'no_warnings': True,
            }
        
        # Extract download URLs
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            # Get the best matching format
            if 'formats' in info:
                formats = info['formats']
                
                # Filter formats based on request
                filtered_formats = []
                for fmt in formats:
                    if format_type == 'mp3':
                        if fmt.get('acodec') != 'none' and fmt.get('vcodec') == 'none':
                            filtered_formats.append(fmt)
                    else:
                        if fmt.get('vcodec') != 'none':
                            filtered_formats.append(fmt)
                
                # Sort by quality
                if format_type != 'mp3':
                    filtered_formats.sort(key=lambda x: x.get('height', 0), reverse=True)
                else:
                    filtered_formats.sort(key=lambda x: x.get('abr', 0), reverse=True)
                
                download_links = []
                for fmt in filtered_formats[:5]:  # Return top 5 options
                    if fmt.get('url'):
                        link_info = {
                            'format_id': fmt.get('format_id'),
                            'url': fmt['url'],
                            'ext': fmt.get('ext'),
                            'quality': fmt.get('format_note', 'Unknown'),
                            'filesize': fmt.get('filesize'),
                        }
                        
                        if format_type != 'mp3':
                            link_info.update({
                                'resolution': f"{fmt.get('width', 'Unknown')}x{fmt.get('height', 'Unknown')}",
                                'fps': fmt.get('fps'),
                                'vcodec': fmt.get('vcodec'),
                                'acodec': fmt.get('acodec')
                            })
                        else:
                            link_info.update({
                                'bitrate': fmt.get('abr'),
                                'sample_rate': fmt.get('asr')
                            })
                        
                        download_links.append(link_info)
            
            else:
                # Fallback for single URL
                download_links = [{
                    'format_id': 'single',
                    'url': info.get('url', ''),
                    'ext': format_type,
                    'quality': quality,
                }]
            
            response = {
                'status': 'success',
                'video_info': {
                    'id': info.get('id'),
                    'title': info.get('title'),
                    'uploader': info.get('uploader'),
                    'duration': info.get('duration'),
                    'view_count': info.get('view_count'),
                    'description': info.get('description', '')[:500] + '...' if info.get('description', '') else '',
                    'thumbnail': info.get('thumbnail'),
                    'upload_date': info.get('upload_date')
                },
                'download_links': download_links,
                'requested_format': format_type,
                'requested_quality': quality
            }
            
            return jsonify(response)
    
    except Exception as e:
        logger.error(f"Error in youtube_downloader: {str(e)}")
        return jsonify({
            'error': f'Failed to process video: {str(e)}',
            'status': 'failed'
        }), 500

@app.route('/api/video-info', methods=['GET'])
@require_api_key
def video_info():
    """Get video information without download links"""
    try:
        url = request.args.get('url')
        
        if not url:
            return jsonify({
                'error': 'URL parameter is required',
                'status': 'failed'
            }), 400
        
        url = unquote(url)
        
        # Validate YouTube URL
        video_id = extract_video_id(url)
        if not video_id:
            return jsonify({
                'error': 'Invalid YouTube URL',
                'status': 'failed'
            }), 400
        
        # Get video info
        info, error = get_video_info(url)
        if error:
            return jsonify({
                'error': error,
                'status': 'failed'
            }), 400
        
        response = {
            'status': 'success',
            'video_info': {
                'id': info.get('id'),
                'title': info.get('title'),
                'uploader': info.get('uploader'),
                'duration': info.get('duration'),
                'view_count': info.get('view_count'),
                'like_count': info.get('like_count'),
                'description': info.get('description', ''),
                'thumbnail': info.get('thumbnail'),
                'upload_date': info.get('upload_date'),
                'categories': info.get('categories', []),
                'tags': info.get('tags', [])[:10],  # Limit tags
                'webpage_url': info.get('webpage_url')
            }
        }
        
        return jsonify(response)
    
    except Exception as e:
        logger.error(f"Error in video_info: {str(e)}")
        return jsonify({
            'error': f'Failed to get video info: {str(e)}',
            'status': 'failed'
        }), 500

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint for monitoring"""
    return jsonify({
        'status': 'healthy',
        'service': 'YouTube Downloader API',
        'timestamp': str(os.environ.get('RENDER_SERVICE_ID', 'local'))
    })

@app.errorhandler(404)
def not_found(error):
    return jsonify({
        'error': 'Endpoint not found',
        'status': 'failed',
        'available_endpoints': [
            '/api/youtube-downloader',
            '/api/video-info',
            '/health'
        ]
    }), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({
        'error': 'Internal server error',
        'status': 'failed'
    }), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
