# automations/canonical_path_builder.py

import os
from typing import Optional

def get_path_builder(environment: Optional[str] = None) -> 'PathBuilder':
    """
    Get a path builder instance for the given environment.
    
    Args:
        environment: The environment (dev, staging, prod). If None, uses ENVIRONMENT env var.
        
    Returns:
        PathBuilder instance
    """
    if environment is None:
        environment = os.getenv('ENVIRONMENT', 'dev')
    
    return PathBuilder(environment)

class PathBuilder:
    """Simple path builder for GCS paths and local paths."""
    
    def __init__(self, environment: str = 'dev'):
        self.environment = environment
        
    def get_gcs_path(self, *path_parts: str) -> str:
        """Build a GCS path from parts."""
        return '/'.join(path_parts)
    
    def get_local_path(self, *path_parts: str) -> str:
        """Build a local path from parts."""
        return os.path.join(*path_parts)
    
    def get_bucket_name(self, bucket_type: str = 'assets') -> str:
        """Get the bucket name for the current environment."""
        if self.environment == 'prod':
            return f"trivia-{bucket_type}"
        else:
            return f"trivia-{self.environment}-{bucket_type}"
