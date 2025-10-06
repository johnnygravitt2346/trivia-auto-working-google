# Trivia Video Automation System

A complete automated system for generating trivia quiz videos with AI-generated content, text-to-speech, and YouTube upload capabilities.

## Features

- **Automated Video Generation**: Creates trivia quiz videos from CSV data
- **AI Content Generation**: Uses Google Gemini AI for question generation
- **Text-to-Speech**: Converts questions to audio using external TTS service
- **YouTube Integration**: Automatic upload to YouTube with thumbnails
- **Web Dashboard**: User-friendly interface for job management
- **Firestore Database**: Scalable cloud storage for jobs and metadata
- **Google Cloud Storage**: Asset storage for videos and thumbnails

## Architecture

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   Web Dashboard │    │  Control Center  │    │ Pipeline Manager│
│   (Frontend)    │◄──►│   (Flask API)    │◄──►│  (Job Processor)│
└─────────────────┘    └──────────────────┘    └─────────────────┘
                                │                        │
                                ▼                        ▼
                       ┌──────────────────┐    ┌─────────────────┐
                       │    Firestore     │    │ Unified Pipeline│
                       │   (Database)     │    │ (Video Creator) │
                       └──────────────────┘    └─────────────────┘
                                                        │
                                                        ▼
                                               ┌─────────────────┐
                                               │ YouTube Upload  │
                                               │    Service      │
                                               └─────────────────┘
```

## Prerequisites

- Python 3.8+
- Google Cloud Platform account
- Firebase/Firestore project
- YouTube API credentials
- External TTS service access

## Installation

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd trivia-automation-system
   ```

2. **Install Python dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up Google Cloud credentials**
   ```bash
   # Download service account key from Google Cloud Console
   # Place it in the secrets/ directory
   cp your-service-account-key.json secrets/service-account-key.json
   ```

4. **Configure environment variables**
   ```bash
   export GOOGLE_APPLICATION_CREDENTIALS="secrets/service-account-key.json"
   export ENVIRONMENT="dev"  # or "prod"
   ```

5. **Set up YouTube OAuth credentials**
   ```bash
   # Download OAuth client credentials from Google Cloud Console
   # Place in secrets/youtube_oauth_client.json
   ```

6. **Initialize Firestore**
   ```bash
   # Deploy Firestore rules and indexes
   firebase deploy --only firestore:rules,firestore:indexes
   ```

## Configuration

### Environment Variables

- `ENVIRONMENT`: Set to "dev" or "prod" (default: "dev")
- `GOOGLE_APPLICATION_CREDENTIALS`: Path to service account key
- `GEMINI_API_KEY`: Google Gemini API key for content generation

### Firestore Collections

- `dev_jobs`: Job data and status (development)
- `prod_jobs`: Job data and status (production)
- `dev_assets`: Asset metadata (development)
- `prod_assets`: Asset metadata (production)

### Google Cloud Storage

- Bucket naming: `trivia-{environment}-assets`
- Automatic asset organization by job ID

## Usage

### Starting the System

1. **Start the Control Center (API Server)**
   ```bash
   python3 interface/control_center.py
   ```

2. **Start the Pipeline Manager (Job Processor)**
   ```bash
   python3 -c "
   import os
   import sys
   sys.path.append('.')
   os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = 'secrets/service-account-key.json'
   
   from core.pipeline_manager import PipelineManager
   from interface.control_center import control_center
   
   pipeline_manager = PipelineManager(control_center.jobs_collection, control_center)
   result = pipeline_manager.start_pipeline()
   print(f'Pipeline started: {result}')
   "
   ```

3. **Access the Web Dashboard**
   - Open browser to `http://localhost:5000`
   - Upload CSV files with trivia questions
   - Configure YouTube upload settings
   - Monitor job progress

### Job Types

1. **Single CSV Upload**: Process one CSV file with questions
2. **Bulk CSV Upload**: Process multiple CSV files
3. **CSV + Manifest Upload**: Process with YouTube metadata

### CSV Format

```csv
question,answer,option1,option2,option3,option4
"What is the capital of France?","Paris","London","Berlin","Madrid","Paris"
"Which planet is closest to the Sun?","Mercury","Venus","Earth","Mars","Mercury"
```

### Manifest Format (for YouTube uploads)

```json
{
  "youtube_title": "Amazing Trivia Quiz",
  "youtube_description": "Test your knowledge with these questions!",
  "thumbnail_url": "https://example.com/thumbnail.jpg"
}
```

## API Endpoints

### Job Management
- `POST /api/jobs` - Create new job
- `GET /api/jobs` - List all jobs
- `GET /api/jobs/<job_id>` - Get job details
- `POST /api/jobs/<job_id>/retry` - Retry failed job

### Bulk Operations
- `POST /api/bulk-jobs` - Create bulk jobs
- `POST /api/bulk-jobs/<batch_id>/retry` - Retry batch

### System Status
- `GET /api/health` - System health check
- `GET /api/stats` - System statistics

## File Structure

```
trivia-automation-system/
├── core/                          # Core pipeline components
│   ├── pipeline_manager.py        # Job processing manager
│   ├── template_manager.py        # Video template management
│   ├── unified_trivia_pipeline.py # Main video generation pipeline
│   └── youtube_upload_service.py  # YouTube upload service
├── interface/                     # Web interface
│   ├── control_center.py          # Flask API server
│   └── static/                    # Frontend assets
│       ├── css/                   # Stylesheets
│       └── js/                    # JavaScript files
├── templates/                     # HTML templates
│   └── dashboard_new.html         # Main dashboard
├── config/                        # Configuration files
│   ├── firebase.json              # Firebase configuration
│   ├── firestore.rules            # Firestore security rules
│   └── firestore.indexes.json     # Firestore indexes
├── secrets/                       # Credentials (not in git)
│   ├── service-account-key.json   # Google Cloud service account
│   ├── youtube_oauth_client.json  # YouTube OAuth credentials
│   └── youtube_tokens.json        # YouTube access tokens
└── requirements.txt               # Python dependencies
```

## Development

### Adding New Features

1. **New Pipeline Stages**: Add to `unified_trivia_pipeline.py`
2. **New API Endpoints**: Add to `control_center.py`
3. **New UI Components**: Add to `static/js/` and `templates/`

### Testing

```bash
# Test the pipeline
python3 -c "
from core.unified_trivia_pipeline import UnifiedTriviaPipeline
pipeline = UnifiedTriviaPipeline()
print('Pipeline initialized successfully')
"

# Test the API
curl http://localhost:5000/api/health
```

### Debugging

- Check logs in `/tmp/` directory
- Monitor Firestore for job status updates
- Use browser developer tools for frontend debugging

## Deployment

### Production Setup

1. **Set environment to production**
   ```bash
   export ENVIRONMENT="prod"
   ```

2. **Use production Firestore collections**
   - Jobs: `prod_jobs`
   - Assets: `prod_assets`

3. **Configure production GCS bucket**
   - Bucket: `trivia-prod-assets`

4. **Set up monitoring and logging**
   - Configure log aggregation
   - Set up error alerting
   - Monitor resource usage

### Scaling Considerations

- **Horizontal scaling**: Run multiple pipeline managers
- **Database optimization**: Use Firestore indexes
- **Storage optimization**: Implement asset cleanup
- **API rate limiting**: Configure appropriate limits

## Troubleshooting

### Common Issues

1. **Jobs stuck in "pending" status**
   - Check if Pipeline Manager is running
   - Verify Firestore permissions
   - Check for error logs

2. **YouTube upload failures**
   - Verify OAuth credentials
   - Check video file accessibility
   - Ensure thumbnail URL is valid

3. **TTS generation failures**
   - Verify external TTS service connectivity
   - Check API rate limits
   - Validate text content

### Log Locations

- Control Center: `/tmp/control_center.log`
- Pipeline Manager: `/tmp/pipeline_manager.log`
- YouTube Upload: `/tmp/youtube_upload.log`

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Support

For support and questions:
- Create an issue in the repository
- Check the troubleshooting section
- Review the API documentation

## Changelog

### Version 1.0.0
- Initial release
- Core video generation pipeline
- YouTube upload integration
- Web dashboard interface
- Firestore database integration
