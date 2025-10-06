#!/usr/bin/env python3
"""
Trivia Video Generation Control Center
Web UI for managing the complete pipeline
"""

import os
import sys
import json
import time
import threading
import uuid
import re
import csv
import io
import logging
from datetime import datetime, timedelta, timezone

from flask import Flask, render_template, request, jsonify, redirect, url_for, send_from_directory, make_response
from flask_socketio import SocketIO, emit
import google.generativeai as genai
from google.cloud import firestore, storage

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + '/..')

from core.template_manager import TemplateManager
from core import job_stage_contract
from automations.canonical_path_builder import get_path_builder

# Configuration
ENVIRONMENT = os.getenv('ENVIRONMENT', 'dev')
if ENVIRONMENT not in ['dev', 'prod']:
    raise ValueError(f"❌ Invalid ENVIRONMENT: {ENVIRONMENT}. Must be 'dev' or 'prod'")

# GCS Configuration
GCS_BUCKET = f"trivia-{ENVIRONMENT}-assets"

# Firestore Configuration
FIRESTORE_COLLECTION_PREFIX = ENVIRONMENT
ASSETS_COLLECTION = f"{FIRESTORE_COLLECTION_PREFIX}_assets"

# Feature Flags - Environment-specific defaults
PLACEHOLDER_MODE = os.getenv('PLACEHOLDER_MODE', 'true' if ENVIRONMENT == 'dev' else 'false').lower() == 'true'
STRICT_ASSET_CHECK = os.getenv('STRICT_ASSET_CHECK', 'false' if ENVIRONMENT == 'dev' else 'true').lower() == 'true'
AUTO_SEED_BASELINE = os.getenv('AUTO_SEED_BASELINE', 'false').lower() == 'true'

# Production guardrails
if ENVIRONMENT == 'production':
    if PLACEHOLDER_MODE:
        raise ValueError("❌ CRITICAL: Placeholder mode cannot be enabled in production! Set PLACEHOLDER_MODE=false")
    PLACEHOLDER_MODE = False  # Force off in production
    STRICT_ASSET_CHECK = True  # Force on in production
elif ENVIRONMENT == 'staging':
    PLACEHOLDER_MODE = False  # Force off in staging
    STRICT_ASSET_CHECK = True  # Force on in staging

print(f"🔧 Environment: {ENVIRONMENT}")
print(f"🎭 Placeholder Mode: {PLACEHOLDER_MODE}")
print(f"🔒 Strict Asset Check: {STRICT_ASSET_CHECK}")
print(f"🌱 Auto Seed Baseline: {AUTO_SEED_BASELINE}")

# Set up environment
SERVICE_ACCOUNT_PATH = 'secrets/service-account-key.json'
if os.path.exists(SERVICE_ACCOUNT_PATH):
    os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = SERVICE_ACCOUNT_PATH
    print(f"✅ Using service account: {SERVICE_ACCOUNT_PATH}")
else:
    print(f"⚠️ Service account key not found at {SERVICE_ACCOUNT_PATH}")
    print("   Using default credentials or environment variable")

app = Flask(__name__, template_folder='../templates', static_folder='../static')
app.config['SECRET_KEY'] = 'trivia-control-center-2024'
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB max file size
socketio = SocketIO(app, cors_allowed_origins="*")
# ------------------------------------------------------------
# Editor build/manifest utilities
# ------------------------------------------------------------
import json
import hashlib
from pathlib import Path
# from automations.video_frame_extractor import VideoFrameExtractor  # Module not available

STATIC_EDITOR_DIR = Path(__file__).parent / 'static' / 'editor'
STATIC_EDITOR_SRC = STATIC_EDITOR_DIR / 'src'
STATIC_EDITOR_MANIFEST = STATIC_EDITOR_DIR / 'manifest.json'
STATIC_REFERENCE_DIR = Path(__file__).parent / 'static' / 'reference'


def _content_hash(content: bytes) -> str:
    return hashlib.sha1(content).hexdigest()[:16]


def build_editor_assets() -> dict:
    """Build editor transport assets into content-hashed files and write manifest.json.

    This is intentionally minimal: it takes src/editor.js and src/editor.css (if present),
    emits editor.min.[HASH].js and editor.min.[HASH].css, and writes a manifest mapping.
    If src files are missing, it creates small defaults sufficient for transport controls.
    """
    STATIC_EDITOR_DIR.mkdir(parents=True, exist_ok=True)
    STATIC_EDITOR_SRC.mkdir(parents=True, exist_ok=True)

    # Defaults if not present
    default_js = (
        "window.__EDITOR_TRANSPORT__ = (function(){\n"
        "  function qs(sel){return document.querySelector(sel);}\n"
        "  function fmt(t){t=Math.max(0, t||0); var m=Math.floor(t/60); var s=Math.floor(t%60); return m+':' + String(s).padStart(2,'0');}\n"
        "  function init(){\n"
        "    const v = qs('#bgVideo'); if(!v) return; v.muted = true;\n"
        "    const play = qs('[data-transport=play]'); const pause = qs('[data-transport=pause]');\n"
        "    const cur = qs('[data-transport=current]'); const dur = qs('[data-transport=duration]');\n"
        "    const slider = qs('[data-transport=seek]'); const mute = qs('[data-transport=mute]');\n"
        "    function sync(){ if(!isNaN(v.duration)){ dur.textContent = fmt(v.duration);} cur.textContent = fmt(v.currentTime); if(!isNaN(v.duration)){ slider.max = v.duration; slider.value = v.currentTime; } }\n"
        "    v.addEventListener('loadedmetadata', sync); v.addEventListener('timeupdate', sync);\n"
        "    if(play) play.onclick = ()=>v.play(); if(pause) pause.onclick = ()=>v.pause();\n"
        "    if(slider){ slider.oninput = (e)=>{ v.currentTime = Number(e.target.value)||0; }; }\n"
        "    if(mute){ mute.onclick = ()=>{ v.muted = !v.muted; mute.setAttribute('data-muted', String(v.muted)); }; }\n"
        "    document.addEventListener('keydown', (e)=>{\n"
        "      if(e.target && (e.target.tagName==='INPUT' || e.target.tagName==='TEXTAREA')) return;\n"
        "      if(e.code==='Space'){ e.preventDefault(); if(v.paused) v.play(); else v.pause(); }\n"
        "      if(e.key==='j' || e.key==='J'){ v.currentTime = Math.max(0, v.currentTime-10); }\n"
        "      if(e.key==='k' || e.key==='K'){ v.pause(); }\n"
        "      if(e.key==='l' || e.key==='L'){ v.currentTime = Math.min(v.duration||0, v.currentTime+10); }\n"
        "      if(e.key==='ArrowLeft'){ if(e.shiftKey){ v.currentTime = Math.max(0, v.currentTime-0.1);} else { v.currentTime = Math.max(0, v.currentTime-1);} }\n"
        "      if(e.key==='ArrowRight'){ if(e.shiftKey){ v.currentTime = Math.min(v.duration||0, v.currentTime+0.1);} else { v.currentTime = Math.min(v.duration||0, v.currentTime+1);} }\n"
        "    });\n"
        "  }\n"
        "  if(document.readyState==='loading'){ document.addEventListener('DOMContentLoaded', init); } else { init(); }\n"
        "  return { fmt: fmt };\n"
        "})();\n"
    ).encode('utf-8')

    default_css = (
        ".editor-transport{display:flex;gap:8px;align-items:center;padding:8px;background:rgba(0,0,0,0.6);border-radius:8px;}\n"
        ".editor-transport button{padding:4px 8px;border:none;border-radius:6px;background:#2d6cdf;color:#fff;cursor:pointer;}\n"
        ".editor-transport .time{color:#fff;font:12px/1 monospace;}\n"
        ".editor-transport input[type=range]{width:220px;}\n"
    ).encode('utf-8')

    js_src = (STATIC_EDITOR_SRC / 'editor.js')
    css_src = (STATIC_EDITOR_SRC / 'editor.css')
    if not js_src.exists():
        js_src.write_bytes(default_js)
    if not css_src.exists():
        css_src.write_bytes(default_css)

    js_bytes = js_src.read_bytes()
    css_bytes = css_src.read_bytes()
    js_hash = _content_hash(js_bytes)
    css_hash = _content_hash(css_bytes)
    js_out = STATIC_EDITOR_DIR / f'editor.min.{js_hash}.js'
    css_out = STATIC_EDITOR_DIR / f'editor.min.{css_hash}.css'
    js_out.write_bytes(js_bytes)
    css_out.write_bytes(css_bytes)

    # Single source of truth manifest with absolute paths and build_id
    manifest = {
        'js': f"/static/editor/{js_out.name}",
        'css': f"/static/editor/{css_out.name}",
        'build_id': js_hash
    }
    STATIC_EDITOR_MANIFEST.write_text(json.dumps(manifest, indent=2))
    return manifest


def load_editor_manifest() -> dict:
    try:
        if not STATIC_EDITOR_MANIFEST.exists():
            return build_editor_assets()
        return json.loads(STATIC_EDITOR_MANIFEST.read_text())
    except Exception:
        return build_editor_assets()


# Initialize clients
firestore_client = firestore.Client()
jobs_collection = firestore_client.collection(f"{FIRESTORE_COLLECTION_PREFIX}_jobs")
assets_collection = firestore_client.collection(ASSETS_COLLECTION)
channels_collection = firestore_client.collection("video_channels")
templates_collection = firestore_client.collection(f"{FIRESTORE_COLLECTION_PREFIX}_templates")
template_versions_collection = firestore_client.collection("video_template_versions")
storage_client = storage.Client()

# Initialize Apple-clean GCS manager (lazy initialization)
gcs_manager = None
channel_manager = None

# Reference frame service
# frame_extractor = VideoFrameExtractor(ENVIRONMENT)  # Module not available
STATIC_REFERENCE_DIR.mkdir(parents=True, exist_ok=True)

@app.route('/api/editor/reference-frame', methods=['POST'])
def create_reference_frame():
    try:
        data = request.get_json(force=True) or {}
        asset_id = data.get('asset_id')
        channel_id = data.get('channel_id') or 'shared'
        ts = float(data.get('timestamp_s') or 10.0)
        if not asset_id:
            return jsonify({'error': 'asset_id required'}), 400
        asset_ref = firestore_client.collection(f"{FIRESTORE_COLLECTION_PREFIX}_assets").document(asset_id)
        asset_doc = asset_ref.get()
        if not asset_doc.exists:
            return jsonify({'error': 'Asset not found'}), 404
        asset = asset_doc.to_dict()
        out_dir = STATIC_REFERENCE_DIR / channel_id / asset_id
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{int(ts*1000)}.png"
        if not out_path.exists():
            ok = frame_extractor.extract_frame_from_asset(asset, ts, str(out_path))
            if not ok:
                return jsonify({'error': 'Failed to extract frame'}), 500
        rel_url = f"/static/reference/{channel_id}/{asset_id}/{out_path.name}"
        duration = frame_extractor.get_video_duration(asset) or None
        return jsonify({'success': True, 'png_url': rel_url, 'duration_s': duration})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def get_gcs_manager():
    """Get GCS manager with lazy initialization"""
    global gcs_manager
    if gcs_manager is None:
        gcs_manager = AppleCleanGCSManager(ENVIRONMENT)
    return gcs_manager

def get_channel_manager(environment='dev'):
    """Get channel manager with lazy initialization for specific environment"""
    global channel_manager
    if channel_manager is None or channel_manager.environment != environment:
        # Simple channel manager implementation
        class SimpleChannelManager:
            def __init__(self, environment):
                self.environment = environment
                self.firestore_client = firestore_client
                self.channels_collection = self.firestore_client.collection("video_channels")
            
            def get_channels(self):
                """Get all channels"""
                try:
                    channels = []
                    for doc in self.channels_collection.stream():
                        channel_data = doc.to_dict()
                        channel_data['id'] = doc.id
                        channels.append(channel_data)
                    return channels
                except Exception as e:
                    print(f"Error getting channels: {e}")
                    return []
            
            def get_all_channels(self):
                """Get all channels (alias for get_channels)"""
                return self.get_channels()
            
            def get_channel_assets(self, channel_id, asset_type=None):
                """Get assets for a specific channel"""
                try:
                    # Query assets collection for the specific channel
                    assets_query = assets_collection.where('channel_id', '==', channel_id)
                    
                    if asset_type:
                        assets_query = assets_query.where('type', '==', asset_type)
                    
                    assets = []
                    for doc in assets_query.stream():
                        asset_data = doc.to_dict()
                        asset_data['id'] = doc.id
                        assets.append(asset_data)
                    
                    return assets
                except Exception as e:
                    print(f"Error getting channel assets: {e}")
                    return []
        
        channel_manager = SimpleChannelManager(environment)
    return channel_manager

# Health check functions
def check_database_health():
    """Check database connectivity"""
    try:
        # Test Firestore connection
        firestore_client.collection("_health_check").limit(1).get()
        return "connected"
    except Exception as e:
        print(f"Database health check failed: {e}")
        return "disconnected"

def check_storage_health():
    """Check storage connectivity"""
    try:
        # Test GCS connection
        bucket = storage_client.bucket(GCS_BUCKET)
        bucket.exists()
        return "connected"
    except Exception as e:
        print(f"Storage health check failed: {e}")
        return "disconnected"

def validate_gcs_write(gcs_uri: str, environment: str = None) -> tuple[bool, str]:
    """
    Validate GCS write operation - block bad writes
    Returns: (is_valid, error_message)
    """
    if environment is None:
        environment = os.getenv('ENVIRONMENT', 'dev')
    
    # Check bucket name
    expected_bucket = f"trivia-{environment}-assets"
    if not gcs_uri.startswith(f"gs://{expected_bucket}/"):
        return False, f"FORBIDDEN_BUCKET: Must use {expected_bucket}"
    
    # Check path prefix
    path_builder = get_path_builder(environment)
    if not path_builder.validate_path(gcs_uri):
        return False, "FORBIDDEN_PREFIX: Path must start with shared/, channels/, generated/, logs/, or temp/"
    
    return True, ""

def get_off_schema_objects():
    """Get count and examples of off-schema GCS objects"""
    try:
        path_builder = get_path_builder()
        bucket = storage_client.bucket(path_builder.bucket_name)
        
        off_schema_count = 0
        off_schema_examples = []
        
        # List all objects
        all_objects = bucket.list_blobs()
        
        for blob in all_objects:
            gcs_uri = f"gs://{path_builder.bucket_name}/{blob.name}"
            
            if not path_builder.validate_path(gcs_uri):
                off_schema_count += 1
                if len(off_schema_examples) < 10:  # Keep first 10 examples
                    off_schema_examples.append(gcs_uri)
        
        return off_schema_count, off_schema_examples
        
    except Exception as e:
        print(f"Error getting off-schema objects: {e}")
        return 0, []

def get_pipeline_status():
    """Get pipeline status"""
    global pipeline_manager
    
    if pipeline_manager is None:
        return {"running": False, "status": "stopped", "jobs": [], "queue_size": 0}
    
    try:
        result = pipeline_manager.get_status()
        # Ensure backward compatibility
        if "running" in result:
            result["status"] = "running" if result["running"] else "stopped"
        return result
    except Exception as e:
        print(f"Error getting pipeline status: {e}")
        return {"running": False, "status": "error", "jobs": [], "queue_size": 0}

def check_pipeline_health():
    """Check pipeline status"""
    try:
        # Check if pipeline is running
        pipeline_status = get_pipeline_status()
        return "ready" if pipeline_status.get("status") == "running" else "stopped"
    except Exception as e:
        print(f"Pipeline health check failed: {e}")
        return "error"

def validate_template_assets(template_id, template_data):
    """Validate all required assets for a template using new contract"""
    missing_assets = []
    placeholder_used = []
    
    # Check required fields for template contract
    required_fields = ['state', 'version', 'asset_refs', 'layout', 'styles', 'timing']
    missing_fields = []
    
    for field in required_fields:
        if field not in template_data:
            missing_fields.append(field)
    
    if missing_fields:
        return missing_fields, placeholder_used
    
    # Validate asset_refs (must be asset IDs, not URIs)
    asset_refs = template_data.get('asset_refs', {})
    if not asset_refs:
        missing_assets.append("asset_refs (empty)")
        return missing_assets, placeholder_used
    
    # Validate each asset reference
    for asset_type, asset_id in asset_refs.items():
        if not asset_id:
            missing_assets.append(f"{asset_type} (empty asset ID)")
            continue
        
        # Check if asset ID is valid format (starts with asset_)
        if not asset_id.startswith('asset_'):
            missing_assets.append(f"{asset_type} (invalid asset ID format: {asset_id})")
            continue
        
        # Check if asset exists in Firestore
        try:
            asset_ref = firestore_client.collection(f"{FIRESTORE_COLLECTION_PREFIX}_assets").document(asset_id)
            asset_doc = asset_ref.get()
            
            if not asset_doc.exists:
                missing_assets.append(f"{asset_type} (asset {asset_id} not found)")
                continue
            
            asset_data = asset_doc.to_dict()
            gcs_path = asset_data.get('gcs_path')
            
            if not gcs_path:
                missing_assets.append(f"{asset_type} (asset {asset_id} has no gcs_path)")
                continue
            
            # Validate GCS path format
            if not gcs_path.startswith('gs://'):
                missing_assets.append(f"{asset_type} (asset {asset_id} has invalid gcs_path)")
                continue
            
            # Check if asset exists in GCS
            bucket_name = gcs_path.split('/')[2]
            blob_name = '/'.join(gcs_path.split('/')[3:])
            
            bucket = storage_client.bucket(bucket_name)
            blob = bucket.blob(blob_name)
            
            if not blob.exists():
                missing_assets.append(f"{asset_type} (not found: {gcs_path})")
            else:
                print(f"✅ Asset validated: {asset_type} -> {asset_id} -> {gcs_path}")
        except Exception as e:
            missing_assets.append(f"{asset_type} (error checking: {str(e)})")
    
    return missing_assets, placeholder_used

def create_placeholder_asset(asset_type, template_id):
    """Create a temporary placeholder asset (dev only)"""
    if not PLACEHOLDER_MODE:
        return None
        
    # Create placeholder data in memory (no file storage)
    placeholder_data = {
        'type': asset_type,
        'template_id': template_id,
        'is_placeholder': True,
        'created_at': datetime.utcnow().isoformat() + "Z",
        'placeholder_reason': f'Missing {asset_type} asset'
    }
    
    print(f"🎭 Created placeholder for {asset_type} in template {template_id}")
    return placeholder_data

def seed_baseline_template():
    """Seed baseline template if it doesn't exist"""
    if not AUTO_SEED_BASELINE:
        print("🌱 Auto-seeding disabled")
        return

    baseline_id = "test-sport-template"

    try:
        baseline_ref = templates_collection.document(baseline_id)
        existing_template = baseline_ref.get()

        if existing_template.exists:
            print(f"🌱 Baseline template '{baseline_id}' already exists - skipping seed")
            return

        template_data = {
            'id': baseline_id,
            'name': 'Test Sport Template',
            'description': 'Baseline sports template with question overlay and answer boxes',
            'category': 'sports',
            'status': 'active',
            'environment': ENVIRONMENT,
            'layout': {
                'video': {
                    'resolution': '1280x720',
                    'fps': 24,
                    'format': 'mp4'
                },
                'question_box': {
                    'x': 133,
                    'y': 50,
                    'width': 1000,
                    'height': 117,
                    'background_color': '#00AA00',
                    'stroke_color': '#000000',
                    'stroke_width': 2
                },
                'answer_boxes': [
                    {'id': 'A', 'x': 279, 'y': 262, 'width': 308, 'height': 131},
                    {'id': 'B', 'x': 775, 'y': 259, 'width': 308, 'height': 133},
                    {'id': 'C', 'x': 276, 'y': 462, 'width': 293, 'height': 120},
                    {'id': 'D', 'x': 775, 'y': 463, 'width': 312, 'height': 119}
                ],
                'fonts': {
                    'question': {
                        'font_family': 'liberation_bold',
                        'font_size': 56,
                        'text_color': '#FFFFFF',
                        'stroke_color': '#000000',
                        'stroke_width': 2
                    },
                    'answer': {
                        'font_family': 'liberation_regular',
                        'font_size': 48,
                        'text_color': '#000000'
                    }
                }
            },
            'assets': {
                'backgrounds': [
                    'gs://trivia-dev-assets/channels/test-sport-trivia/assets/backgrounds/sport-bg-1.mp4',
                    'gs://trivia-dev-assets/channels/test-sport-trivia/assets/backgrounds/sport-bg-2.mp4',
                    'gs://trivia-dev-assets/channels/test-sport-trivia/assets/backgrounds/sports-bg-3.mp4',
                    'gs://trivia-dev-assets/channels/test-sport-trivia/assets/backgrounds/sports-bg-4.mp4',
                    'gs://trivia-dev-assets/channels/test-sport-trivia/assets/backgrounds/sports-bg-5.mp4'
                ],
                'transitions': [
                    'gs://trivia-dev-assets/channels/test-sport-trivia/assets/transitions/1.mp4'
                ],
                # Intro and outro will be randomly selected from channel folders
            },
            'styles': {},
            'timing': {},
            'created_at': datetime.utcnow().isoformat() + "Z",
            'updated_at': datetime.utcnow().isoformat() + "Z"
        }

        baseline_ref.set(template_data)
        print(f"🌱 Seeded baseline template '{baseline_id}' successfully")

    except Exception as e:
        print(f"❌ Failed to seed baseline template: {e}")

# Import the new pipeline manager
from core.pipeline_manager import PipelineManager

# Global state
# Global variables for pipeline management
pipeline_manager = None

print("🔧 Initializing global variables...")
current_channel_id = None

class TriviaControlCenter:
    """Main control center class"""
    
    def __init__(self):
        # Expose shared Firestore collections for downstream components
        self.jobs_collection = jobs_collection
        self.templates_collection = templates_collection
        self.channels_collection = channels_collection
        self.storage_client = storage_client
        
        self.logger = logging.getLogger(__name__)

        self.gemini_api_key = os.environ.get("GEMINI_API_KEY")
        if self.gemini_api_key:
            genai.configure(api_key=self.gemini_api_key)
            self.gemini_model = genai.GenerativeModel('gemini-1.5-flash')
        else:
            self.gemini_model = None
    
    def generate_questions_with_gemini(self, num_questions=5):
        """Generate questions using Gemini AI"""
        if not self.gemini_model:
            return None, "Gemini API key not configured"
        
        prompt = f"""
        Generate {num_questions} interesting trivia questions about science, history, or general knowledge.
        Each question should have 4 multiple choice answers (A, B, C, D) with one correct answer.
        
        Return ONLY a valid JSON array with objects containing these exact fields:
        - question: The trivia question text
        - answer_a: First answer option
        - answer_b: Second answer option  
        - answer_c: Third answer option
        - answer_d: Fourth answer option
        - correct_answer: The correct letter (A, B, C, or D)
        - explanation: Brief explanation of the correct answer
        
        Example format:
        [
          {{
            "question": "What is the largest planet in our solar system?",
            "answer_a": "Earth",
            "answer_b": "Jupiter",
            "answer_c": "Saturn", 
            "answer_d": "Neptune",
            "correct_answer": "B",
            "explanation": "Jupiter is the largest planet in our solar system."
          }}
        ]
        
        Make the questions engaging and educational. Return ONLY the JSON array, no other text.
        """
        
        try:
            response = self.gemini_model.generate_content(prompt)
            questions_text = response.text.strip()
            
            # Clean up response
            if questions_text.startswith('```json'):
                questions_text = questions_text[7:]
            if questions_text.endswith('```'):
                questions_text = questions_text[:-3]
            questions_text = questions_text.strip()
            
            questions = json.loads(questions_text)
            return questions, None
            
        except Exception as e:
            return None, f"Error generating questions: {str(e)}"
    
    def create_job(self, questions_data, job_id=None, use_production=False, channel_id=None, template_id=None):
        """Create a job in Firestore"""
        if not job_id:
            job_id = f"trivia_job_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        job_data = {
            "jobId": job_id,
            "status": "local_pending",  # Always use local_pending for server processing
            "stage": "pending",  # Set initial stage for split-worker pipeline
            "input_data": {
                "questions": questions_data,  # Store questions in input_data like other functions!
            },
            "createdAt": firestore.SERVER_TIMESTAMP,
            "updatedAt": firestore.SERVER_TIMESTAMP,
            "gcsVideoPath": None,
            "processingTime": 0,
            "error": None,
            "progress": 0,
            "estimatedTimeRemaining": None,
            "localProcessing": True,  # Always set to True for server processing
            "use_production": True,  # Always use unified pipeline
            "channel_id": channel_id,
            "template_id": template_id
        }
        
        jobs_collection.document(job_id).set(job_data)
        return job_id
    
    def create_job_from_data(self, job_data):
        """Create a job in Firestore from complete job data"""
        job_id = job_data.get('job_id') or f"job_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        job_data['id'] = job_id
        jobs_collection.document(job_id).set(job_data)
        return job_id
    
    def get_all_jobs(self, limit: int | None = None):
        """Get jobs ordered by creation time descending."""
        jobs = []
        
        # Get all jobs without ordering first (to handle both createdAt and created_at)
        all_docs = jobs_collection.stream()
        
        for doc in all_docs:
            job_data = doc.to_dict()
            job_data['id'] = doc.id
            
            # Normalize timestamp fields (support both camelCase and snake_case)
            created = job_data.get('createdAt') or job_data.get('created_at')
            updated = job_data.get('updatedAt') or job_data.get('updated_at')
            
            if created:
                if hasattr(created, 'isoformat'):
                    job_data['createdAt'] = created.isoformat()
                    job_data['created_at'] = created.isoformat()
                else:
                    job_data['createdAt'] = created
                    job_data['created_at'] = created
            
            if updated:
                if hasattr(updated, 'isoformat'):
                    job_data['updatedAt'] = updated.isoformat()
                    job_data['updated_at'] = updated.isoformat()
                else:
                    job_data['updatedAt'] = updated
                    job_data['updated_at'] = updated
            
            jobs.append(job_data)
        
        # Sort by created_at or createdAt (descending)
        jobs.sort(key=lambda j: j.get('created_at') or j.get('createdAt') or '', reverse=True)
        
        # Apply limit if specified
        if limit:
            jobs = jobs[:limit]
        
        return jobs
    
    def get_job(self, job_id):
        """Get a specific job"""
        doc = jobs_collection.document(job_id).get()
        if doc.exists:
            job_data = doc.to_dict()
            job_data['id'] = doc.id
            return job_data
        return None
    
    def update_job_status(self, job_id, status, **kwargs):
        """Update job status with explicit stage/heartbeat control."""
        update_data = {
            "status": status,
            "updatedAt": firestore.SERVER_TIMESTAMP,
        }

        stage_value = kwargs.pop("stage", None)
        stage_entered = kwargs.pop("stageEnteredAt", None)
        heartbeat = kwargs.pop("lastHeartbeatAt", None)
        previous_stage = kwargs.pop("previous_stage", None)

        if previous_stage is None and stage_value is not None:
            try:
                existing_doc = jobs_collection.document(job_id).get()
                if existing_doc.exists:
                    previous_stage = existing_doc.to_dict().get("stage")
            except Exception:
                previous_stage = None

        if stage_value is not None:
            from core import job_stage_contract as stage_contract

            normalized_stage = stage_contract.normalize_stage(stage_value)
            update_data["stage"] = normalized_stage

            default_progress = stage_contract.get_progress_for_stage(normalized_stage)
            if "progress" not in kwargs and default_progress is not None:
                update_data["progress"] = default_progress

            try:
                transition_ok = stage_contract.is_forward_transition(previous_stage, normalized_stage)
            except stage_contract.StageContractError as exc:
                transition_ok = True
                self.logger.warning(
                    "⚠️ Stage transition validation error",
                    extra={
                        "job_id": job_id,
                        "from": previous_stage,
                        "to": normalized_stage,
                        "error": str(exc),
                    },
                )
            if not transition_ok:
                self.logger.warning(
                    "⚠️ Non-forward stage transition detected",
                    extra={
                        "job_id": job_id,
                        "from": previous_stage,
                        "to": normalized_stage,
                    },
                )

            timestamp_source = stage_entered or datetime.utcnow().isoformat() + "Z"
            update_data["stageEnteredAt"] = timestamp_source
            update_data.update(stage_contract.stage_specific_timestamps(normalized_stage, timestamp_source))

        if heartbeat is not None:
            update_data["lastHeartbeatAt"] = heartbeat
        else:
            update_data.setdefault("lastHeartbeatAt", datetime.utcnow().isoformat() + "Z")

        if stage_value is None and stage_entered:
            update_data["stageEnteredAt"] = stage_entered

        update_data.update(kwargs)
        jobs_collection.document(job_id).update(update_data)
    
    def delete_job(self, job_id):
        """Delete a job"""
        jobs_collection.document(job_id).delete()
    
    def parse_csv_questions(self, csv_content):
        """Parse CSV content into questions format"""
        questions = []
        try:
            csv_file = io.StringIO(csv_content)
            reader = csv.DictReader(csv_file)
            
            for row in reader:
                def _norm(s: str):
                    if not s:
                        return s
                    s = s.replace("''", "'").replace('""', '"')
                    s = s.replace("\"'", "'").replace("'\"", "'")
                    s = ' '.join(s.split())
                    return s

                question = {
                    'question': _norm(row.get('question', '')),
                    'answer_a': _norm(row.get('answer_a', '')),
                    'answer_b': _norm(row.get('answer_b', '')),
                    'answer_c': _norm(row.get('answer_c', '')),
                    'answer_d': _norm(row.get('answer_d', '')),
                    'correct_answer': _norm(row.get('correct_answer', 'A')),
                    'explanation': _norm(row.get('explanation', ''))
                }
                questions.append(question)
            
            return questions, None
        except Exception as e:
            return None, f"Error parsing CSV: {str(e)}"
    
    def upload_asset(self, file, asset_name, asset_type, asset_category="general", channel_id=None):
        """Upload asset to GCS and store metadata in Firestore"""
        try:
            # Generate unique asset ID
            asset_id = f"asset_{uuid.uuid4().hex[:8]}"
            
            # Use provided channel_id or fall back to global
            if not channel_id:
                global current_channel_id
                channel_id = current_channel_id
            
            if not channel_id:
                return None, "No channel selected"
            
            # Get channel data from Firestore
            channel_doc = channels_collection.document(channel_id).get()
            if not channel_doc.exists:
                return None, f"Channel {channel_id} not found"
            
            channel_data = channel_doc.to_dict()
            bucket_name = channel_data.get('gcs_bucket')
            folders = channel_data.get('folders', {})
            
            if not bucket_name:
                return None, f"No GCS bucket specified for channel {channel_id}"
            
            # Determine GCS path based on asset type and channel folders
            if asset_type == "background":
                gcs_path = f"{folders.get('backgrounds', '')}/{asset_name}"
            elif asset_type == "audio":
                gcs_path = f"{folders.get('audio', '')}/{asset_name}"
            elif asset_type == "overlay":
                gcs_path = f"{folders.get('overlays', '')}/{asset_name}"
            elif asset_type == "intro":
                gcs_path = f"{folders.get('intros', '')}/{asset_name}"
            elif asset_type == "outro":
                gcs_path = f"{folders.get('outros', '')}/{asset_name}"
            elif asset_type == "transition":
                gcs_path = f"{folders.get('transitions', '')}/{asset_name}"
            else:
                gcs_path = f"channels/{channel_id}/{asset_name}"
            
            # Validate GCS path before upload
            full_gcs_uri = f"gs://{bucket_name}/{gcs_path}"
            is_valid, error_msg = validate_gcs_write(full_gcs_uri)
            if not is_valid:
                return None, f"GCS write validation failed: {error_msg}"
            
            # Upload to GCS using channel's bucket
            bucket = storage_client.bucket(bucket_name)
            blob = bucket.blob(gcs_path)
            blob.upload_from_file(file, content_type=file.content_type)
            
            # Make the asset publicly accessible
            blob.make_public()
            
            # Store metadata in Firestore
            asset_data = {
                "id": asset_id,
                "name": asset_name,
                "type": asset_type,
                "category": asset_category,
                "channel_id": channel_id,
                "gcs_path": gcs_path,
                "gcs_url": blob.public_url,
                "file_size": file.content_length,
                "content_type": file.content_type,
                "uploaded_at": firestore.SERVER_TIMESTAMP,
                "status": "active",
                "is_test_asset": asset_category == "test-assets"
            }
            
            assets_collection.document(asset_id).set(asset_data)
            
            # Return serializable data for JSON response
            return_data = {
                "id": asset_id,
                "name": asset_name,
                "type": asset_type,
                "category": asset_category,
                "channel_id": channel_id,
                "gcs_path": gcs_path,
                "gcs_url": blob.public_url,
                "file_size": file.content_length,
                "content_type": file.content_type,
                "uploaded_at": datetime.now().isoformat(),
                "status": "active",
                "is_test_asset": asset_category == "test-assets"
            }
            
            print(f"✅ Asset uploaded: {asset_name} -> {gcs_path}")
            return return_data, None
            
        except Exception as e:
            return None, f"Error uploading asset: {str(e)}"
    
    def get_all_assets(self):
        """Get all assets from Firestore"""
        assets = []
        docs = assets_collection.order_by("uploaded_at", direction=firestore.Query.DESCENDING).stream()
        
        for doc in docs:
            asset_data = doc.to_dict()
            asset_data['id'] = doc.id
            assets.append(asset_data)
        
        return assets
    
    def delete_asset(self, asset_id):
        """Delete asset from GCS and Firestore"""
        try:
            # Get asset data from the correct collection
            assets_ref = firestore_client.collection(f"{FIRESTORE_COLLECTION_PREFIX}_assets")
            doc = assets_ref.document(asset_id).get()
            if not doc.exists:
                return False, "Asset not found"
            
            asset_data = doc.to_dict()
            
            # Delete from GCS (ignore if not found)
            try:
                bucket = storage_client.bucket(GCS_ASSETS_BUCKET)
                blob = bucket.blob(asset_data['gcs_path'])
                blob.delete()
                print(f"🗑️ Deleted from GCS: {asset_data['gcs_path']}")
            except Exception as gcs_error:
                print(f"⚠️ GCS deletion failed (may not exist): {gcs_error}")
            
            # Delete from Firestore
            assets_ref.document(asset_id).delete()
            
            print(f"✅ Asset deleted: {asset_data['name']} (ID: {asset_id})")
            return True, None
            
        except Exception as e:
            return False, f"Error deleting asset: {str(e)}"
    
    def get_asset_config(self):
        """Get asset configuration for video pipeline"""
        assets = self.get_all_assets()
        
        # Group assets by type
        config = {
            "backgrounds": [],
            "audio": [],
            "overlays": [],
            "intros": [],
            "outros": [],
            "transitions": [],
            "test_assets": []
        }
        
        for asset in assets:
            if asset.get('is_test_asset'):
                config["test_assets"].append(asset)
            elif asset['type'] == 'background':
                config["backgrounds"].append(asset)
            elif asset['type'] == 'audio':
                config["audio"].append(asset)
            elif asset['type'] == 'overlay':
                config["overlays"].append(asset)
            elif asset['type'] == 'intro':
                config["intros"].append(asset)
            elif asset['type'] == 'outro':
                config["outros"].append(asset)
            elif asset['type'] == 'transition':
                config["transitions"].append(asset)
        
        return config

# Initialize control center
control_center = TriviaControlCenter()

# Initialize template manager
# Use the backup TemplateManager which includes preview/background helpers
from core.template_manager import TemplateManager as BackupTemplateManager
template_manager = BackupTemplateManager()

# Routes
# Health Endpoints
@app.route('/health')
def health_check():
    """System health check endpoint"""
    try:
        database_status = check_database_health()
        storage_status = check_storage_health()
        pipeline_status = check_pipeline_health()
        
        overall_status = "healthy" if all([
            database_status == "connected",
            storage_status == "connected",
            pipeline_status in ["ready", "stopped"]
        ]) else "unhealthy"
        
        return jsonify({
            "status": overall_status,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "version": "5.0",
            "environment": ENVIRONMENT,
            "services": {
                "database": database_status,
                "storage": storage_status,
                "pipeline": pipeline_status
            }
        }), 200
    except Exception as e:
        return jsonify({
            "error": f"Health check failed: {str(e)}",
            "code": "HEALTH_CHECK_FAILED",
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }), 500

@app.route('/health/pipeline')
def health_pipeline():
    """Pipeline-specific health check"""
    try:
        pipeline_status = get_pipeline_status()
        active_jobs = len([job for job in pipeline_status.get("jobs", []) if job.get("status") == "processing"])
        
        return jsonify({
            "status": pipeline_status.get("status", "unknown"),
            "active_jobs": active_jobs,
            "queue_size": pipeline_status.get("queue_size", 0),
            "last_processed": pipeline_status.get("last_processed")
        }), 200
    except Exception as e:
        return jsonify({
            "error": f"Pipeline health check failed: {str(e)}",
            "code": "PIPELINE_HEALTH_FAILED",
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }), 500

@app.route('/health/ready')
def health_ready():
    """Readiness check with placeholder warnings"""
    try:
        pipeline_status = get_pipeline_status()
        warnings = []
        
        if PLACEHOLDER_MODE:
            warnings.append("Placeholder mode is enabled - assets may be substituted")
        
        if ENVIRONMENT == 'dev':
            warnings.append("Development environment - data may be reset")
        elif ENVIRONMENT == 'prod':
            warnings.append("Production environment - strict asset validation enabled")
        
        # Get off-schema count and examples
        path_builder = get_path_builder()
        off_schema_count, off_schema_examples = get_off_schema_objects()
        
        # Get publish guard status
        publish_guard_status = "OK"
        try:
            templates_ref = firestore_client.collection(f"{FIRESTORE_COLLECTION_PREFIX}_templates")
            published_templates = templates_ref.where('state', '==', 'published').stream()
            
            for template_doc in published_templates:
                template_data = template_doc.to_dict()
                asset_refs = template_data.get('asset_refs', {})
                
                for asset_type, asset_id in asset_refs.items():
                    asset_ref = firestore_client.collection(f"{FIRESTORE_COLLECTION_PREFIX}_assets").document(asset_id)
                    if not asset_ref.get().exists:
                        publish_guard_status = f"Template {template_doc.id} references missing asset {asset_id}"
                        break
        except Exception as e:
            publish_guard_status = f"Error checking publish guard: {str(e)}"
        
        return jsonify({
            "ready": True,
            "status": pipeline_status.get("status", "unknown"),
            "environment": ENVIRONMENT,
            "placeholder_mode": PLACEHOLDER_MODE,
            "strict_asset_check": STRICT_ASSET_CHECK,
            "off_schema_count": off_schema_count,
            "off_schema_examples": off_schema_examples[:5],  # First 5 examples
            "publish_guard": publish_guard_status,
            "warnings": warnings,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }), 200
    except Exception as e:
        return jsonify({
            "ready": False,
            "error": f"Readiness check failed: {str(e)}",
            "code": "READINESS_CHECK_FAILED",
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }), 500

@app.route('/static/<path:filename>')
def static_files(filename):
    """Serve static files"""
    return send_from_directory('static', filename)

@app.route('/test-template-creation')
def test_template_creation():
    """Test page for template creation debugging"""
    return send_from_directory('.', 'test_template_creation.html')

@app.route('/')
def index():
    """New Apple-inspired dashboard (default)"""
    import time
    return render_template('dashboard_new.html', timestamp=int(time.time()))

@app.route('/legacy')
def legacy_dashboard():
    """Original dashboard (preserved as backup)"""
    import time
    return render_template('dashboard.html', timestamp=int(time.time()))

@app.route('/new')
def new_dashboard():
    """New Apple-inspired dashboard"""
    import time
    return render_template('dashboard_new.html', timestamp=int(time.time()))

@app.route('/studio')
def template_studio():
    """Template Studio - Drag & Drop Editor"""
    import time
    resp = make_response(render_template('template_studio.html', timestamp=int(time.time())))
    resp.headers['Cache-Control'] = 'no-store'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['Expires'] = '0'
    return resp

@app.route('/channels')
def channel_manager_page():
    """Channel Manager - Production Setup"""
    import time
    return render_template('channel_manager.html', timestamp=int(time.time()))

@app.route('/api/jobs')
def get_jobs():
    """Get all jobs with pagination and filtering"""
    try:
        # Get query parameters
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 20))
        status_filter = request.args.get('status')
        template_id_filter = request.args.get('template_id')
        grouped = request.args.get('grouped', 'false').lower() == 'true'
        
        # Get all jobs
        jobs = control_center.get_all_jobs()
        
        # Apply filters
        if status_filter:
            jobs = [job for job in jobs if job.get('status') == status_filter]
        if template_id_filter:
            jobs = [job for job in jobs if job.get('template_id') == template_id_filter]
        
        # Group jobs by batch_id if they have one (ALWAYS do this)
        batch_groups = {}
        individual_jobs = []
        
        for job in jobs:
            batch_id = job.get('batch_id')
            if batch_id:
                if batch_id not in batch_groups:
                    batch_groups[batch_id] = []
                batch_groups[batch_id].append(job)
            else:
                individual_jobs.append(job)
        
        # Create grouped job list
        grouped_job_list = []
        
        # Add batch groups (each batch becomes one collapsible item)
        for batch_id, batch_jobs in batch_groups.items():
            # Sort by batch_index
            batch_jobs.sort(key=lambda j: j.get('batch_index', 0))
            
            # Calculate batch stats
            batch_statuses = [j.get('status') for j in batch_jobs]
            completed = sum(1 for s in batch_statuses if s == 'completed')
            processing = sum(1 for s in batch_statuses if s == 'processing')
            pending = sum(1 for s in batch_statuses if s == 'pending')
            failed = sum(1 for s in batch_statuses if s == 'failed')
            aborted = sum(1 for s in batch_statuses if s == 'aborted')
            
            # Determine overall batch status
            if all(s == 'completed' for s in batch_statuses):
                batch_status = 'completed'
            elif any(s == 'processing' for s in batch_statuses):
                batch_status = 'processing'
            elif any(s == 'failed' for s in batch_statuses):
                batch_status = 'failed'
            elif any(s == 'aborted' for s in batch_statuses):
                batch_status = 'aborted'
            else:
                batch_status = 'pending'
            
            # Get first job's title for batch title
            first_title = batch_jobs[0].get('youtube_title', 'Bulk Upload Batch')
            
            grouped_job_list.append({
                'batch_id': batch_id,
                'jobs': batch_jobs,
                'total_jobs': len(batch_jobs),
                'completed_jobs': completed,
                'processing_jobs': processing,
                'pending_jobs': pending,
                'failed_jobs': failed,
                'aborted_jobs': aborted,
                'status': batch_status,
                'created_at': batch_jobs[0].get('created_at'),
                'group_title': f"Manifest Batch ({len(batch_jobs)} videos)",
                'is_batch': True
            })
        
        # Add individual jobs
        for job in individual_jobs:
            grouped_job_list.append(job)
        
        # Sort by created_at (most recent first)
        grouped_job_list.sort(key=lambda x: x.get('created_at', ''), reverse=True)
        
        # Calculate pagination
        total = len(grouped_job_list)
        start_idx = (page - 1) * limit
        end_idx = start_idx + limit
        paginated_jobs = grouped_job_list[start_idx:end_idx]
        
        # Transform to new contract format
        formatted_jobs = []
        for job in paginated_jobs:
            # Check if this is a batch group
            if job.get('is_batch'):
                # Pass through batch group as-is (frontend will handle it)
                formatted_jobs.append(job)
            else:
                # Transform individual job
                stage = job.get("stage")
                formatted_job = {
                    "id": job.get("id", str(uuid.uuid4())),
                    "channel_id": job.get("channel_id"),
                    "template_id": job.get("template_id"),
                    "template_version": job.get("template_version", "1.0.0"),
                    "status": job.get("status", "pending"),
                    "stage": stage,
                    "progress": job.get("progress", 0),
                    "stage_progress": job_stage_contract.get_progress_for_stage(stage),
                    "created_at": job.get("createdAt", job.get("created_at", datetime.utcnow().isoformat() + "Z")),
                    "stage_entered_at": job.get("stageEnteredAt"),
                    "last_heartbeat_at": job.get("lastHeartbeatAt"),
                    "timestamps": {
                        "ttsStartedAt": job.get("ttsStartedAt"),
                        "ttsCompletedAt": job.get("ttsCompletedAt"),
                        "renderStartedAt": job.get("renderStartedAt"),
                        "concatStartedAt": job.get("concatStartedAt"),
                        "uploadStartedAt": job.get("uploadStartedAt"),
                        "completed_at": job.get("completed_at"),
                        "failedAt": job.get("failedAt"),
                    },
                    "started_at": job.get("started_at"),
                    "completed_at": job.get("completed_at"),
                    "input_data": job.get("input_data", {}),
                    "output": {
                        "video_url": job.get("output", {}).get("video_url"),
                        "gcs_uri": job.get("output", {}).get("gcs_uri"),
                        "srt_url": job.get("output", {}).get("srt_url"),
                        "duration": job.get("output", {}).get("duration"),
                        "file_size": job.get("output", {}).get("file_size")
                    },
                    "logs": job.get("logs", []),
                    "lastError": job.get("lastError"),
            "retry_count": job.get("retry_count", 0),
            "queue_position": job.get("queue_position"),
                }
                formatted_jobs.append(formatted_job)
        
        return jsonify({
            "jobs": formatted_jobs,
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total,
                "total_pages": (total + limit - 1) // limit
            }
        }), 200
    except Exception as e:
        return jsonify({
            "error": f"Error getting jobs: {str(e)}",
            "code": "JOBS_FETCH_FAILED",
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }), 500

@app.route('/api/jobs/<job_id>/video', methods=['GET'])
def get_job_video(job_id):
    """Get a signed URL for the job's video"""
    try:
        # Get job data
        job_doc = jobs_collection.document(job_id).get()
        if not job_doc.exists:
            return jsonify({'error': 'Job not found'}), 404
        
        job_data = job_doc.to_dict()
        video_url = job_data.get('output', {}).get('video_url')
        
        if not video_url:
            return jsonify({'error': 'Video not available'}), 404
        
        # Parse GCS URI
        if video_url.startswith('gs://'):
            # Extract bucket and object path
            parts = video_url[5:].split('/', 1)  # Remove 'gs://' prefix
            if len(parts) != 2:
                return jsonify({'error': 'Invalid video URL format'}), 400
            
            bucket_name, object_path = parts
            
            # Generate signed URL
            from google.cloud import storage
            from datetime import datetime, timedelta
            
            client = storage.Client()
            bucket = client.bucket(bucket_name)
            blob = bucket.blob(object_path)
            
            # Generate signed URL valid for 1 hour
            signed_url = blob.generate_signed_url(
                expiration=datetime.utcnow() + timedelta(hours=1),
                method='GET'
            )
            
            return jsonify({'video_url': signed_url})
        else:
            # Already a direct URL
            return jsonify({'video_url': video_url})
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/jobs/<job_id>')
def get_job(job_id):
    """Get specific job by ID"""
    try:
        job = control_center.get_job(job_id)
        if not job:
            return jsonify({
                "error": "Job not found",
                "code": "JOB_NOT_FOUND",
                "timestamp": datetime.utcnow().isoformat() + "Z"
            }), 404
        
        # Transform to new contract format
        stage = job.get("stage")
        formatted_job = {
            "id": job.get("id", job_id),
            "template_id": job.get("template_id"),
            "template_version": job.get("template_version", "1.0.0"),
            "status": job.get("status", "pending"),
            "stage": stage,
            "progress": job.get("progress", 0),
            "stage_progress": job_stage_contract.get_progress_for_stage(stage),
            "created_at": job.get("created_at", datetime.utcnow().isoformat() + "Z"),
            "stage_entered_at": job.get("stageEnteredAt"),
            "last_heartbeat_at": job.get("lastHeartbeatAt"),
            "timestamps": {
                "ttsStartedAt": job.get("ttsStartedAt"),
                "ttsCompletedAt": job.get("ttsCompletedAt"),
                "renderStartedAt": job.get("renderStartedAt"),
                "concatStartedAt": job.get("concatStartedAt"),
                "uploadStartedAt": job.get("uploadStartedAt"),
                "completed_at": job.get("completed_at"),
                "failedAt": job.get("failedAt"),
            },
            "started_at": job.get("started_at"),
            "completed_at": job.get("completed_at"),
            "current_phase": job.get("current_phase"),
            "input_data": job.get("input_data", {}),
            "output": {
                "video_url": job.get("output", {}).get("video_url"),
                "gcs_uri": job.get("output", {}).get("gcs_uri"),
                "srt_url": job.get("output", {}).get("srt_url"),
                "duration": job.get("output", {}).get("duration"),
                "file_size": job.get("output", {}).get("file_size")
            },
            "logs": job.get("logs", []),
            "lastError": job.get("lastError"),
            "retry_count": job.get("retry_count", 0),
        }
        
        return jsonify(formatted_job), 200
    except Exception as e:
        return jsonify({
            "error": f"Error getting job: {str(e)}",
            "code": "JOB_FETCH_FAILED",
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }), 500

@app.route('/api/jobs/<job_id>', methods=['DELETE'])
def delete_job(job_id):
    """Delete a job"""
    control_center.delete_job(job_id)
    return jsonify({'success': True})

@app.route('/api/generate', methods=['POST'])
def generate_questions():
    """Generate questions with Gemini"""
    data = request.get_json()
    num_questions = data.get('num_questions', 5)
    
    questions, error = control_center.generate_questions_with_gemini(num_questions)
    
    if error:
        return jsonify({'error': error}), 400
    
    return jsonify({
        'success': True,
        'questions': questions
    })

@app.route('/api/upload-csv', methods=['POST'])
def upload_csv():
    """Upload CSV with questions"""
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    try:
        csv_content = file.read().decode('utf-8')
        questions, error = control_center.parse_csv_questions(csv_content)
        
        if error:
            return jsonify({'error': error}), 400
        
        return jsonify({
            'success': True,
            'questions': questions
        })
    
    except Exception as e:
        return jsonify({'error': f'Error processing file: {str(e)}'}), 400


@app.route('/api/test', methods=['GET'])
def test_route():
    """Test route to verify Flask is working"""
    with open('/tmp/test_route.log', 'a') as f:
        f.write("🧪 TEST ROUTE CALLED!\n")
    return jsonify({'success': True, 'message': 'Test route working'})

@app.route('/api/pipeline/start', methods=['POST'])
def start_pipeline():
    """Start the pipeline watcher"""
    global pipeline_manager
    
    if pipeline_manager is None:
        pipeline_manager = PipelineManager(jobs_collection, control_center)
    
    result = pipeline_manager.start_pipeline()
    
    if 'error' in result:
        return jsonify(result), 400
    else:
        return jsonify(result)

@app.route('/api/pipeline/stop', methods=['POST'])
def stop_pipeline():
    """Stop the pipeline watcher"""
    global pipeline_manager
    
    if pipeline_manager is None:
        return jsonify({'error': 'Pipeline not initialized'}), 400
    
    result = pipeline_manager.stop_pipeline()
    return jsonify(result)

@app.route('/api/jobs/<job_id>/retry', methods=['POST'])
def retry_job(job_id):
    """Retry a failed job"""
    job = control_center.get_job(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    
    if job['status'] not in ['failed', 'pending']:
        return jsonify({'error': 'Only failed or pending jobs can be retried'}), 400
    
    # Reset job status to pending
    control_center.update_job_status(job_id, "pending", progress=0, error=None)
    
    return jsonify({'success': True, 'message': 'Job queued for retry'})

@app.route('/api/jobs/<job_id>/restart', methods=['POST'])
def restart_aborted_job(job_id):
    """Restart an aborted job.
    - If a TTS checkpoint exists (stage == 'tts_completed'), preserve it and start from render (progress 10)
    - Otherwise, fully reset to pending (progress 0)
    - Clears any lingering TTS queue work
    """
    try:
        job = control_center.get_job(job_id)
        if not job:
            return jsonify({'error': 'Job not found'}), 404

        if job.get('status') != 'aborted':
            return jsonify({'error': 'Only aborted jobs can be restarted via this endpoint'}), 400

        # Best-effort: clear any queued/active TTS work for this job
        try:
            from core.tts_queue_manager import tts_queue_manager
            tts_queue_manager.abort_job(job_id)
        except Exception:
            pass

        # If we already have TTS artifacts checkpointed, resume from render
        stage = job.get('stage')
        has_tts_checkpoint = stage == 'tts_completed' and bool(((job.get('tts_artifacts') or {}).get('question_audio_uris') or []))

        progress = 10 if has_tts_checkpoint else 0
        control_center.update_job_status(job_id, 'pending', progress=progress, error=None)
        return jsonify({'success': True, 'message': f'Job {job_id} restarted', 'resuming_from_tts': has_tts_checkpoint})
    except Exception as e:
        return jsonify({'error': f'Failed to restart job: {str(e)}'}), 500

@app.route('/api/tts-watchdog/status', methods=['GET'])
def get_tts_watchdog_status():
    """Get TTS watchdog status for monitoring"""
    try:
        from core.tts_watchdog import tts_watchdog
        
        # Get all active TTS requests
        active_requests = {}
        for request_id, request_info in tts_watchdog.active_requests.items():
            active_requests[request_id] = tts_watchdog.get_tts_status(request_id)
        
        # Check for stuck jobs
        stuck_jobs = tts_watchdog.check_stuck_jobs()
        
        return jsonify({
            'active_requests': active_requests,
            'stuck_jobs': stuck_jobs,
            'total_active': len(active_requests),
            'total_stuck': len(stuck_jobs)
        })
        
    except Exception as e:
        return jsonify({'error': f'Failed to get TTS watchdog status: {str(e)}'}), 500

@app.route('/api/tts-queue/status', methods=['GET'])
def get_tts_queue_status():
    """Get TTS queue status for monitoring"""
    try:
        from core.tts_queue_manager import tts_queue_manager
        
        queue_status = tts_queue_manager.get_queue_status()
        
        return jsonify({
            'queue_status': queue_status,
            'timestamp': datetime.utcnow().isoformat() + "Z"
        })
        
    except Exception as e:
        return jsonify({'error': f'Failed to get TTS queue status: {str(e)}'}), 500

@app.route('/api/tts-queue/request/<request_id>', methods=['GET'])
def get_tts_queue_request_status(request_id):
    """Get status of a specific TTS queue request"""
    try:
        from core.tts_queue_manager import tts_queue_manager
        
        status = tts_queue_manager.get_request_status(request_id)
        if not status:
            return jsonify({'error': 'TTS queue request not found'}), 404
        
        return jsonify(status)
        
    except Exception as e:
        return jsonify({'error': f'Failed to get TTS queue request status: {str(e)}'}), 500

@app.route('/api/jobs/<job_id>/abort', methods=['POST'])
def abort_job(job_id):
    """Abort a specific job (any status). Marks as aborted and clears TTS queue work."""
    try:
        job = control_center.get_job(job_id)
        if not job:
            return jsonify({'error': 'Job not found'}), 404

        # Update status first
        control_center.update_job_status(job_id, 'aborted', error='Aborted by user')

        # Abort any TTS activity
        try:
            from core.tts_queue_manager import tts_queue_manager
            tts_result = tts_queue_manager.abort_job(job_id)
        except Exception:
            tts_result = {'removed_from_queue': 0, 'was_active': False}

        return jsonify({'success': True, 'message': f'Job {job_id} aborted', 'tts': tts_result})
    except Exception as e:
        return jsonify({'error': f'Failed to abort job: {str(e)}'}), 500

@app.route('/api/jobs/abort-all-processing', methods=['POST'])
def abort_all_processing():
    """Abort all jobs currently in processing or pending."""
    try:
        aborted = 0
        jobs = control_center.get_all_jobs()
        for job in jobs:
            if job.get('status') in ['processing', 'pending', 'local_pending']:
                job_id = job['id']
                control_center.update_job_status(job_id, 'aborted', error='Aborted by user (bulk)')
                try:
                    from core.tts_queue_manager import tts_queue_manager
                    tts_queue_manager.abort_job(job_id)
                except Exception:
                    pass
                aborted += 1

        return jsonify({'success': True, 'aborted_count': aborted})
    except Exception as e:
        return jsonify({'error': f'Failed to abort processing jobs: {str(e)}'}), 500

@app.route('/api/jobs/<job_id>/requeue', methods=['POST'])
def requeue_job(job_id):
    """Force-requeue a job by setting it to pending, regardless of current status."""
    try:
        job = control_center.get_job(job_id)
        if not job:
            return jsonify({'error': 'Job not found'}), 404

        # Clear any TTS queue work
        try:
            from core.tts_queue_manager import tts_queue_manager
            tts_queue_manager.abort_job(job_id)
        except Exception:
            pass

        control_center.update_job_status(job_id, 'pending', progress=0, error='Requeued by user')
        return jsonify({'success': True, 'message': f'Job {job_id} set to pending'})
    except Exception as e:
        return jsonify({'error': f'Failed to requeue job: {str(e)}'}), 500

@app.route('/api/jobs/<job_id>/continue-from-tts', methods=['POST'])
def continue_from_tts(job_id):
    """Mark job as pending with a TTS-completed checkpoint preserved (resume render)."""
    try:
        job = control_center.get_job(job_id)
        if not job:
            return jsonify({'error': 'Job not found'}), 404

        # Do not remove tts_artifacts; just move to pending so watcher picks it up
        control_center.update_job_status(job_id, 'pending', progress=10, error=None)
        return jsonify({'success': True, 'message': f'Job {job_id} queued to continue from TTS'})
    except Exception as e:
        return jsonify({'error': f'Failed to continue from TTS: {str(e)}'}), 500

# --- Direct start for a pending job (bypass watcher) ---
@app.route('/api/jobs/<job_id>/start-now', methods=['POST'])
def start_job_now(job_id):
    """Force-start a pending job immediately in a background thread.
    Useful when the watcher is slow or unresponsive.
    """
    try:
        job = control_center.get_job(job_id)
        if not job:
            return jsonify({'error': 'Job not found'}), 404

        if job.get('status') not in ['pending', 'local_pending']:
            return jsonify({'error': 'Only pending jobs can be started now'}), 400

        # Ensure pipeline manager exists
        global pipeline_manager
        if pipeline_manager is None:
            pipeline_manager = PipelineManager(jobs_collection, control_center)

        # Mark as processing and launch processing in a background thread - NO FAKE PROGRESS
        control_center.update_job_status(job_id, 'processing', progress=0, error=None)

        def _run():
            try:
                pipeline_manager._process_job(job_id, job)
            except Exception as e:
                control_center.update_job_status(job_id, 'failed', error=f'Immediate start error: {e}')

        import threading
        threading.Thread(target=_run, daemon=True).start()
        return jsonify({'success': True, 'message': f'Job {job_id} started'}), 200
    except Exception as e:
        return jsonify({'error': f'Failed to start job: {str(e)}'}), 500

@app.route('/api/jobs/<job_id>/fast-rerender', methods=['POST'])
def fast_rerender_job(job_id):
    """Fast re-render a job by skipping TTS and starting directly from render stage.
    Requires TTS artifacts to exist. Useful for template changes without re-generating audio.
    """
    try:
        job = control_center.get_job(job_id)
        if not job:
            return jsonify({'error': 'Job not found'}), 404

        # Check if job has TTS artifacts
        tts_artifacts = job.get('tts_artifacts', {})
        if not tts_artifacts or not tts_artifacts.get('question_audio_uris'):
            return jsonify({'error': 'Job must have TTS artifacts to fast re-render. Run full pipeline first.'}), 400

        # Check if job is in a state that allows re-rendering
        if job['status'] not in ['completed', 'failed', 'aborted']:
            return jsonify({'error': 'Job must be completed, failed, or aborted to fast re-render'}), 400

        # Reset job to processing with TTS checkpoint preserved
        control_center.update_job_status(
            job_id, 
            'processing', 
            progress=40,  # Start at 40% (post-TTS)
            error=None, 
            started_at=datetime.utcnow().isoformat() + "Z", 
            stage='tts_completed',  # Preserve TTS checkpoint
            renderStartedAt=None,  # Reset render timestamps
            concatStartedAt=None,
            uploadStartedAt=None,
            completed_at=None
        )

        # Clear any TTS queue work for this job
        try:
            from core.tts_queue_manager import tts_queue_manager
            tts_queue_manager.abort_job(job_id)
        except Exception:
            pass

        return jsonify({
            'success': True, 
            'message': f'Job {job_id} queued for fast re-render (skipping TTS)',
            'tts_artifacts_count': len(tts_artifacts.get('question_audio_uris', []))
        })
    except Exception as e:
        return jsonify({'error': f'Failed to fast re-render job: {str(e)}'}), 500

@app.route('/api/jobs/clear-completed', methods=['POST'])
def clear_completed_jobs():
    """Clear all completed jobs"""
    try:
        # Get all completed jobs
        completed_jobs = jobs_collection.where("status", "==", "completed").stream()
        
        # Delete them
        deleted_count = 0
        for job_doc in completed_jobs:
            job_doc.reference.delete()
            deleted_count += 1
        
        return jsonify({'success': True, 'deleted_count': deleted_count})
    except Exception as e:
        return jsonify({'error': f'Error clearing completed jobs: {str(e)}'}), 500

@app.route('/api/pipeline/status')
def pipeline_status():
    """Get pipeline status"""
    global pipeline_manager
    
    if pipeline_manager is None:
        return jsonify({'running': False, 'splitEnabled': PIPELINE_SPLIT_ENABLED})

    result = pipeline_manager.get_status()
    result.setdefault('splitEnabled', False)  # Force disable split workers
    result.setdefault('ttsEngine', os.getenv('PIPELINE_TTS_ENGINE', 'custom'))
    return jsonify(result)


@app.route('/api/pipeline/toggle-split', methods=['POST'])
def toggle_split_pipeline():
    global pipeline_manager

    data = request.get_json(silent=True) or {}
    enabled = bool(data.get('enabled', True))

    if pipeline_manager is None:
        return jsonify({'error': 'Pipeline not initialized'}), 400

    update = pipeline_manager.update_split_enabled(enabled)
    return jsonify(update)

# Channel Management API endpoints
@app.route('/api/channels')
def get_channels():
    """Get active channels using channel manager"""
    try:
        # Use channel manager to get channels from both GCS and Firestore
        manager = get_channel_manager(ENVIRONMENT)
        channels = manager.get_all_channels()
        
        # Filter to only active channels
        active_channels = [ch for ch in channels if ch.get('status') == 'active']
        
        return jsonify(active_channels)
    except Exception as e:
        return jsonify({
            'error': f'Failed to get channels: {str(e)}',
            'code': 'CHANNELS_FETCH_FAILED',
            'message': str(e),
            'hint': 'Check channel manager and service account'
        }), 500

@app.route('/api/channels', methods=['POST'])
def create_channel():
    """Create a new channel with environment support"""
    try:
        data = request.get_json()
        name = data.get('name', '')
        slug = data.get('slug', '')
        description = data.get('description', '')
        status = data.get('status', 'active')
        environment = data.get('environment', 'dev')  # Default to dev
        branding = data.get('branding')
        
        if not name:
            return jsonify({'error': 'Channel name is required'}), 400
        
        if not slug:
            return jsonify({'error': 'Channel slug is required'}), 400
        
        # Validate environment
        if environment not in ['dev', 'prod']:
            return jsonify({'error': 'Environment must be dev or prod'}), 400
        
        # Get environment-specific manager
        manager = get_channel_manager(environment)
        channel_id = manager.create_channel(name, description, slug=slug)
        
        # Update the channel with additional fields
        update_data = {
            'status': status,
            'environment': environment,
            'updated_at': datetime.utcnow().isoformat() + "Z"
        }
        
        if branding:
            update_data['branding'] = branding
        
        manager.update_channel(channel_id, update_data)
        
        return jsonify({
            'success': True,
            'channel_id': channel_id,
            'environment': environment,
            'message': f'Channel "{name}" created successfully in {environment}'
        })
    except Exception as e:
        return jsonify({'error': f'Error creating channel: {str(e)}'}), 500

@app.route('/api/channels/<channel_id>')
def get_channel(channel_id):
    """Get a specific channel"""
    try:
        manager = get_channel_manager()
        channel = manager.get_channel(channel_id)
        if not channel:
            return jsonify({'error': 'Channel not found'}), 404
        
        return jsonify(channel)
    except Exception as e:
        return jsonify({'error': f'Error getting channel: {str(e)}'}), 500

@app.route('/api/channels/<channel_id>', methods=['PUT'])
def update_channel(channel_id):
    """Update channel data"""
    try:
        data = request.get_json()
        manager = get_channel_manager()
        success = manager.update_channel(channel_id, data)
        
        if success:
            return jsonify({'success': True, 'message': 'Channel updated successfully'})
        else:
            return jsonify({'error': 'Failed to update channel'}), 500
    except Exception as e:
        return jsonify({'error': f'Error updating channel: {str(e)}'}), 500

@app.route('/api/channels/<channel_id>', methods=['DELETE'])
def delete_channel(channel_id):
    """Delete a channel and all its assets from Firestore and GCS"""
    try:
        manager = get_channel_manager()
        
        # Get channel info before deletion
        channel = manager.get_channel(channel_id)
        if not channel:
            return jsonify({'error': 'Channel not found'}), 404
        
        # Check if it's a legacy channel (protect from deletion)
        if channel.get('status') == 'legacy':
            return jsonify({'error': 'Cannot delete legacy channels'}), 403
        
        # Delete channel and all its assets
        success, message = manager.delete_channel_completely(channel_id)
        
        if success:
            return jsonify({
                'success': True,
                'message': f'Channel "{channel.get("title", channel_id)}" deleted successfully',
                'deleted_assets': message.get('deleted_assets', 0),
                'deleted_gcs_objects': message.get('deleted_gcs_objects', 0)
            })
        else:
            return jsonify({'error': f'Failed to delete channel: {message}'}), 500
            
    except Exception as e:
        return jsonify({'error': f'Error deleting channel: {str(e)}'}), 500


@app.route('/api/channels/<channel_id>/assets')
def get_channel_assets(channel_id):
    """Get assets for a specific channel"""
    try:
        asset_type = request.args.get('type')
        manager = get_channel_manager(ENVIRONMENT)
        assets = manager.get_channel_assets(channel_id, asset_type)
        return jsonify(assets)
    except Exception as e:
        return jsonify({'error': f'Error getting channel assets: {str(e)}'}), 500

@app.route('/api/channels/<channel_id>/templates')
def get_channel_templates(channel_id):
    """Get templates for a specific channel"""
    try:
        manager = get_channel_manager(ENVIRONMENT)
        templates = manager.get_channel_templates(channel_id)
        return jsonify(templates)
    except Exception as e:
        return jsonify({'error': f'Error getting channel templates: {str(e)}'}), 500

@app.route('/api/channels/<channel_id>/jobs')
def get_channel_jobs(channel_id):
    """Get jobs for a specific channel"""
    try:
        manager = get_channel_manager(ENVIRONMENT)
        jobs = manager.get_channel_jobs(channel_id)
        return jsonify(jobs)
    except Exception as e:
        return jsonify({'error': f'Error getting channel jobs: {str(e)}'}), 500

@app.route('/api/channels/test/create', methods=['POST'])
def create_test_channel():
    """Create a test channel with default assets"""
    try:
        manager = get_channel_manager(ENVIRONMENT)
        channel_id = manager.create_test_channel()
        return jsonify({
            'success': True,
            'channel_id': channel_id,
            'message': 'Test channel created successfully'
        })
    except Exception as e:
        return jsonify({'error': f'Error creating test channel: {str(e)}'}), 500

@app.route('/api/channels/current', methods=['GET', 'POST'])
def current_channel():
    """Get or set current channel"""
    global current_channel_id
    
    if request.method == 'GET':
        if current_channel_id:
            # Return full channel object
            manager = get_channel_manager(ENVIRONMENT)
            channel = manager.get_channel(current_channel_id)
            return jsonify(channel if channel else None)
        else:
            return jsonify(None)
    else:
        data = request.get_json()
        current_channel_id = data.get('channel_id')
        return jsonify({'success': True, 'current_channel_id': current_channel_id})

# Add missing API endpoints for frontend functionality

@app.route('/api/bulk-upload-assets', methods=['POST'])
def bulk_upload_assets():
    """Bulk upload multiple asset files"""
    if 'files' not in request.files:
        return jsonify({'error': 'No files uploaded'}), 400
    
    files = request.files.getlist('files')
    if not files or all(file.filename == '' for file in files):
        return jsonify({'error': 'No files selected'}), 400
    
    asset_type = request.form.get('asset_type', 'background')
    asset_category = request.form.get('asset_category', 'general')
    channel_id = request.form.get('channel_id', current_channel_id)
    
    if not channel_id:
        return jsonify({'error': 'No channel selected'}), 400
    
    # Validate file types
    allowed_extensions = {
        'background': ['.mp4', '.avi', '.mov', '.mkv'],
        'audio': ['.mp3', '.wav', '.aac', '.m4a'],
        'music': ['.mp3', '.wav', '.aac', '.m4a'],  # Music assets
        'overlay': ['.png', '.jpg', '.jpeg', '.gif'],
        'intro': ['.mp4', '.avi', '.mov', '.mkv'],
        'outro': ['.mp4', '.avi', '.mov', '.mkv'],
        'transition': ['.mp4', '.avi', '.mov', '.mkv']
    }
    
    if asset_type in allowed_extensions:
        for file in files:
            file_ext = os.path.splitext(file.filename)[1].lower()
            if file_ext not in allowed_extensions[asset_type]:
                return jsonify({'error': f'Invalid file type for {asset_type}: {file.filename}. Allowed: {allowed_extensions[asset_type]}'}), 400
    
    try:
        results = []
        success_count = 0
        error_count = 0
        
        for file in files:
            if file.filename == '':
                continue
                
            # Use filename without extension as asset name
            asset_name = os.path.splitext(file.filename)[0]
            
            asset_data, error = control_center.upload_asset(file, asset_name, asset_type, asset_category, channel_id)
            
            if error:
                results.append({
                    'filename': file.filename,
                    'success': False,
                    'error': error
                })
                error_count += 1
            else:
                results.append({
                    'filename': file.filename,
                    'success': True,
                    'asset': asset_data
                })
                success_count += 1
        
        return jsonify({
            'success': True,
            'summary': {
                'total': len(files),
                'successful': success_count,
                'failed': error_count
            },
            'results': results
        })
    
    except Exception as e:
        return jsonify({'error': f'Error during bulk upload: {str(e)}'}), 400

@app.route('/api/upload-asset', methods=['POST'])
def upload_asset():
    """Upload asset file"""
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    asset_name = request.form.get('asset_name', file.filename)
    asset_type = request.form.get('asset_type', 'background')
    asset_category = request.form.get('asset_category', 'general')
    channel_id = request.form.get('channel_id', current_channel_id)
    
    if not channel_id:
        return jsonify({'error': 'No channel selected'}), 400
    
    # Validate file type
    allowed_extensions = {
        'background': ['.mp4', '.avi', '.mov', '.mkv'],
        'audio': ['.mp3', '.wav', '.aac', '.m4a'],
        'music': ['.mp3', '.wav', '.aac', '.m4a'],  # Music assets
        'overlay': ['.png', '.jpg', '.jpeg', '.gif'],
        'intro': ['.mp4', '.avi', '.mov', '.mkv'],
        'outro': ['.mp4', '.avi', '.mov', '.mkv'],
        'transition': ['.mp4', '.avi', '.mov', '.mkv']
    }
    
    if asset_type in allowed_extensions:
        file_ext = os.path.splitext(file.filename)[1].lower()
        if file_ext not in allowed_extensions[asset_type]:
            return jsonify({'error': f'Invalid file type for {asset_type}. Allowed: {allowed_extensions[asset_type]}'}), 400
    
    try:
        asset_data, error = control_center.upload_asset(file, asset_name, asset_type, asset_category, channel_id)
        
        if error:
            return jsonify({'error': error}), 400
        
        return jsonify({
            'success': True,
            'asset': asset_data
        })
    
    except Exception as e:
        return jsonify({'error': f'Error uploading asset: {str(e)}'}), 400

@app.route('/api/assets/<asset_id>', methods=['DELETE'])
def delete_asset(asset_id):
    """Delete asset"""
    success, error = control_center.delete_asset(asset_id)
    
    if not success:
        return jsonify({'error': error}), 400
    
    return jsonify({'success': True})

@app.route('/api/upload-asset-v2', methods=['POST'])
def upload_asset_v2():
    """Enhanced asset upload with new schema"""
    try:
        # Validate request
        if 'file' not in request.files:
            return jsonify({'error': 'No file uploaded'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        # Get form data
        scope = request.form.get('scope', 'shared')  # shared | channel
        channel_id = request.form.get('channel_id') if scope == 'channel' else None
        asset_type = request.form.get('asset_type', request.form.get('type', 'background'))
        
        # Validate scope and channel
        if scope == 'channel' and not channel_id:
            return jsonify({'error': 'Channel ID required for channel scope'}), 400
        
        if scope not in ['shared', 'channel']:
            return jsonify({'error': 'Scope must be "shared" or "channel"'}), 400
        
        # Validate asset type
        valid_types = ['background', 'audio', 'overlay', 'sfx', 'font', 'intro', 'outro', 'transition']
        if asset_type not in valid_types:
            return jsonify({'error': f'Invalid type. Choose one of: {", ".join(valid_types)}'}), 400
        
        # Validate file size
        file.seek(0, 2)  # Seek to end
        file_size = file.tell()
        file.seek(0)  # Reset to beginning
        
        if file_size == 0:
            return jsonify({'error': 'File is empty'}), 400
        
        # Validate file extension
        file_ext = os.path.splitext(file.filename)[1].lower()
        expected_extensions = {
            'background': ['.mp4', '.avi', '.mov', '.mkv'],
            'audio': ['.mp3', '.wav', '.aac', '.m4a'],
            'overlay': ['.png', '.jpg', '.jpeg'],
            'sfx': ['.wav', '.mp3', '.aac'],
            'font': ['.ttf', '.otf', '.woff', '.woff2'],
            'intro': ['.mp4', '.avi', '.mov', '.mkv'],
            'outro': ['.mp4', '.avi', '.mov', '.mkv'],
            'transition': ['.mp4', '.avi', '.mov', '.mkv']
        }
        
        if file_ext not in expected_extensions.get(asset_type, []):
            return jsonify({'error': f'Invalid extension for {asset_type}. Expected: {", ".join(expected_extensions.get(asset_type, []))}'}), 400
        
        # Build GCS path using path helper
        path_builder = get_path_builder()
        
        # Map singular types to plural for path builder
        # Note: shared assets have limited types, channel assets support more
        shared_type_mapping = {
            'audio': 'audio',
            'overlay': 'overlays',
            'sfx': 'sfx',
            'font': 'fonts',
            'transition': 'transitions'
        }
        
        channel_type_mapping = {
            'background': 'backgrounds',
            'audio': 'audio',
            'overlay': 'overlays',
            'sfx': 'sfx',
            'font': 'fonts',
            'intro': 'intros',
            'outro': 'outros',
            'transition': 'transitions'
        }
        
        if scope == 'shared':
            if asset_type not in shared_type_mapping:
                return jsonify({'error': f'Shared assets do not support type "{asset_type}". Supported: {", ".join(shared_type_mapping.keys())}'}), 400
            plural_type = shared_type_mapping[asset_type]
            gcs_path_obj = path_builder.shared(plural_type, file.filename)
        else:
            if asset_type not in channel_type_mapping:
                return jsonify({'error': f'Channel assets do not support type "{asset_type}". Supported: {", ".join(channel_type_mapping.keys())}'}), 400
            plural_type = channel_type_mapping[asset_type]
            gcs_path_obj = path_builder.channel_asset(channel_id, plural_type, file.filename)
        
        # Validate the path
        is_valid, error_msg = validate_gcs_write(gcs_path_obj.gs_uri)
        if not is_valid:
            return jsonify({'error': f'GCS write validation failed: {error_msg}'}), 400
        
        # Upload to GCS
        bucket = storage_client.bucket(path_builder.bucket_name)
        blob = bucket.blob(gcs_path_obj.path)
        
        # Set content type
        content_type_map = {
            '.mp4': 'video/mp4',
            '.avi': 'video/avi',
            '.mov': 'video/quicktime',
            '.mkv': 'video/x-matroska',
            '.mp3': 'audio/mpeg',
            '.wav': 'audio/wav',
            '.aac': 'audio/aac',
            '.m4a': 'audio/mp4',
            '.png': 'image/png',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.ttf': 'font/ttf',
            '.otf': 'font/otf',
            '.woff': 'font/woff',
            '.woff2': 'font/woff2'
        }
        
        content_type = content_type_map.get(file_ext, 'application/octet-stream')
        
        blob.upload_from_file(file, content_type=content_type)
        
        # Compute file hash
        file.seek(0)
        file_content = file.read()
        import hashlib
        file_hash = hashlib.sha256(file_content).hexdigest()
        
        # Check for duplicates by hash
        assets_ref = firestore_client.collection(f"{FIRESTORE_COLLECTION_PREFIX}_assets")
        duplicate_query = assets_ref.where('hash', '==', file_hash).limit(1)
        duplicates = list(duplicate_query.stream())
        
        if duplicates:
            duplicate_doc = duplicates[0]
            duplicate_data = duplicate_doc.to_dict()
            
            # Update updated_at for reused file
            duplicate_data['updated_at'] = datetime.utcnow().isoformat() + "Z"
            duplicate_doc.reference.update(duplicate_data)
            
            return jsonify({
                'success': True,
                'status': 'reused',
                'asset_id': duplicate_doc.id,
                'asset_data': duplicate_data,
                'gcs_uri': duplicate_data.get('gcs_path'),
                'message': f'File already exists (reused): {duplicate_data.get("name")}'
            })
        
        # Check if filename already exists with different content - rename with hash suffix
        filename_query = assets_ref.where('name', '==', file.filename).where('gcs_path', '==', gcs_path_obj.gs_uri).limit(1)
        filename_docs = list(filename_query.stream())
        
        if filename_docs:
            # Same filename and path exists with different content - rename with hash suffix
            name_parts = file.filename.rsplit('.', 1)
            if len(name_parts) == 2:
                new_filename = f"{name_parts[0]}@sha1-{file_hash[:8]}.{name_parts[1]}"
            else:
                new_filename = f"{file.filename}@sha1-{file_hash[:8]}"
            
            # Rebuild path with new filename
            if scope == 'shared':
                gcs_path_obj = path_builder.shared(plural_type, new_filename)
            else:
                gcs_path_obj = path_builder.channel_asset(channel_id, plural_type, new_filename)
            
            # Re-upload with new filename
            bucket = storage_client.bucket(path_builder.bucket_name)
            blob = bucket.blob(gcs_path_obj.path)
            blob.upload_from_file(file, content_type=content_type)
            
            # Set metadata
            blob.metadata = {
                'env': ENVIRONMENT,
                'channel': channel_id if scope == 'channel' else 'shared',
                'asset_type': asset_type,
                'content_hash': file_hash,
                'uploaded_at': datetime.utcnow().isoformat() + "Z",
                'renamed_from': file.filename
            }
            blob.patch()
            
            # Create Asset document with renamed filename
            asset_data = {
                'channel_id': 'shared' if scope == 'shared' else channel_id,
                'type': asset_type,
                'name': new_filename,
                'original_name': file.filename,
                'gcs_path': gcs_path_obj.gs_uri,
                'hash': file_hash,
                'duration_sec': None,
                'dimensions': None,
                'tags': [],
                'created_at': datetime.utcnow().isoformat() + "Z",
                'updated_at': datetime.utcnow().isoformat() + "Z"
            }
            
            # Auto-probe metadata for media files
            if asset_type in ['background', 'audio', 'intro', 'outro', 'transition']:
                try:
                    if asset_type == 'audio':
                        asset_data['duration_sec'] = 30.0  # Placeholder
                    else:
                        asset_data['duration_sec'] = 10.0  # Placeholder
                        asset_data['dimensions'] = {'w': 1920, 'h': 1080}  # Placeholder
                except Exception as e:
                    print(f"Auto-probe failed: {e}")
            
            asset_id = f"asset_{asset_type}_{uuid.uuid4().hex[:8]}"
            asset_ref = firestore_client.collection(f"{FIRESTORE_COLLECTION_PREFIX}_assets").document(asset_id)
            asset_ref.set(asset_data)
            
            return jsonify({
                'success': True,
                'status': 'renamed',
                'asset_id': asset_id,
                'asset_data': asset_data,
                'gcs_uri': gcs_path_obj.gs_uri,
                'message': f'File renamed to avoid conflict: {new_filename}'
            })
        
        # Create Asset document
        asset_data = {
            'channel_id': 'shared' if scope == 'shared' else channel_id,
            'type': asset_type,  # Singular as required
            'name': file.filename,
            'gcs_path': gcs_path_obj.gs_uri,
            'hash': file_hash,
            'duration_sec': None,  # Will be filled by auto-probe
            'dimensions': None,    # Will be filled by auto-probe
            'tags': [],
            'created_at': datetime.utcnow().isoformat() + "Z",
            'updated_at': datetime.utcnow().isoformat() + "Z"
        }
        
        # Auto-probe metadata for media files
        if asset_type in ['background', 'audio', 'intro', 'outro', 'transition']:
            try:
                # This would use ffprobe in a real implementation
                # For now, we'll set placeholder values
                if asset_type == 'audio':
                    asset_data['duration_sec'] = 30.0  # Placeholder
                else:
                    asset_data['duration_sec'] = 10.0  # Placeholder
                    asset_data['dimensions'] = {'w': 1920, 'h': 1080}  # Placeholder
            except Exception as e:
                print(f"Auto-probe failed: {e}")
        
        # Upsert Asset document
        asset_id = f"asset_{asset_type}_{uuid.uuid4().hex[:8]}"
        asset_ref = firestore_client.collection(f"{FIRESTORE_COLLECTION_PREFIX}_assets").document(asset_id)
        asset_ref.set(asset_data)
        
        return jsonify({
            'success': True,
            'status': 'uploaded',
            'asset_id': asset_id,
            'asset_data': asset_data,
            'gcs_uri': gcs_path_obj.gs_uri,
            'message': f'Asset uploaded successfully: {file.filename}'
        })
        
    except Exception as e:
        return jsonify({'error': f'Upload failed: {str(e)}'}), 500

@app.route('/api/assets', methods=['GET'])
def get_assets_by_type():
    """Get assets filtered by type"""
    try:
        asset_type = request.args.get('type')
        limit = request.args.get('limit', 50, type=int)
        
        assets_ref = firestore_client.collection(f"{FIRESTORE_COLLECTION_PREFIX}_assets")
        
        if asset_type:
            query = assets_ref.where('type', '==', asset_type).limit(limit)
        else:
            query = assets_ref.limit(limit)
        
        assets = []
        for doc in query.stream():
            asset_data = doc.to_dict()
            assets.append({
                'id': doc.id,
                'name': asset_data.get('name'),
                'type': asset_data.get('type'),
                'gcs_path': asset_data.get('gcs_path'),
                'created_at': asset_data.get('created_at')
            })
        
        return jsonify({
            'success': True,
            'assets': assets
        })
        
    except Exception as e:
        return jsonify({'error': f'Failed to get assets: {str(e)}'}), 500

@app.route('/api/assets/<asset_id>', methods=['GET'])
def get_asset(asset_id):
    """Get specific asset with signed URL"""
    try:
        asset_ref = firestore_client.collection(f"{FIRESTORE_COLLECTION_PREFIX}_assets").document(asset_id)
        asset_doc = asset_ref.get()
        
        if not asset_doc.exists:
            return jsonify({'error': 'Asset not found'}), 404
        
        asset_data = asset_doc.to_dict()
        gcs_path = asset_data.get('gcs_path')
        
        if not gcs_path:
            return jsonify({'error': 'Asset has no GCS path'}), 400
        
        # Generate signed URL
        bucket_name = gcs_path.split('/')[2]
        blob_name = '/'.join(gcs_path.split('/')[3:])
        
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(blob_name)
        
        if not blob.exists():
            return jsonify({'error': 'Asset file not found in GCS'}), 404
        
        # Generate signed URL (valid for 1 hour)
        signed_url = blob.generate_signed_url(
            version="v4",
            expiration=timedelta(hours=1),
            method="GET"
        )
        
        return jsonify({
            'success': True,
            'asset': asset_data,
            'signed_url': signed_url
        })
        
    except Exception as e:
        return jsonify({'error': f'Failed to get asset: {str(e)}'}), 500

@app.route('/api/recent-uploads', methods=['GET'])
def get_recent_uploads():
    """Get recent asset uploads - includes all audio assets for music selection"""
    try:
        limit = request.args.get('limit', 50, type=int)  # Increased default limit
        
        assets_ref = firestore_client.collection(f"{FIRESTORE_COLLECTION_PREFIX}_assets")
        
        # Get all assets (not just recent ones) to ensure audio files are included
        all_assets = assets_ref.stream()
        
        uploads = []
        for asset_doc in all_assets:
            asset_data = asset_doc.to_dict()
            uploads.append({
                'id': asset_doc.id,
                'name': asset_data.get('name'),
                'type': asset_data.get('type'),
                'scope': 'shared' if asset_data.get('channel_id') == 'shared' else 'channel',
                'channel_id': asset_data.get('channel_id'),
                'gcs_path': asset_data.get('gcs_path'),
                'created_at': asset_data.get('created_at'),
                'status': 'active'
            })
        
        # Sort by created_at descending and limit
        uploads.sort(key=lambda x: x.get('created_at', ''), reverse=True)
        uploads = uploads[:limit]
        
        return jsonify({
            'success': True,
            'uploads': uploads
        })
        
    except Exception as e:
        return jsonify({'error': f'Failed to get recent uploads: {str(e)}'}), 500

@app.route('/templates/new/editor-minimal')
def template_editor_new():
    return redirect(url_for('index'))

@app.route('/templates/<template_id>/editor-minimal')
def template_editor_minimal(template_id):
    return redirect(url_for('index'))


@app.after_request
def _set_cache_headers(resp):
    """Set strong caching for hashed editor assets and no-store for manifest."""
    try:
        p = request.path or ''
        if p.startswith('/static/editor/manifest'):
            resp.headers['Cache-Control'] = 'no-store'
        elif p.startswith('/static/editor/editor.min.'):
            resp.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
    except Exception:
        pass
    return resp


@app.route('/static/editor/manifest.json')
def editor_manifest_route():
    manifest = load_editor_manifest()
    resp = make_response(jsonify(manifest))
    resp.headers['Cache-Control'] = 'no-store'
    return resp


@app.route('/api/upload-csvs', methods=['POST'])
def upload_csvs():
    """Upload multiple CSV files to staging folder"""
    try:
        if 'files' not in request.files:
            return jsonify({'error': 'No files provided'}), 400
        
        files = request.files.getlist('files')
        if not files or files[0].filename == '':
            return jsonify({'error': 'No files selected'}), 400
        
        # Get output target (test or production)
        output_target = request.form.get('output_target', 'test')
        if output_target not in ['test', 'production']:
            return jsonify({'error': 'output_target must be "test" or "production"'}), 400
        
        # Generate run ID
        run_id = f"run_{int(time.time())}"
        
        # Determine staging bucket and prefix
        if output_target == 'test':
            bucket_name = 'trivia-videos-test'
        else:
            bucket_name = 'trivia-videos-prod'
        
        staging_prefix = f"staging/{run_id}/csv/"
        
        # Upload files to GCS staging
        uploaded_files = []
        storage_client = storage.Client()
        bucket = storage_client.bucket(bucket_name)
        
        for file in files:
            if file and file.filename.endswith('.csv'):
                # Create safe filename
                safe_filename = clean_filename(file.filename)
                blob_name = f"{staging_prefix}{safe_filename}"
                
                # Upload to GCS
                blob = bucket.blob(blob_name)
                blob.upload_from_file(file)
                
                uploaded_files.append({
                    'original_filename': file.filename,
                    'safe_filename': safe_filename,
                    'gcs_path': f"gs://{bucket_name}/{blob_name}"
                })
        
        if not uploaded_files:
            return jsonify({'error': 'No valid CSV files uploaded'}), 400
        
        return jsonify({
            'run_id': run_id,
            'output_target': output_target,
            'uploaded_files': uploaded_files,
            'message': f'Successfully uploaded {len(uploaded_files)} CSV files'
        })
        
    except Exception as e:
        print(f"Error uploading CSVs: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/upload-manifest', methods=['POST'])
def upload_manifest():
    """Upload and validate manifest.json against uploaded CSVs"""
    try:
        if 'manifest' not in request.files:
            return jsonify({'error': 'No manifest file provided'}), 400
        
        manifest_file = request.files['manifest']
        if not manifest_file or not manifest_file.filename.endswith('.json'):
            return jsonify({'error': 'Invalid manifest file'}), 400
        
        # Get run_id and output_target from form
        run_id = request.form.get('run_id')
        output_target = request.form.get('output_target', 'test')
        
        if not run_id:
            return jsonify({'error': 'run_id is required'}), 400
        
        # Parse manifest
        manifest_data = json.loads(manifest_file.read().decode('utf-8'))
        
        # Validate manifest structure
        if 'version' not in manifest_data or 'batches' not in manifest_data:
            return jsonify({'error': 'Invalid manifest structure'}), 400
        
        # Determine staging bucket
        if output_target == 'test':
            bucket_name = 'trivia-videos-test'
        else:
            bucket_name = 'trivia-videos-prod'
        
        staging_prefix = f"staging/{run_id}/csv/"
        
        # Get list of uploaded CSV files
        storage_client = storage.Client()
        bucket = storage_client.bucket(bucket_name)
        blobs = list(bucket.list_blobs(prefix=staging_prefix))
        uploaded_csvs = [blob.name.split('/')[-1] for blob in blobs if '/csv/' in blob.name]
        
        # Validate manifest against uploaded CSVs
        validation_errors = []
        for batch in manifest_data['batches']:
            if 'filename' not in batch:
                validation_errors.append(f"Batch missing 'filename' field")
                continue
            
            filename = batch['filename']
            safe_filename = clean_filename(filename)
            
            if safe_filename not in uploaded_csvs:
                validation_errors.append(f"CSV file '{filename}' not found in uploaded files")
        
        if validation_errors:
            return jsonify({
                'error': 'Manifest validation failed',
                'validation_errors': validation_errors
            }), 400
        
        # Upload manifest to staging
        manifest_blob_name = f"staging/{run_id}/manifest.json"
        manifest_blob = bucket.blob(manifest_blob_name)
        manifest_blob.upload_from_string(json.dumps(manifest_data, indent=2))
        
        return jsonify({
            'run_id': run_id,
            'output_target': output_target,
            'manifest_validated': True,
            'batch_count': len(manifest_data['batches']),
            'message': 'Manifest uploaded and validated successfully'
        })
        
    except json.JSONDecodeError as e:
        return jsonify({'error': f'Invalid JSON in manifest: {e}'}), 400
    except Exception as e:
        print(f"Error uploading manifest: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/upload-youtube-manifest', methods=['POST'])
def upload_youtube_manifest():
    """Upload and validate YouTube metadata manifest for bulk jobs"""
    try:
        if 'manifest' not in request.files:
            return jsonify({'error': 'No manifest file provided'}), 400
        
        manifest_file = request.files['manifest']
        if not manifest_file or not manifest_file.filename.endswith('.json'):
            return jsonify({'error': 'Manifest must be a .json file'}), 400
        
        # Parse manifest
        try:
            manifest_content = manifest_file.read().decode('utf-8')
            manifest_data = json.loads(manifest_content)
        except json.JSONDecodeError as e:
            return jsonify({'error': f'Invalid JSON in manifest: {str(e)}'}), 400
        
        # Validate structure: must be array of objects with title and description
        if not isinstance(manifest_data, list):
            return jsonify({'error': 'Manifest must be a JSON array'}), 400
        
        for idx, entry in enumerate(manifest_data):
            if not isinstance(entry, dict):
                return jsonify({'error': f'Entry {idx} must be an object'}), 400
            if 'title' not in entry or 'description' not in entry:
                return jsonify({'error': f'Entry {idx} missing required "title" or "description"'}), 400
            if not entry['title'] or not entry['description']:
                return jsonify({'error': f'Entry {idx} has empty title or description'}), 400
        
        return jsonify({
            'success': True,
            'manifest_count': len(manifest_data),
            'manifest_data': manifest_data,
            'message': f'Manifest validated: {len(manifest_data)} entries'
        })
        
    except Exception as e:
        print(f"Error uploading YouTube manifest: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/create-bulk-jobs-with-manifest', methods=['POST'])
def create_bulk_jobs_with_manifest():
    """Create multiple jobs from CSVs with YouTube metadata from manifest"""
    try:
        data = request.get_json()
        
        # Required fields
        csv_list = data.get('csv_list', [])  # Array of {questions: [...]}
        manifest_data = data.get('manifest_data', [])  # Array of {title, description}
        thumbnail_urls = data.get('thumbnail_urls', [])  # Array of thumbnail URLs in order
        channel_id = data.get('channel_id')
        template_id = data.get('template_id')
        
        # Optional fields
        music_enabled = data.get('music_enabled', True)
        output_mode = data.get('output_mode', 'test')
        youtube_upload_test = data.get('youtube_upload_test', False)
        tts_engine = data.get('tts_engine', 'custom')
        selected_voice = data.get('selected_voice', 'af-alt')
        
        # Validation
        if not csv_list:
            return jsonify({'error': 'No CSV data provided'}), 400
        if not manifest_data:
            return jsonify({'error': 'No manifest data provided - manifest is required'}), 400
        if not channel_id:
            return jsonify({'error': 'No channel_id provided'}), 400
        if not template_id:
            return jsonify({'error': 'No template_id provided'}), 400
        
        # STRICT: CSV count must match manifest count
        if len(csv_list) != len(manifest_data):
            return jsonify({
                'error': f'CSV/Manifest count mismatch: {len(csv_list)} CSVs but {len(manifest_data)} manifest entries. Counts must match exactly.'
            }), 400
        
        # Validate manifest entries
        for idx, entry in enumerate(manifest_data):
            if not entry.get('title') or not entry.get('description'):
                return jsonify({'error': f'Manifest entry {idx} missing title or description'}), 400
        
        # Get template and validate
        validator = FirestoreValidator()
        template_ref = firestore_client.collection(f"{FIRESTORE_COLLECTION_PREFIX}_templates").document(template_id)
        template_doc = template_ref.get()
        
        if not template_doc.exists:
            return jsonify({'error': f'Template {template_id} not found'}), 404
        
        template_data = template_doc.to_dict()
        
        # In production, template must be published
        if ENVIRONMENT == 'production' and template_data.get('state') != 'published':
            return jsonify({'error': f'Template {template_id} is not published'}), 400
        
        # Resolve assets if in production
        resolved_assets = None
        if ENVIRONMENT == 'production':
            resolved_assets, message = validator.resolve_template_assets(template_id)
            if not resolved_assets:
                return jsonify({'error': f'Cannot resolve assets: {message}'}), 400
        
        # Create jobs
        created_jobs = []
        now_iso = datetime.now(timezone.utc).isoformat()
        template_version = template_data.get('version', '1.0.0')
        
        # Generate batch_id for grouping these jobs together
        batch_id = f"batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        
        for idx, (csv_data, manifest_entry) in enumerate(zip(csv_list, manifest_data)):
            questions = csv_data.get('questions', [])
            
            if not questions:
                return jsonify({'error': f'CSV {idx} has no questions'}), 400
            
            # Create job with YouTube metadata
            job_id = f"job_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
            
            job_data = {
                'channel_id': channel_id,
                'template_id': template_id,
                'template_version': template_version,
                'input_data': {
                    'questions': questions,  # Store questions in input_data like single uploads!
                    'music_enabled': music_enabled,
                    'output_mode': output_mode,
                    'youtube_upload_test': youtube_upload_test,
                    'tts_engine': tts_engine,
                    'selected_voice': selected_voice
                },
                'status': 'pending',
                'created_at': now_iso,
                'updated_at': now_iso,
                
                # Batch grouping
                'batch_id': batch_id,
                'batch_size': len(csv_list),
                'batch_index': idx,
                
                # YouTube metadata from manifest
                'youtube_title': manifest_entry['title'],
                'youtube_description': manifest_entry['description'],
                'manifest_index': idx,
                'requires_youtube_metadata': True,
                
                # Thumbnail URL if available
                'thumbnail_url': thumbnail_urls[idx] if idx < len(thumbnail_urls) else None,
                
                # Snapshot data
                'template_snapshot': {
                    'name': template_data.get('name', 'Unknown Template'),
                    'version': template_version,
                    'template_data': template_data
                }
            }
            
            # Add resolved assets if available
            if resolved_assets:
                job_data['resolved_assets'] = resolved_assets
            
            # Save to Firestore
            jobs_ref = firestore_client.collection(f"{FIRESTORE_COLLECTION_PREFIX}_jobs")
            jobs_ref.document(job_id).set(job_data)
            
            created_jobs.append({
                'job_id': job_id,
                'youtube_title': manifest_entry['title'],
                'question_count': len(questions)
            })
            
            print(f"✅ Created job {job_id} with YouTube metadata (manifest index {idx})")
        
        return jsonify({
            'success': True,
            'jobs_created': len(created_jobs),
            'created_jobs': created_jobs,
            'message': f'Successfully created {len(created_jobs)} jobs with YouTube metadata'
        })
        
    except Exception as e:
        print(f"Error creating bulk jobs with manifest: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/abort-batch', methods=['POST'])
def abort_batch():
    """Abort all jobs in a batch (identified by batch_id or bulk_upload_id)"""
    try:
        data = request.get_json()
        batch_id = data.get('batch_id') or data.get('bulk_upload_id')
        
        if not batch_id:
            return jsonify({'error': 'batch_id or bulk_upload_id required'}), 400
        
        # Find all jobs with this batch_id
        jobs_ref = firestore_client.collection(f"{FIRESTORE_COLLECTION_PREFIX}_jobs")
        
        # Try batch_id first
        batch_jobs = list(jobs_ref.where('batch_id', '==', batch_id).stream())
        
        # If not found, try bulk_upload_id (for old batches)
        if not batch_jobs:
            batch_jobs = list(jobs_ref.where('bulk_upload_id', '==', batch_id).stream())
        
        if not batch_jobs:
            return jsonify({'error': f'No jobs found with batch_id: {batch_id}'}), 404
        
        # Abort all jobs that are pending or processing
        aborted_count = 0
        now_iso = datetime.now(timezone.utc).isoformat()
        
        for job_doc in batch_jobs:
            job_data = job_doc.to_dict()
            status = job_data.get('status')
            
            if status in ['pending', 'processing']:
                job_doc.reference.update({
                    'status': 'aborted',
                    'updated_at': now_iso,
                    'aborted_at': now_iso,
                    'error': 'Batch aborted by user'
                })
                aborted_count += 1
                print(f"✅ Aborted job: {job_doc.id}")
        
        return jsonify({
            'success': True,
            'aborted_count': aborted_count,
            'total_jobs': len(batch_jobs),
            'message': f'Aborted {aborted_count} jobs in batch'
        })
        
    except Exception as e:
        print(f"Error aborting batch: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/retry-batch', methods=['POST'])
def retry_batch():
    """Retry all failed/aborted jobs in a batch"""
    try:
        data = request.get_json()
        batch_id = data.get('batch_id') or data.get('bulk_upload_id')
        
        if not batch_id:
            return jsonify({'error': 'batch_id or bulk_upload_id required'}), 400
        
        # Find all jobs with this batch_id
        jobs_ref = firestore_client.collection(f"{FIRESTORE_COLLECTION_PREFIX}_jobs")
        
        # Try batch_id first
        batch_jobs = list(jobs_ref.where('batch_id', '==', batch_id).stream())
        
        # If not found, try bulk_upload_id (for old batches)
        if not batch_jobs:
            batch_jobs = list(jobs_ref.where('bulk_upload_id', '==', batch_id).stream())
        
        if not batch_jobs:
            return jsonify({'error': f'No jobs found with batch_id: {batch_id}'}), 404
        
        # Retry all jobs that are failed or aborted
        retried_count = 0
        now_iso = datetime.now(timezone.utc).isoformat()
        
        for job_doc in batch_jobs:
            job_data = job_doc.to_dict()
            status = job_data.get('status')
            
            if status in ['failed', 'aborted']:
                # Check if job has old structure and migrate it
                update_data = {
                    'status': 'pending',
                    'updated_at': now_iso,
                    'error': None,
                    'retry_count': job_data.get('retry_count', 0) + 1
                }
                
                # Migrate old structure to new structure
                if 'questions' in job_data and 'input_data' not in job_data:
                    print(f"🔄 Migrating old structure for job: {job_doc.id}")
                    questions = job_data['questions']
                    
                    # Create input_data structure
                    input_data = {
                        'questions': questions,
                        'music_enabled': job_data.get('music_enabled', True),
                        'output_mode': job_data.get('output_mode', 'test'),
                        'youtube_upload_test': job_data.get('youtube_upload', False),
                        'tts_engine': job_data.get('tts_engine', 'custom'),
                        'selected_voice': job_data.get('selected_voice', 'af-alt')
                    }
                    
                    update_data['input_data'] = input_data
                    
                    # Remove old questions field
                    from google.cloud import firestore
                    update_data['questions'] = firestore.DELETE_FIELD
                    
                    print(f"✅ Migrated {len(questions)} questions to input_data structure")
                
                job_doc.reference.update(update_data)
                retried_count += 1
                print(f"✅ Reset to pending: {job_doc.id}")
        
        return jsonify({
            'success': True,
            'retried_count': retried_count,
            'total_jobs': len(batch_jobs),
            'message': f'Reset {retried_count} jobs to pending'
        })
        
    except Exception as e:
        print(f"Error retrying batch: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/start-manifest-processing', methods=['POST'])
def start_manifest_processing():
    """Start processing jobs from uploaded manifest and CSVs"""
    try:
        data = request.get_json()
        run_id = data.get('run_id')
        output_target = data.get('output_target', 'test')
        channel_id = data.get('channel_id')
        template_id = data.get('template_id')
        youtube_upload_test = data.get('youtube_upload_test', False)
        selected_voice = data.get('selected_voice', 'af-alt')
        
        if not all([run_id, channel_id, template_id]):
            return jsonify({'error': 'run_id, channel_id, and template_id are required'}), 400
        
        # Determine staging bucket
        if output_target == 'test':
            bucket_name = 'trivia-videos-test'
        else:
            bucket_name = 'trivia-videos-prod'
        
        # Download and parse manifest
        storage_client = storage.Client()
        bucket = storage_client.bucket(bucket_name)
        manifest_blob = bucket.blob(f"staging/{run_id}/manifest.json")
        
        if not manifest_blob.exists():
            return jsonify({'error': 'Manifest not found'}), 404
        
        manifest_data = json.loads(manifest_blob.download_as_text())
        
        # Create jobs for each batch
        created_jobs = []
        bulk_upload_id = f"manifest_{run_id}"
        
        print(f"Processing {len(manifest_data['batches'])} batches from manifest")
        
        for i, batch in enumerate(manifest_data['batches']):
            try:
                print(f"Processing batch {i}: {batch.get('filename', 'unknown')}")
                
                # Download CSV from staging
                csv_filename = batch['filename']
                # Use the filename directly as it should match what was uploaded
                csv_blob = bucket.blob(f"staging/{run_id}/csv/{csv_filename}")
                
                print(f"Looking for CSV: staging/{run_id}/csv/{csv_filename}")
                
                if not csv_blob.exists():
                    print(f"CSV file not found: {csv_filename}")
                    continue
                
                print(f"CSV file found, downloading content...")
                
                # Parse CSV content
                csv_content = csv_blob.download_as_text()
                questions = parse_csv_content(csv_content)
                
                print(f"Parsed {len(questions)} questions from CSV")
                
                if not questions:
                    print(f"No questions found in CSV: {csv_filename}")
                    continue
                
                # Clean title and get description from manifest
                title = clean_video_title(batch.get('title', csv_filename))
                youtube_description = batch.get('youtube_description', 'Sports trivia quiz video')
                
                # Create job data with proper structure
                job_data = {
                    'channel_id': channel_id,
                    'template_id': template_id,
                    'input_data': {
                        'questions': questions,
                        'music_enabled': True,
                        'selected_voice': selected_voice
                    },
                    'output_mode': output_target,
                    'youtube_upload_test': youtube_upload_test,
                    'youtube_title': title,
                    'youtube_description': youtube_description,
                    'clean_filename': clean_filename(csv_filename),
                    'csv_filename': csv_filename,
                    'bulk_upload_id': bulk_upload_id,
                    'bulk_upload_index': i,
                    'run_id': run_id,
                    'batch_data': batch,
                    'status': 'pending',
                    'created_at': time.time(),
                    'progress': 0,
                    'error': None
                }
                
                # Create job in Firestore
                print(f"Creating job for batch {i}...")
                job_id = control_center.create_job_from_data(job_data)
                print(f"Created job: {job_id}")
                
                created_jobs.append({
                    'job_id': job_id,
                    'title': title,
                    'question_count': len(questions),
                    'csv_filename': csv_filename
                })
                
                print(f"Successfully processed batch {i}")
                
            except Exception as e:
                print(f"Error processing batch {i}: {e}")
                continue
        
        if not created_jobs:
            return jsonify({'error': 'No jobs were created'}), 400
        
        return jsonify({
            'run_id': run_id,
            'output_target': output_target,
            'created_jobs': created_jobs,
            'total_jobs': len(created_jobs),
            'message': f'Successfully created {len(created_jobs)} jobs from manifest'
        })
        
    except Exception as e:
        print(f"Error starting manifest processing: {e}")
        return jsonify({'error': str(e)}), 500

def parse_csv_content(csv_content):
    """Parse CSV content into questions list"""
    try:
        import io
        import csv
        
        questions = []
        reader = csv.DictReader(io.StringIO(csv_content))
        
        for row in reader:
            if not row.get('question'):
                continue
            
            question = {
                'question': row['question'].strip(),
                'answer_a': row.get('answer_a', '').strip(),
                'answer_b': row.get('answer_b', '').strip(),
                'answer_c': row.get('answer_c', '').strip(),
                'answer_d': row.get('answer_d', '').strip(),
                'correct_answer': row.get('correct_answer', '').strip(),
                'explanation': row.get('explanation', '').strip()
            }
            
            # Validate required fields
            if question['question'] and question['correct_answer']:
                questions.append(question)
        
        return questions
        
    except Exception as e:
        print(f"Error parsing CSV content: {e}")
        return []

def clean_filename(csv_filename):
    """
    Clean filename for safe storage
    """
    if not csv_filename:
        return "sports_quiz_video"
    
    # Remove .csv extension
    filename = csv_filename.replace('.csv', '')
    
    # Replace spaces and special characters with underscores
    filename = re.sub(r'[^\w\-]', '_', filename)
    
    # Remove multiple underscores
    filename = re.sub(r'_+', '_', filename)
    
    # Remove leading/trailing underscores
    filename = filename.strip('_')
    
    # Ensure it starts with sports if not present
    if not filename.lower().startswith('sports'):
        filename = f"sports_{filename}"
    
    # Convert to lowercase
    filename = filename.lower()
    
    return filename if filename else "sports_quiz_video"

def clean_video_title(csv_filename):
    """
    Clean and format CSV filename for YouTube-ready video title
    """
    if not csv_filename:
        return "Sports Quiz Video"
    
    # Remove .csv extension
    title = csv_filename.replace('.csv', '')
    
    # Replace hyphens and underscores with spaces
    title = re.sub(r'[-_]', ' ', title)
    
    # Remove extra whitespace
    title = re.sub(r'\s+', ' ', title).strip()
    
    # Ensure "Sports" is present (add if missing)
    if 'sports' not in title.lower():
        title = f"Sports {title}"
    
    # Title case formatting
    title = title.title()
    
    # Fix common words that should be lowercase
    title = re.sub(r'\b(And|Or|The|Of|In|On|At|To|For|With|By)\b', lambda m: m.group(1).lower(), title)
    
    # Capitalize first word
    if title:
        title = title[0].upper() + title[1:]
    
    return title if title else "Sports Quiz Video"

def build_youtube_description(batch_data, question_count):
    """Build YouTube-ready description from batch data"""
    try:
        # Extract data with defaults
        title = batch_data.get('title', 'Sports Trivia Quiz')
        size = batch_data.get('size', question_count)
        sports_mix = batch_data.get('sports_mix', {})
        theme_keywords = batch_data.get('theme_keywords', [])
        timestamps = batch_data.get('timestamps', {})
        
        # Build hook
        sports_list = list(sports_mix.keys())[:3] if sports_mix else []
        if sports_list:
            sports_text = ', '.join(sports_list)
            hook = f"Think you know sports? Test yourself with {size} sports trivia questions covering {sports_text} and more!"
        else:
            hook = f"Think you know sports? Test yourself with {size} sports trivia questions covering general sports knowledge!"
        
        # How to play section
        how_to_play = f"""🎯 How to Play:
• Answer {size} sports trivia questions
• You have 7 seconds per question
• Choose the correct answer from 4 options
• Test your sports knowledge and see how you score!

🏆 Perfect for:
• Sports fans and enthusiasts
• Trivia lovers
• Family game nights
• Sports bar challenges
• Educational content

📊 Question Breakdown:
{size} challenging sports trivia questions covering various sports and topics.

#SportsTrivia #TriviaQuiz #SportsQuiz #TriviaChallenge #SportsFans #QuizTime #SportsKnowledge #TriviaGame #SportsQuestions #QuizChallenge"""

        return f"{hook}\n\n{how_to_play}"
        
    except Exception as e:
        print(f"Error building YouTube description: {e}")
        return f"Test your sports knowledge with {question_count} challenging trivia questions! Perfect for sports fans and trivia lovers. #SportsTrivia #TriviaQuiz"

@app.route('/api/tts-preview', methods=['POST'])
def tts_preview():
    """Generate TTS preview audio"""
    try:
        data = request.get_json()
        text = data.get('text', 'Hello, this is a preview.')
        voice = data.get('voice', 'af-alt')
        
        # Use af-alt as the default voice for external TTS service
        # Voice mapping removed - using af-alt as default
        
        # Create previews directory
        previews_dir = Path("./audio_output/previews")
        previews_dir.mkdir(parents=True, exist_ok=True)
        
        # Generate preview audio using external TTS service
        import requests
        import tempfile
        
        try:
            # Use the same TTS endpoint as the pipeline
            tts_endpoint = "http://tts.ytsites.org/v1/audio"
            payload = {
                "model": "tts1",
                "voice": voice,
                "input": text,
                "response_format": "mp3"
            }
            
            response = requests.post(tts_endpoint, json=payload, timeout=30)
            
            if response.status_code == 200:
                # Create temporary file
                with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as temp_file:
                    temp_file.write(response.content)
                    temp_file_path = temp_file.name
                
                result = {
                    'success': True,
                    'file_path': temp_file_path
                }
            else:
                result = {
                    'success': False,
                    'error': f'TTS failed with status {response.status_code}'
                }
        except Exception as e:
            result = {
                'success': False,
                'error': str(e)
            }
        
        if result.get('success') and result.get('file_path'):
            # Move to persistent previews directory
            import shutil
            import time
            timestamp = int(time.time())
            preview_filename = f"{voice}_{timestamp}.mp3"
            preview_path = previews_dir / preview_filename
            
            # Copy to previews directory (don't delete original)
            shutil.copy2(result['file_path'], preview_path)
            
            # Read the generated audio file
            with open(result['file_path'], 'rb') as f:
                audio_content = f.read()
            
            # Clean up the temporary file
            os.unlink(result['file_path'])
            
            from flask import Response
            return Response(
                audio_content,
                mimetype='audio/mpeg',
                headers={
                    'Content-Disposition': 'inline; filename=preview.mp3',
                    'Cache-Control': 'no-cache',
                    'X-Preview-File': f'/previews/{preview_filename}'
                }
            )
        else:
            error_msg = result.get('error', 'TTS generation failed')
            print(f"TTS Preview Error for voice '{voice}': {error_msg}")
            return jsonify({'error': error_msg, 'voice': voice}), 500
            
    except Exception as e:
        print(f"TTS Preview Exception: {str(e)}")
        return jsonify({'error': str(e), 'voice': voice}), 500

@app.route('/health/editor')
def health_editor():
    manifest = load_editor_manifest()
    return jsonify({
        'build_id': request.args.get('build') or 'runtime',
        'manifest_files': manifest,
        'timestamp': datetime.utcnow().isoformat() + 'Z'
    })


@app.route('/api/logs/client', methods=['POST'])
def client_logs():
    try:
        payload = request.get_json(force=True, silent=True) or {}
        print(f"[client-log] {payload}")
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 400

@app.route('/api/templates/<template_id>/reference', methods=['POST'])
def upload_reference_png(template_id):
    """Upload reference PNG for template"""
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file uploaded'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        # Validate PNG
        if not file.filename.lower().endswith('.png'):
            return jsonify({'error': 'Only PNG files allowed'}), 400
        
        # Check file size (8MB max)
        file.seek(0, 2)
        file_size = file.tell()
        file.seek(0)
        
        if file_size > 8 * 1024 * 1024:
            return jsonify({'error': 'File too large (max 8MB)'}), 400
        
        # Generate temp path
        timestamp = int(time.time())
        random_suffix = uuid.uuid4().hex[:8]
        filename = f"{timestamp}-{random_suffix}.png"
        temp_path = f"temp/templates/{template_id}/{filename}"
        
        # Upload to GCS
        bucket = storage_client.bucket(GCS_BUCKET)
        blob = bucket.blob(temp_path)
        
        file.seek(0)
        blob.upload_from_file(file, content_type='image/png')
        
        # Generate signed URL
        signed_url = blob.generate_signed_url(
            version="v4",
            expiration=datetime.timedelta(hours=24),
            method="GET"
        )
        
        # Get image dimensions
        from PIL import Image
        import io
        file.seek(0)
        img = Image.open(io.BytesIO(file.read()))
        width, height = img.size
        
        return jsonify({
            'success': True,
            'gcs_path': f"gs://{GCS_BUCKET}/{temp_path}",
            'signed_url': signed_url,
            'width': width,
            'height': height
        })
        
    except Exception as e:
        return jsonify({'error': f'Failed to upload reference: {str(e)}'}), 500

@app.route('/api/templates/<template_id>/reference', methods=['DELETE'])
def delete_reference_png(template_id):
    """Delete reference PNG for template"""
    try:
        # List and delete temp files for this template
        bucket = storage_client.bucket(GCS_BUCKET)
        prefix = f"temp/templates/{template_id}/"
        
        blobs = bucket.list_blobs(prefix=prefix)
        deleted_count = 0
        
        for blob in blobs:
            blob.delete()
            deleted_count += 1
        
        return jsonify({
            'success': True,
            'deleted_count': deleted_count
        })
        
    except Exception as e:
        return jsonify({'error': f'Failed to delete reference: {str(e)}'}), 500

@app.route('/api/templates/cleanup-duplicates', methods=['POST'])
def cleanup_duplicate_templates():
    """Remove duplicate templates, keeping only the most recent one for each name"""
    try:
        templates_ref = firestore_client.collection(f"{FIRESTORE_COLLECTION_PREFIX}_templates")
        templates = list(templates_ref.stream())
        
        # Group templates by name
        templates_by_name = {}
        for template in templates:
            template_data = template.to_dict()
            name = template_data.get('name', 'Unnamed Template')
            
            if name not in templates_by_name:
                templates_by_name[name] = []
            
            templates_by_name[name].append({
                'id': template.id,
                'data': template_data,
                'created_at': template_data.get('created_at', ''),
                'updated_at': template_data.get('updated_at', '')
            })
        
        # Find duplicates and remove older ones
        duplicates_removed = 0
        for name, template_list in templates_by_name.items():
            if len(template_list) > 1:
                print(f"Found {len(template_list)} duplicates for template '{name}'")
                
                # Sort by updated_at, then created_at (most recent first)
                template_list.sort(key=lambda t: (
                    t['updated_at'] or t['created_at'] or '1970-01-01T00:00:00Z'
                ), reverse=True)
                
                # Keep the first (most recent), remove the rest
                for i, template in enumerate(template_list[1:], 1):
                    print(f"  Removing duplicate {i+1}: {template['id']}")
                    templates_ref.document(template['id']).delete()
                    duplicates_removed += 1
        
        return jsonify({
            'success': True,
            'message': f'Removed {duplicates_removed} duplicate templates',
            'duplicates_removed': duplicates_removed
        })
        
    except Exception as e:
        return jsonify({'error': f'Failed to cleanup duplicates: {str(e)}'}), 500

@app.route('/api/templates', methods=['GET', 'POST'])
def templates_api():
    """Get all templates or create new template"""
    if request.method == 'GET':
        try:
            templates_ref = firestore_client.collection(f"{FIRESTORE_COLLECTION_PREFIX}_templates")
            templates = []
            
            for doc in templates_ref.stream():
                template_data = doc.to_dict()
                templates.append({
                    'id': doc.id,
                    'name': template_data.get('name', 'Unnamed Template'),
                    'state': template_data.get('state', 'draft'),
                    'version': template_data.get('version', '1.0.0'),
                    'created_at': template_data.get('created_at'),
                    'updated_at': template_data.get('updated_at'),
                    'channel_id': template_data.get('channel_id'),
                    'environment': template_data.get('environment'),
                    'asset_refs': template_data.get('asset_refs', {}),
                    'settings': template_data.get('settings', {}),
                    'video_dimensions': template_data.get('video_dimensions', {'width': 1920, 'height': 1080}),
                    'description': template_data.get('description', '')
                })
            
            return jsonify(templates)
            
        except Exception as e:
            return jsonify({'error': f'Failed to get templates: {str(e)}'}), 500
    
    elif request.method == 'POST':
        try:
            data = request.get_json()
            
            # Generate template ID
            template_id = f"template_{uuid.uuid4().hex[:12]}"
            
            # Prepare template data
            template_data = {
                'id': template_id,
                'name': data.get('name', 'New Template'),
                'state': data.get('state', 'draft'),
                'version': data.get('version', '1.0.0'),
                'asset_refs': data.get('asset_refs', {}),
                'layout_base': data.get('layout_base', {'width': 1920, 'height': 1080}),
                'layout': data.get('layout', {}),
                'layout_norm': data.get('layout_norm', {}),
                'styles': data.get('styles', {}),
                'timing': data.get('timing', {}),
                'created_at': datetime.utcnow().isoformat() + "Z",
                'updated_at': datetime.utcnow().isoformat() + "Z"
            }
            
            # Save to Firestore
            templates_ref = firestore_client.collection(f"{FIRESTORE_COLLECTION_PREFIX}_templates")
            templates_ref.document(template_id).set(template_data)
            
            return jsonify({
                'success': True,
                'template_id': template_id,
                'template': template_data
            })
            
        except Exception as e:
            return jsonify({'error': f'Failed to create template: {str(e)}'}), 500

@app.route('/api/templates/<template_id>', methods=['GET', 'PUT'])
def template_api(template_id):
    """Get or update specific template"""
    if request.method == 'GET':
        try:
            template_ref = firestore_client.collection(f"{FIRESTORE_COLLECTION_PREFIX}_templates").document(template_id)
            template_doc = template_ref.get()
            
            if not template_doc.exists:
                return jsonify({'error': 'Template not found'}), 404
            
            template_data = template_doc.to_dict()
            template_data['id'] = template_id
            
            return jsonify({
                'success': True,
                'template': template_data
            })
            
        except Exception as e:
            return jsonify({'error': f'Failed to get template: {str(e)}'}), 500
    
    elif request.method == 'PUT':
        try:
            data = request.get_json()
            
            # Validate required fields
            required_fields = ['state', 'version', 'asset_refs', 'layout_base', 'layout', 'layout_norm', 'styles', 'timing']
            for field in required_fields:
                if field not in data:
                    return jsonify({'error': f'Missing required field: {field}'}), 400
            
            # Validate state
            if data['state'] not in ['draft', 'published']:
                return jsonify({'error': 'Invalid state. Must be draft or published'}), 400
            
            # If trying to PUT with published state, reject (use publish endpoint)
            if data['state'] == 'published':
                return jsonify({'error': 'Cannot update published template directly. Use publish endpoint.'}), 409
            
            # Recompute layout_norm server-side (trust but verify)
            computed_norm = {}
            base = data['layout_base']
            for key, region in data['layout'].items():
                computed_norm[key] = {
                    'x': region['x'] / base['width'],
                    'y': region['y'] / base['height'],
                    'width': region['width'] / base['width'],
                    'height': region['height'] / base['height']
                }
            
            # Update template data
            template_data = {
                'name': data.get('name', 'Template'),
                'state': data['state'],
                'version': data['version'],
                'asset_refs': data['asset_refs'],
                'layout_base': data['layout_base'],
                'layout': data['layout'],
                'layout_norm': computed_norm,  # Use server-computed values
                'styles': data['styles'],
                'timing': data['timing'],
                'updated_at': datetime.utcnow().isoformat() + "Z"
            }
            
            # Check if document exists, if not add created_at
            template_ref = firestore_client.collection(f"{FIRESTORE_COLLECTION_PREFIX}_templates").document(template_id)
            existing_doc = template_ref.get()
            
            if not existing_doc.exists:
                # New template - add created_at
                template_data['created_at'] = datetime.utcnow().isoformat() + "Z"
                template_ref.set(template_data)
            else:
                # Existing template - keep created_at, update
                existing_data = existing_doc.to_dict()
                if 'created_at' in existing_data:
                    template_data['created_at'] = existing_data['created_at']
                template_ref.set(template_data)
            
            # Get the updated document to return
            updated_doc = template_ref.get()
            updated_data = updated_doc.to_dict()
            updated_data['id'] = template_id
            
            return jsonify({
                'success': True,
                'id': template_id,
                'template': updated_data
            })
            
        except Exception as e:
            return jsonify({'error': f'Failed to update template: {str(e)}'}), 500

@app.route('/api/assets', methods=['GET'])
def get_assets():
    """Get assets filtered by type and channel_id"""
    try:
        asset_type = request.args.get('type')
        channel_id = request.args.get('channel_id')
        
        if not asset_type:
            return jsonify({'error': 'type parameter is required'}), 400
        
        assets_ref = firestore_client.collection(f"{FIRESTORE_COLLECTION_PREFIX}_assets")
        
        # Build query
        query = assets_ref.where('type', '==', asset_type)
        
        # Don't filter by channel_id in the query since the field is null
        # We'll filter after extracting channel_id from gcs_path
        
        assets = []
        for doc in query.stream():
            asset_data = doc.to_dict()
            asset_data['id'] = doc.id
            
            # Always try to extract channel_id from gcs_path if it exists
            if asset_data.get('gcs_path'):
                gcs_path = asset_data['gcs_path']
                
                # Extract channel from path like: gs://bucket/channels/channel-name/assets/...
                if '/channels/' in gcs_path:
                    path_parts = gcs_path.split('/channels/')[1].split('/')
                    if len(path_parts) > 0:
                        extracted_channel = path_parts[0]
                        asset_data['channel_id'] = extracted_channel
            
            # Now filter by channel_id if specified
            if channel_id:
                if asset_data.get('channel_id') not in [channel_id, 'shared']:
                    continue
            
            assets.append(asset_data)
        
        return jsonify({
            'success': True,
            'assets': assets
        })
        
    except Exception as e:
        return jsonify({'error': f'Failed to get assets: {str(e)}'}), 500

@app.route('/api/assets/<asset_id>/signed-url', methods=['GET'])
def get_asset_signed_url(asset_id):
    """Get signed URL for an asset"""
    try:
        asset_ref = firestore_client.collection(f"{FIRESTORE_COLLECTION_PREFIX}_assets").document(asset_id)
        asset_doc = asset_ref.get()
        
        if not asset_doc.exists:
            return jsonify({'error': 'Asset not found'}), 404
        
        asset_data = asset_doc.to_dict()
        gcs_path = asset_data.get('gcs_path')
        
        if not gcs_path:
            return jsonify({'error': 'Asset has no GCS path'}), 400
        
        # Generate signed URL based on gcs_path bucket and blob
        # Accept either full gs://bucket/path or a plain path under the current env bucket
        if gcs_path.startswith("gs://"):
            parts = gcs_path.split('/')
            bucket_name = parts[2]
            blob_name = '/'.join(parts[3:])
            bucket = storage_client.bucket(bucket_name)
        else:
            bucket = storage_client.bucket(GCS_BUCKET)
            blob_name = gcs_path
        
        if not blob_name:
            return jsonify({'error': 'Invalid GCS path'}), 400
        
        blob = bucket.blob(blob_name)
        
        signed_url = blob.generate_signed_url(
            version="v4",
            expiration=timedelta(hours=1),
            method="GET"
        )
        
        return jsonify({
            'success': True,
            'signed_url': signed_url
        })
        
    except Exception as e:
        return jsonify({'error': f'Failed to get signed URL: {str(e)}'}), 500

@app.route('/api/templates/<template_id>/publish', methods=['POST'])
def publish_template(template_id):
    """Publish template with validation"""
    try:
        # Get template
        template_ref = firestore_client.collection(f"{FIRESTORE_COLLECTION_PREFIX}_templates").document(template_id)
        template_doc = template_ref.get()
        
        if not template_doc.exists:
            return jsonify({'error': 'Template not found'}), 404
        
        template_data = template_doc.to_dict()
        
        # Validation
        errors = []
        
        if not template_data.get('version'):
            errors.append('Missing version')
        
        if not template_data.get('asset_refs', {}).get('background'):
            errors.append('Missing background asset')
        
        if not template_data.get('layout'):
            errors.append('Missing layout')
        
        if not template_data.get('styles'):
            errors.append('Missing styles')
        
        if not template_data.get('timing'):
            errors.append('Missing timing')
        
        # Validate background asset exists
        if template_data.get('asset_refs', {}).get('background'):
            background_id = template_data['asset_refs']['background']
            asset_ref = firestore_client.collection(f"{FIRESTORE_COLLECTION_PREFIX}_assets").document(background_id)
            asset_doc = asset_ref.get()
            
            if not asset_doc.exists:
                errors.append('Background asset not found')
            else:
                asset_data = asset_doc.to_dict()
                gcs_path = asset_data.get('gcs_path')
                
                if gcs_path:
                    bucket_name = gcs_path.split('/')[2]
                    blob_name = '/'.join(gcs_path.split('/')[3:])
                    bucket = storage_client.bucket(bucket_name)
                    blob = bucket.blob(blob_name)
                    
                    if not blob.exists():
                        errors.append('Background asset file not found in GCS')
        
        # Validate font asset if present
        if template_data.get('asset_refs', {}).get('font'):
            font_id = template_data['asset_refs']['font']
            asset_ref = firestore_client.collection(f"{FIRESTORE_COLLECTION_PREFIX}_assets").document(font_id)
            asset_doc = asset_ref.get()
            
            if not asset_doc.exists:
                errors.append('Font asset not found')
        
        # Validate layout bounds
        layout = template_data.get('layout', {})
        layout_base = template_data.get('layout_base', {'width': 1920, 'height': 1080})
        
        for region_name, region_data in layout.items():
            if not isinstance(region_data, dict):
                continue
            
            x = region_data.get('x', 0)
            y = region_data.get('y', 0)
            width = region_data.get('width', 0)
            height = region_data.get('height', 0)
            
            if x < 0 or y < 0:
                errors.append(f'{region_name} has negative coordinates')
            
            if x + width > layout_base['width'] or y + height > layout_base['height']:
                errors.append(f'{region_name} extends outside canvas')
            
            if width < 24 or height < 24:
                errors.append(f'{region_name} too small (min 24x24)')
        
        if errors:
            return jsonify({
                'success': False,
                'error': 'Validation failed: ' + ', '.join(errors)
            }), 400
        
        # Publish template
        template_ref.update({
            'state': 'published',
            'updated_at': datetime.utcnow().isoformat() + "Z"
        })
        
        return jsonify({
            'success': True,
            'template_id': template_id
        })
        
    except Exception as e:
        return jsonify({'error': f'Failed to publish template: {str(e)}'}), 500

@app.route('/asset-upload')
def asset_upload():
    """Asset upload page"""
    return render_template('asset_upload.html')

@app.route('/asset-upload-test')
def asset_upload_test():
    """Test page for asset upload functionality"""
    return render_template('asset_upload_test.html')

@app.route('/api/assets/<asset_id>/assign', methods=['POST'])
def assign_asset_to_channel(asset_id):
    """Assign asset to a channel"""
    try:
        data = request.get_json()
        channel_id = data.get('channel_id')
        
        if not channel_id:
            return jsonify({'error': 'Channel ID is required'}), 400
        
        # Get asset document
        doc = assets_collection.document(asset_id).get()
        if not doc.exists:
            return jsonify({'error': 'Asset not found'}), 404
        
        # Update asset with channel assignment
        assets_collection.document(asset_id).update({
            'channel_id': channel_id,
            'assigned_at': datetime.now().isoformat()
        })
        
        return jsonify({'success': True, 'message': 'Asset assigned to channel successfully'})
        
    except Exception as e:
        return jsonify({'error': f'Error assigning asset: {str(e)}'}), 500

@app.route('/api/assets/<asset_id>/unassign', methods=['POST'])
def unassign_asset_from_channel(asset_id):
    """Unassign asset from a channel"""
    try:
        # Get asset document
        doc = assets_collection.document(asset_id).get()
        if not doc.exists:
            return jsonify({'error': 'Asset not found'}), 404
        
        # Remove channel assignment
        assets_collection.document(asset_id).update({
            'channel_id': None,
            'unassigned_at': datetime.now().isoformat()
        })
        
        return jsonify({'success': True, 'message': 'Asset unassigned from channel successfully'})
        
    except Exception as e:
        return jsonify({'error': f'Error unassigning asset: {str(e)}'}), 500

@app.route('/api/templates')
def get_templates():
    """Get all templates with versioning support"""
    try:
        templates = template_manager.get_all_templates()
        
        # Transform to new contract format
        formatted_templates = []
        for template in templates:
            formatted_template = {
                "id": template.get("id", str(uuid.uuid4())),
                "name": template.get("name", "Unnamed Template"),
                "version": template.get("version", "1.0.0"),
                "status": template.get("status", "published"),
                "created_at": template.get("created_at", datetime.utcnow().isoformat() + "Z"),
                "updated_at": template.get("updated_at", datetime.utcnow().isoformat() + "Z"),
                "fields": template.get("fields", []),
                "assets": template.get("assets", {})
            }
            formatted_templates.append(formatted_template)
        
        return jsonify({
            "templates": formatted_templates,
            "total": len(formatted_templates)
        }), 200
    except Exception as e:
        return jsonify({
            "error": f"Error getting templates: {str(e)}",
            "code": "TEMPLATES_FETCH_FAILED",
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }), 500

@app.route('/api/templates', methods=['POST'])
def create_template():
    """Create a new template with asset validation"""
    data = request.get_json()
    name = data.get('name', 'New Template')
    description = data.get('description', '')
    video_dimensions = data.get('video_dimensions', (1920, 1080))
    channel_id = data.get('channel_id', current_channel_id)
    assets = data.get('assets', {})
    
    if not channel_id:
        return jsonify({'error': 'No channel selected'}), 400
    
    # Validate assets if provided
    if assets:
        missing_assets, placeholder_used = validate_template_assets("new_template", data)
        
        if missing_assets and not PLACEHOLDER_MODE:
            return jsonify({
                'error': f'Missing required assets: {", ".join(missing_assets)}. Upload assets first or enable placeholder mode.',
                'code': 'MISSING_ASSETS',
                'missing_assets': missing_assets
            }), 400
    
    template_id = template_manager.create_template(name, description, video_dimensions, channel_id=channel_id)
    
    # Add asset validation info to response
    response_data = {
        'success': True,
        'template_id': template_id,
        'message': f'Template "{name}" created successfully'
    }
    
    if assets:
        missing_assets, placeholder_used = validate_template_assets(template_id, data)
        if missing_assets:
            response_data['placeholder_mode'] = PLACEHOLDER_MODE
            response_data['missing_assets'] = missing_assets
            if PLACEHOLDER_MODE:
                response_data['warning'] = f'Template created with {len(missing_assets)} placeholder assets'
    
    return jsonify(response_data)

@app.route('/api/templates/<template_id>/publish', methods=['POST'])
def publish_template_api(template_id):
    """Publish a template (only if all assets are valid)"""
    try:
        template = template_manager.get_template(template_id)
        if not template:
            return jsonify({
                'error': 'Template not found',
                'code': 'TEMPLATE_NOT_FOUND',
                'timestamp': datetime.utcnow().isoformat() + "Z"
            }), 404
        
        # Validate all assets before publishing
        missing_assets, placeholder_used = validate_template_assets(template_id, template)
        
        if missing_assets:
            return jsonify({
                'error': f'Cannot publish template with missing assets: {", ".join(missing_assets)}',
                'code': 'MISSING_ASSETS_FOR_PUBLISH',
                'missing_assets': missing_assets,
                'timestamp': datetime.utcnow().isoformat() + "Z"
            }), 400
        
        # Update template status to published
        template['status'] = 'published'
        template['published_at'] = datetime.utcnow().isoformat() + "Z"
        
        # Save updated template
        template_manager.update_template(template_id, template)
        
        return jsonify({
            'success': True,
            'message': f'Template "{template.get("name", template_id)}" published successfully',
            'template_id': template_id,
            'status': 'published'
        }), 200
        
    except Exception as e:
        return jsonify({
            'error': f'Error publishing template: {str(e)}',
            'code': 'PUBLISH_FAILED',
            'timestamp': datetime.utcnow().isoformat() + "Z"
        }), 500

@app.route('/api/templates/<template_id>', methods=['PUT'])
def update_template(template_id):
    """Update template configuration"""
    data = request.get_json()
    
    success = template_manager.update_template(template_id, data)
    if success:
        return jsonify({
            'success': True,
            'message': 'Template updated successfully'
        })
    return jsonify({'error': 'Failed to update template'}), 400

@app.route('/api/templates/<template_id>', methods=['DELETE'])
def delete_template(template_id):
    """Delete template"""
    success = template_manager.delete_template(template_id)
    if success:
        return jsonify({
            'success': True,
            'message': 'Template deleted successfully'
        })
    return jsonify({'error': 'Failed to delete template'}), 400

@app.route('/api/templates/backgrounds')
def get_backgrounds():
    """Get available background videos"""
    try:
        backgrounds = template_manager.get_background_assets()
        return jsonify(backgrounds)
    except Exception as e:
        return jsonify({'error': f'Failed to get backgrounds: {str(e)}'}), 400

@app.route('/api/templates/<template_id>/preview-frames', methods=['POST'])
def preview_frames(template_id):
    """Generate preview frames for a template"""
    try:
        data = request.get_json()
        background_asset_id = data.get('background_asset_id')
        
        print(f"DEBUG: Preview request for template {template_id}, background {background_asset_id}")
        
        if not background_asset_id:
            print("DEBUG: No background asset ID provided")
            return jsonify({'error': 'Background asset ID required'}), 400
        
        # Extract preview frames
        print(f"DEBUG: Calling extract_template_preview_frames...")
        preview_data = template_manager.extract_template_preview_frames(template_id, background_asset_id)
        
        print(f"DEBUG: Preview data result: {preview_data}")
        
        if not preview_data:
            print("DEBUG: No preview data returned")
            return jsonify({'error': 'Failed to extract preview frames'}), 400
        
        # Save previews to GCS
        preview_urls = {}
        for preview_type, preview_path in preview_data['previews'].items():
            gcs_url = template_manager.save_preview_to_gcs(preview_path, template_id, preview_type)
            if gcs_url:
                preview_urls[preview_type] = gcs_url
        
        return jsonify({
            'success': True,
            'preview_urls': preview_urls,
            'background_asset': preview_data['background_asset'],
            'template_id': template_id
        })
        
    except Exception as e:
        return jsonify({'error': f'Failed to generate preview frames: {str(e)}'}), 400

@app.route('/api/templates/<template_id>/generate-script', methods=['POST'])
def generate_script(template_id):
    """Generate script for a template"""
    try:
        script_content = template_manager.generate_script_from_template(template_id)
        script_path = template_manager.save_generated_script(template_id, script_content)
        
        return jsonify({
            'success': True,
            'script_path': script_path,
            'message': 'Script generated successfully'
        })
    except Exception as e:
        return jsonify({'error': f'Failed to generate script: {str(e)}'}), 400

# Template Configuration UI Routes
@app.route('/api/templates/<template_id>/text-config')
def get_template_text_config(template_id):
    """Get text configuration for a template"""
    try:
        template = template_manager.get_template(template_id)
        if not template:
            return jsonify({'error': 'Template not found'}), 404
        
        # Extract text configuration from template
        text_boxes = template.get('text_boxes', {})
        
        # Convert to our enhanced format
        config = {
            'question': text_boxes.get('question', {}),
            'answer': text_boxes.get('answer_a', {}),  # Use answer_a as base for all answers
            'explanation': text_boxes.get('explanation', {})
        }
        
        return jsonify({
            'success': True,
            'config': config,
            'template_id': template_id
        })
        
    except Exception as e:
        return jsonify({'error': f'Failed to get text config: {str(e)}'}), 400

@app.route('/api/templates/<template_id>/text-config', methods=['PUT'])
def update_template_text_config(template_id):
    """Update text configuration for a template"""
    try:
        data = request.get_json()
        config = data.get('config', {})
        
        # Get current template
        template = template_manager.get_template(template_id)
        if not template:
            return jsonify({'error': 'Template not found'}), 404
        
        # Update text_boxes with new configuration
        text_boxes = template.get('text_boxes', {})
        
        # Apply question config to question box
        if 'question' in config:
            text_boxes['question'] = {**text_boxes.get('question', {}), **config['question']}
        
        # Apply answer config to all answer boxes
        if 'answer' in config:
            for answer_key in ['answer_a', 'answer_b', 'answer_c', 'answer_d']:
                text_boxes[answer_key] = {**text_boxes.get(answer_key, {}), **config['answer']}
        
        # Apply explanation config
        if 'explanation' in config:
            text_boxes['explanation'] = {**text_boxes.get('explanation', {}), **config['explanation']}
        
        # Update template
        template['text_boxes'] = text_boxes
        success = template_manager.update_template(template_id, template)
        
        if success:
            return jsonify({
                'success': True,
                'message': 'Text configuration updated successfully'
            })
        else:
            return jsonify({'error': 'Failed to update template'}), 400
            
    except Exception as e:
        return jsonify({'error': f'Failed to update text config: {str(e)}'}), 400

# Enhanced Template Editor API Endpoints

@app.route('/api/templates/backgrounds')
def get_available_backgrounds():
    """Get list of available background videos"""
    try:
        from enhanced_template_manager import EnhancedTemplateManager
        
        manager = EnhancedTemplateManager()
        backgrounds = manager.get_available_backgrounds()
        
        return jsonify({
            'success': True,
            'backgrounds': backgrounds
        })
        
    except Exception as e:
        return jsonify({'error': f'Failed to get backgrounds: {str(e)}'}), 400

@app.route('/api/templates/background-preview')
def get_background_preview():
    """Generate background preview image"""
    try:
        from enhanced_template_manager import EnhancedTemplateManager
        
        video_path = request.args.get('path')
        if not video_path:
            return jsonify({'error': 'Video path required'}), 400
        
        manager = EnhancedTemplateManager()
        
        # Create preview
        preview_url = manager._create_background_preview(video_path)
        
        if preview_url:
            return jsonify({
                'success': True,
                'preview_url': preview_url
            })
        else:
            return jsonify({'error': 'Failed to create preview'}), 400
            
    except Exception as e:
        return jsonify({'error': f'Failed to create preview: {str(e)}'}), 400

@app.route('/api/templates', methods=['POST'])
def create_enhanced_template():
    """Create a new template with enhanced features"""
    try:
        from enhanced_template_manager import EnhancedTemplateManager
        
        data = request.get_json()
        name = data.get('name', 'New Template')
        description = data.get('description', '')
        background_video = data.get('background_video')
        text_boxes = data.get('text_boxes', {})
        
        manager = EnhancedTemplateManager()
        
        # Create template
        template_id = manager.create_template(name, description, background_video)
        
        if template_id and text_boxes:
            # Update text boxes if provided
            manager.update_text_boxes(template_id, text_boxes)
        
        if template_id:
            return jsonify({
                'success': True,
                'template_id': template_id,
                'message': 'Template created successfully'
            })
        else:
            return jsonify({'error': 'Failed to create template'}), 400
            
    except Exception as e:
        return jsonify({'error': f'Failed to create template: {str(e)}'}), 400

@app.route('/api/template-studio/<template_id>', methods=['PUT'])
def update_template_studio(template_id):
    """Update template from Template Studio (enhanced format)"""
    try:
        data = request.get_json()
        
        # Use the existing template manager
        success = template_manager.update_template(template_id, data)
        
        if success:
            return jsonify({
                'success': True,
                'message': 'Template updated successfully',
                'template': data
            })
        else:
            return jsonify({'error': 'Failed to update template'}), 500
            
    except Exception as e:
        return jsonify({'error': f'Failed to update template: {str(e)}'}), 500

@app.route('/api/templates/<template_id>', methods=['PUT'])
def update_enhanced_template(template_id):
    """Update template with enhanced features"""
    try:
        from enhanced_template_manager import EnhancedTemplateManager
        
        data = request.get_json()
        
        manager = EnhancedTemplateManager()
        
        # Get current template
        template_data = manager.get_template(template_id)
        if not template_data:
            return jsonify({'error': 'Template not found'}), 404
        
        # Update fields
        if 'name' in data:
            template_data['name'] = data['name']
        if 'description' in data:
            template_data['description'] = data['description']
        if 'text_boxes' in data:
            template_data['text_boxes'] = data['text_boxes']
        if 'background_video' in data:
            template_data['background_video'] = data['background_video']
        
        # Update template
        success = manager.update_template(template_id, template_data)
        
        if success:
            return jsonify({
                'success': True,
                'message': 'Template updated successfully'
            })
        else:
            return jsonify({'error': 'Failed to update template'}), 400
            
    except Exception as e:
        return jsonify({'error': f'Failed to update template: {str(e)}'}), 400

@app.route('/api/templates/preview', methods=['POST'])
def generate_template_preview():
    """Generate preview image for template"""
    try:
        from enhanced_template_manager import EnhancedTemplateManager
        
        data = request.get_json()
        template_data = data.get('template_data', {})
        
        manager = EnhancedTemplateManager()
        
        # Create temporary template for preview
        temp_template_id = manager.create_template(
            template_data.get('name', 'Preview Template'),
            template_data.get('description', ''),
            template_data.get('background_video')
        )
        
        if temp_template_id:
            # Update text boxes
            if template_data.get('text_boxes'):
                manager.update_text_boxes(temp_template_id, template_data['text_boxes'])
            
            # Generate preview
            preview_url = f"/api/templates/{temp_template_id}/preview-image"
            
            return jsonify({
                'success': True,
                'preview_url': preview_url,
                'template_id': temp_template_id
            })
        else:
            return jsonify({'error': 'Failed to create preview template'}), 400
            
    except Exception as e:
        return jsonify({'error': f'Failed to generate preview: {str(e)}'}), 400

@app.route('/api/templates/<template_id>/preview-image')
def get_template_preview_image(template_id):
    """Get preview image for template"""
    try:
        from enhanced_template_manager import EnhancedTemplateManager
        
        manager = EnhancedTemplateManager()
        template_data = manager.get_template(template_id)
        
        if not template_data:
            return jsonify({'error': 'Template not found'}), 404
        
        # Generate preview image
        from video_background_extractor import VideoBackgroundExtractor
        extractor = VideoBackgroundExtractor()
        
        # Create preview with text boxes
        temp_dir = tempfile.mkdtemp()
        preview_path = os.path.join(temp_dir, f"preview_{template_id}.png")
        
        background_video = template_data.get('background_video')
        if background_video:
            # Download video if GCS
            if background_video.startswith("gs://"):
                bucket_name, video_path = background_video[5:].split("/", 1)
                local_video = extractor.download_video_from_gcs(bucket_name, video_path)
                if local_video:
                    success = extractor.create_template_preview(
                        local_video, 
                        template_data['text_boxes'], 
                        preview_path
                    )
                    os.unlink(local_video)
                else:
                    success = False
            else:
                success = extractor.create_template_preview(
                    background_video, 
                    template_data['text_boxes'], 
                    preview_path
                )
        else:
            success = False
        
        if success and os.path.exists(preview_path):
            return send_file(preview_path, mimetype='image/png')
        else:
            return jsonify({'error': 'Failed to generate preview'}), 400
            
    except Exception as e:
        return jsonify({'error': f'Failed to get preview: {str(e)}'}), 400

@app.route('/api/templates/<template_id>/text-preview/<text_type>')
def get_text_preview(template_id, text_type):
    """Generate text preview for a template"""
    try:
        from enhanced_text_renderer import EnhancedTextRenderer
        
        # Get template configuration
        template = template_manager.get_template(template_id)
        if not template:
            return jsonify({'error': 'Template not found'}), 404
        
        text_boxes = template.get('text_boxes', {})
        
        # Get configuration for text type
        if text_type == 'question':
            config = text_boxes.get('question', {})
            text = "Which country hosted the 2016 Summer Olympics?"
        elif text_type in ['answer_a', 'answer_b', 'answer_c', 'answer_d']:
            config = text_boxes.get(text_type, {})
            text = "United Kingdom"
        elif text_type == 'explanation':
            config = text_boxes.get('explanation', {})
            text = "Brazil hosted the 2016 Summer Olympics in Rio de Janeiro."
        else:
            return jsonify({'error': 'Invalid text type'}), 400
        
        # Create renderer and generate preview
        renderer = EnhancedTextRenderer()
        
        # Create temporary file
        import tempfile
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.png')
        temp_file.close()
        
        # Render text
        renderer.render_text_to_png(text, config, temp_file.name)
        
        # Return the image file
        from flask import send_file
        return send_file(temp_file.name, mimetype='image/png')
        
    except Exception as e:
        return jsonify({'error': f'Failed to generate preview: {str(e)}'}), 400

@app.route('/api/templates/<template_id>/export-config')
def export_template_config(template_id):
    """Export template configuration as JSON"""
    try:
        template = template_manager.get_template(template_id)
        if not template:
            return jsonify({'error': 'Template not found'}), 404
        
        # Create export data
        export_data = {
            'template_id': template_id,
            'name': template.get('name', 'Unknown Template'),
            'description': template.get('description', ''),
            'text_configuration': template.get('text_boxes', {}),
            'exported_at': datetime.now().isoformat(),
            'version': '1.0'
        }
        
        # Create temporary file
        import tempfile
        temp_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json')
        json.dump(export_data, temp_file, indent=2)
        temp_file.close()
        
        # Return the file
        from flask import send_file
        return send_file(temp_file.name, as_attachment=True, download_name=f'template_{template_id}_config.json')
        
    except Exception as e:
        return jsonify({'error': f'Failed to export config: {str(e)}'}), 400

@app.route('/api/assets/config')
def get_asset_config():
    """Get asset configuration for video pipeline"""
    config = control_center.get_asset_config()
    return jsonify(config)

@app.route('/api/channels/<channel_id>/update-folders', methods=['POST'])
def update_channel_folders(channel_id):
    """Update channel folders configuration"""
    try:
        data = request.get_json()
        folders = data.get('folders', {})
        
        # Update channel in Firestore
        channel_ref = firestore_client.collection(f"{FIRESTORE_COLLECTION_PREFIX}_channels").document(channel_id)
        channel_doc = channel_ref.get()
        
        if not channel_doc.exists:
            return jsonify({'error': f'Channel {channel_id} not found'}), 404
        
        # Update the folders field
        channel_ref.update({
            'folders': folders,
            'updated_at': datetime.utcnow().isoformat() + "Z"
        })
        
        return jsonify({
            'message': f'Channel {channel_id} folders updated successfully',
            'folders': folders
        })
        
    except Exception as e:
        logger.error(f"Error updating channel folders: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/upload-thumbnail', methods=['POST'])
def upload_thumbnail():
    """Upload a thumbnail image for YouTube videos"""
    try:
        if 'thumbnail' not in request.files:
            return jsonify({'error': 'No thumbnail file provided'}), 400
        
        thumbnail_file = request.files['thumbnail']
        if thumbnail_file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        # Validate file type
        allowed_extensions = {'jpg', 'jpeg', 'png', 'webp'}
        if not ('.' in thumbnail_file.filename and 
                thumbnail_file.filename.rsplit('.', 1)[1].lower() in allowed_extensions):
            return jsonify({'error': 'Invalid file type. Only JPG, PNG, and WebP are allowed'}), 400
        
        # Generate unique filename
        timestamp = int(time.time() * 1000)
        filename = f"thumbnail_{timestamp}_{thumbnail_file.filename}"
        
        # Upload to GCS
        bucket_name = f"trivia-{ENVIRONMENT}-assets"
        gcs_path = f"thumbnails/{filename}"
        
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(gcs_path)
        
        # Upload file
        thumbnail_file.seek(0)
        blob.upload_from_file(thumbnail_file, content_type=thumbnail_file.content_type)
        
        # For uniform bucket-level access, we don't need to make individual objects public
        # The bucket should already be configured for public access
        # Return the public URL (assuming bucket allows public access)
        public_url = f"https://storage.googleapis.com/{bucket_name}/{gcs_path}"
        
        return jsonify({
            'success': True,
            'thumbnail_url': public_url,
            'filename': filename,
            'gcs_path': gcs_path
        })
        
    except Exception as e:
        return jsonify({'error': f'Failed to upload thumbnail: {str(e)}'}), 500

@app.route('/api/create-job', methods=['POST'])
def create_job():
    """Create a job with complete snapshot using FirestoreValidator"""
    try:
        data = request.get_json()
        questions = data.get('questions', [])
        channel_id = data.get('channel_id')
        template_id = data.get('template_id')
        music_enabled = data.get('music_enabled', True)  # Default to True for backward compatibility
        output_mode = data.get('output_mode', 'test')  # Default to test mode
        youtube_upload_test = data.get('youtube_upload_test', False)
        tts_engine = data.get('tts_engine', 'custom')  # Default to custom TTS
        selected_voice = data.get('selected_voice', 'af-alt')  # Default to af-alt voice
        thumbnail_file = data.get('thumbnail_file')  # Thumbnail file for YouTube upload
        
        if not questions:
            return jsonify({'error': 'No questions provided'}), 400
        
        if not channel_id:
            return jsonify({'error': 'No channel_id provided'}), 400
        
        if not template_id:
            return jsonify({'error': 'No template_id provided'}), 400
        
        # Use FirestoreValidator for proper job creation
        validator = FirestoreValidator()
        
        # Check if template is published
        template_ref = firestore_client.collection(f"{FIRESTORE_COLLECTION_PREFIX}_templates").document(template_id)
        template_doc = template_ref.get()
        
        if not template_doc.exists:
            return jsonify({'error': f'Template {template_id} not found'}), 404
        
        template_data = template_doc.to_dict()
        
        # In development, allow draft templates for testing
        if ENVIRONMENT == 'production' and template_data.get('state') != 'published':
            return jsonify({'error': f'Template {template_id} is not published'}), 400
        
        # Resolve assets (skip validation in development for custom templates)
        resolved_assets = None
        if ENVIRONMENT == 'production':
            resolved_assets, message = validator.resolve_template_assets(template_id)
            if not resolved_assets:
                return jsonify({'error': f'Cannot resolve assets: {message}'}), 400
        
        # Handle thumbnail upload if provided
        thumbnail_url = None
        if thumbnail_file and youtube_upload_test:
            try:
                # Upload thumbnail to GCS
                timestamp = int(time.time() * 1000)
                filename = f"thumbnail_{timestamp}_{thumbnail_file.name}"
                bucket_name = f"trivia-{ENVIRONMENT}-assets"
                gcs_path = f"thumbnails/{filename}"
                
                bucket = storage_client.bucket(bucket_name)
                blob = bucket.blob(gcs_path)
                
                # Convert File object to bytes for upload
                thumbnail_data = thumbnail_file.read()
                blob.upload_from_string(thumbnail_data, content_type=thumbnail_file.type)
                
                # Make blob publicly readable
                blob.make_public()
                
                # Store the public URL
                thumbnail_url = f"https://storage.googleapis.com/{bucket_name}/{gcs_path}"
                
            except Exception as e:
                return jsonify({'error': f'Failed to upload thumbnail: {str(e)}'}), 500

        # Create job with complete snapshot
        now_iso = datetime.now(timezone.utc).isoformat()
        template_version = template_data.get('version', '1.0.0')
        job_data = {
            'channel_id': channel_id,
            'template_id': template_id,
            'template_version': template_version,
            'input_data': {
                'questions': questions,  # Store questions in input_data!
                'music_enabled': music_enabled,  # Store music setting
                'output_mode': output_mode,
                'youtube_upload_test': youtube_upload_test,
                'tts_engine': tts_engine,  # Store TTS engine selection
                'selected_voice': selected_voice  # Store selected voice
            },
            'resolved_assets': resolved_assets,
            'layout': template_data['layout'],
            'styles': template_data['styles'],
            'timing': template_data['timing'],
            'status': 'pending',
            'stage': 'pending',
            'progress': 0.0,
            'stageEnteredAt': now_iso,
            'lastHeartbeatAt': now_iso,
            'placeholders': {
                'background': False,
                'intro': False,
                'outro': False,
                'audio': False,
                'font': False,
                'question_overlay': False,
                'correct_sfx': False,
                'wrong_sfx': False
            },
            'output': {
                'folder': f'generated/{datetime.now().strftime("%Y/%m/%d")}/{channel_id}/job_{uuid.uuid4().hex[:8]}/',
                'gcs_uri': '',
                'captions_uri': '',
                'thumb_uri': '',
                'manifest_uri': ''
            },
            'error': None,
            'createdAt': now_iso,
            'thumbnail_url': thumbnail_url,  # Store thumbnail URL for YouTube upload
            'updatedAt': now_iso
        }
        
        # Create job document
        job_id = f"job_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        job_ref = firestore_client.collection(f"{FIRESTORE_COLLECTION_PREFIX}_jobs").document(job_id)
        job_ref.set(job_data)
        
        return jsonify({
            'job_id': job_id,
            'status': 'created',
            'template_version': template_data['version'],
            'resolved_assets_count': len(resolved_assets) if resolved_assets else 0,
            'message': 'Job created with complete snapshot'
        })
        
    except Exception as e:
        return jsonify({'error': f'Failed to create job: {str(e)}'}), 500

@app.route('/api/create-production-job', methods=['POST'])
def create_production_job():
    """Create a job with production module enabled and asset validation"""
    data = request.get_json()
    questions = data.get('questions', [])
    use_production = data.get('use_production', True)
    channel_id = data.get('channel_id')
    template_id = data.get('template_id')
    
    if not questions:
        return jsonify({'error': 'No questions provided'}), 400
    
    # Validate template assets if template_id provided
    placeholder_assets_used = []
    if template_id:
        template = template_manager.get_template(template_id)
        if template:
            missing_assets, placeholder_used = validate_template_assets(template_id, template)
            
            if missing_assets and not PLACEHOLDER_MODE:
                return jsonify({
                    'error': f'Cannot create job with missing template assets: {", ".join(missing_assets)}',
                    'code': 'MISSING_TEMPLATE_ASSETS',
                    'missing_assets': missing_assets,
                    'template_id': template_id
                }), 400
            
            if missing_assets and PLACEHOLDER_MODE:
                # Create placeholders for missing assets
                for asset_type in missing_assets:
                    placeholder = create_placeholder_asset(asset_type, template_id)
                    if placeholder:
                        placeholder_assets_used.append(placeholder)
    
    # Create job with production flag, channel, and template
    job_id = control_center.create_job(questions, use_production=use_production, channel_id=channel_id, template_id=template_id)
    
    response_data = {
        'success': True,
        'job_id': job_id,
        'questions': questions,
        'use_production': use_production,
        'channel_id': channel_id,
        'template_id': template_id
    }
    
    # Add placeholder info if used
    if placeholder_assets_used:
        response_data['placeholder_mode'] = True
        response_data['placeholder_assets_used'] = placeholder_assets_used
        response_data['warning'] = f'Job created with {len(placeholder_assets_used)} placeholder assets'
    
    return jsonify(response_data)

# -----------------------------
# Template Versions API
# -----------------------------
@app.route('/api/templates/<template_id>/versions', methods=['GET'])
def list_template_versions(template_id):
    """List saved versions for a template (most recent first)"""
    try:
        versions = []
        # Query latest 20 versions for this template_id
        docs = (template_versions_collection
                .where('template_id', '==', template_id)
                .order_by('created_at', direction=firestore.Query.DESCENDING)
                .limit(20)
                .stream())
        for doc in docs:
            data = doc.to_dict()
            data['id'] = doc.id
            versions.append(data)
        return jsonify({'success': True, 'versions': versions})
    except Exception as e:
        return jsonify({'error': f'Failed to list versions: {str(e)}'}), 500

@app.route('/api/templates/<template_id>/versions', methods=['POST'])
def create_template_version(template_id):
    """Create a new snapshot/version of the current template config"""
    try:
        template = template_manager.get_template(template_id)
        if not template:
            return jsonify({'error': 'Template not found'}), 404
        version_doc = {
            'template_id': template_id,
            'snapshot': template,
            'created_at': datetime.now().isoformat()
        }
        ref = template_versions_collection.add(version_doc)
        version_doc['id'] = ref[1].id
        return jsonify({'success': True, 'version': version_doc})
    except Exception as e:
        return jsonify({'error': f'Failed to create version: {str(e)}'}), 500

@app.route('/api/templates/<template_id>/versions/<version_id>/restore', methods=['POST'])
def restore_template_version(template_id, version_id):
    """Restore a template to a specific saved version"""
    try:
        doc = template_versions_collection.document(version_id).get()
        if not doc.exists:
            return jsonify({'error': 'Version not found'}), 404
        data = doc.to_dict()
        if data.get('template_id') != template_id:
            return jsonify({'error': 'Version does not belong to this template'}), 400
        snapshot = data.get('snapshot')
        if not snapshot:
            return jsonify({'error': 'Invalid snapshot data'}), 400
        # Apply snapshot (preserve original id)
        snapshot['updated_at'] = firestore.SERVER_TIMESTAMP
        success = template_manager.update_template(template_id, snapshot)
        if not success:
            return jsonify({'error': 'Failed to restore version'}), 500
        return jsonify({'success': True, 'message': 'Template restored from version'})
    except Exception as e:
        return jsonify({'error': f'Failed to restore version: {str(e)}'}), 500

# -----------------------------
# Job logs API
# -----------------------------
@app.route('/api/jobs/<job_id>/logs')
def get_job_logs(job_id):
    """Download job logs as a text file"""
    try:
        job = control_center.get_job(job_id)
        if not job:
            return jsonify({
                "error": "Job not found",
                "code": "JOB_NOT_FOUND",
                "timestamp": datetime.utcnow().isoformat() + "Z"
            }), 404
        
        logs = job.get("logs", [])
        if not logs:
            return jsonify({
                "error": "No logs available for this job",
                "code": "NO_LOGS_AVAILABLE",
                "timestamp": datetime.utcnow().isoformat() + "Z"
            }), 404
        
        # Format logs as text
        log_text = f"Job Logs for {job_id}\n"
        log_text += f"Status: {job.get('status', 'unknown')}\n"
        log_text += f"Created: {job.get('created_at', 'unknown')}\n"
        log_text += f"Template: {job.get('template_id', 'unknown')}\n"
        log_text += "=" * 50 + "\n\n"
        
        for log_entry in logs:
            timestamp = log_entry.get('timestamp', 'unknown')
            phase = log_entry.get('phase', 'unknown')
            level = log_entry.get('level', 'info')
            message = log_entry.get('message', '')
            log_text += f"[{timestamp}] [{level.upper()}] [{phase}] {message}\n"
        
        # Create response with text content
        from flask import Response
        return Response(
            log_text,
            mimetype='text/plain',
            headers={
                'Content-Disposition': f'attachment; filename=job_{job_id}_logs.txt'
            }
        )
    except Exception as e:
        return jsonify({
            "error": f"Error downloading logs: {str(e)}",
            "code": "LOGS_DOWNLOAD_FAILED",
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }), 500

@app.route('/api/template-configs', methods=['GET'])
def get_template_configs():
    """Get all template configurations"""
    try:
        configs = []
        docs = templates_collection.where("status", "==", "active").stream()
        for doc in docs:
            config_data = doc.to_dict()
            config_data['id'] = doc.id
            configs.append(config_data)
        return jsonify(configs)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/template-configs/<config_id>', methods=['GET'])
def get_template_config(config_id):
    """Get specific template configuration"""
    try:
        doc = templates_collection.document(config_id).get()
        if doc.exists:
            config_data = doc.to_dict()
            config_data['id'] = doc.id
            return jsonify(config_data)
        else:
            return jsonify({'error': 'Template configuration not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/template-configs', methods=['POST'])
def save_template_config():
    """Save template configuration"""
    try:
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['template_id', 'template_type', 'asset_mappings', 'text_positions', 'font_settings', 'timing_settings']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'Missing required field: {field}'}), 400
        
        # Create configuration document
        config_data = {
            'template_id': data['template_id'],
            'template_type': data['template_type'],
            'asset_mappings': data['asset_mappings'],
            'text_positions': data['text_positions'],
            'font_settings': data['font_settings'],
            'timing_settings': data['timing_settings'],
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat(),
            'status': 'active'
        }
        
        # Save to Firestore
        doc_ref = templates_collection.add(config_data)
        config_data['id'] = doc_ref[1].id
        
        return jsonify({'message': 'Template configuration saved successfully', 'config': config_data}), 201
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/template-configs/<config_id>', methods=['PUT'])
def update_template_config(config_id):
    """Update template configuration"""
    try:
        data = request.get_json()
        
        # Update configuration
        update_data = {
            'asset_mappings': data.get('asset_mappings'),
            'text_positions': data.get('text_positions'),
            'font_settings': data.get('font_settings'),
            'timing_settings': data.get('timing_settings'),
            'updated_at': datetime.now().isoformat()
        }
        
        # Remove None values
        update_data = {k: v for k, v in update_data.items() if v is not None}
        
        # Update in Firestore
        templates_collection.document(config_id).update(update_data)
        
        return jsonify({'message': 'Template configuration updated successfully'}), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/template-configs/<config_id>/validate', methods=['POST'])
def validate_template_config(config_id):
    """Validate template configuration"""
    try:
        doc = templates_collection.document(config_id).get()
        if not doc.exists:
            return jsonify({'error': 'Template configuration not found'}), 404
        
        config_data = doc.to_dict()
        validation_results = {
            'valid': True,
            'errors': [],
            'warnings': []
        }
        
        # Validate asset mappings
        asset_mappings = config_data.get('asset_mappings', {})
        required_assets = ['background_asset', 'intro_asset', 'outro_asset', 'transition_asset']
        
        for asset_type in required_assets:
            if not asset_mappings.get(asset_type):
                validation_results['errors'].append(f'Missing required asset: {asset_type}')
                validation_results['valid'] = False
        
        # Validate text positions
        text_positions = config_data.get('text_positions', {})
        required_positions = ['question_x', 'question_y', 'question_width', 'question_height', 
                             'answer_x', 'answer_y', 'answer_width', 'answer_height']
        
        for position in required_positions:
            if not text_positions.get(position):
                validation_results['errors'].append(f'Missing required text position: {position}')
                validation_results['valid'] = False
        
        # Validate font settings
        font_settings = config_data.get('font_settings', {})
        required_fonts = ['question_font_size', 'answer_font_size', 'correct_answer_font_size', 'font_file']
        
        for font_setting in required_fonts:
            if not font_settings.get(font_setting):
                validation_results['errors'].append(f'Missing required font setting: {font_setting}')
                validation_results['valid'] = False
        
        # Validate timing settings
        timing_settings = config_data.get('timing_settings', {})
        required_timing = ['question_fade_in', 'answer_fade_in', 'answer_fade_out', 'correct_answer_reveal']
        
        for timing in required_timing:
            if not timing_settings.get(timing):
                validation_results['errors'].append(f'Missing required timing setting: {timing}')
                validation_results['valid'] = False
        
        return jsonify(validation_results), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/template-configs/<config_id>', methods=['DELETE'])
def delete_template_config(config_id):
    """Delete template configuration"""
    try:
        templates_collection.document(config_id).delete()
        return jsonify({'message': 'Template configuration deleted successfully'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/system-check')
def system_check_page():
    """System check page"""
    return render_template('system_check.html')

@app.route('/api/system-check')
def system_check():
    """System check for off-schema objects and canonical path compliance"""
    try:
        path_builder = get_path_builder()
        storage_client = storage.Client()
        
        # Get bucket
        bucket = storage_client.bucket(path_builder.bucket_name)
        
        # Scan all objects
        results = {
            'timestamp': datetime.utcnow().isoformat() + "Z",
            'environment': ENVIRONMENT,
            'firestore_prefix': FIRESTORE_COLLECTION_PREFIX,
            'bucket_name': path_builder.bucket_name,
            'checks': {}
        }
        
        # Channel Collection Check
        try:
            channels_ref = firestore_client.collection(f"{FIRESTORE_COLLECTION_PREFIX}_channels")
            channels = list(channels_ref.stream())
            
            results['checks']['channel_collection'] = {
                'status': 'ok' if len(channels) > 0 else 'warning',
                'collection': f"{FIRESTORE_COLLECTION_PREFIX}_channels",
                'count': len(channels),
                'channels': []
            }
            
            # Show first 5 channels
            for i, doc in enumerate(channels[:5]):
                channel_data = doc.to_dict()
                channel_data['id'] = doc.id
                results['checks']['channel_collection']['channels'].append(channel_data)
            
            if len(channels) == 0:
                results['checks']['channel_collection']['message'] = 'No channels found. Create one channel doc in dev_channels or switch FIRESTORE_PREFIX.'
                
        except Exception as e:
            results['checks']['channel_collection'] = {
                'status': 'error',
                'message': f'Failed to check channel collection: {str(e)}'
            }
        
        return jsonify(results)
        
    except Exception as e:
        return jsonify({'error': f'System check failed: {str(e)}'}), 500
        all_objects = list(bucket.list_blobs())
        total_objects = len(all_objects)
        
        # Categorize objects
        compliant_objects = 0
        off_schema_objects = []
        area_counts = {
            'shared': 0,
            'channels': 0,
            'generated': 0,
            'logs': 0,
            'temp': 0,
            'off_schema': 0
        }
        
        for blob in all_objects:
            gs_uri = f"gs://{path_builder.bucket_name}/{blob.name}"
            
            if path_builder.validate_path(gs_uri):
                compliant_objects += 1
                
                # Categorize by area
                if blob.name.startswith('shared/'):
                    area_counts['shared'] += 1
                elif blob.name.startswith('channels/'):
                    area_counts['channels'] += 1
                elif blob.name.startswith('generated/'):
                    area_counts['generated'] += 1
                elif blob.name.startswith('logs/'):
                    area_counts['logs'] += 1
                elif blob.name.startswith('temp/'):
                    area_counts['temp'] += 1
            else:
                area_counts['off_schema'] += 1
                off_schema_objects.append({
                    'path': blob.name,
                    'size': blob.size or 0,
                    'created': blob.time_created.isoformat() if blob.time_created else None
                })
        
        # Limit off-schema examples to first 5
        off_schema_examples = off_schema_objects[:5]
        
        # Firestore Analysis
        # firestore_client is already defined globally
        
        # Check new Apple-clean collections
        new_collections = [
            f"{FIRESTORE_COLLECTION_PREFIX}_channels",
            f"{FIRESTORE_COLLECTION_PREFIX}_assets", 
            f"{FIRESTORE_COLLECTION_PREFIX}_templates",
            f"{FIRESTORE_COLLECTION_PREFIX}_jobs"
        ]
        
        firestore_counts = {}
        for collection_name in new_collections:
            try:
                docs = list(firestore_client.collection(collection_name).stream())
                firestore_counts[collection_name] = len(docs)
            except Exception as e:
                firestore_counts[collection_name] = f"Error: {str(e)}"
        
        # Check for legacy collections - comprehensive list
        apple_clean_collections = [
            f"{FIRESTORE_COLLECTION_PREFIX}_channels",
            f"{FIRESTORE_COLLECTION_PREFIX}_assets", 
            f"{FIRESTORE_COLLECTION_PREFIX}_templates",
            f"{FIRESTORE_COLLECTION_PREFIX}_jobs"
        ]
        
        # All possible legacy collections
        legacy_collections = [
            'video_channels', 'video_assets', 'video_templates', 'video_jobs',
            'channels', 'assets', 'templates', 'jobs',
            'quizzes', 'quiz_snapshots', 'jobs_global', 'gemini_questions',
            'gemini_responses', 'questions', 'content_catalog',
            'gemini_outputs', 'gemini_prompts', 'gemini_tests', 'questions_global',
            'trivia_channels', 'unique_questions', 'videos', 'video_template_versions',
            'video_channels_backup', 'gemini_*', 'trivia_*', 'question_*'
        ]
        
        legacy_counts = {}
        for collection_name in legacy_collections:
            try:
                docs = list(firestore_client.collection(collection_name).stream())
                if len(docs) > 0:
                    legacy_counts[collection_name] = len(docs)
            except Exception:
                pass  # Collection doesn't exist
        
        # Template contract audit
        template_audit = {
            'total_templates': 0,
            'conforming_templates': 0,
            'non_conforming_templates': [],
            'missing_fields_summary': {}
        }
        
        try:
            templates_ref = firestore_client.collection(f"{FIRESTORE_COLLECTION_PREFIX}_templates")
            all_templates = list(templates_ref.stream())
            
            template_audit['total_templates'] = len(all_templates)
            
            required_fields = ['state', 'version', 'asset_refs', 'layout', 'styles', 'timing']
            
            for template_doc in all_templates:
                template_data = template_doc.to_dict()
                template_id = template_doc.id
                
                missing_fields = []
                for field in required_fields:
                    if field not in template_data:
                        missing_fields.append(field)
                
                if missing_fields:
                    template_audit['non_conforming_templates'].append({
                        'template_id': template_id,
                        'missing_fields': missing_fields
                    })
                    
                    # Track missing fields summary
                    for field in missing_fields:
                        if field not in template_audit['missing_fields_summary']:
                            template_audit['missing_fields_summary'][field] = 0
                        template_audit['missing_fields_summary'][field] += 1
                else:
                    template_audit['conforming_templates'] += 1
        
        except Exception as e:
            template_audit['error'] = f"Error auditing templates: {str(e)}"

        # Publish guard status
        publish_guard_status = "OK"
        try:
            # Check if any published templates have missing assets
            templates_ref = firestore_client.collection(f"{FIRESTORE_COLLECTION_PREFIX}_templates")
            published_templates = templates_ref.where('state', '==', 'published').stream()

            for template_doc in published_templates:
                template_data = template_doc.to_dict()
                asset_refs = template_data.get('asset_refs', {})

                for asset_type, asset_id in asset_refs.items():
                    asset_ref = firestore_client.collection(f"{FIRESTORE_COLLECTION_PREFIX}_assets").document(asset_id)
                    if not asset_ref.get().exists:
                        publish_guard_status = f"Template {template_doc.id} references missing asset {asset_id}"
                        break

        except Exception as e:
            publish_guard_status = f"Error checking publish guard: {str(e)}"
        
        # Asset validation
        asset_audit = {
            'total_assets': 0,
            'valid_assets': 0,
            'invalid_assets': [],
            'off_schema_count': 0,
            'off_schema_examples': []
        }
        
        try:
            assets_ref = firestore_client.collection(f"{FIRESTORE_COLLECTION_PREFIX}_assets")
            all_assets = list(assets_ref.stream())
            
            asset_audit['total_assets'] = len(all_assets)
            
            valid_types = ['background', 'audio', 'overlay', 'sfx', 'font', 'intro', 'outro', 'transition']
            
            for asset_doc in all_assets:
                asset_data = asset_doc.to_dict()
                asset_id = asset_doc.id
                
                # Check if asset has valid gcs_path
                gcs_path = asset_data.get('gcs_path', '')
                if not gcs_path.startswith('gs://'):
                    asset_audit['invalid_assets'].append({
                        'asset_id': asset_id,
                        'issue': 'Invalid gcs_path format'
                    })
                    continue
                
                # Check if gcs_path follows canonical grammar
                path_builder = get_path_builder()
                if not path_builder.validate_path(gcs_path):
                    asset_audit['off_schema_count'] += 1
                    if len(asset_audit['off_schema_examples']) < 3:
                        asset_audit['off_schema_examples'].append(gcs_path)
                    continue
                
                # Check if type is valid
                asset_type = asset_data.get('type', '')
                if asset_type not in valid_types:
                    asset_audit['invalid_assets'].append({
                        'asset_id': asset_id,
                        'issue': f'Invalid type: {asset_type}'
                    })
                    continue
                
                # Check if type is singular (not plural)
                if asset_type.endswith('s') and asset_type not in ['sfx']:
                    asset_audit['invalid_assets'].append({
                        'asset_id': asset_id,
                        'issue': f'Type should be singular: {asset_type}'
                    })
                    continue
                
                asset_audit['valid_assets'] += 1
        
        except Exception as e:
            asset_audit['error'] = f"Error auditing assets: {str(e)}"
        
        return jsonify({
            'gcs': {
                'bucket_name': path_builder.bucket_name,
                'environment': path_builder.environment,
                'total_objects': total_objects,
                'compliant_objects': compliant_objects,
                'off_schema_count': area_counts['off_schema'],
                'area_counts': area_counts,
                'off_schema_examples': off_schema_examples,
                'compliance_percentage': round((compliant_objects / total_objects * 100) if total_objects > 0 else 100, 2)
            },
            'firestore': {
                'new_collections': firestore_counts,
                'legacy_collections': legacy_counts,
                'publish_guard_status': publish_guard_status,
                'total_legacy_documents': sum(legacy_counts.values()) if legacy_counts else 0,
                'template_audit': template_audit,
                'asset_audit': asset_audit
            },
            'timestamp': datetime.utcnow().isoformat() + "Z"
        })
        
    except Exception as e:
        print(f"Error in system check: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/jobs/<job_id>/download')
def get_job_download_url(job_id):
    """Get signed download URL for job output using Apple-clean architecture"""
    try:
        # Get job data
        job_ref = jobs_collection.document(job_id)
        job_doc = job_ref.get()
        
        if not job_doc.exists:
            return jsonify({"error": "Job not found"}), 404
        
        job_data = job_doc.to_dict()
        
        # Get output path from job data
        output_path = job_data.get('output_path')
        if not output_path:
            return jsonify({"error": "No output path found"}), 404
        
        # Generate signed download URL using canonical path builder
        path_builder = get_path_builder()
        
        # Validate the output path follows canonical grammar
        if not path_builder.validate_path(output_path):
            return jsonify({"error": "Invalid output path format"}), 400
        
        # Parse the path to get components
        path_components = path_builder.parse_path(output_path)
        if not path_components or path_components['type'] != 'generated':
            return jsonify({"error": "Output path is not a generated file"}), 400
        
        # Create GCSPath object
        gcs_path = GCSPath(
            bucket=path_builder.bucket_name,
            path=output_path.replace(f"gs://{path_builder.bucket_name}/", ""),
            gs_uri=output_path
        )
        
        # Get GCS manager for signed URL generation
        gcs_mgr = get_gcs_manager()
        signed_url = gcs_mgr.generate_signed_url(gcs_path, expiration_hours=24)
        
        return jsonify({
            "job_id": job_id,
            "download_url": signed_url,
            "expires_in_hours": 24,
            "output_path": output_path
        })
        
    except Exception as e:
        print(f"Error generating download URL: {e}")
        return jsonify({"error": str(e)}), 500

# Socket.IO events for real-time updates
@socketio.on('connect')
def handle_connect():
    print('Client connected')

@socketio.on('disconnect')
def handle_disconnect():
    print('Client disconnected')

@socketio.on('request_job_updates')
def handle_job_updates():
    """Send job updates to connected clients"""
    while True:
        jobs = control_center.get_all_jobs()
        emit('job_updates', jobs)
        time.sleep(5)

def _load_channel_folders_from_gcs(bucket_name: str, channel_slug: str) -> dict:
    """Discover channel asset folders in GCS when Firestore metadata is missing."""
    from google.cloud import storage

    storage_client = storage.Client()
    channel_prefix = f"channels/{channel_slug}/assets/"
    bucket = storage_client.bucket(bucket_name)

    folders = {}
    subfolders = {
        'backgrounds': f"{channel_prefix}backgrounds/",
        'transitions': f"{channel_prefix}transitions/",
        'intro': f"{channel_prefix}intros/",
        'outro': f"{channel_prefix}outros/",
        'overlays': f"{channel_prefix}overlays/",
        'audio': f"{channel_prefix}audio/",
        'sfx': f"{channel_prefix}sfx/"
    }

    for key, prefix in subfolders.items():
        blobs = list(storage_client.list_blobs(bucket_name, prefix=prefix, max_results=1))
        if blobs:
            folders[key] = prefix

    return folders


def seed_baseline_channel():
    """Seed the baseline sports channel if it is missing."""
    if not AUTO_SEED_BASELINE:
        return

    channel_id = 'test-sport-trivia'
    channel_ref = channels_collection.document(channel_id)
    existing = channel_ref.get()

    if existing.exists:
        current = existing.to_dict() or {}
        folders = current.get('folders') or {}
        if folders:
            return
    
    bucket_name = os.getenv('BASELINE_CHANNEL_BUCKET', 'trivia-dev-assets')
    folders = _load_channel_folders_from_gcs(bucket_name, channel_id)
    
    channel_data = {
        'id': channel_id,
        'slug': channel_id,
        'name': 'Test Sport Trivia',
        'description': 'Baseline sports trivia channel',
        'category': 'sports',
        'environment': ENVIRONMENT,
        'status': 'active',
        'is_test': True,
        'bucket_name': bucket_name,
        'folders': folders,
        'template_id': 'test-sport-template',
        'created_at': (existing.to_dict() or {}).get('created_at', datetime.utcnow().isoformat() + "Z"),
        'updated_at': datetime.utcnow().isoformat() + "Z"
    }
    
    channel_ref.set(channel_data)
    print(f"🌱 Seeded baseline channel '{channel_id}' with folders {folders}")

@app.route('/api/jobs/queues')
def get_job_queues():
    try:
        def _serialize(doc):
            data = doc.to_dict() or {}
            data['id'] = doc.id
            stage = data.get('stage') or data.get('status')
            if hasattr(data.get('stageEnteredAt'), 'isoformat'):
                data['stageEnteredAt'] = data['stageEnteredAt'].isoformat()
            if hasattr(data.get('lastHeartbeatAt'), 'isoformat'):
                data['lastHeartbeatAt'] = data['lastHeartbeatAt'].isoformat()
            data.setdefault('progress', job_stage_contract.get_progress_for_stage(stage))
            return data

        pending_docs = jobs_collection.where('stage', '==', job_stage_contract.STAGE_PENDING).order_by('createdAt', direction=firestore.Query.ASCENDING).limit(50).stream()
        ready_docs = jobs_collection.where('stage', '==', job_stage_contract.STAGE_READY_FOR_RENDER).order_by('createdAt', direction=firestore.Query.ASCENDING).limit(50).stream()
        processing_tts_docs = jobs_collection.where('stage', '==', job_stage_contract.STAGE_PROCESSING_TTS).order_by('createdAt', direction=firestore.Query.ASCENDING).limit(50).stream()
        processing_render_docs = jobs_collection.where('stage', '==', job_stage_contract.STAGE_PROCESSING_RENDER).order_by('createdAt', direction=firestore.Query.ASCENDING).limit(50).stream()
        recent_failed_docs = jobs_collection.where('status', '==', 'failed').order_by('updatedAt', direction=firestore.Query.DESCENDING).limit(20).stream()

        return jsonify({
            'queues': {
                'pending': [_serialize(doc) for doc in pending_docs],
                'ready_for_render': [_serialize(doc) for doc in ready_docs],
                'processing_tts': [_serialize(doc) for doc in processing_tts_docs],
                'processing_render': [_serialize(doc) for doc in processing_render_docs],
            },
            'recentErrors': [_serialize(doc) for doc in recent_failed_docs],
        })
    except Exception as exc:
        return jsonify({'error': str(exc)}), 500

if __name__ == '__main__':
    # Get port from environment variable, default to 63531
    port = int(os.getenv('PORT', 6001))
    
    print("🎛️ Starting Trivia Control Center...")
    print(f"🌐 Web UI will be available at: http://localhost:{port}")
    print(f"📊 Dashboard: http://localhost:{port}")
    
    # Seed baseline template if needed
    print(f"🌱 Auto-seeding enabled: {AUTO_SEED_BASELINE}")
    seed_baseline_template()
    
    # Start pipeline manager
    print("🚀 Starting pipeline manager...")
    with app.app_context():
        start_pipeline()
    
    socketio.run(app, host='0.0.0.0', port=port, debug=False, allow_unsafe_werkzeug=True)
