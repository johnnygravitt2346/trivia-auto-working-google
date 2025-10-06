#!/usr/bin/env python3
"""
Unified Trivia Pipeline - Single, Simple Pipeline for All Jobs
Handles dynamic templates and channels from UI selections
"""

import os
import sys
import json
import time
import subprocess
import tempfile
import logging
import hashlib
import random
import shutil
from typing import Dict, List, Optional, Tuple
from pathlib import Path
from datetime import datetime, timezone

import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud import storage

# Add current directory to path for imports
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core.youtube_upload_service import YouTubeUploadService

class NullTTSClient:
    def __getattr__(self, name):
        raise RuntimeError("Legacy TTS client usage detected; all TTS must be generated upstream.")

class UnifiedTriviaPipeline:
    """
    Unified pipeline that handles all trivia video generation
    Supports dynamic templates and channels from UI
    """
    
    def __init__(self):
        """Initialize the unified pipeline"""
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)
        self.tts_client = NullTTSClient()
        self._tts_cache: Dict[str, Path] = {}
        self.tts_failures: List[int] = []
        
        # Initialize Firebase
        if not firebase_admin._apps:
            service_account_path = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')
            if service_account_path and os.path.exists(service_account_path):
                cred = credentials.Certificate(service_account_path)
                firebase_admin.initialize_app(cred)
            else:
                # Try to use default credentials
                firebase_admin.initialize_app()
        
        self.db = firestore.client()
        self.storage_client = storage.Client()
        # Bucket will be set dynamically from channel data
        self.bucket = None
        
        # YouTube upload service
        self.youtube_upload_service = YouTubeUploadService()
        
        # TTS client
        # Provide a Google-like TTS client (implemented via external service)
        try:
            self.tts_client = get_google_tts_client()
        except Exception:
            self.tts_client = None
        
        # Collections - use environment-prefixed collections
        environment = os.environ.get('ENVIRONMENT', 'dev')
        self.jobs_collection = self.db.collection(f'{environment}_jobs')
        self.templates_collection = self.db.collection(f'{environment}_templates')
        self.channels_collection = self.db.collection(f'{environment}_channels')
        
        # Store current job ID for heartbeat updates
        self.current_job_id = None
        
        self.logger.info("🎬 Unified Trivia Pipeline initialized")
    
    def _update_heartbeat(self, job_id: str, progress: int = None):
        """Update job heartbeat to prevent it from being marked as stuck"""
        try:
            current_time = datetime.now(timezone.utc)
            update_data = {
                'lastHeartbeatAt': current_time.isoformat() + 'Z',
                'updated_at': current_time.isoformat() + 'Z'
            }
            
            if progress is not None:
                update_data['progress'] = progress
            
            self.jobs_collection.document(job_id).update(update_data)
            self.logger.debug(f"💓 Heartbeat updated for job {job_id} (progress: {progress}%)")
            
        except Exception as e:
            self.logger.warning(f"⚠️ Failed to update heartbeat for job {job_id}: {e}")
    
    def process_job(self, job_id: str) -> Optional[str]:
        """
        Process a single job with unified pipeline
        Returns GCS path to final video or None if failed
        """
        try:
            self.logger.info(f"🚀 Processing job: {job_id}")
            self.current_job_id = job_id  # Store for heartbeat updates
            
            # Get job data
            job_doc = self.jobs_collection.document(job_id).get()
            if not job_doc.exists:
                self.logger.error(f"❌ Job {job_id} not found")
                return None
            
            job_data = job_doc.to_dict()
            self.job_data = job_data  # Store job_data for later use in completion
            input_data = job_data.get('input_data', {})
            questions = input_data.get('questions', [])
            
            # Initial heartbeat
            self._update_heartbeat(job_id, 10)
            template_id = job_data.get('template_id')
            channel_id = job_data.get('channel_id')
            
            # Store template_id and channel_id as instance variables for use in slide creation
            self.template_id = template_id
            self.channel_id = channel_id
            self.job_data = job_data  # Store job_data for later use in completion
            
            if not questions:
                self.logger.error(f"❌ No questions found for job {job_id}")
                return None
            
            # Get template and channel data
            template_data = self._get_template(template_id)
            channel_data = self._get_channel(channel_id)
            
            if not template_data:
                self.logger.error(f"❌ Template {template_id} not found")
                return None
            
            if not channel_data:
                self.logger.error(f"❌ Channel {channel_id} not found")
                return None
            
            # Add job-specific settings to template data
            template_data['input_data'] = input_data
            
            # Store channel_data after it's retrieved
            self.channel_data = channel_data
            
            self.logger.info(f"📋 Using template: {template_data.get('name', 'Unknown')}")
            self.logger.info(f"📺 Using channel: {channel_data.get('name', 'Unknown')}")
            
            # Create temporary directory
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)
                
                # Generate TTS audio for all questions
                self._update_heartbeat(self.current_job_id, 20)
                tts_results = self._generate_tts_audio(questions, temp_path, job_data)
                
                # Create video slides for each question
                self._update_heartbeat(self.current_job_id, 40)
                video_files = []
                for i, question in enumerate(questions):
                    tts_result = tts_results[i]
                    if tts_result.get('failed'):
                        self.logger.error(f"❌ Skipping question {i} due to TTS failure")
                        continue

                    video_file = self._create_question_slide(
                        question,
                        template_data,
                        channel_data,
                        tts_result.get('question_audio'),
                        temp_path,
                        i,
                        tts_result.get('answer_audio')
                    )
                    if video_file:
                        video_files.append(video_file)
                
                if not video_files:
                    self.logger.error("❌ No video files created")
                    return None
                
                # Build sequence: INTRO → TRANSITION → Q1 → TRANSITION → Q2 → … → OUTRO
                self._update_heartbeat(self.current_job_id, 60)
                final_video = self._concatenate_videos(video_files, temp_path)
                
                if not final_video:
                    self.logger.error("❌ Failed to concatenate videos")
                    return None
                
                # Upload to GCS
                self._update_heartbeat(self.current_job_id, 80)
                gcs_path = self._upload_to_gcs(final_video, job_id, channel_data)
                
                if gcs_path:
                    # Update job with completion status and video URL
                    self._update_heartbeat(self.current_job_id, 100)
                    self._update_job_completion(job_id, gcs_path)
                    self.logger.info(f"✅ Job {job_id} completed successfully")
                    return gcs_path
                else:
                    self.logger.error(f"❌ Failed to upload video for job {job_id}")
                    return None
                    
        except Exception as e:
            self.logger.error(f"❌ Error processing job {job_id}: {str(e)}")
            import traceback
            traceback.print_exc()
            return None
    
    def _get_template(self, template_id: str) -> Optional[Dict]:
        """Get template data from Firestore"""
        try:
            template_doc = self.templates_collection.document(template_id).get()
            if template_doc.exists:
                return template_doc.to_dict()
            return None
        except Exception as e:
            self.logger.error(f"❌ Error getting template {template_id}: {str(e)}")
            return None
    
    def _get_channel(self, channel_id: str) -> Optional[Dict]:
        """Get channel data from Firestore"""
        try:
            channel_doc = self.channels_collection.document(channel_id).get()
            if channel_doc.exists:
                return channel_doc.to_dict()
            return None
        except Exception as e:
            self.logger.error(f"❌ Error getting channel {channel_id}: {str(e)}")
            return None
    
    def _generate_tts_audio(self, questions: List[Dict], temp_path: Path, job_data: Dict = None) -> List[Dict[str, Optional[str]]]:
        import requests
        import time

        job_data = job_data or getattr(self, 'job_data', {}) or {}
        voice = job_data.get('input_data', {}).get('selected_voice', 'af-alt')
        if voice == 'ana_florence':
            voice = 'af-alt'

        cache_dir = temp_path / "tts_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)

        results: List[Dict[str, Optional[str]]] = []
        endpoint = "http://tts.ytsites.org/v1/audio"

        for index, question in enumerate(questions):
            question_text = question.get('question', '') or ''
            answer_text = self._build_answer_announcement(question)

            question_audio = self._fetch_tts_audio(
                text=question_text,
                voice=voice,
                cache_dir=cache_dir,
                filename=temp_path / f"question_{index}_audio.mp3",
                endpoint=endpoint,
                label=f"question {index}"
            )

            answer_audio = self._fetch_tts_audio(
                text=answer_text,
                voice=voice,
                cache_dir=cache_dir,
                filename=temp_path / f"answer_{index}_tts.mp3",
                endpoint=endpoint,
                label=f"answer {index}"
            )

            if question_audio is None:
                self.logger.error(f"❌ TTS permanently failed for question {index}; skipping slide generation for this question")
                self.tts_failures.append(index)

            results.append({
                'question_audio': question_audio,
                'answer_audio': answer_audio,
                'failed': question_audio is None
            })

        if self.tts_failures:
            self.logger.warning(f"⚠️ TTS failures encountered for questions: {self.tts_failures}")

        return results
    
    def _process_question_data(self, question: Dict) -> Dict:
        """Process question data to ensure correct format for video generation"""
        processed = question.copy()
        
        # Convert correct_answer to actual answer text
        correct_answer = processed.get('correct_answer', 0)
        
        # Handle both integer indices and letter answers
        if isinstance(correct_answer, int):
            # Convert integer index to letter
            letters = ['A', 'B', 'C', 'D']
            if 0 <= correct_answer < len(letters):
                correct_letter = letters[correct_answer]
            else:
                correct_letter = 'A'
        else:
            # Handle letter answers
            correct_letter = str(correct_answer).upper()
        
        if correct_letter in ['A', 'B', 'C', 'D']:
            answer_key = f'answer_{correct_letter.lower()}'
            if answer_key in processed:
                processed['correct_answer'] = processed[answer_key]
            else:
                processed['correct_answer'] = 'Correct!'
        else:
            # If it's already text, keep it as is
            processed['correct_answer'] = processed.get('correct_answer', 'Correct!')
        
        return processed
    
    def _process_question_data_for_template_manager(self, question: Dict) -> Dict:
        """Process question data for template_manager format (answer_a, answer_b, etc.)"""
        try:
            # Handle both formats: individual answer fields or answers array
            if 'answer_a' in question:
                # Format: answer_a, answer_b, answer_c, answer_d
                processed = {
                    'question': question.get('question', ''),
                    'answer_a': question.get('answer_a', ''),
                    'answer_b': question.get('answer_b', ''),
                    'answer_c': question.get('answer_c', ''),
                    'answer_d': question.get('answer_d', ''),
                    'correct_answer': question.get('correct_answer', 'A'),
                    'explanation': question.get('explanation', '')
                }
            else:
                # Format: answers array
                answers = question.get('answers', [])
                correct_answer = question.get('correct_answer', 0)
                
                # Convert correct_answer index to letter if needed
                if isinstance(correct_answer, int) and 0 <= correct_answer < len(answers):
                    correct_letter = chr(ord('A') + correct_answer)
                else:
                    correct_letter = 'A'  # Default fallback
                
                processed = {
                    'question': question.get('question', ''),
                    'answer_a': answers[0] if len(answers) > 0 else '',
                    'answer_b': answers[1] if len(answers) > 1 else '',
                    'answer_c': answers[2] if len(answers) > 2 else '',
                    'answer_d': answers[3] if len(answers) > 3 else '',
                    'correct_answer': correct_letter,
                    'explanation': question.get('explanation', '')
                }
            
            return processed
            
        except Exception as e:
            self.logger.error(f"❌ Error processing question data for template_manager: {str(e)}")
            return {
                'question': question.get('question', ''),
                'answer_a': '',
                'answer_b': '',
                'answer_c': '',
                'answer_d': '',
                'correct_answer': 'A',
                'explanation': question.get('explanation', '')
            }
    
    def _create_question_slide(self, question: Dict, template_data: Dict, channel_data: Dict,
                              question_audio: Optional[str], temp_path: Path, question_index: int,
                              answer_audio: Optional[str] = None) -> Optional[str]:
        """Create a video slide for a single question using GeneratedVideoModule or Audio-Driven Engine"""
        try:
            # Check if we should use audio-driven engine
            use_audio_driven = template_data.get('use_audio_driven', False)
            
            if use_audio_driven:
                return self._create_audio_driven_slide(question, template_data, channel_data, temp_path, question_index)
            else:
                return self._create_traditional_slide(
                    question,
                    template_data,
                    channel_data,
                    question_audio,
                    temp_path,
                    question_index,
                    answer_audio
                )
            
        except Exception as e:
            self.logger.error(f"❌ Error creating slide for question {question_index}: {str(e)}")
            import traceback
            traceback.print_exc()
            return None
    
    def _create_traditional_slide(self, question: Dict, template_data: Dict,
                                 channel_data: Dict, audio_file: Optional[str],
                                 temp_path: Path, question_index: int,
                                 answer_audio: Optional[str] = None) -> Optional[str]:
        """Create a video slide using the working template_manager system"""
        try:
            # Get background video from channel
            background_video = self._get_background_video(channel_data, temp_path, question_index)
            
            if not background_video:
                self.logger.error("❌ No background video found")
                return None
            
            # Import and use the working GeneratedVideoModule from template_manager
            from core.template_manager import GeneratedVideoModule
            
            # Create output directory for this question
            question_output_dir = temp_path / f"question_{question_index}"
            question_output_dir.mkdir(exist_ok=True)
            
            # Initialize the working GeneratedVideoModule with TTS client
            video_module = GeneratedVideoModule(self.tts_client)
            
            # Process question data to ensure correct format for template_manager
            processed_question = self._process_question_data(question)
            
            # If template has audio-driven timing, pass explanation_start override
            explanation_start_override = None
            ad_timing = template_data.get('audio_driven_timing') or {}
            if 'explanation_start' in ad_timing and isinstance(ad_timing['explanation_start'], (int, float)):
                explanation_start_override = float(ad_timing['explanation_start'])

            # Create the question slide using the working module
            if hasattr(self, 'current_background_name'):
                processed_question['background_name'] = self.current_background_name
            else:
                processed_question['background_name'] = ''

            slide_path = video_module.create_question_slide(
                processed_question,
                background_video,
                str(temp_path),
                str(question_output_dir),
                explanation_start_override=explanation_start_override,
                template_data=template_data,
                audio_path=audio_file,
                explanation_audio_path=answer_audio,
                question_index=question_index
            )
            
            if slide_path and Path(slide_path).exists():
                # Persist local debug artifacts in a stable location
                try:
                    import shutil, os
                    local_debug_root = Path('/root/trivia_auto/debug_audio') / getattr(self, 'current_job_id', 'unknown_job') / f"question_{question_index}"
                    os.makedirs(local_debug_root, exist_ok=True)
                    for fname in ["debug_explanation_tts.mp3", "debug_question_tts.mp3"]:
                        src = Path(question_output_dir) / fname
                        if src.exists():
                            dst = local_debug_root / fname
                            shutil.copy(src, dst)
                            self.logger.info(f"📁 Saved local debug artifact: {dst}")
                except Exception as e:
                    self.logger.error(f"⚠️ Failed saving local debug artifacts: {e}")

                # Upload debug TTS artifacts if present
                try:
                    bucket_name = channel_data.get('bucket_name', channel_data.get('gcs_bucket', ''))
                    if bucket_name:
                        from google.cloud import storage
                        storage_client = storage.Client()
                        bucket = storage_client.bucket(bucket_name)
                        for fname in ["debug_explanation_tts.mp3", "debug_question_tts.mp3"]:
                            fpath = Path(question_output_dir) / fname
                            if fpath.exists():
                                blob_path = f"videos/{getattr(self, 'current_job_id', 'unknown_job')}/debug/question_{question_index}/{fname}"
                                blob = bucket.blob(blob_path)
                                blob.upload_from_filename(str(fpath))
                                self.logger.info(f"📤 Uploaded debug artifact: gs://{bucket_name}/{blob_path}")
                    else:
                        self.logger.warning("⚠️ No bucket_name found; skipping debug artifact upload")
                except Exception as e:
                    self.logger.error(f"⚠️ Failed to upload debug TTS artifacts: {e}")
                self.logger.info(f"✅ Created traditional slide: {slide_path}")
                return slide_path
            else:
                self.logger.error("❌ Failed to create traditional slide")
                return None
                
        except Exception as e:
            self.logger.error(f"❌ Error creating traditional slide: {str(e)}")
            import traceback
            traceback.print_exc()
            return None
    
    def _create_audio_driven_slide(self, question: Dict, template_data: Dict, 
                                  channel_data: Dict, temp_path: Path, 
                                  question_index: int) -> Optional[str]:
        """Create a video slide using audio-driven timing with existing GeneratedVideoModule"""
        try:
            self.logger.info(f"🎵 Creating audio-driven slide for question {question_index}")
            
            # Import audio-driven engine for timing only
            from audio_driven_engine import AudioDrivenEngine
            
            # Initialize audio-driven engine
            audio_engine = AudioDrivenEngine()
            
            # Get background video from channel
            background_video = self._get_background_video(channel_data, temp_path, question_index)
            
            if not background_video:
                self.logger.error("❌ No background video found")
                return None
            
            # Create output directory for this question
            question_output_dir = temp_path / f"question_{question_index}"
            question_output_dir.mkdir(exist_ok=True)
            
            # Extract audio from background video
            self.logger.info("🎵 Extracting audio from background video...")
            audio_path = audio_engine.extract_audio_from_video(background_video)
            
            # Detect audio cues
            self.logger.info("🔍 Detecting audio cues...")
            cues = audio_engine.detect_audio_cues(audio_path)
            
            if not cues:
                self.logger.warning("⚠️ No audio cues detected, falling back to traditional method")
                return self._create_traditional_slide(question, template_data, channel_data, "", temp_path, question_index)
            
            # Map audio cues to timing events
            self.logger.info("⏰ Mapping audio cues to timing events...")
            timing_events = self._map_cues_to_timing(cues)
            
            # Create modified template with audio-driven timing
            audio_driven_template = template_data.copy()
            audio_driven_template['audio_driven_timing'] = timing_events
            
            # Import and use the CleanGeneratedVideoModule with audio-driven timing
            from template_manager import GeneratedVideoModule
            
            # Initialize the GeneratedVideoModule with TTS client
            video_module = GeneratedVideoModule(self.tts_client)
            
            # Process question data to ensure correct format
            processed_question = self._process_question_data(question)
            
            # Create the question slide using the module with proper drawtext filters
            output_video = video_module.create_question_slide(
                question_data=processed_question,
                background_path=background_video,
                tmp_dir=str(temp_path),
                output_dir=str(question_output_dir),
                template_data=template_data
            )
            
            # Cleanup
            audio_engine.cleanup()
            
            if output_video and os.path.exists(output_video):
                # Persist local debug artifacts in a stable location
                try:
                    import shutil, os
                    local_debug_root = Path('/root/trivia_auto/debug_audio') / getattr(self, 'current_job_id', 'unknown_job') / f"question_{question_index}"
                    os.makedirs(local_debug_root, exist_ok=True)
                    for fname in ["debug_explanation_tts.mp3", "debug_question_tts.mp3"]:
                        src = Path(question_output_dir) / fname
                        if src.exists():
                            dst = local_debug_root / fname
                            shutil.copy(src, dst)
                            self.logger.info(f"📁 Saved local debug artifact: {dst}")
                except Exception as e:
                    self.logger.error(f"⚠️ Failed saving local debug artifacts: {e}")

                # Upload debug TTS artifacts if present
                try:
                    bucket_name = channel_data.get('bucket_name', channel_data.get('gcs_bucket', ''))
                    if bucket_name:
                        from google.cloud import storage
                        storage_client = storage.Client()
                        bucket = storage_client.bucket(bucket_name)
                        for fname in ["debug_explanation_tts.mp3", "debug_question_tts.mp3"]:
                            fpath = Path(question_output_dir) / fname
                            if fpath.exists():
                                blob_path = f"videos/{getattr(self, 'current_job_id', 'unknown_job')}/debug/question_{question_index}/{fname}"
                                blob = bucket.blob(blob_path)
                                blob.upload_from_filename(str(fpath))
                                self.logger.info(f"📤 Uploaded debug artifact: gs://{bucket_name}/{blob_path}")
                    else:
                        self.logger.warning("⚠️ No bucket_name found; skipping debug artifact upload")
                except Exception as e:
                    self.logger.error(f"⚠️ Failed to upload debug TTS artifacts: {e}")
                self.logger.info(f"✅ Created audio-driven video slide for question {question_index}")
                return output_video
            else:
                self.logger.error(f"❌ Audio-driven engine failed to create video for question {question_index}")
                return None
            
        except Exception as e:
            self.logger.error(f"❌ Error creating audio-driven slide for question {question_index}: {str(e)}")
            import traceback
            traceback.print_exc()
            return None
    
    def _map_cues_to_timing(self, cues: List) -> Dict:
        """Map detected audio cues to timing events"""
        timing_events = {
            'question_start': None,
            'answer_a_start': None,
            'answer_b_start': None,
            'answer_c_start': None,
            'answer_d_start': None,
            'explanation_start': None
        }
        
        # Find the first opening cue for question
        opening_cues = [c for c in cues if c.cue_type == 'opening']
        if opening_cues:
            timing_events['question_start'] = opening_cues[0].timestamp
        
        # Find pop cues for answers (A, B, C, D)
        pop_cues = [c for c in cues if c.cue_type == 'pop']
        if len(pop_cues) >= 4:
            timing_events['answer_a_start'] = pop_cues[0].timestamp
            timing_events['answer_b_start'] = pop_cues[1].timestamp
            timing_events['answer_c_start'] = pop_cues[2].timestamp
            timing_events['answer_d_start'] = pop_cues[3].timestamp
        
        # Find chime cue for explanation
        chime_cues = [c for c in cues if c.cue_type == 'chime']
        if chime_cues:
            timing_events['explanation_start'] = chime_cues[0].timestamp
        
        return timing_events
    
    # Remove unused helper methods - now using direct FFmpeg drawtext filters
    
    def _get_transition_video(self, temp_path: Path, transition_index: int = 0) -> Optional[str]:
        """Get transition video from template assets, cycling through available transitions"""
        try:
            self.logger.info("🔍 _get_transition_video called")
            
            # Get template data
            template_data = self._get_template(self.template_id)
            if not template_data:
                self.logger.error("❌ Template not found")
                return None
            
            # Check if template has transition assets
            assets = template_data.get('assets', {})
            transitions = assets.get('transitions', [])
            
            # Fallback: if no template-level transitions, pull from channel transitions folder in GCS
            if not transitions:
                self.logger.warning("⚠️ No transition assets found in template - checking channel transitions folder")
                try:
                    from automations.canonical_path_builder import get_path_builder
                    
                    path_builder = get_path_builder()
                    bucket_name = path_builder.bucket_name
                    
                    # Set bucket dynamically
                    self.bucket = self.storage_client.bucket(bucket_name)
                    
                    # List all files in the transitions folder
                    folder_prefix = f"channels/{self.channel_id}/assets/transitions/"
                    blobs = list(self.bucket.list_blobs(prefix=folder_prefix))
                    
                    # Filter for video files
                    video_files = []
                    for blob in blobs:
                        if blob.name.lower().endswith(('.mp4', '.avi', '.mov', '.mkv')):
                            video_files.append(blob.name)
                    
                    if not video_files:
                        self.logger.warning(f"⚠️ No transition videos found in {folder_prefix}")
                        return None
                    
                    # Sort for stable ordering, then select by index (sequential)
                    video_files.sort()
                    selected_video = video_files[transition_index % len(video_files)]
                    
                    # Download the selected transition file
                    local_original = temp_path / f"transition_original_{hash(selected_video)}.mp4"
                    blob = self.bucket.blob(selected_video)
                    blob.download_to_filename(str(local_original))
                    
                    # Standardize FPS/audio for safe concat
                    standardized_path = temp_path / f"transition_24fps_{hash(selected_video)}.mp4"
                    if self._standardize_video_fps(str(local_original), str(standardized_path), 24):
                        self.logger.info(f"✅ Downloaded & standardized transition (channel): {selected_video}")
                        return str(standardized_path)
                    else:
                        self.logger.info(f"✅ Downloaded transition (channel): {selected_video}")
                        return str(local_original)
                except Exception as e:
                    self.logger.error(f"❌ Error loading channel transitions: {e}")
                    return None
            
            self.logger.info(f"🔍 Template has {len(transitions)} transition assets")
            
            # Cycle through transitions based on index
            selected_transition_uri = transitions[transition_index % len(transitions)]
            
            self.logger.info(f"🔍 Selected transition {transition_index + 1}/{len(transitions)}: {selected_transition_uri}")
            
            # Parse GCS URI
            if not selected_transition_uri.startswith('gs://'):
                self.logger.error(f"❌ Invalid GCS URI: {selected_transition_uri}")
                return None
            
            # Extract bucket and blob name
            uri_parts = selected_transition_uri[5:].split('/', 1)  # Remove 'gs://' and split
            bucket_name = uri_parts[0]
            blob_name = uri_parts[1]
            
            self.logger.info(f"🔍 Bucket: {bucket_name}, Blob: {blob_name}")
            
            # Set bucket dynamically
            self.bucket = self.storage_client.bucket(bucket_name)
            
            # Check if the blob exists before trying to download
            blob = self.bucket.blob(blob_name)
            if not blob.exists():
                self.logger.warning(f"⚠️ Transition video not found: {blob_name}")
                # Try to find an alternative transition that exists
                for alt_index in range(len(transitions)):
                    if alt_index != transition_index:
                        alt_transition_uri = transitions[alt_index]
                        alt_uri_parts = alt_transition_uri[5:].split('/', 1)
                        alt_bucket_name = alt_uri_parts[0]
                        alt_blob_name = alt_uri_parts[1]
                        alt_blob = self.storage_client.bucket(alt_bucket_name).blob(alt_blob_name)
                        if alt_blob.exists():
                            self.logger.info(f"🔄 Using alternative transition {alt_index + 1}: {alt_blob_name}")
                            # Update variables to use the alternative
                            bucket_name = alt_bucket_name
                            blob_name = alt_blob_name
                            blob = alt_blob
                            break
                else:
                    self.logger.warning(f"⚠️ No alternative transitions found, skipping transition")
                    return None
            
            # Download the selected transition file
            local_original = temp_path / f"transition_original_{hash(blob_name)}.mp4"
            blob.download_to_filename(str(local_original))
            
            # Standardize to 24fps for reliable concat
            standardized_path = temp_path / f"transition_24fps_{hash(blob_name)}.mp4"
            if self._standardize_video_fps(str(local_original), str(standardized_path), 24):
                self.logger.info(f"✅ Downloaded & standardized transition video: {blob_name}")
                return str(standardized_path)
            else:
                self.logger.info(f"✅ Downloaded transition video: {blob_name}")
                return str(local_original)
            
        except Exception as e:
            self.logger.error(f"❌ Error getting transition video: {str(e)}")
            return None

    def _standardize_video_fps(self, input_path: str, output_path: str, target_fps: int = 24) -> bool:
        """Standardize video frame rate and audio characteristics for consistent concatenation"""
        try:
            cmd = [
                'ffmpeg', '-y',
                '-i', input_path,
                '-c:v', 'libx264',
                '-c:a', 'aac',
                '-pix_fmt', 'yuv420p',
                '-r', str(target_fps),  # Force target frame rate
                '-ar', '44100',         # Standardize audio sample rate
                '-ac', '2',             # Standardize to stereo
                '-movflags', '+faststart',
                output_path
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode == 0:
                self.logger.info(f"✅ Standardized video to {target_fps}fps: {output_path}")
                return True
            else:
                self.logger.error(f"❌ Failed to standardize video FPS: {result.stderr}")
                return False
                
        except Exception as e:
            self.logger.error(f"❌ Error standardizing video FPS: {str(e)}")
            return False

    def _get_intro_video(self, temp_path: Path) -> Optional[str]:
        """Get intro video from template assets and standardize to 24fps"""
        try:
            self.logger.info("🔍 _get_intro_video called")
            
            # Get template data
            template_data = self._get_template(self.template_id)
            if not template_data:
                self.logger.error("❌ Template not found")
                return None
            
            # Check if template has intro asset
            asset_mappings = template_data.get('asset_mappings', {})
            intro_gs_uri = asset_mappings.get('intro_asset')
            
            if not intro_gs_uri:
                # Try to get random intro from channel assets
                intro_gs_uri = self._get_random_asset_from_folder("intros")
                if intro_gs_uri:
                    self.logger.info(f"🔍 Found random channel intro: {intro_gs_uri}")
            
            if not intro_gs_uri:
                self.logger.warning("⚠️ No intro asset found in template or channel - skipping intro")
                return None
            
            self.logger.info(f"🔍 Template intro asset: {intro_gs_uri}")
            
            # Parse GCS URI
            if not intro_gs_uri.startswith('gs://'):
                self.logger.error(f"❌ Invalid GCS URI: {intro_gs_uri}")
                return None
            
            # Extract bucket and blob name
            uri_parts = intro_gs_uri[5:].split('/', 1)  # Remove 'gs://' and split
            bucket_name = uri_parts[0]
            blob_name = uri_parts[1]
            
            self.logger.info(f"🔍 Bucket: {bucket_name}, Blob: {blob_name}")
            
            # Set bucket dynamically
            self.bucket = self.storage_client.bucket(bucket_name)
            
            # Download original intro
            original_path = temp_path / f"intro_original_{hash(blob_name)}.mp4"
            blob = self.bucket.blob(blob_name)
            
            # Check if blob exists
            if not blob.exists():
                self.logger.error(f"❌ Intro blob does not exist: {blob_name}")
                return None
                
            blob.download_to_filename(str(original_path))
            
            # Verify the downloaded file is valid
            if not original_path.exists() or original_path.stat().st_size == 0:
                self.logger.error(f"❌ Intro file download failed or is empty: {original_path}")
                return None
            
            # Standardize to 24fps for consistent concatenation
            standardized_path = temp_path / f"intro_24fps_{hash(blob_name)}.mp4"
            
            if self._standardize_video_fps(str(original_path), str(standardized_path), 24):
                self.logger.info(f"✅ Downloaded and standardized intro video: {blob_name}")
                return str(standardized_path)
            else:
                self.logger.error(f"❌ Failed to standardize intro video: {blob_name} - skipping intro")
                return None
            
        except Exception as e:
            self.logger.error(f"❌ Error getting intro video: {str(e)}")
            return None

    def _get_outro_video(self, temp_path: Path) -> Optional[str]:
        """Get outro video from template assets and standardize to 24fps"""
        try:
            self.logger.info("🔍 _get_outro_video called")
            
            # Get template data
            template_data = self._get_template(self.template_id)
            if not template_data:
                self.logger.error("❌ Template not found")
                return None
            
            # Check if template has outro asset
            asset_mappings = template_data.get('asset_mappings', {})
            outro_gs_uri = asset_mappings.get('outro_asset')
            
            if not outro_gs_uri:
                # Try to get random outro from channel assets
                outro_gs_uri = self._get_random_asset_from_folder("outros")
                if outro_gs_uri:
                    self.logger.info(f"🔍 Found random channel outro: {outro_gs_uri}")
            
            if not outro_gs_uri:
                self.logger.warning("⚠️ No outro asset found in template or channel - skipping outro")
                return None
            
            self.logger.info(f"🔍 Template outro asset: {outro_gs_uri}")
            
            # Parse GCS URI
            if not outro_gs_uri.startswith('gs://'):
                self.logger.error(f"❌ Invalid GCS URI: {outro_gs_uri}")
                return None
            
            # Extract bucket and blob name
            uri_parts = outro_gs_uri[5:].split('/', 1)  # Remove 'gs://' and split
            bucket_name = uri_parts[0]
            blob_name = uri_parts[1]
            
            self.logger.info(f"🔍 Bucket: {bucket_name}, Blob: {blob_name}")
            
            # Set bucket dynamically
            self.bucket = self.storage_client.bucket(bucket_name)
            
            # Download original outro
            original_path = temp_path / f"outro_original_{hash(blob_name)}.mp4"
            blob = self.bucket.blob(blob_name)
            blob.download_to_filename(str(original_path))
            
            # Standardize to 24fps for consistent concatenation
            standardized_path = temp_path / f"outro_24fps_{hash(blob_name)}.mp4"
            
            if self._standardize_video_fps(str(original_path), str(standardized_path), 24):
                self.logger.info(f"✅ Downloaded and standardized outro video: {blob_name}")
                return str(standardized_path)
            else:
                self.logger.error(f"❌ Failed to standardize outro video: {blob_name} - skipping outro")
                return None
            
        except Exception as e:
            self.logger.error(f"❌ Error getting outro video: {str(e)}")
            return None
    
    def _get_random_asset_from_folder(self, asset_type: str) -> Optional[str]:
        """Get a random asset from the specified folder type (intros, outros, etc.)"""
        try:
            from automations.canonical_path_builder import get_path_builder
            import random
            
            path_builder = get_path_builder()
            bucket_name = path_builder.bucket_name
            
            # Set bucket dynamically
            self.bucket = self.storage_client.bucket(bucket_name)
            
            # List all files in the asset folder
            folder_prefix = f"channels/{self.channel_id}/assets/{asset_type}/"
            blobs = list(self.bucket.list_blobs(prefix=folder_prefix))
            
            # Filter for video files
            video_files = []
            for blob in blobs:
                if blob.name.lower().endswith(('.mp4', '.avi', '.mov', '.mkv')):
                    video_files.append(blob.name)
            
            if not video_files:
                self.logger.warning(f"⚠️ No {asset_type} videos found in {folder_prefix}")
                return None
            
            # Select random video
            selected_video = random.choice(video_files)
            gs_uri = f"gs://{bucket_name}/{selected_video}"
            
            self.logger.info(f"🎲 Randomly selected {asset_type}: {selected_video}")
            return gs_uri
            
        except Exception as e:
            self.logger.error(f"❌ Error getting random {asset_type}: {str(e)}")
            return None
    
    def _get_background_video(self, channel_data: Dict, temp_path: Path, question_index: int = 0) -> Optional[str]:
        """Get background video from channel assets, cycling through available backgrounds and standardize to 24fps"""
        try:
            # Get bucket from channel data
            bucket_name = channel_data.get('bucket_name', channel_data.get('gcs_bucket', ''))
            if not bucket_name:
                self.logger.error("❌ No GCS bucket specified in channel")
                return None
            
            # Set bucket dynamically
            self.bucket = self.storage_client.bucket(bucket_name)
            
            # Get backgrounds from channel assets or folders
            folders = channel_data.get('folders', {})
            backgrounds_folder = folders.get('backgrounds', '')
            
            # Check if channel has assets structure (new format)
            assets = channel_data.get('assets', {})
            background_assets = assets.get('backgrounds', [])
            
            video_files = []
            
            if background_assets:
                # Use assets structure (new format)
                for asset in background_assets:
                    gcs_path = asset.get('gcs_path', '')
                    if gcs_path and gcs_path.startswith('gs://'):
                        # Extract the blob path from gs://bucket/path
                        blob_path = gcs_path.replace(f'gs://{bucket_name}/', '')
                        if blob_path.lower().endswith('.mp4'):
                            video_files.append(blob_path)
                self.logger.info(f"🎬 Found {len(video_files)} background assets from channel assets")
            elif backgrounds_folder:
                # Use folders structure (old format)
                blobs = list(self.bucket.list_blobs(prefix=backgrounds_folder))
                for blob in blobs:
                    if blob.name.lower().endswith('.mp4'):
                        video_files.append(blob.name)
                self.logger.info(f"🎬 Found {len(video_files)} background files from folder: {backgrounds_folder}")
            else:
                self.logger.error("❌ No backgrounds folder or assets specified in channel")
                return None
            
            # Sort by name to ensure consistent ordering
            video_files.sort()
            
            if not video_files:
                self.logger.error(f"❌ No background videos found in: {backgrounds_folder}")
                self.logger.error(f"❌ Please upload background videos (.mp4 files) to: gs://{bucket_name}/{backgrounds_folder}")
                return None
            
            # Cycle through backgrounds based on question index
            selected_video = video_files[question_index % len(video_files)]
            self.current_background_name = selected_video
            
            self.logger.info(f"🎬 Using background video {question_index + 1}/{len(video_files)}: {selected_video}")
            
            # Download the selected video file
            original_path = temp_path / f"background_original_{hash(selected_video)}.mp4"
            blob = self.bucket.blob(selected_video)
            blob.download_to_filename(str(original_path))
            
            # Standardize to 24fps for consistent concatenation
            standardized_path = temp_path / f"background_24fps_{hash(selected_video)}.mp4"
            
            if self._standardize_video_fps(str(original_path), str(standardized_path), 24):
                self.logger.info(f"✅ Downloaded and standardized background video: {selected_video}")
                return str(standardized_path)
            else:
                self.logger.error(f"❌ Failed to standardize background video: {selected_video}")
                return str(original_path)  # Fallback to original
            
        except Exception as e:
            self.logger.error(f"❌ Error getting background video: {str(e)}")
            return None
    
    
    def _concatenate_videos(self, video_files: List[str], temp_path: Path) -> Optional[str]:
        """Concatenate all video files into final video with intro, transitions, and outro"""
        try:
            self.logger.info(f"🎬 Starting concatenation with {len(video_files)} question videos")
            for i, vf in enumerate(video_files):
                self.logger.info(f"🎬 Question video {i+1}: {vf}")
            
            # Get intro and outro videos (optional - don't fail if not found)
            self.logger.info("🎬 ATTEMPTING TO GET INTRO VIDEO...")
            intro_video = self._get_intro_video(temp_path)
            if intro_video:
                self.logger.info(f"✅ INTRO VIDEO FOUND: {intro_video}")
            else:
                self.logger.warning("⚠️ NO INTRO VIDEO FOUND - PROCEEDING WITHOUT INTRO")
                intro_video = None
                
            self.logger.info("🎬 ATTEMPTING TO GET OUTRO VIDEO...")
            outro_video = self._get_outro_video(temp_path)
            if outro_video:
                self.logger.info(f"✅ OUTRO VIDEO FOUND: {outro_video}")
            else:
                self.logger.warning("⚠️ NO OUTRO VIDEO FOUND - PROCEEDING WITHOUT OUTRO")
            
            # Build the complete video sequence
            complete_video_files = []
            
            # Add intro if available
            if intro_video:
                complete_video_files.append(intro_video)
                self.logger.info("🎬 Added intro video to sequence")
                # Insert a transition immediately after intro per required sequence
                try:
                    self.logger.info("🎬 ATTEMPTING TO GET TRANSITION AFTER INTRO...")
                    intro_transition = self._get_transition_video(temp_path, 0)
                    if intro_transition:
                        complete_video_files.append(intro_transition)
                        self.logger.info(f"✅ TRANSITION AFTER INTRO FOUND: {intro_transition}")
                    else:
                        self.logger.warning("⚠️ NO TRANSITION AFTER INTRO FOUND - CONTINUING")
                except Exception as e:
                    self.logger.error(f"⚠️ Could not add transition after intro: {e}")
            
            # Add question videos with transitions
            transition_index = 0  # Start with index 0 for first transition after intro
            for i, video_file in enumerate(video_files):
                # Add question video
                self.logger.info(f"🎬 Adding question video {i+1} to sequence: {video_file}")
                complete_video_files.append(video_file)
                
                # Add transition after every question (including the last one)
                transition_index += 1
                self.logger.info(f"🎬 ATTEMPTING TO GET TRANSITION VIDEO {transition_index}...")
                transition_video = self._get_transition_video(temp_path, transition_index)
                if transition_video:
                    complete_video_files.append(transition_video)
                    self.logger.info(f"✅ TRANSITION VIDEO {transition_index} FOUND: {transition_video}")
                else:
                    self.logger.warning(f"⚠️ NO TRANSITION VIDEO {transition_index} FOUND - PROCEEDING WITHOUT TRANSITION")
            
            # Add outro if available
            if outro_video:
                complete_video_files.append(outro_video)
                self.logger.info("🎬 Added outro video to sequence")
            
            if len(complete_video_files) == 1:
                return complete_video_files[0]
            
            # Create file list for FFmpeg
            file_list = temp_path / "file_list.txt"
            with open(file_list, 'w') as f:
                for video_file in complete_video_files:
                    f.write(f"file '{video_file}'\n")
            
            # Concatenate videos with proper audio/video synchronization
            final_video = temp_path / "final_video.mp4"
            
            # Build input arguments for multiple files
            input_args = []
            for video_file in complete_video_files:
                input_args.extend(['-i', video_file])
            
            # Use filter_complex for proper concatenation with resolution scaling
            # First scale all videos to 1280x720, then concatenate
            # For audio: use audio from question videos, mute transitions/outro audio
            scale_filters = []
            concat_inputs = []
            
            for i in range(len(complete_video_files)):
                scale_filters.append(f'[{i}:v]scale=1280:720[v{i}]')
                
                # Check if this is a question video (has music) or transition/outro
                video_file = complete_video_files[i]
                if 'question' in video_file or 'generated_question_slide' in video_file:
                    # Question videos: use their audio (which includes music)
                    concat_inputs.append(f'[v{i}][{i}:a]')
                else:
                    # Transitions/outro: create silent audio to preserve music continuity
                    scale_filters.append(f'[{i}:a]anull[a{i}]')
                    concat_inputs.append(f'[v{i}][a{i}]')
            
            filter_complex = ';'.join(scale_filters) + ';' + ''.join(concat_inputs) + f'concat=n={len(complete_video_files)}:v=1:a=1[outv][outa]'
            
            cmd = [
                'ffmpeg', '-y',
                *input_args,
                '-filter_complex', filter_complex,
                '-map', '[outv]', '-map', '[outa]',
                '-c:v', 'libx264',  # Re-encode to ensure consistent frame rate
                '-c:a', 'aac',      # Re-encode audio for consistency
                '-pix_fmt', 'yuv420p',
                '-movflags', '+faststart',
                str(final_video)
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode == 0:
                self.logger.info("✅ Successfully concatenated videos with intro, transitions, and outro")
                return str(final_video)
            else:
                self.logger.error(f"❌ FFmpeg concatenation error: {result.stderr}")
                return None
                
        except Exception as e:
            self.logger.error(f"❌ Error concatenating videos: {str(e)}")
            return None
    
    def _upload_to_gcs(self, video_path: str, job_id: str, channel_data: Dict) -> Optional[str]:
        """Upload final video to GCS"""
        try:
            # Get bucket from channel data
            bucket_name = channel_data.get('bucket_name', channel_data.get('gcs_bucket', ''))
            if not bucket_name:
                self.logger.error("❌ No GCS bucket specified in channel")
                return None
            
            # Set bucket dynamically
            self.bucket = self.storage_client.bucket(bucket_name)
            
            gcs_path = f"videos/{job_id}/final_video.mp4"
            
            # Debug: Check file before upload
            from pathlib import Path
            if Path(video_path).exists():
                file_size = Path(video_path).stat().st_size
                self.logger.info(f"📊 File size before upload: {file_size:,} bytes")
            else:
                self.logger.error(f"❌ File not found: {video_path}")
                return None
            
            # Use direct storage client upload (this works)
            from google.cloud import storage
            storage_client = storage.Client()
            bucket = storage_client.bucket(bucket_name)
            blob = bucket.blob(gcs_path)
            blob.upload_from_filename(video_path)
            
            # Debug: Check uploaded file
            if blob.exists():
                uploaded_size = blob.size or 0
                self.logger.info(f"📊 Uploaded file size: {uploaded_size:,} bytes")
            else:
                self.logger.error("❌ Uploaded file not found")
            
            self.logger.info(f"✅ Uploaded video to GCS: {gcs_path}")
            return gcs_path
            
        except Exception as e:
            self.logger.error(f"❌ Error uploading to GCS: {str(e)}")
            return None
    
    def _update_job_completion(self, job_id: str, gcs_path: str):
        """Update job document with completion status and video URL"""
        try:
            from datetime import datetime, timedelta
            
            # Use direct storage client (this works)
            from google.cloud import storage
            storage_client = storage.Client()
            
            # Use the correct bucket name
            bucket_name = 'trivia-dev-assets'
            blob_name = gcs_path
            
            bucket = storage_client.bucket(bucket_name)
            blob = bucket.blob(blob_name)
            
            # Create signed URL (valid for 7 days)
            video_url = blob.generate_signed_url(
                version="v4",
                expiration=datetime.utcnow() + timedelta(days=7),
                method="GET"
            )
            
            # Get YouTube metadata from job data
            youtube_title = self.job_data.get('youtube_title', 'Sports Trivia Quiz')
            youtube_description = self.job_data.get('youtube_description', 'Sports trivia quiz video')
            
            # Update job document
            job_ref = self.jobs_collection.document(job_id)
            job_ref.update({
                'status': 'completed',
                'progress': 100,
                'completed_at': datetime.utcnow().isoformat() + "Z",
                'output.video_url': video_url,
                'output.gcs_uri': f"gs://{bucket_name}/{gcs_path}",
                'final_video_path': f"gs://{bucket_name}/{gcs_path}",  # Add this for control center compatibility
                'youtube_title': youtube_title,
                'youtube_description': youtube_description,
                'updated_at': datetime.utcnow().isoformat() + "Z"
            })
            
            self.logger.info(f"✅ Updated job {job_id} with video URL: {video_url[:50]}...")
            
            # Check if YouTube upload is enabled for this job
            input_data = self.job_data.get('input_data', {})
            youtube_upload_enabled = input_data.get('youtube_upload_test', False)
            if youtube_upload_enabled:
                self.logger.info(f"🎬 YouTube upload enabled for job {job_id}, starting upload...")
                self._upload_to_youtube(job_id, local_video_path, self.job_data)
            
        except Exception as e:
            self.logger.error(f"❌ Error updating job completion: {str(e)}")
            import traceback
            traceback.print_exc()

    def _upload_to_youtube(self, job_id: str, video_path: str, job_data: Dict) -> None:
        """Upload completed video to YouTube if enabled"""
        try:
            self.logger.info(f"🎬 Starting YouTube upload for job {job_id}")
            
            # Get thumbnail path if available
            thumbnail_path = job_data.get('thumbnail_url')
            if thumbnail_path and thumbnail_path.startswith('http'):
                # Download thumbnail from URL to local path
                import requests
                thumbnail_response = requests.get(thumbnail_path)
                if thumbnail_response.status_code == 200:
                    thumbnail_local_path = Path(tempfile.gettempdir()) / f"thumbnail_{job_id}.jpg"
                    with open(thumbnail_local_path, 'wb') as f:
                        f.write(thumbnail_response.content)
                    thumbnail_path = str(thumbnail_local_path)
                else:
                    thumbnail_path = None
            
            # Use the YouTube upload service
            result = self.youtube_upload_service.upload_video_from_job(
                video_path=video_path,
                job_data=job_data,
                thumbnail_path=thumbnail_path
            )
            
            if result.get('success'):
                youtube_url = result.get('video_url', 'Unknown URL')
                youtube_id = result.get('video_id', 'Unknown ID')
                
                # Update job with YouTube information
                job_ref = self.jobs_collection.document(job_id)
                job_ref.update({
                    'youtube_upload_status': 'completed',
                    'youtube_url': youtube_url,
                    'youtube_video_id': youtube_id,
                    'youtube_uploaded_at': datetime.utcnow().isoformat() + "Z",
                    'updated_at': datetime.utcnow().isoformat() + "Z"
                })
                
                self.logger.info(f"✅ YouTube upload completed for job {job_id}")
                self.logger.info(f"   YouTube URL: {youtube_url}")
                self.logger.info(f"   Video ID: {youtube_id}")
                
            else:
                error_msg = result.get('error', 'Unknown error')
                error_code = result.get('error_code', 'UNKNOWN')
                
                # Update job with YouTube upload failure
                job_ref = self.jobs_collection.document(job_id)
                job_ref.update({
                    'youtube_upload_status': 'failed',
                    'youtube_upload_error': error_msg,
                    'youtube_upload_error_code': error_code,
                    'youtube_upload_failed_at': datetime.utcnow().isoformat() + "Z",
                    'updated_at': datetime.utcnow().isoformat() + "Z"
                })
                
                self.logger.error(f"❌ YouTube upload failed for job {job_id}: {error_msg}")
                
        except Exception as e:
            self.logger.error(f"❌ YouTube upload error for job {job_id}: {str(e)}")
            
            # Update job with YouTube upload exception
            try:
                job_ref = self.jobs_collection.document(job_id)
                job_ref.update({
                    'youtube_upload_status': 'error',
                    'youtube_upload_error': str(e),
                    'youtube_upload_error_code': 'EXCEPTION',
                    'youtube_upload_failed_at': datetime.utcnow().isoformat() + "Z",
                    'updated_at': datetime.utcnow().isoformat() + "Z"
                })
            except Exception as update_error:
                self.logger.error(f"❌ Failed to update job with YouTube error: {str(update_error)}")

    def _fetch_tts_audio(self, text: str, voice: str, cache_dir: Path, filename: Path,
                         endpoint: str, label: str) -> Optional[str]:
        import requests
        import time

        normalized = text.strip()
        if not normalized:
            self.logger.warning(f"⚠️ Skipping empty TTS input for {label}")
            return None

        content_hash = hashlib.sha256(normalized.encode('utf-8')).hexdigest()
        cache_path = cache_dir / f"tts_{content_hash}.mp3"

        if cache_path.exists() and cache_path.stat().st_size > 0:
            shutil.copy(cache_path, filename)
            self.logger.info(f"♻️ Reused cached TTS audio for {label}")
            return str(filename)

        payload = {
            "model": "tts1",
            "voice": voice,
            "input": normalized,
            "response_format": "mp3"
        }
        headers = {"Accept": "audio/mpeg"}
        max_attempts = 5

        for attempt in range(max_attempts):
            wait_required = False
            wait_reason = ""
            try:
                response = requests.post(
                    endpoint,
                    json=payload,
                    headers=headers,
                    timeout=(10, 45)
                )
            except requests.exceptions.Timeout:
                wait_required = True
                wait_reason = "timeout"
            except requests.exceptions.RequestException as exc:
                if attempt < max_attempts - 1:
                    wait_required = True
                    wait_reason = f"request error: {exc}"
                else:
                    self.logger.error(f"❌ TTS request failed for {label}: {exc}")
                    return None
            else:
                content_type = response.headers.get('Content-Type', '')
                if response.status_code == 200 and 'audio' in content_type.lower():
                    cache_path.write_bytes(response.content)
                    shutil.copy(cache_path, filename)
                    self.logger.info(f"✅ Generated TTS audio for {label} (attempt {attempt + 1}/{max_attempts})")
                    return str(filename)

                if response.status_code == 429 or response.status_code >= 500:
                    wait_required = True
                    wait_reason = f"HTTP {response.status_code}"
                else:
                    snippet = response.text[:200] if response.text else '<empty>'
                    self.logger.error(
                        f"❌ TTS request for {label} failed (HTTP {response.status_code}): {snippet}"
                    )
                    return None

            if wait_required and attempt < max_attempts - 1:
                delay = min(2 ** attempt, 8) + random.uniform(0, 0.75)
                self.logger.warning(
                    f"⚠️ TTS retry for {label} due to {wait_reason}; backing off {delay:.2f}s"
                )
                time.sleep(delay)
            elif wait_required:
                self.logger.error(f"❌ Exhausted retries for {label} ({wait_reason})")

        return None

    def _build_answer_announcement(self, question: Dict) -> str:
        correct = question.get('correct_answer')
        if isinstance(correct, str) and correct.upper() in ['A', 'B', 'C', 'D']:
            idx = ord(correct.upper()) - ord('A')
            option_key = f"answer_{chr(ord('a') + idx)}"
            answer_text = question.get(option_key, correct)
        else:
            answer_text = question.get('answer', correct)
        answer_text = answer_text or 'the correct answer'
        return f"The correct answer is {answer_text}."

if __name__ == "__main__":
    # Test the unified pipeline
    pipeline = UnifiedTriviaPipeline()
    print("🎬 Unified Trivia Pipeline ready for testing")
