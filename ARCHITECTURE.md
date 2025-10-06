# 🏗️ Trivia Video Automation System - Complete Architecture

## Overview

This document provides a comprehensive architectural overview of the Trivia Video Automation System, showing how all components work together to transform CSV data into YouTube videos through an automated pipeline.

## 🎯 System Overview - The Big Picture

```
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                    🎬 TRIVIA VIDEO STUDIO                                        │
│                              Complete Automated Video Generation System                         │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘

┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   👤 USER       │    │  🌐 WEB DASHBOARD │    │  🎛️ CONTROL     │    │  ⚙️ PIPELINE     │
│   INTERFACE     │◄──►│   (Frontend)     │◄──►│   CENTER        │◄──►│   MANAGER       │
│                 │    │   - HTML/CSS/JS  │    │   (Flask API)   │    │   (Job Processor)│
│ • Upload CSV    │    │   - Real-time UI │    │   - REST API    │    │   - FIFO Queue  │
│ • Monitor Jobs  │    │   - Socket.IO    │    │   - Auth/Val    │    │   - Status Track│
│ • Configure     │    │   - File Upload  │    │   - Job Mgmt    │    │   - Error Handle│
└─────────────────┘    └──────────────────┘    └──────────────────┘    └─────────────────┘
                                │                        │                        │
                                ▼                        ▼                        ▼
                       ┌──────────────────┐    ┌──────────────────┐    ┌─────────────────┐
                       │  📁 ASSET        │    │  🗄️ FIRESTORE     │    │  🎥 UNIFIED     │
                       │  MANAGEMENT      │    │   DATABASE       │    │   PIPELINE      │
                       │  - GCS Storage   │    │   - Job Status   │    │   - Video Gen   │
                       │  - File Org      │    │   - Metadata     │    │   - TTS Process │
                       │  - Asset Meta    │    │   - Templates    │    │   - Render Eng  │
                       └──────────────────┘    └──────────────────┘    └─────────────────┘
                                │                        │                        │
                                ▼                        ▼                        ▼
                       ┌──────────────────┐    ┌──────────────────┐    ┌─────────────────┐
                       │  🤖 AI CONTENT   │    │  🎨 TEMPLATE     │    │  📺 YOUTUBE     │
                       │  GENERATION      │    │   MANAGER        │    │   UPLOAD        │
                       │  - Gemini API    │    │   - Video Temp   │    │   - OAuth Auth  │
                       │  - Question Gen  │    │   - Asset Coord  │    │   - Thumbnail   │
                       │  - Answer Gen    │    │   - Layout Mgmt  │    │   - Metadata    │
                       └──────────────────┘    └──────────────────┘    └─────────────────┘
```

## 🔄 Complete Data Flow - From CSV to YouTube

```
📊 INPUT STAGE
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│  📁 CSV UPLOAD → 🎛️ DASHBOARD → 📤 FILE VALIDATION → 🗄️ FIRESTORE (Job Created)                │
│                                                                                                 │
│  CSV Format: question,answer,option1,option2,option3,option4                                   │
│  Example: "What is the capital of France?","Paris","London","Berlin","Madrid","Paris"          │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
                                        │
                                        ▼
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│  ⚙️ PIPELINE PROCESSING STAGE                                                                   │
│                                                                                                 │
│  🎯 Job Status: pending → processing_tts → ready_for_render → processing_render → completed    │
│                                                                                                 │
│  📋 Processing Steps:                                                                           │
│  1. 🔍 Job Discovery (FIFO - oldest first)                                                     │
│  2. 🤖 AI Content Generation (Gemini API)                                                      │
│  3. 🎤 Text-to-Speech Processing (External TTS Service)                                        │
│  4. 🎨 Video Template Assembly (Template Manager)                                              │
│  5. 🎥 Video Rendering (Unified Pipeline)                                                      │
│  6. 📺 YouTube Upload (OAuth + Metadata)                                                       │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
                                        │
                                        ▼
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│  📤 OUTPUT STAGE                                                                                │
│                                                                                                 │
│  🎥 Generated Video → 📁 GCS Storage → 📺 YouTube Upload → ✅ Job Complete                      │
│                                                                                                 │
│  📊 Final Assets:                                                                               │
│  • MP4 Video File (GCS: gs://trivia-dev-assets/jobs/{job_id}/video.mp4)                       │
│  • Thumbnail Image (GCS: gs://trivia-dev-assets/jobs/{job_id}/thumbnail.jpg)                   │
│  • YouTube URL (https://youtube.com/watch?v={video_id})                                        │
│  • Job Metadata (Firestore: dev_jobs/{job_id})                                                 │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

## 🏗️ Detailed Component Architecture

### Control Center (Flask API) - Port 6001

```
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                    🎛️ CONTROL CENTER (Flask API)                               │
│                                    Port: 6001                                                  │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘

┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  📡 API ROUTES  │    │  🔐 AUTHENTICATION│    │  📊 JOB         │    │  🌐 SOCKET.IO   │
│                 │    │                  │    │   MANAGEMENT    │    │   REAL-TIME     │
│ • /api/jobs     │    │ • Google Cloud   │    │                 │    │                 │
│ • /api/channels │    │   Credentials    │    │ • Create Jobs   │    │ • Live Updates  │
│ • /api/templates│    │ • Service Account│    │ • Status Track  │    │ • Progress Push │
│ • /api/assets   │    │ • Firestore Auth │    │ • Error Handle  │    │ • Event Stream  │
│ • /health/ready │    │ • GCS Permissions│    │ • Retry Logic   │    │ • Client Sync   │
└─────────────────┘    └──────────────────┘    └─────────────────┘    └─────────────────┘
                                │                        │                        │
                                ▼                        ▼                        ▼
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  🗄️ FIRESTORE   │    │  📁 GOOGLE CLOUD │    │  🎨 TEMPLATE    │    │  🤖 AI SERVICES │
│   CONNECTIONS   │    │   STORAGE        │    │   MANAGER       │    │                 │
│                 │    │                  │    │                 │    │ • Gemini API    │
│ • dev_jobs      │    │ • trivia-dev-    │    │ • Video Layouts │    │ • Content Gen   │
│ • dev_assets    │    │   assets bucket  │    │ • Asset Coord   │    │ • Question Gen  │
│ • dev_channels  │    │ • File Storage   │    │ • Template DB   │    │ • Answer Gen    │
│ • dev_templates │    │ • Asset Metadata │    │ • Layout Engine │    │ • Quality Check │
└─────────────────┘    └──────────────────┘    └─────────────────┘    └─────────────────┘
```

### Pipeline Manager - The Heart of the System

```
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                    ⚙️ PIPELINE MANAGER                                         │
│                              FIFO Single-Job Processing (Baseline 2)                          │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘

┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  🔍 JOB         │    │  ⏱️ TIMEOUT       │    │  🔄 CHECKPOINT  │    │  📊 PROGRESS    │
│   DISCOVERY     │    │   MANAGEMENT     │    │   SYSTEM        │    │   TRACKING      │
│                 │    │                  │    │                 │    │                 │
│ • FIFO Queue    │    │ • 30min TTS      │    │ • Resume Points │    │ • Real-time     │
│ • Oldest First  │    │   Timeout        │    │ • State Save    │    │   Updates       │
│ • Status Filter │    │ • Job Failure    │    │ • Recovery      │    │ • Stage Progress│
│ • Error Retry   │    │   on Timeout     │    │ • Restart Logic │    │ • Completion %  │
└─────────────────┘    └──────────────────┘    └─────────────────┘    └─────────────────┘
                                │                        │                        │
                                ▼                        ▼                        ▼
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  🎥 UNIFIED     │    │  🎤 TTS           │    │  🎨 RENDER      │    │  📺 YOUTUBE     │
│   PIPELINE      │    │   PROCESSING     │    │   ENGINE        │    │   UPLOAD        │
│                 │    │                  │    │                 │    │                 │
│ • Video Assembly│    │ • External API   │    │ • Template      │    │ • OAuth Auth    │
│ • Asset Coord   │    │ • Audio Gen      │    │   Rendering     │    │ • Metadata      │
│ • Quality Check │    │ • Progress Track │    │ • Video Output  │    │ • Thumbnail     │
│ • Error Handle  │    │ • Checkpoint     │    │ • File Upload   │    │ • URL Return    │
└─────────────────┘    └──────────────────┘    └─────────────────┘    └─────────────────┘
```

### Web Dashboard - User Interface

```
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                    🌐 WEB DASHBOARD                                            │
│                              Real-time Job Management Interface                               │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘

┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  📁 FILE        │    │  📊 JOB          │    │  ⚙️ SYSTEM       │    │  🔧 CONFIG      │
│   UPLOAD        │    │   MONITORING     │    │   STATUS        │    │   MANAGEMENT    │
│                 │    │                  │    │                 │    │                 │
│ • CSV Upload    │    │ • Live Status    │    │ • Health Check  │    │ • Channel Sel   │
│ • Drag & Drop   │    │ • Progress Bars  │    │ • API Status    │    │ • Template Sel  │
│ • Validation    │    │ • Error Display  │    │ • GCS Status    │    │ • YouTube Setup │
│ • Batch Upload  │    │ • Retry Options  │    │ • Pipeline Stat │    │ • Asset Config  │
└─────────────────┘    └──────────────────┘    └─────────────────┘    └─────────────────┘
                                │                        │                        │
                                ▼                        ▼                        ▼
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  📈 ANALYTICS   │    │  🔔 NOTIFICATIONS│    │  🎨 ASSET       │    │  📺 YOUTUBE     │
│   DASHBOARD     │    │   SYSTEM         │    │   BROWSER       │    │   INTEGRATION   │
│                 │    │                  │    │                 │    │                 │
│ • Job Stats     │    │ • Success Alerts │    │ • Asset Preview │    │ • Upload Status │
│ • Performance   │    │ • Error Alerts   │    │ • File Browser  │    │ • Video Links   │
│ • Usage Metrics │    │ • Progress Notif │    │ • Asset Upload  │    │ • Thumbnail Gen │
│ • System Health │    │ • System Alerts  │    │ • Metadata Edit │    │ • Channel Mgmt  │
└─────────────────┘    └──────────────────┘    └─────────────────┘    └─────────────────┘
```

## 🗄️ Data Storage Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                    🗄️ DATA STORAGE LAYER                                      │
│                              Firestore + Google Cloud Storage                                 │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘

┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  🗄️ FIRESTORE   │    │  📁 GOOGLE CLOUD │    │  🔐 SECURITY    │    │  📊 METADATA    │
│   DATABASE      │    │   STORAGE        │    │   LAYER         │    │   MANAGEMENT    │
│                 │    │                  │    │                 │    │                 │
│ • dev_jobs      │    │ • trivia-dev-    │    │ • Service       │    │ • Asset Index   │
│   - Job Status  │    │   assets bucket  │    │   Account Auth  │    │ • File Tracking │
│   - Progress    │    │ • File Storage   │    │ • IAM Roles     │    │ • Version Ctrl  │
│   - Metadata    │    │ • Asset Org      │    │ • API Keys      │    │ • Cleanup Jobs  │
│ • dev_assets    │    │ • Backup System  │    │ • Firestore     │    │ • Usage Stats   │
│   - File Info   │    │ • CDN Delivery   │    │   Rules         │    │ • Performance   │
│   - GCS Paths   │    │ • Lifecycle Mgmt │    │ • GCS Policies  │    │   Metrics       │
└─────────────────┘    └──────────────────┘    └─────────────────┘    └─────────────────┘
```

## 🔄 Complete Job Lifecycle

```
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                    🔄 JOB LIFECYCLE                                            │
│                              From CSV Upload to YouTube Video                                 │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘

📊 STAGE 1: INPUT & VALIDATION
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  📁 CSV UPLOAD  │───►│  ✅ VALIDATION   │───►│  🗄️ JOB CREATE  │───►│  📊 STATUS:     │
│                 │    │                  │    │                 │    │   PENDING       │
│ • File Check    │    │ • Format Check   │    │ • Firestore     │    │                 │
│ • Size Check    │    │ • Data Validate  │    │ • Metadata      │    │                 │
│ • Type Check    │    │ • Error Report   │    │ • Queue Entry   │    │                 │
└─────────────────┘    └──────────────────┘    └─────────────────┘    └─────────────────┘
                                        │
                                        ▼
📊 STAGE 2: AI CONTENT GENERATION
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  🤖 GEMINI API  │───►│  📝 CONTENT      │───►│  ✅ QUALITY     │───►│  📊 STATUS:     │
│                 │    │   GENERATION     │    │   CHECK         │    │   PROCESSING_TTS│
│ • Question Gen  │    │ • Question Text  │    │ • Content Rev   │    │                 │
│ • Answer Gen    │    │ • Answer Options │    │ • Error Handle  │    │                 │
│ • Option Gen    │    │ • Metadata       │    │ • Retry Logic   │    │                 │
└─────────────────┘    └──────────────────┘    └─────────────────┘    └─────────────────┘
                                        │
                                        ▼
📊 STAGE 3: TEXT-TO-SPEECH PROCESSING
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  🎤 TTS SERVICE │───►│  🔊 AUDIO        │───►│  💾 AUDIO       │───►│  📊 STATUS:     │
│                 │    │   GENERATION     │    │   STORAGE       │    │   READY_FOR_    │
│ • External API  │    │ • Voice Synthesis│    │ • GCS Upload    │    │   RENDER        │
│ • Progress Track│    │ • Quality Check  │    │ • Metadata      │    │                 │
│ • Checkpoint    │    │ • Error Handle   │    │ • File Org      │    │                 │
└─────────────────┘    └──────────────────┘    └─────────────────┘    └─────────────────┘
                                        │
                                        ▼
📊 STAGE 4: VIDEO RENDERING
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  🎨 TEMPLATE    │───►│  🎥 VIDEO        │───►│  💾 VIDEO       │───►│  📊 STATUS:     │
│   ASSEMBLY      │    │   RENDERING      │    │   STORAGE       │    │   PROCESSING_   │
│                 │    │                  │    │                 │    │   RENDER        │
│ • Layout Coord  │    │ • Video Compose  │    │ • GCS Upload    │    │                 │
│ • Asset Coord   │    │ • Audio Sync     │    │ • Thumbnail Gen │    │                 │
│ • Template App  │    │ • Quality Check  │    │ • Metadata      │    │                 │
└─────────────────┘    └──────────────────┘    └─────────────────┘    └─────────────────┘
                                        │
                                        ▼
📊 STAGE 5: YOUTUBE UPLOAD
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  📺 YOUTUBE     │───►│  🔐 AUTHENTICATE │───►│  📤 UPLOAD      │───►│  📊 STATUS:     │
│   PREPARATION   │    │                  │    │                 │    │   COMPLETED     │
│                 │    │ • OAuth Token    │    │ • Video Upload  │    │                 │
│ • Metadata Prep │    │ • API Access     │    │ • Thumbnail     │    │                 │
│ • Thumbnail Gen │    │ • Permission     │    │ • Description   │    │                 │
│ • Description   │    │ • Rate Limit     │    │ • Title/Tags    │    │                 │
└─────────────────┘    └──────────────────┘    └─────────────────┘    └─────────────────┘
```

## 🔧 Technical Stack & Dependencies

```
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                    🔧 TECHNICAL STACK                                          │
│                              Complete Technology Architecture                                  │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘

┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  🐍 BACKEND     │    │  🌐 FRONTEND     │    │  ☁️ CLOUD        │    │  🔌 EXTERNAL    │
│   STACK         │    │   STACK          │    │   SERVICES      │    │   SERVICES      │
│                 │    │                  │    │                 │    │                 │
│ • Python 3.8+   │    │ • HTML5/CSS3     │    │ • Google Cloud  │    │ • Gemini API    │
│ • Flask         │    │ • JavaScript ES6 │    │ • Firestore     │    │ • TTS Service   │
│ • Socket.IO     │    │ • Socket.IO      │    │ • GCS Storage   │    │ • YouTube API   │
│ • Requests      │    │ • Fetch API      │    │ • IAM Auth      │    │ • OAuth 2.0     │
└─────────────────┘    └──────────────────┘    └─────────────────┘    └─────────────────┘
                                │                        │                        │
                                ▼                        ▼                        ▼
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  🗄️ DATABASE    │    │  📁 STORAGE      │    │  🔐 SECURITY    │    │  📊 MONITORING  │
│   LAYER         │    │   LAYER          │    │   LAYER         │    │   LAYER         │
│                 │    │                  │    │                 │    │                 │
│ • Firestore     │    │ • GCS Buckets    │    │ • Service       │    │ • Real-time     │
│ • NoSQL         │    │ • File Org       │    │   Accounts      │    │   Updates       │
│ • Real-time     │    │ • CDN Delivery   │    │ • IAM Roles     │    │ • Progress      │
│ • Indexing      │    │ • Lifecycle      │    │ • API Keys      │    │   Tracking      │
└─────────────────┘    └──────────────────┘    └─────────────────┘    └─────────────────┘
```

## 📁 File Structure

```
trivia-automation-system/
├── core/                          # Core pipeline components
│   ├── pipeline_manager.py        # Job processing manager (FIFO)
│   ├── template_manager.py        # Video template management
│   ├── unified_trivia_pipeline.py # Main video generation pipeline
│   ├── youtube_upload_service.py  # YouTube upload service
│   └── job_stage_contract.py      # Job stage definitions
├── interface/                     # Web interface
│   ├── control_center.py          # Flask API server (Port 6001)
│   └── static/                    # Frontend assets
│       ├── css/                   # Stylesheets
│       │   ├── design_tokens.css  # Design system tokens
│       │   └── components.css     # Component styles
│       └── js/                    # JavaScript files
│           ├── dashboard_new.js   # Main dashboard logic
│           └── assets.js          # Asset management
├── templates/                     # HTML templates
│   └── dashboard_new.html         # Main dashboard
├── automations/                   # Automation modules
│   ├── __init__.py               # Package initialization
│   └── canonical_path_builder.py # Path building utilities
├── secrets/                       # Credentials (not in git)
│   ├── service-account-key.json  # Google Cloud service account
│   ├── youtube_oauth_client.json # YouTube OAuth credentials
│   └── youtube_tokens.json       # YouTube access tokens
├── config/                        # Configuration files
│   ├── firebase.json              # Firebase configuration
│   ├── firestore.rules            # Firestore security rules
│   └── firestore.indexes.json     # Firestore indexes
├── README.md                      # Project documentation
├── ARCHITECTURE.md                # This architecture document
└── requirements.txt               # Python dependencies
```

## 🚀 Key Features

### Modular Design
- **Component Separation**: Each system component is clearly separated and independently maintainable
- **Debugging Support**: Easy to debug individual components without affecting the whole pipeline
- **Seamless Integration**: New processes can be inserted without breaking existing functionality

### FIFO Processing
- **Single Job Processing**: Only one job processes at a time (Baseline 2 requirement)
- **Oldest First**: Jobs are processed in the order they were created
- **Timeout Handling**: TTS jobs timeout after 30 minutes with failure handling
- **Checkpoint System**: Jobs can resume from TTS checkpoints with progress updates

### Real-time Updates
- **Live Dashboard**: Real-time job status updates via Socket.IO
- **Progress Tracking**: Detailed progress updates for each processing stage
- **Error Handling**: Comprehensive error reporting and retry mechanisms

### Cloud Integration
- **Google Cloud Storage**: Scalable file storage for videos and assets
- **Firestore Database**: Real-time NoSQL database for job metadata
- **YouTube API**: Direct integration for video uploads and management

## 🔧 Configuration

### Environment Variables
- `ENVIRONMENT`: Set to "dev" or "prod" (default: "dev")
- `GOOGLE_APPLICATION_CREDENTIALS`: Path to service account key
- `GEMINI_API_KEY`: Google Gemini API key for content generation
- `PORT`: Control Center port (default: 6001)

### Firestore Collections
- `dev_jobs`: Job data and status (development)
- `prod_jobs`: Job data and status (production)
- `dev_assets`: Asset metadata (development)
- `prod_assets`: Asset metadata (production)
- `dev_channels`: Channel configurations
- `dev_templates`: Video templates

### Google Cloud Storage
- Bucket naming: `trivia-{environment}-assets`
- Automatic asset organization by job ID
- Lifecycle management for cleanup

## 📊 Job Status Flow

```
pending → processing_tts → ready_for_render → processing_render → completed
    ↓           ↓                ↓                ↓
  failed    failed          failed          failed
    ↓           ↓                ↓                ↓
  aborted   aborted         aborted         aborted
```

## 🔍 Monitoring & Debugging

### Log Locations
- Control Center: `/tmp/control_center.log`
- Pipeline Manager: `/tmp/pipeline_manager.log`
- YouTube Upload: `/tmp/youtube_upload.log`

### Health Checks
- `/health/ready`: System readiness check
- `/api/stats`: System statistics
- Real-time job monitoring via dashboard

### Error Handling
- Comprehensive error logging
- Automatic retry mechanisms
- Checkpoint recovery system
- User-friendly error messages

---

*This architecture document provides a complete overview of the Trivia Video Automation System. For implementation details, see the individual component files and the main README.md.*
