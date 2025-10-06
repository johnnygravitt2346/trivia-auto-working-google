#!/usr/bin/env python3
"""
Pipeline Manager - Manages the pipeline watcher and job processing
"""

import threading
import time
import logging
from typing import Optional
from datetime import datetime, timezone

from google.cloud import firestore

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class PipelineManager:
    """Manages the pipeline watcher and job processing"""
    
    def __init__(self, jobs_collection, control_center):
        self.jobs_collection = jobs_collection
        self.control_center = control_center
        self.pipeline_running = False
        self.watcher_thread = None
        self.logger = logger
        self.processing_lock = threading.Lock()  # Ensure only one job processes at a time
        self.currently_processing = False
        
    def start_pipeline(self) -> dict:
        """Start the pipeline watcher"""
        self.logger.info("🔄 Pipeline start requested")
        
        if self.pipeline_running:
            self.logger.warning("⚠️ Pipeline already running")
            return {'error': 'Pipeline already running'}
        
        try:
            self.logger.info("🚀 Creating pipeline watcher thread...")
            self.pipeline_running = True
            self.watcher_thread = threading.Thread(target=self._run_pipeline_watcher)
            self.watcher_thread.daemon = True
            
            self.logger.info("🚀 Starting pipeline watcher thread...")
            self.watcher_thread.start()
            
            self.logger.info(f"✅ Pipeline watcher thread started: {self.watcher_thread.ident}")
            
            return {'success': True, 'message': 'Pipeline started'}
        except Exception as e:
            self.pipeline_running = False
            self.logger.error(f"❌ Error starting pipeline: {e}")
            import traceback
            traceback.print_exc()
            return {'error': f'Failed to start pipeline: {str(e)}'}
    
    def stop_pipeline(self) -> dict:
        """Stop the pipeline watcher"""
        self.logger.info("🛑 Stopping pipeline...")
        self.pipeline_running = False
        return {'success': True, 'message': 'Pipeline stopped'}
    
    def get_status(self) -> dict:
        """Get pipeline status"""
        return {'running': self.pipeline_running}
    
    def _run_pipeline_watcher(self):
        """Background thread to watch for pending jobs"""
        self.logger.info("🚀 Pipeline watcher started")
        
        while self.pipeline_running:
            try:
                self.logger.info("🔍 Checking for pending jobs...")
                
                # Get all jobs and filter for pending ones and failed ones that need retry
                # Get all jobs without ordering first to debug the query issue
                self.logger.info("🔍 Starting database query...")
                all_jobs = self.jobs_collection.stream()
                self.logger.info("🔍 Database query completed, iterating results...")
                pending_jobs = []
                failed_jobs_to_retry = []
                
                # Check for stuck processing jobs (no heartbeat for 30 minutes)
                self._check_stuck_jobs()
                
                job_count = 0
                for job_doc in all_jobs:
                    job_count += 1
                    job_data = job_doc.to_dict()
                    status = job_data.get("status")
                    
                    # Debug logging for our specific job
                    if job_doc.id == "job_20251003_114421_2ed3fbbd":
                        self.logger.info(f"🔍 Found our job: {job_doc.id}, status: {status}")
                    
                    if status in ["pending", "local_pending"]:
                        pending_jobs.append((job_doc.id, job_data))
                    elif status == "failed":
                        # Check if this failed job should be retried
                        retry_count = job_data.get("retry_count", 0)
                        max_retries = job_data.get("max_retries", 3)  # Default 3 retries
                        
                        if retry_count < max_retries:
                            failed_jobs_to_retry.append((job_doc.id, job_data))
                
                self.logger.info(f"🔍 Total jobs examined: {job_count}")
                
                self.logger.info(f"📊 Found {len(pending_jobs)} pending jobs and {len(failed_jobs_to_retry)} failed jobs to retry")
                
                # TTS server wake-up logic removed - using external TTS service
                
                # Process pending jobs first (FIFO order - oldest first)
                for i, (job_id, job_data) in enumerate(pending_jobs):
                    if not self.pipeline_running:
                        break
                    
                    # Check if we're already processing a job
                    if self.currently_processing:
                        self.logger.info(f"⏸️ Skipping job {job_id} - another job is currently processing")
                        continue
                    
                    # Add 1-second spacing between jobs (except the first one)
                    if i > 0:
                        self.logger.info(f"⏱️ Waiting 1 second before processing next job...")
                        time.sleep(1)
                    
                    # Process all jobs locally on the server
                    local_processing = job_data.get("localProcessing", True)  # Default to True
                    use_production = job_data.get("use_production", False)
                    
                    # Process all jobs locally (no cloud worker filtering)
                    self.logger.info(f"🚀 Processing job: {job_id} (localProcessing={local_processing}, use_production={use_production}) [Position {i+1}/{len(pending_jobs)}]")
                    
                    # Mark as processing
                    self.control_center.update_job_status(job_id, "processing", progress=10)
                    
                    # Process the job with lock to ensure single-job processing
                    self._process_job_with_lock(job_id, job_data)
                
                # DISABLED: Automatic retry of failed jobs to improve system performance
                # Failed jobs will remain failed and can be manually retried if needed
                if failed_jobs_to_retry:
                    self.logger.info(f"⏸️ Skipping {len(failed_jobs_to_retry)} failed jobs (automatic retry disabled)")
                
                time.sleep(10)  # Check every 10 seconds
                
            except Exception as e:
                self.logger.error(f"⚠️ Error in pipeline watcher: {e}")
                import traceback
                traceback.print_exc()
                time.sleep(30)
    
    def _process_job_with_lock(self, job_id: str, job_data: dict):
        """Process a single job with lock to ensure only one job processes at a time"""
        with self.processing_lock:
            self.currently_processing = True
            try:
                self.logger.info(f"🔒 Processing job {job_id} (single-job mode)")
                self._process_job(job_id, job_data)
            finally:
                self.currently_processing = False
                self.logger.info(f"🔓 Job {job_id} processing completed, lock released")
    
    def _process_job(self, job_id: str, job_data: dict):
        """Process a single job with retry logic"""
        try:
            self.logger.info(f"🎬 Processing job {job_id}")
            
            # Mark as local processing
            self.control_center.update_job_status(job_id, "processing", localProcessing=True, progress=10)
            
            # Import the unified pipeline
            self.logger.info("🎬 Using unified pipeline")
            from core.unified_trivia_pipeline import UnifiedTriviaPipeline
            pipeline = UnifiedTriviaPipeline()
            
            # Process the job
            result = pipeline.process_job(job_id)
            
            if result:
                # Store the GCS path (not the full URL)
                gcs_path = result
                
                # Mark as completed
                self.control_center.update_job_status(
                    job_id, 
                    "completed",
                    progress=100,
                    gcsVideoPath=gcs_path,
                    processingTime=10.0,
                    localProcessing=True,  # Keep as True since it was processed locally
                    retry_count=0  # Reset retry count on success
                )
                self.logger.info(f"✅ Job {job_id} completed successfully")
            else:
                # Mark as permanently failed (no automatic retries)
                self.control_center.update_job_status(
                    job_id, 
                    "failed", 
                    error="Pipeline processing failed",
                    localProcessing=True,  # Keep as True since it was processed locally
                    retry_count=0
                )
                self.logger.error(f"❌ Job {job_id} failed - no automatic retry")
            
        except Exception as e:
            self.logger.error(f"❌ Error processing job {job_id}: {e}")
            import traceback
            traceback.print_exc()
            
            # Mark as permanently failed (no automatic retries)
            self.control_center.update_job_status(
                job_id, 
                "failed", 
                error=f"Exception: {str(e)}",
                localProcessing=True,  # Keep as True since it was processed locally
                retry_count=0
            )
            self.logger.error(f"❌ Job {job_id} failed with exception - no automatic retry")
        finally:
            self.currently_processing = False
            self.logger.info(f"🔓 Job {job_id} processing completed, lock released")
    
    def _check_stuck_jobs(self):
        """Check for processing jobs that haven't sent a heartbeat in 30 minutes and fail them"""
        try:
            # Get all processing jobs
            processing_jobs = self.jobs_collection.where('status', '==', 'processing').stream()
            current_time = datetime.now(timezone.utc)
            stuck_jobs = []
            
            for job_doc in processing_jobs:
                job_data = job_doc.to_dict()
                job_id = job_doc.id
                
                # Get the last heartbeat time
                last_heartbeat = job_data.get('lastHeartbeatAt')
                if not last_heartbeat:
                    # If no heartbeat, use the updated_at time
                    last_heartbeat = job_data.get('updated_at')
                
                if last_heartbeat:
                    try:
                        # Parse the timestamp (handle both ISO format and simple format)
                        if isinstance(last_heartbeat, str):
                            # Fix double timezone issue
                            heartbeat_str = str(last_heartbeat)
                            if '+00:00+00:00' in heartbeat_str:
                                heartbeat_str = heartbeat_str.replace('+00:00+00:00', '+00:00')
                            elif 'Z+00:00' in heartbeat_str:
                                heartbeat_str = heartbeat_str.replace('Z+00:00', 'Z')
                            
                            if heartbeat_str.endswith('Z'):
                                # ISO format with Z
                                heartbeat_time = datetime.fromisoformat(heartbeat_str.replace('Z', '+00:00'))
                            else:
                                # Try parsing as ISO format
                                heartbeat_time = datetime.fromisoformat(heartbeat_str)
                        else:
                            # Assume it's already a datetime object
                            heartbeat_time = last_heartbeat
                        
                        # Calculate time difference
                        time_diff = current_time - heartbeat_time
                        
                        # If no heartbeat for 30 minutes (1800 seconds), mark as stuck
                        if time_diff.total_seconds() > 1800:  # 30 minutes
                            stuck_jobs.append((job_id, job_data, time_diff))
                            
                    except Exception as e:
                        self.logger.warning(f"⚠️ Could not parse heartbeat time for job {job_id}: {e}")
                        # If we can't parse the time, assume it's stuck
                        stuck_jobs.append((job_id, job_data, None))
            
            # Fail all stuck jobs
            for job_id, job_data, time_diff in stuck_jobs:
                self.logger.warning(f"⏰ Job {job_id} is stuck (no heartbeat for {time_diff} if available), failing it")
                
                # Update job status to failed with stuck reason
                self.jobs_collection.document(job_id).update({
                    'status': 'failed',
                    'error': f'Job stuck - no heartbeat for 30+ minutes',
                    'updated_at': current_time.isoformat() + 'Z',
                    'failed_at': current_time.isoformat() + 'Z'
                })
                
                self.logger.info(f"❌ Failed stuck job: {job_id}")
                
        except Exception as e:
            self.logger.error(f"❌ Error checking for stuck jobs: {e}")
            import traceback
            traceback.print_exc()
    
    def _wake_up_tts_server(self):
        """TTS server wake-up logic removed - using external TTS service"""
        return True  # External TTS service is always ready
    
    def _is_tts_server_ready(self):
        """TTS server check removed - using external TTS service"""
        return True  # External TTS service is always ready
    
    def _check_tts_server_idle_shutdown(self):
        """TTS server shutdown logic removed - using external TTS service"""
        pass  # External TTS service doesn't need shutdown
