"""
Job Stage Contract - Defines job stages and their progress values
"""

# Job stages
STAGE_PENDING = "pending"
STAGE_PROCESSING_TTS = "processing_tts"
STAGE_READY_FOR_RENDER = "ready_for_render"
STAGE_PROCESSING_RENDER = "processing_render"
STAGE_COMPLETED = "completed"
STAGE_FAILED = "failed"
STAGE_ABORTED = "aborted"

# Stage progress mapping (0-100)
STAGE_PROGRESS = {
    STAGE_PENDING: 0,
    STAGE_PROCESSING_TTS: 25,
    STAGE_READY_FOR_RENDER: 50,
    STAGE_PROCESSING_RENDER: 75,
    STAGE_COMPLETED: 100,
    STAGE_FAILED: 0,
    STAGE_ABORTED: 0
}

def normalize_stage(stage_value):
    """Normalize stage value to a known stage constant"""
    if not stage_value:
        return STAGE_PENDING
    
    stage_lower = str(stage_value).lower().strip()
    
    # Map various stage representations to standard stages
    stage_mapping = {
        'pending': STAGE_PENDING,
        'queued': STAGE_PENDING,
        'waiting': STAGE_PENDING,
        
        'processing_tts': STAGE_PROCESSING_TTS,
        'tts': STAGE_PROCESSING_TTS,
        'text_to_speech': STAGE_PROCESSING_TTS,
        'generating_audio': STAGE_PROCESSING_TTS,
        
        'ready_for_render': STAGE_READY_FOR_RENDER,
        'ready': STAGE_READY_FOR_RENDER,
        'tts_complete': STAGE_READY_FOR_RENDER,
        'audio_ready': STAGE_READY_FOR_RENDER,
        
        'processing_render': STAGE_PROCESSING_RENDER,
        'rendering': STAGE_PROCESSING_RENDER,
        'video_generation': STAGE_PROCESSING_RENDER,
        'creating_video': STAGE_PROCESSING_RENDER,
        
        'completed': STAGE_COMPLETED,
        'done': STAGE_COMPLETED,
        'finished': STAGE_COMPLETED,
        'success': STAGE_COMPLETED,
        
        'failed': STAGE_FAILED,
        'error': STAGE_FAILED,
        'failure': STAGE_FAILED,
        
        'aborted': STAGE_ABORTED,
        'cancelled': STAGE_ABORTED,
        'stopped': STAGE_ABORTED
    }
    
    return stage_mapping.get(stage_lower, STAGE_PENDING)

def get_progress_for_stage(stage):
    """Get progress percentage for a given stage"""
    normalized_stage = normalize_stage(stage)
    return STAGE_PROGRESS.get(normalized_stage, 0)

def is_terminal_stage(stage):
    """Check if a stage is terminal (completed, failed, or aborted)"""
    normalized_stage = normalize_stage(stage)
    return normalized_stage in [STAGE_COMPLETED, STAGE_FAILED, STAGE_ABORTED]

def is_processing_stage(stage):
    """Check if a stage indicates the job is actively processing"""
    normalized_stage = normalize_stage(stage)
    return normalized_stage in [STAGE_PROCESSING_TTS, STAGE_PROCESSING_RENDER]

def get_next_stage(current_stage):
    """Get the next stage in the pipeline"""
    normalized_stage = normalize_stage(current_stage)
    
    stage_sequence = [
        STAGE_PENDING,
        STAGE_PROCESSING_TTS,
        STAGE_READY_FOR_RENDER,
        STAGE_PROCESSING_RENDER,
        STAGE_COMPLETED
    ]
    
    try:
        current_index = stage_sequence.index(normalized_stage)
        if current_index < len(stage_sequence) - 1:
            return stage_sequence[current_index + 1]
    except ValueError:
        pass
    
    return normalized_stage  # Return current stage if no next stage

def get_stage_display_name(stage):
    """Get a human-readable display name for a stage"""
    normalized_stage = normalize_stage(stage)
    
    display_names = {
        STAGE_PENDING: "Pending",
        STAGE_PROCESSING_TTS: "Generating Audio",
        STAGE_READY_FOR_RENDER: "Ready for Render",
        STAGE_PROCESSING_RENDER: "Creating Video",
        STAGE_COMPLETED: "Completed",
        STAGE_FAILED: "Failed",
        STAGE_ABORTED: "Aborted"
    }
    
    return display_names.get(normalized_stage, "Unknown")
