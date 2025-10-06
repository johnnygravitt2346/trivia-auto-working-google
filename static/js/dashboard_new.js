// Trivia Video Studio - New Dashboard JavaScript
// Apple-inspired, production-ready interface with accessibility features

// Global state
let jobs = [];
let assets = [];
let templates = [];
let channels = [];
let pipelineRunning = false;
let pipelineSplitEnabled = false;
let pipelineStatus = null;
let currentChannel = null;
let currentTemplate = null;

// Accessibility utilities
function announceToScreenReader(message) {
    const ariaLive = document.getElementById('aria-live');
    if (ariaLive) {
        ariaLive.textContent = message;
        // Clear after announcement
        setTimeout(() => {
            ariaLive.textContent = '';
        }, 1000);
    }
}

function setFocusRing(element) {
    element.classList.add('focus-visible');
    element.addEventListener('blur', () => {
        element.classList.remove('focus-visible');
    });
}

function toggleYouTubeUploadOption() {
    const outputMode = document.querySelector('input[name="outputMode"]:checked').value;
    const youtubeUploadOption = document.getElementById('youtubeUploadOption');
    
    console.log('🔍 YouTube toggle - Output mode:', outputMode);
    console.log('🔍 YouTube toggle - Element found:', youtubeUploadOption);
    
    if (outputMode === 'test') {
        // Show YouTube toggle in test mode, but let upload mode control visibility
        console.log('✅ Test mode - letting upload mode toggle control YouTube visibility');
        
        // Call the upload mode toggle to show/hide appropriately
        toggleUploadModeYouTube();
    } else {
        // Hide YouTube toggle in production mode
        youtubeUploadOption.style.display = 'none';
        // Uncheck the YouTube upload options when switching to production
        document.getElementById('youtubeUploadTest').checked = false;
        console.log('✅ YouTube upload options hidden for production mode');
    }
}

function toggleUploadModeYouTube() {
    // This function controls which YouTube toggle is visible based on upload mode
    const uploadMode = document.querySelector('input[name="uploadMode"]:checked').value;
    const youtubeUploadOption = document.getElementById('youtubeUploadOption');
    
    console.log('🔍 Upload mode toggle - Mode:', uploadMode);
    console.log('🔍 YouTube upload option element:', youtubeUploadOption);
    
    if (uploadMode === 'bulk') {
        // Hide YouTube toggle for bulk mode (CSV + Manifest has its own YouTube option)
        if (youtubeUploadOption) {
            youtubeUploadOption.style.display = 'none';
            console.log('✅ Hiding YouTube toggle for bulk mode (using CSV + Manifest option)');
        } else {
            console.error('❌ YouTube upload option element not found!');
        }
    } else {
        // Show YouTube toggle for single mode
        if (youtubeUploadOption) {
            youtubeUploadOption.style.display = 'block';
            console.log('✅ Showing YouTube toggle for single mode');
        } else {
            console.error('❌ YouTube upload option element not found!');
        }
    }
}


// Thumbnail upload functionality
let uploadedThumbnails = [];

function initializeThumbnailUpload() {
    const thumbnailUploadArea = document.getElementById('thumbnailUploadArea');
    const thumbnailFiles = document.getElementById('thumbnailFiles');
    
    if (!thumbnailUploadArea || !thumbnailFiles) return;
    
    // Click to upload
    thumbnailUploadArea.addEventListener('click', () => {
        thumbnailFiles.click();
    });
    
    // File selection
    thumbnailFiles.addEventListener('change', handleThumbnailFiles);
    
    // Drag and drop
    thumbnailUploadArea.addEventListener('dragover', (e) => {
        e.preventDefault();
        thumbnailUploadArea.classList.add('dragover');
    });
    
    thumbnailUploadArea.addEventListener('dragleave', () => {
        thumbnailUploadArea.classList.remove('dragover');
    });
    
    thumbnailUploadArea.addEventListener('drop', (e) => {
        e.preventDefault();
        thumbnailUploadArea.classList.remove('dragover');
        const files = Array.from(e.dataTransfer.files).filter(file => 
            file.type.startsWith('image/')
        );
        handleThumbnailFiles({ target: { files: files } });
    });
}

function handleThumbnailFiles(event) {
    const files = Array.from(event.target.files);
    const validFiles = files.filter(file => file.type.startsWith('image/'));
    
    if (validFiles.length === 0) {
        alert('Please select valid image files (JPG, PNG, WebP)');
        return;
    }
    
    // Add new files to existing thumbnails
    uploadedThumbnails.push(...validFiles);
    updateThumbnailPreview();
    
    console.log(`✅ Added ${validFiles.length} thumbnail(s). Total: ${uploadedThumbnails.length}`);
}

function updateThumbnailPreview() {
    const thumbnailPreview = document.getElementById('thumbnailPreview');
    const thumbnailList = document.getElementById('thumbnailList');
    
    if (uploadedThumbnails.length === 0) {
        thumbnailPreview.style.display = 'none';
        return;
    }
    
    thumbnailPreview.style.display = 'block';
    thumbnailList.innerHTML = '';
    
    uploadedThumbnails.forEach((file, index) => {
        const thumbnailItem = document.createElement('div');
        thumbnailItem.className = 'thumbnail-item';
        
        const reader = new FileReader();
        reader.onload = (e) => {
            thumbnailItem.innerHTML = `
                <button class="thumbnail-remove" onclick="removeThumbnail(${index})" title="Remove">
                    <i class="fas fa-times"></i>
                </button>
                <img src="${e.target.result}" alt="Thumbnail ${index + 1}" class="thumbnail-preview">
                <div class="thumbnail-info">
                    <div class="thumbnail-index">#${index + 1}</div>
                    <div class="thumbnail-name">${file.name}</div>
                </div>
            `;
        };
        reader.readAsDataURL(file);
        
        thumbnailList.appendChild(thumbnailItem);
    });
}

function removeThumbnail(index) {
    uploadedThumbnails.splice(index, 1);
    updateThumbnailPreview();
    console.log(`🗑️ Removed thumbnail at index ${index}. Remaining: ${uploadedThumbnails.length}`);
}

function clearThumbnails() {
    uploadedThumbnails = [];
    updateThumbnailPreview();
    console.log('🧹 Cleared all thumbnails');
}

// Manifest Thumbnail Upload Variables
let uploadedManifestThumbnails = [];

// Manifest Thumbnail Upload Functions
function toggleManifestThumbnailUpload() {
    const youtubeUploadEnabled = document.getElementById('youtubeUploadManifest').checked;
    const thumbnailSection = document.getElementById('manifestThumbnailUploadOption');
    
    console.log('🎬 Manifest YouTube upload toggled:', youtubeUploadEnabled);
    
    if (youtubeUploadEnabled) {
        thumbnailSection.style.display = 'block';
        initializeManifestThumbnailUpload();
    } else {
        thumbnailSection.style.display = 'none';
        clearManifestThumbnails();
    }
}

function initializeManifestThumbnailUpload() {
    const uploadArea = document.getElementById('manifestThumbnailUploadArea');
    const fileInput = document.getElementById('manifestThumbnailFiles');
    
    // Click to upload
    uploadArea.addEventListener('click', () => {
        fileInput.click();
    });
    
    // File selection
    fileInput.addEventListener('change', (e) => {
        handleManifestThumbnailFiles(e.target.files);
    });
    
    // Drag and drop
    uploadArea.addEventListener('dragover', (e) => {
        e.preventDefault();
        uploadArea.classList.add('drag-over');
    });
    
    uploadArea.addEventListener('dragleave', () => {
        uploadArea.classList.remove('drag-over');
    });
    
    uploadArea.addEventListener('drop', (e) => {
        e.preventDefault();
        uploadArea.classList.remove('drag-over');
        handleManifestThumbnailFiles(e.dataTransfer.files);
    });
}

function handleManifestThumbnailFiles(files) {
    console.log('📸 Manifest thumbnail files selected:', files.length);
    
    Array.from(files).forEach(file => {
        if (file.type.startsWith('image/')) {
            uploadedManifestThumbnails.push(file);
        }
    });
    
    updateManifestThumbnailPreview();
    console.log(`📸 Total manifest thumbnails: ${uploadedManifestThumbnails.length}`);
}

function updateManifestThumbnailPreview() {
    const preview = document.getElementById('manifestThumbnailPreview');
    const list = document.getElementById('manifestThumbnailList');
    
    if (uploadedManifestThumbnails.length === 0) {
        preview.style.display = 'none';
        return;
    }
    
    preview.style.display = 'block';
    list.innerHTML = '';
    
    uploadedManifestThumbnails.forEach((file, index) => {
        const item = document.createElement('div');
        item.className = 'thumbnail-item';
        item.innerHTML = `
            <div class="thumbnail-info">
                <span class="thumbnail-index">${index + 1}</span>
                <span class="thumbnail-name">${file.name}</span>
                <span class="thumbnail-size">(${(file.size / 1024).toFixed(1)} KB)</span>
            </div>
            <button type="button" class="btn btn-sm btn-outline-danger" onclick="removeManifestThumbnail(${index})">
                <i class="fas fa-times"></i>
            </button>
        `;
        list.appendChild(item);
    });
}

function removeManifestThumbnail(index) {
    uploadedManifestThumbnails.splice(index, 1);
    updateManifestThumbnailPreview();
    console.log(`🗑️ Removed manifest thumbnail at index ${index}. Remaining: ${uploadedManifestThumbnails.length}`);
}

function clearManifestThumbnails() {
    uploadedManifestThumbnails = [];
    updateManifestThumbnailPreview();
    console.log('🧹 Cleared all manifest thumbnails');
}

// Initialize thumbnail upload when page loads
document.addEventListener('DOMContentLoaded', () => {
    initializeThumbnailUpload();
});

// Initialize Socket.IO
const socket = io();

// Check system readiness and placeholder mode
async function checkSystemReadiness() {
    try {
        const response = await fetch('/health/ready');
        const data = await response.json();
        
        // Do not surface placeholder mode in production UI
        const badge = document.getElementById('placeholder-mode-badge');
        if (badge) {
            badge.style.display = 'none';
        }
        
        if (data.warnings && data.warnings.length > 0) {
            console.log('⚠️ System warnings:', data.warnings);
            data.warnings.forEach(warning => {
                announceToScreenReader(`Warning: ${warning}`);
            });
        }
        
        console.log('✅ System readiness check complete');
    } catch (error) {
        console.error('❌ System readiness check failed:', error);
        announceToScreenReader('System readiness check failed');
    }
}

// Initialize dashboard when DOM is loaded
document.addEventListener('DOMContentLoaded', async function() {
    console.log('🎬 Trivia Video Studio initializing...');
    
    try {
        await checkSystemReadiness();
        
        const savedChannelId = localStorage.getItem('selectedChannelId');
        const savedTemplateId = localStorage.getItem('selectedTemplateId');
        
        await Promise.all([
            loadJobs(),
            loadChannels(savedChannelId),
            loadTemplates(savedTemplateId),
            loadAssets(),
            checkPipelineStatus()
        ]);
        
        // Setup event listeners
        setupEventListeners();
        
        // Setup Socket.IO
        setupSocketIO();
        
        // Update UI
        updateDashboard();
        
        // Initialize YouTube upload toggle (with delay to ensure DOM is ready)
        setTimeout(() => {
            console.log('🚀 Initializing YouTube upload toggles...');
            toggleYouTubeUploadOption();
            toggleUploadModeYouTube();
            console.log('✅ YouTube upload toggles initialized');
        }, 100);
        
        console.log('✅ Dashboard initialized successfully');
    
    // Start real-time job updates
    startJobUpdates();
        
    } catch (error) {
        console.error('❌ Dashboard initialization failed:', error);
        showNotification('Failed to initialize dashboard', 'error');
    }
});

// Cleanup polling intervals when page is unloaded
window.addEventListener('beforeunload', function() {
    if (window.assetCountInterval) {
        clearInterval(window.assetCountInterval);
    }
});

// Fallback initialization for YouTube toggle
window.addEventListener('load', function() {
    setTimeout(() => {
        console.log('🔄 Fallback initialization for YouTube toggles...');
        toggleYouTubeUploadOption();
        toggleUploadModeYouTube();
        console.log('✅ Fallback initialization complete');
    }, 200);
});

// Setup event listeners
function setupEventListeners() {
    // Channel selector
    const channelSelector = document.getElementById('channelSelector');
    if (channelSelector) {
        channelSelector.addEventListener('change', onChannelChange);
    }
    
    // Template selector
    const templateSelector = document.getElementById('templateSelector');
    if (templateSelector) {
        templateSelector.addEventListener('change', onTemplateChange);
    }

    const splitToggleButton = document.querySelector('[data-action="toggle-split"]');
    if (splitToggleButton) {
        splitToggleButton.addEventListener('click', toggleSplitPipeline);
    }
    
    // Content source radio buttons
    const contentSources = document.querySelectorAll('input[name="contentSource"]');
    contentSources.forEach(radio => {
        radio.addEventListener('change', onContentSourceChange);
    });
    
    // Initialize CSV section visibility
    const selectedSource = document.querySelector('input[name="contentSource"]:checked');
    if (selectedSource) {
        onContentSourceChange({ target: selectedSource });
    }
}

// Setup Socket.IO
function setupSocketIO() {
    socket.on('job_update', (data) => {
        console.log('📊 Job update received:', data);
        updateJobInList(data);
        updateStats();
        
        // Announce job status change to screen readers
        if (data.status) {
            announceToScreenReader(`Job ${data.id || 'unknown'} status updated to ${data.status}`);
        }
    });
    
    socket.on('pipeline_status', (data) => {
        console.log('🔄 Pipeline status update:', data);
        updatePipelineStatus(data);
        
        // Announce pipeline status change
        if (data.status) {
            announceToScreenReader(`Pipeline ${data.status}`);
        }
    });
    
    socket.on('system_error', (data) => {
        console.error('❌ System error:', data);
        showNotification(data.message || 'System error occurred', 'error');
        
        // Announce error to screen readers
        announceToScreenReader(`System error: ${data.message || 'Unknown error occurred'}`);
    });
}

// Load jobs from API
async function loadJobs() {
    try {
        console.log('📋 Loading jobs...');
        const response = await fetch('/api/jobs?grouped=true');
        console.log('📋 Jobs response status:', response.status);
        
        const data = await response.json();
        console.log('📋 Jobs response data:', data);
        
        if (data.jobs) {
            jobs = data.jobs || [];
            console.log(`📋 Loaded ${jobs.length} jobs:`, jobs);
            
            // If we have summary data, also load individual jobs for detailed view
            if (jobs.length === 1 && jobs[0].status === 'summary') {
                await loadIndividualJobs();
            }
            
            renderJobs();
            updateStats();
        } else {
            console.error('❌ No jobs in response:', data);
            throw new Error(data.error || 'Failed to load jobs');
        }
    } catch (error) {
        console.error('❌ Failed to load jobs:', error);
        showNotification('Failed to load jobs: ' + error.message, 'error');
    }
}

// Load individual jobs for detailed view
async function loadIndividualJobs() {
    try {
        console.log('📋 Loading individual jobs...');
        const response = await fetch('/api/jobs?limit=50');
        const data = await response.json();
        
        if (data.jobs) {
            // Add individual jobs to the jobs array
            jobs.push(...data.jobs);
            console.log(`📋 Added ${data.jobs.length} individual jobs`);
        }
    } catch (error) {
        console.error('❌ Failed to load individual jobs:', error);
    }
}

    // Load channels from API
    async function loadChannels(savedChannelId = null) {
        try {
            const response = await fetch('/api/channels');
            const data = await response.json();
            
            if (Array.isArray(data)) {
                channels = data || [];
                renderChannelSelector(savedChannelId);
            } else if (data.channels && Array.isArray(data.channels)) {
                // Fallback for old response format
                channels = data.channels || [];
                renderChannelSelector(savedChannelId);
            } else {
                throw new Error(data.error || 'Failed to load channels');
            }
        } catch (error) {
            console.error('Failed to load channels:', error);
            showNotification('Failed to load channels', 'error');
        }
    }

// Load templates from API
async function loadTemplates(savedTemplateId = null) {
    try {
        const response = await fetch('/api/templates');
        const data = await response.json();
        
        if (Array.isArray(data)) {
            templates = data || [];
            renderTemplateSelector(savedTemplateId);
        } else if (data.templates && Array.isArray(data.templates)) {
            templates = data.templates || [];
            renderTemplateSelector(savedTemplateId);
        } else {
            throw new Error(data.error || 'Failed to load templates');
        }
    } catch (error) {
        console.error('Failed to load templates:', error);
        showNotification('Failed to load templates', 'error');
    }
}

// Render template selector
function renderTemplateSelector(savedTemplateId = null) {
    const selector = document.getElementById('templateSelector');
    if (!selector) {
        console.error('Template selector element not found!');
        return;
    }
    
    selector.innerHTML = '<option value="">Select a template...</option>';
    
    templates.forEach(template => {
        const option = document.createElement('option');
        option.value = template.id;
        option.textContent = template.name;
        selector.appendChild(option);
    });
    
    if (!currentTemplate && savedTemplateId) {
        const savedTemplate = templates.find(template => template.id === savedTemplateId);
        if (savedTemplate) {
            currentTemplate = savedTemplate;
            selector.value = savedTemplate.id;
        }
    }
    
    if (!currentTemplate && templates.length > 0) {
        const preferredTemplate = templates.find(template => template.is_default) || templates[0];
        selector.value = preferredTemplate.id;
        currentTemplate = preferredTemplate;
    }
}

// Check pipeline status
async function checkPipelineStatus() {
    try {
        const response = await fetch('/api/pipeline/status');
        const data = await response.json();
        
        if (data) {
            updatePipelineStatus(data);
            if (data.queues) {
                updateQueueSnapshot(data.queues);
            }
        }
    } catch (error) {
        console.error('Failed to check pipeline status:', error);
    }
}

    // Render channel selector
    function renderChannelSelector(savedChannelId = null) {
        const selector = document.getElementById('channelSelector');
        if (!selector) {
            console.error('Channel selector element not found!');
            return;
        }
        
        selector.innerHTML = '<option value="">Select a channel...</option>';
        
        channels.forEach(channel => {
            const option = document.createElement('option');
            option.value = channel.id;
            option.textContent = channel.title || channel.name || channel.id;
            selector.appendChild(option);
        });
        
        if (!currentChannel) {
            if (savedChannelId) {
                const savedChannel = channels.find(channel => channel.id === savedChannelId);
                if (savedChannel) {
                    currentChannel = savedChannel;
                    selector.value = savedChannel.id;
                }
            }
        }
        
        if (!currentChannel && channels.length > 0) {
            const preferredChannel = channels.find(channel => channel.is_default) || channels[0];
            currentChannel = preferredChannel;
            selector.value = preferredChannel.id;
        }
        
        if (selector.value) {
            onChannelChange({ target: selector });
        }
    }

// Render jobs list
function renderJobs() {
    const container = document.getElementById('jobsContainer');
    if (!container) return;
    
    if (jobs.length === 0) {
        container.innerHTML = `
            <div class="text-center text-muted py-4">
                <i class="fas fa-video fa-2x mb-3"></i>
                <p>No jobs yet. Start generating videos!</p>
            </div>
        `;
        return;
    }
    
    // Check if we have grouped summary data
    const summaryJob = jobs.find(job => job.status === 'summary');
    const individualJobs = jobs.filter(job => job.status !== 'summary');
    
    let html = '';
    
    // Render summary if available
    if (summaryJob) {
        html += `
            <div class="job-summary">
                <div class="summary-stats">
                    <div class="stat-item">
                        <span class="stat-number">${summaryJob.total_jobs}</span>
                        <span class="stat-label">Total Jobs</span>
                    </div>
                    <div class="stat-item">
                        <span class="stat-number">${summaryJob.completed_jobs}</span>
                        <span class="stat-label">Completed</span>
                    </div>
                    <div class="stat-item">
                        <span class="stat-number">${summaryJob.processing_jobs}</span>
                        <span class="stat-label">Processing</span>
                    </div>
                    <div class="stat-item">
                        <span class="stat-number">${summaryJob.pending_jobs}</span>
                        <span class="stat-label">Pending</span>
                    </div>
                    <div class="stat-item">
                        <span class="stat-number">${summaryJob.failed_jobs}</span>
                        <span class="stat-label">Failed</span>
                    </div>
                </div>
                <div class="summary-message">
                    <i class="fas fa-info-circle"></i>
                    <span>System is processing ${summaryJob.processing_jobs} jobs with ${summaryJob.pending_jobs} pending</span>
                </div>
            </div>
        `;
    }
    
    // Render individual jobs
    if (individualJobs.length > 0) {
        html += individualJobs.map(item => {
            // Check if this is a job group (bulk or individual)
            if (item.jobs && Array.isArray(item.jobs)) {
                return renderBulkJobGroup(item);
            } else {
                return renderIndividualJob(item);
            }
        }).join('');
    }
    
    container.innerHTML = html;
}

function renderBulkJobGroup(group) {
    // Handle both bulk uploads and batch groups
    const groupId = group.batch_id || group.bulk_upload_id || `group_${group.jobs[0]?.id || 'unknown'}`;
    const isExpanded = window.expandedGroups && window.expandedGroups[groupId];
    const isBatchGroup = !!group.batch_id;
    
    return `
        <div class="bulk-job-group" data-group-id="${groupId}">
            <div class="bulk-job-header" onclick="toggleBulkGroup('${groupId}')">
                <div class="d-flex align-items-center justify-content-between">
                    <div class="d-flex align-items-center gap-3">
                        <i class="fas fa-chevron-${isExpanded ? 'down' : 'right'} group-toggle"></i>
                        <div>
                            <div class="bulk-job-title">${group.group_title}</div>
                            <div class="bulk-job-meta">
                                ${group.total_jobs} videos • 
                                ${group.completed_jobs} completed • 
                                ${group.failed_jobs} failed • 
                                ${group.processing_jobs} processing • 
                                ${group.pending_jobs} pending
                                ${group.aborted_jobs ? ` • ${group.aborted_jobs} aborted` : ''}
                            </div>
                        </div>
                    </div>
                    <div class="d-flex align-items-center gap-2">
                        <span class="job-status status-${group.status}">${group.status}</span>
                        <span class="bulk-job-date">${new Date(group.created_at).toLocaleString()}</span>
                        ${(group.status === 'pending' || group.status === 'processing' || group.status === 'failed') ? `
                            <button class="btn-apple btn-apple-danger btn-sm" onclick="event.stopPropagation(); abortBulkJob('${groupId}')" title="Abort all remaining jobs in this batch">
                                <i class="fas fa-stop"></i> Abort Batch
                            </button>
                        ` : ''}
                        ${(group.status === 'aborted' || group.failed_jobs > 0) ? `
                            <button class="btn-apple btn-apple-warning btn-sm" onclick="event.stopPropagation(); retryBulkJob('${groupId}')" title="Retry all failed/aborted jobs in this batch">
                                <i class="fas fa-redo"></i> Retry Batch
                            </button>
                        ` : ''}
                    </div>
                </div>
            </div>
            <div class="bulk-job-content" id="${groupId}" style="display: ${isExpanded ? 'block' : 'none'};">
                ${group.jobs.map(job => renderIndividualJob(job, true)).join('')}
            </div>
        </div>
    `;
}

function renderIndividualJob(job, isSubJob = false) {
    const jobTitle = job.video_title || job.csv_filename?.replace('.csv', '') || job.id;
    const jobClass = isSubJob ? 'sub-job-item' : 'job-item';
    
    return `
        <div class="${jobClass}">
            <div class="job-info">
                <div class="job-title">${jobTitle}</div>
                <div class="job-meta">
                    ${getChannelName(job.channel_id, job) || 'No Channel'} • 
                    ${getTemplateName(job.template_id) || 'No Template'} • 
                    ${new Date(job.created_at).toLocaleString()}
                </div>
                ${job.progress !== undefined ? `
                    <div class="progress-apple mt-2">
                        <div class="progress-bar-apple" style="width: ${job.progress}%"></div>
                    </div>
                ` : ''}
            </div>
            <div class="d-flex align-items-center gap-2">
                <span class="job-status status-${job.status}">${job.status}</span>
                ${job.status === 'completed' && job.output?.video_url ? `
                    <button class="btn-apple btn-apple-primary" onclick="viewVideo('${job.output.video_url}', '${job.id}')">
                        <i class="fas fa-play"></i>
                    </button>
                ` : ''}
                ${job.status === 'completed' && job.tts_artifacts && job.tts_artifacts.question_audio_uris ? `
                    <button class="btn-apple btn-apple-success" onclick="fastRerenderJob('${job.id}')" title="Fast re-render (skip TTS, use existing audio)">
                        <i class="fas fa-bolt"></i>
                    </button>
                ` : ''}
                ${['pending', 'failed'].includes(job.status) ? `
                    <button class="btn-apple btn-apple-warning" onclick="retryJob('${job.id}')">
                        <i class="fas fa-redo"></i>
                    </button>
                ` : ''}
                ${job.status === 'aborted' ? `
                    <button class="btn-apple btn-apple-warning" onclick="restartJob('${job.id}')" title="Restart aborted job">
                        <i class="fas fa-sync"></i>
                    </button>
                ` : ''}
                <button class="btn-apple btn-apple-danger" onclick="abortJob('${job.id}')" title="Abort this job">
                    <i class="fas fa-stop"></i>
                </button>
                <button class="btn-apple btn-apple-secondary" onclick="viewJobDetails('${job.id}')">
                    <i class="fas fa-info"></i>
                </button>
            </div>
        </div>
    `;
}

function toggleBulkGroup(groupId) {
    if (!window.expandedGroups) {
        window.expandedGroups = {};
    }
    
    window.expandedGroups[groupId] = !window.expandedGroups[groupId];
    
    const content = document.getElementById(groupId);  // Fixed: was looking for group_${groupId}
    const toggle = document.querySelector(`[data-group-id="${groupId}"] .group-toggle`);
    
    if (content && toggle) {
        content.style.display = window.expandedGroups[groupId] ? 'block' : 'none';
        toggle.className = `fas fa-chevron-${window.expandedGroups[groupId] ? 'down' : 'right'} group-toggle`;
    } else {
        console.error('Toggle failed - content or toggle not found', {groupId, content: !!content, toggle: !!toggle});
    }
}

async function abortBulkJob(groupId) {
    if (!confirm(`Are you sure you want to abort all jobs in this batch? This action cannot be undone.`)) {
        return;
    }
    
    try {
        showNotification('Aborting batch...', 'info');
        
        // groupId could be batch_id or bulk_upload_id
        const response = await fetch(`/api/abort-batch`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                batch_id: groupId,
                bulk_upload_id: groupId  // Support both for backward compatibility
            })
        });
        
        const data = await response.json();
        
        if (data.success) {
            showNotification(`Successfully aborted ${data.aborted_count} jobs in batch`, 'success');
            await loadJobs();
        } else {
            throw new Error(data.error || 'Failed to abort batch');
        }
        
    } catch (error) {
        console.error('Failed to abort batch:', error);
        showNotification(`Failed to abort batch: ${error.message}`, 'error');
    }
}

async function abortJob(jobId) {
    if (!confirm(`Abort job ${jobId}? This cannot be undone.`)) {
        return;
    }
    try {
        showNotification('Aborting job...', 'info');
        const res = await fetch(`/api/jobs/${jobId}/abort`, { method: 'POST' });
        const data = await res.json();
        if (!res.ok || !data.success) throw new Error(data.error || 'Abort failed');
        showNotification(`Job ${jobId} aborted`, 'success');
        await loadJobs();
    } catch (err) {
        console.error(err);
        showNotification(`Failed to abort job: ${err.message}`,'error');
    }
}

async function abortAllProcessing() {
    if (!confirm('Abort ALL processing/pending jobs?')) return;
    try {
        showNotification('Aborting all processing jobs...','info');
        const res = await fetch('/api/jobs/abort-all-processing', { method: 'POST' });
        const data = await res.json();
        if (!res.ok || !data.success) throw new Error(data.error || 'Abort failed');
        showNotification(`Aborted ${data.aborted_count} jobs`, 'success');
        await loadJobs();
    } catch (err) {
        console.error(err);
        showNotification(`Failed to abort all: ${err.message}`,'error');
    }
}

async function retryBulkJob(groupId) {
    if (!confirm(`Are you sure you want to retry all failed/aborted jobs in this batch?`)) {
        return;
    }
    
    try {
        showNotification('Retrying batch jobs...', 'info');
        
        const response = await fetch(`/api/retry-batch`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                batch_id: groupId,
                bulk_upload_id: groupId  // Support both for backward compatibility
            })
        });
        
        const data = await response.json();
        
        if (data.success) {
            showNotification(`Successfully reset ${data.retried_count} jobs to pending`, 'success');
            await loadJobs();
        } else {
            throw new Error(data.error || 'Failed to retry batch');
        }
        
    } catch (error) {
        console.error('Failed to retry batch:', error);
        showNotification(`Failed to retry batch: ${error.message}`, 'error');
    }
}

// Update stats
function updateStats() {
    let totalJobs, completedJobs, activeJobs;
    
    // Check if we have grouped data (single summary object with counts)
    if (jobs.length === 1 && jobs[0].total_jobs !== undefined) {
        // Use grouped summary data
        totalJobs = jobs[0].total_jobs || 0;
        completedJobs = jobs[0].completed_jobs || 0;
        activeJobs = (jobs[0].pending_jobs || 0) + (jobs[0].processing_jobs || 0);
    } else {
        // Use individual job counting (fallback)
        totalJobs = jobs.length;
        completedJobs = jobs.filter(job => job.status === 'completed').length;
        activeJobs = jobs.filter(job => ['pending', 'processing'].includes(job.status)).length;
    }
    
    const successRate = totalJobs > 0 ? Math.round((completedJobs / totalJobs) * 100) : 0;
    
    document.getElementById('totalJobs').textContent = totalJobs;
    document.getElementById('completedJobs').textContent = completedJobs;
    document.getElementById('activeJobs').textContent = activeJobs;
    document.getElementById('successRate').textContent = successRate + '%';
}

// Update pipeline status
function updatePipelineStatus(data) {
    pipelineRunning = data.running || false;
    const statusDot = document.getElementById('systemStatus');
    const statusText = document.getElementById('systemStatusText');
    
    pipelineSplitEnabled = Boolean(data.splitEnabled);

    if (pipelineRunning) {
        statusDot.classList.remove('stopped');
        statusText.textContent = pipelineSplitEnabled ? 'Pipeline Running (Split Workers)' : 'Pipeline Running';
    } else {
        statusDot.classList.add('stopped');
        statusText.textContent = pipelineSplitEnabled ? 'Pipeline Stopped (Split Workers)' : 'Pipeline Stopped';
    }

    const splitBadge = document.querySelector('[data-pipeline-split]');
    if (splitBadge) {
        splitBadge.textContent = pipelineSplitEnabled ? 'Split Workers Enabled' : 'Split Workers Disabled';
        splitBadge.classList.toggle('enabled', pipelineSplitEnabled);
        splitBadge.classList.toggle('disabled', !pipelineSplitEnabled);
    }

    const splitToggleButton = document.querySelector('[data-action="toggle-split"]');
    if (splitToggleButton) {
        splitToggleButton.disabled = !data.running;
        splitToggleButton.textContent = pipelineSplitEnabled ? 'Disable Split Workers' : 'Enable Split Workers';
    }
}

function updateQueueSnapshot(snapshot) {
    const pendingCountEl = document.querySelector('[data-queue-count="pending"]');
    const readyCountEl = document.querySelector('[data-queue-count="ready_for_render"]');
    const googleTtsCountEl = document.querySelector('[data-queue-count="pending_google_tts"]');
    const customTtsCountEl = document.querySelector('[data-queue-count="pending_custom_tts"]');
    const pendingAgeEl = document.querySelector('[data-queue-oldest="pending"]');
    const readyAgeEl = document.querySelector('[data-queue-oldest="ready_for_render"]');

    if (!snapshot || !snapshot.depths) return;

    if (pendingCountEl) {
        pendingCountEl.textContent = snapshot.depths.pending ?? 0;
    }
    if (googleTtsCountEl) {
        googleTtsCountEl.textContent = snapshot.depths.pending_google_tts ?? 0;
    }
    if (customTtsCountEl) {
        customTtsCountEl.textContent = snapshot.depths.pending_custom_tts ?? 0;
    }
    if (readyCountEl) {
        readyCountEl.textContent = snapshot.depths.ready_for_render ?? 0;
    }
    if (pendingAgeEl) {
        pendingAgeEl.textContent = snapshot.oldest?.pending ? timeSince(snapshot.oldest.pending) : '—';
    }
    if (readyAgeEl) {
        readyAgeEl.textContent = snapshot.oldest?.ready_for_render ? timeSince(snapshot.oldest.ready_for_render) : '—';
    }
}

function timeSince(isoString) {
    if (!isoString) return '—';
    const timestamp = new Date(isoString).getTime();
    if (Number.isNaN(timestamp)) return '—';
    const diffMs = Date.now() - timestamp;
    if (diffMs <= 0) return 'just now';
    const diffMinutes = Math.floor(diffMs / 60000);
    if (diffMinutes < 1) return 'seconds ago';
    if (diffMinutes < 60) return `${diffMinutes} min ago`;
    const diffHours = Math.floor(diffMinutes / 60);
    if (diffHours < 24) return `${diffHours} hr ago`;
    const diffDays = Math.floor(diffHours / 24);
    return `${diffDays} d ago`;
}

// Update job in list
function updateJobInList(jobData) {
    const jobIndex = jobs.findIndex(job => job.id === jobData.id);
    if (jobIndex !== -1) {
        jobs[jobIndex] = { ...jobs[jobIndex], ...jobData };
        renderJobs();
        updateStats();
    }
}

// Event handlers
async function onChannelChange(event) {
    const channelId = event.target.value;
    currentChannel = channels.find(channel => channel.id === channelId);
    if (currentChannel) {
        localStorage.setItem('selectedChannelId', currentChannel.id);
    } else {
        localStorage.removeItem('selectedChannelId');
    }
    
    // Clear any existing polling interval
    if (window.assetCountInterval) {
        clearInterval(window.assetCountInterval);
        window.assetCountInterval = null;
    }
    
    if (currentChannel) {
        // Fetch asset count for this channel
        await loadChannelAssetCount(channelId, currentChannel);
    } else {
        hideChannelInfo();
    }
}

function onTemplateChange(event) {
    const templateId = event.target.value;
    currentTemplate = templates.find(template => template.id === templateId);
    if (currentTemplate) {
        localStorage.setItem('selectedTemplateId', currentTemplate.id);
    } else {
        localStorage.removeItem('selectedTemplateId');
    }
}

function onContentSourceChange(event) {
    const source = event.target.value;
    console.log('Content source changed to:', source);
    
    // Show/hide CSV upload section based on selection
    const csvUploadSection = document.getElementById('csvUploadSection');
    if (csvUploadSection) {
        csvUploadSection.style.display = source === 'csv' ? 'block' : 'none';
        console.log('CSV upload section display:', csvUploadSection.style.display);
    } else {
        console.error('CSV upload section not found!');
    }
}

// Debug function to test CSV section
function testCSVSection() {
    const csvSection = document.getElementById('csvUploadSection');
    console.log('CSV section found:', !!csvSection);
    if (csvSection) {
        console.log('CSV section display:', csvSection.style.display);
        csvSection.style.display = 'block';
        console.log('CSV section now visible');
    }
}

// CSV Upload handling
function handleCSVUpload(event) {
    const file = event.target.files[0];
    if (!file) return;
    
    if (!file.name.toLowerCase().endsWith('.csv')) {
        showNotification('Please select a CSV file', 'error');
        return;
    }
    
    const reader = new FileReader();
    reader.onload = function(e) {
        try {
            const csvText = e.target.result;
            console.log('CSV text preview:', csvText.substring(0, 200));
            const questions = parseCSV(csvText);
            console.log('Parsed questions:', questions);
            
            if (questions.length === 0) {
                showNotification('No valid questions found in CSV', 'error');
                return;
            }
            
            // Store questions for mass generation
            window.csvQuestions = questions;
            showNotification(`Loaded ${questions.length} questions from CSV`, 'success');
            
        } catch (error) {
            console.error('CSV parsing error:', error);
            showNotification('Error parsing CSV file', 'error');
        }
    };
    
    reader.readAsText(file);
}

// Bulk CSV Upload handling
function handleBulkCSVUpload(event) {
    const files = Array.from(event.target.files);
    
    if (files.length === 0) {
        document.getElementById('bulkCsvPreview').style.display = 'none';
        return;
    }
    
    // Validate all files are CSV
    const invalidFiles = files.filter(file => !file.name.toLowerCase().endsWith('.csv'));
    if (invalidFiles.length > 0) {
        showNotification(`Please select only CSV files. Found ${invalidFiles.length} invalid files.`, 'error');
        return;
    }
    
    // Show preview
    document.getElementById('bulkCsvCount').textContent = files.length;
    document.getElementById('bulkCsvPreview').style.display = 'block';
    
    // Store files for bulk processing
    window.bulkCsvFiles = files;
    
    showNotification(`Selected ${files.length} CSV files for bulk upload`, 'success');
}

// Process bulk CSV uploads
async function processBulkCSVUpload() {
    if (!window.bulkCsvFiles || window.bulkCsvFiles.length === 0) {
        showNotification('No CSV files selected for bulk upload', 'error');
        return;
    }
    
    const files = window.bulkCsvFiles;
    const channelId = currentChannel?.id;
    const templateId = currentTemplate?.id;
    const youtubeUploadEnabled = false; // Bulk CSV mode doesn't support YouTube upload (use CSV + Manifest instead)
    
    if (!channelId || !templateId) {
        showNotification('Please select a channel and template first', 'error');
        return;
    }
    
    // Validate thumbnail count if YouTube upload is enabled
    if (youtubeUploadEnabled) {
        if (uploadedThumbnails.length === 0) {
            showNotification('Please upload thumbnails for YouTube videos', 'warning');
            return;
        }
        if (uploadedThumbnails.length !== files.length) {
            showNotification(`Thumbnail count (${uploadedThumbnails.length}) must match CSV count (${files.length})`, 'warning');
            return;
        }
    }
    
    try {
        showNotification(`Starting bulk upload of ${files.length} CSV files...`, 'info');
        
        // Generate a unique bulk upload ID for this batch
        const bulkUploadId = `bulk_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
        
        // Process each CSV file
        const uploadPromises = files.map(async (file, index) => {
            return new Promise((resolve, reject) => {
                const reader = new FileReader();
                reader.onload = async function(e) {
                    try {
                        const csvText = e.target.result;
                        const questions = parseCSV(csvText);
                        
                        console.log(`📊 CSV ${file.name}:`, {
                            csvLength: csvText.length,
                            questionsFound: questions.length,
                            firstQuestion: questions[0] || 'None'
                        });
                        
                        if (questions.length === 0) {
                            console.error(`❌ No valid questions found in ${file.name}`);
                            reject(new Error(`No valid questions found in ${file.name}`));
                            return;
                        }
                        
                        // Create job for this CSV
                        const jobData = {
                            channel_id: channelId,
                            template_id: templateId,
                            questions: questions,
                            music_enabled: document.getElementById('musicToggle').checked,
                            output_mode: document.querySelector('input[name="outputMode"]:checked').value,
                            youtube_upload_test: false, // Bulk CSV mode doesn't support YouTube upload (use CSV + Manifest instead)
                            csv_filename: file.name,
                            bulk_upload_index: index,
                            bulk_upload_id: bulkUploadId
                        };
                        
                        // Upload thumbnail if YouTube upload is enabled
                        if (youtubeUploadEnabled && uploadedThumbnails[index]) {
                            try {
                                const thumbnailFormData = new FormData();
                                thumbnailFormData.append('thumbnail', uploadedThumbnails[index]);
                                
                                const thumbnailResponse = await fetch('/api/upload-thumbnail', {
                                    method: 'POST',
                                    body: thumbnailFormData
                                });
                                
                                if (!thumbnailResponse.ok) {
                                    throw new Error(`Failed to upload thumbnail for ${file.name}`);
                                }
                                
                                const thumbnailResult = await thumbnailResponse.json();
                                jobData.thumbnail_url = thumbnailResult.thumbnail_url;
                                
                            } catch (error) {
                                reject(new Error(`Thumbnail upload failed for ${file.name}: ${error.message}`));
                                return;
                            }
                        }
                        
                        const response = await fetch('/api/create-job', {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/json'
                            },
                            body: JSON.stringify(jobData)
                        });
                        
                        if (!response.ok) {
                            throw new Error(`Failed to create job for ${file.name}`);
                        }
                        
                        const result = await response.json();
                        resolve({
                            filename: file.name,
                            jobId: result.job_id,
                            questionCount: questions.length
                        });
                        
                    } catch (error) {
                        reject(error);
                    }
                };
                
                reader.readAsText(file);
            });
        });
        
        // Wait for all uploads to complete
        const results = await Promise.allSettled(uploadPromises);
        
        // Process results
        const successful = results.filter(r => r.status === 'fulfilled').length;
        const failed = results.filter(r => r.status === 'rejected').length;
        
        if (successful > 0) {
            showNotification(`Successfully queued ${successful} CSV files for processing`, 'success');
            
            // Show detailed results
            const details = results.map((result, index) => {
                if (result.status === 'fulfilled') {
                    return `✅ ${result.value.filename}: ${result.value.questionCount} questions`;
                } else {
                    return `❌ ${files[index].name}: ${result.reason.message}`;
                }
            }).join('\n');
            
            console.log('Bulk upload results:', details);
        }
        
        if (failed > 0) {
            showNotification(`${failed} CSV files failed to upload`, 'error');
        }
        
        // Clear the files
        window.bulkCsvFiles = [];
        document.getElementById('bulkCsvFileInput').value = '';
        document.getElementById('bulkCsvPreview').style.display = 'none';
        
    } catch (error) {
        console.error('Bulk upload error:', error);
        showNotification(`Bulk upload failed: ${error.message}`, 'error');
    }
}

function parseCSV(csvText) {
    const lines = csvText.split('\n').filter(line => line.trim());
    if (lines.length < 2) return [];
    
    const headers = parseCSVLine(lines[0]).map(h => h.trim().toLowerCase());
    const headerMap = {};
    headers.forEach((header, index) => {
        if (header) {
            headerMap[header] = index;
        }
    });
    
    const requiredHeaders = ['question', 'answer_a', 'answer_b', 'answer_c', 'answer_d', 'correct_answer'];
    const missingHeaders = requiredHeaders.filter(h => !(h in headerMap));
    if (missingHeaders.length > 0) {
        console.error('❌ CSV missing required headers:', missingHeaders);
        return [];
    }
    
    const questions = [];
    
    for (let i = 1; i < lines.length; i++) {
        const values = parseCSVLine(lines[i]);
        if (!values || values.length === 0) continue;
        
        const question = {};
        requiredHeaders.forEach(header => {
            const idx = headerMap[header];
            const rawValue = idx !== undefined ? values[idx] || '' : '';
            question[header] = (rawValue || '').trim();
        });
        
        if (question.question && question.answer_a && question.answer_b && question.answer_c && question.answer_d) {
            questions.push(question);
        } else {
            console.warn(`⚠️ Skipping row ${i} due to missing required fields`, question);
        }
    }
    
    console.log(`📄 Parsed ${questions.length} questions from CSV (headers: ${headers.join(', ')})`);
    return questions;
}

function parseCSVLine(line) {
    const result = [];
    let current = '';
    let inQuotes = false;
    let i = 0;
    
    while (i < line.length) {
        const char = line[i];
        
        if (char === '"') {
            if (inQuotes && line[i + 1] === '"') {
                // Escaped quote - add one quote to result
                current += '"';
                i += 2; // Skip both quotes
            } else {
                // Toggle quote state
                inQuotes = !inQuotes;
                i++;
            }
        } else if (char === ',' && !inQuotes) {
            // End of field
            result.push(current.trim());
            current = '';
            i++;
        } else {
            // Regular character
            current += char;
            i++;
        }
    }
    
    // Add the last field
    result.push(current.trim());
    
    return result;
}

// Channel management
function createChannel() {
    // Open channel creation modal or redirect
    showNotification('Channel creation feature coming soon', 'info');
}

function manageAssets() {
    // Open polished asset upload page in new tab
    window.open('/asset-upload', '_blank');
}

function showChannelInfo(channel, assetCount = 0) {
    const channelInfo = document.getElementById('channelInfo');
    const channelName = document.getElementById('currentChannelName');
    const channelAssets = document.getElementById('currentChannelAssets');
    
    if (channelInfo && channelName && channelAssets) {
        channelName.textContent = channel.title || channel.name || channel.id;
        channelAssets.textContent = assetCount.toString();
        channelInfo.style.display = 'block';
    }
}

function hideChannelInfo() {
    const channelInfo = document.getElementById('channelInfo');
    if (channelInfo) {
        channelInfo.style.display = 'none';
    }
}

// Load asset count for a specific channel
async function loadChannelAssetCount(channelId, channel) {
    try {
        const response = await fetch(`/api/channels/${channelId}/assets`);
        const assets = await response.json();
        const assetCount = Array.isArray(assets) ? assets.length : 0;
        showChannelInfo(channel, assetCount);
        
        // Set up automatic polling to refresh asset count every 30 seconds
        if (window.assetCountInterval) {
            clearInterval(window.assetCountInterval);
        }
        
        window.assetCountInterval = setInterval(async () => {
            try {
                const refreshResponse = await fetch(`/api/channels/${channelId}/assets`);
                const refreshAssets = await refreshResponse.json();
                const refreshCount = Array.isArray(refreshAssets) ? refreshAssets.length : 0;
                
                // Only update if count changed
                const currentCountElement = document.getElementById('currentChannelAssets');
                if (currentCountElement && currentCountElement.textContent !== refreshCount.toString()) {
                    currentCountElement.textContent = refreshCount.toString();
                    console.log(`Asset count updated: ${refreshCount} assets`);
                }
            } catch (error) {
                console.error('Failed to refresh asset count:', error);
            }
        }, 60000); // Poll every 60 seconds (reduced from 30)
        
    } catch (error) {
        console.error('Failed to load asset count:', error);
        showChannelInfo(channel, 0);
    }
}

// Template management
function openTemplateStudio() {
    if (!currentTemplate) {
        showNotification('Please select a template first', 'warning');
        return;
    }
    // Open template studio with canvas editor
    showNotification('Opening Template Studio for ' + currentTemplate.name, 'info');
}

function createTemplate() {
    // Open template creation modal
    showNotification('Template creation feature coming soon', 'info');
}

// Pipeline management
async function startPipeline() {
    try {
        const response = await fetch('/api/pipeline/start', { method: 'POST' });
        const data = await response.json();
        
        if (data.success) {
            showNotification('Pipeline started successfully', 'success');
            checkPipelineStatus();
        } else {
            throw new Error(data.error || 'Failed to start pipeline');
        }
    } catch (error) {
        console.error('Failed to start pipeline:', error);
        showNotification('Failed to start pipeline', 'error');
    }
}

async function stopPipeline() {
    try {
        const response = await fetch('/api/pipeline/stop', { method: 'POST' });
        const data = await response.json();
        
        if (data.success) {
            showNotification('Pipeline stopped successfully', 'success');
            checkPipelineStatus();
        } else {
            throw new Error(data.error || 'Failed to stop pipeline');
        }
    } catch (error) {
        console.error('Failed to stop pipeline:', error);
        showNotification('Failed to stop pipeline', 'error');
    }
}

async function toggleSplitPipeline() {
    try {
        const desiredState = !pipelineSplitEnabled;
        const response = await fetch('/api/pipeline/toggle-split', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ enabled: desiredState }),
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.error || 'Failed to toggle split workers');
        }

        const result = await response.json();
        showNotification(`Split workers ${result.splitEnabled ? 'enabled' : 'disabled'}`, 'success');
        await checkPipelineStatus();
    } catch (error) {
        console.error('Failed to toggle split workers', error);
        showNotification(error.message || 'Failed to toggle split workers', 'error');
    }
}

// Mass generation
async function startMassGeneration() {
    console.log('🚀 Starting mass generation...');
    console.log('Current channel:', currentChannel);
    console.log('Current template:', currentTemplate);
    
    if (!currentChannel) {
        showNotification('Please select a channel first', 'warning');
        return;
    }
    
    if (!currentTemplate) {
        showNotification('Please select a template first', 'warning');
        return;
    }
    
    const contentSource = document.querySelector('input[name="contentSource"]:checked').value;
    const batchSize = document.getElementById('batchSize').value;
    const musicEnabled = document.getElementById('musicToggle').checked;
    const outputMode = document.querySelector('input[name="outputMode"]:checked').value;
    const ttsEngine = document.querySelector('input[name="ttsEngine"]:checked').value;
    const selectedVoice = document.getElementById('voiceSelector').value;
    
    console.log('Content source:', contentSource);
    console.log('Batch size:', batchSize);
    console.log('Music enabled:', musicEnabled);
    console.log('TTS Engine:', ttsEngine);
    console.log('Selected Voice:', selectedVoice);
    
    // Get questions based on content source
    let questions = [];
    if (contentSource === 'csv') {
        // Check upload mode
        const uploadMode = document.querySelector('input[name="uploadMode"]:checked').value;
        
        if (uploadMode === 'bulk') {
            // Handle bulk CSV upload
            if (!window.bulkCsvFiles || window.bulkCsvFiles.length === 0) {
                showNotification('Please select CSV files for bulk upload first', 'warning');
                return;
            }
            
            // Process bulk upload
            await processBulkCSVUpload();
            return; // Exit early for bulk upload
        } else {
            // Handle single CSV upload
            if (!window.csvQuestions || window.csvQuestions.length === 0) {
                showNotification('Please upload a CSV file first', 'warning');
                return;
            }
            questions = window.csvQuestions; // Use all questions, no batch limit
            console.log('Using CSV questions:', questions.length);
        }
    } else {
        // Gemini AI - use sample questions for now
        questions = [
            {
                question: "Sample question for testing",
                answer_a: "Answer A",
                answer_b: "Answer B", 
                answer_c: "Answer C",
                answer_d: "Answer D",
                correct_answer: "A",
                explanation: "This is a sample explanation"
            }
        ];
        console.log('Using sample questions:', questions.length);
    }
    
    try {
        console.log('📤 Sending job creation request...');
        // Get YouTube upload option (check both toggles)
        const uploadMode = document.querySelector('input[name="uploadMode"]:checked').value;
        let youtubeUploadTest = false;
        
        if (uploadMode === 'bulk') {
            youtubeUploadTest = false; // Bulk CSV mode doesn't support YouTube upload (use CSV + Manifest instead)
        } else {
            youtubeUploadTest = document.getElementById('youtubeUploadTest').checked;
        }
        
        const requestData = {
            channel_id: currentChannel.id,
            template_id: currentTemplate.id,
            questions: questions,
            music_enabled: musicEnabled,
            output_mode: outputMode,
            youtube_upload_test: youtubeUploadTest,
            tts_engine: ttsEngine,
            selected_voice: selectedVoice
        };
        console.log('Request data:', requestData);
        
        const response = await fetch('/api/create-job', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(requestData)
        });
        
        console.log('📥 Response status:', response.status);
        const data = await response.json();
        console.log('📥 Response data:', data);
        
        if (data.status === 'created' || data.created) {
            // Check if this is a single CSV upload or bulk upload
            const uploadMode = document.querySelector('input[name="uploadMode"]:checked').value;
            const isSingleCsv = uploadMode === 'single' && !data.bulk_upload_id;
            
            if (isSingleCsv) {
                showNotification(`Single video generation started! Processing ${questions.length} questions...`, 'success');
            } else {
                showNotification(`Mass generation started! Creating ${questions.length} videos...`, 'success');
            }
            console.log('✅ Job created successfully, refreshing jobs list...');
            loadJobs(); // Refresh jobs list
        } else {
            console.error('❌ Job creation failed:', data.error);
            throw new Error(data.error || 'Failed to start mass generation');
        }
    } catch (error) {
        console.error('❌ Failed to start mass generation:', error);
        showNotification('Failed to start mass generation: ' + error.message, 'error');
    }
}

// Helper functions for job display
function getChannelName(channelId, job) {
    if (!channelId) return null;
    if (job && job.channel_name) return job.channel_name;
    const channel = channels.find(c => c.id === channelId);
    if (channel && (channel.title || channel.name)) {
        return channel.title || channel.name;
    }
    return channelId;
}

function getTemplateName(templateId) {
    if (!templateId) return null;
    const template = templates.find(t => t.id === templateId);
    return template ? template.name : templateId;
}

// Retry job functionality
async function retryJob(jobId) {
    try {
        showNotification('Retrying job...', 'info');
        const response = await fetch(`/api/jobs/${jobId}/retry`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        const data = await response.json();
        if (!response.ok || !data.success) {
            throw data;
        }
        showNotification('Job queued for retry!', 'success');
        await loadJobs();
    } catch (error) {
        console.error('❌ Failed to retry job:', error);
        showNotification('Failed to retry job: ' + error.message, 'error');
    }
}

async function restartJob(jobId) {
    if (!confirm(`Restart aborted job ${jobId}?`)) return;
    try {
        showNotification('Restarting job...', 'info');
        const res = await fetch(`/api/jobs/${jobId}/restart`, { method: 'POST' });
        const data = await res.json();
        if (!res.ok || data.error) throw new Error(data.error || 'Restart failed');
        const resumeNote = data.resuming_from_tts ? ' (resuming from TTS)' : '';
        showNotification(`Job ${jobId} restarted${resumeNote}`, 'success');
        await loadJobs();
    } catch (err) {
        console.error('Failed to restart job:', err);
        showNotification(`Failed to restart job: ${err.message}`, 'error');
    }
}

async function fastRerenderJob(jobId) {
    if (!confirm(`Fast re-render job ${jobId}? This will skip TTS and use existing audio artifacts.`)) return;
    try {
        showNotification('Starting fast re-render...', 'info');
        const res = await fetch(`/api/jobs/${jobId}/fast-rerender`, { method: 'POST' });
        const data = await res.json();
        if (!res.ok || data.error) throw new Error(data.error || 'Fast re-render failed');
        showNotification(`Job ${jobId} queued for fast re-render (${data.tts_artifacts_count} audio files)`, 'success');
        await loadJobs();
    } catch (err) {
        console.error('Failed to fast re-render job:', err);
        showNotification(`Failed to fast re-render job: ${err.message}`, 'error');
    }
}

function viewJobDetails(jobId) {
    // Open job details modal
    showNotification('Job details for ' + jobId, 'info');
}

// Utility functions
function showNotification(message, type = 'info') {
    // Create notification element
    const notification = document.createElement('div');
    notification.className = `notification notification-${type}`;
    notification.innerHTML = `
        <div class="notification-content">
            <i class="fas fa-${getNotificationIcon(type)}"></i>
            <span>${message}</span>
        </div>
    `;
    
    // Add styles
    notification.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        background: ${getNotificationColor(type)};
        color: white;
        padding: 16px 20px;
        border-radius: 12px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        z-index: 1000;
        animation: slideIn 0.3s ease;
    `;
    
    // Add to page
    document.body.appendChild(notification);
    
    // Remove after 3 seconds
    setTimeout(() => {
        notification.style.animation = 'slideOut 0.3s ease';
        setTimeout(() => notification.remove(), 300);
    }, 3000);
}

function getNotificationIcon(type) {
    const icons = {
        success: 'check-circle',
        error: 'exclamation-circle',
        warning: 'exclamation-triangle',
        info: 'info-circle'
    };
    return icons[type] || 'info-circle';
}

function getNotificationColor(type) {
    const colors = {
        success: '#34C759',
        error: '#FF3B30',
        warning: '#FF9500',
        info: '#007AFF'
    };
    return colors[type] || '#007AFF';
}

function toggleDarkMode() {
    document.body.classList.toggle('dark-mode');
    localStorage.setItem('darkMode', document.body.classList.contains('dark-mode'));
}

// Update dashboard
function updateDashboard() {
    updateStats();
    renderJobs();
}

// Real-time job updates
let jobUpdateInterval = null;

function startJobUpdates() {
    // Update jobs every 5 seconds
    if (jobUpdateInterval) {
        clearInterval(jobUpdateInterval);
    }
    
    jobUpdateInterval = setInterval(async () => {
        try {
            console.log('🔄 Auto-updating jobs...');
            await loadJobs();
        } catch (error) {
            console.error('❌ Auto-update failed:', error);
        }
    }, 30000); // Update every 30 seconds (reduced from 5)
    
    console.log('✅ Real-time job updates started');
}

function stopJobUpdates() {
    if (jobUpdateInterval) {
        clearInterval(jobUpdateInterval);
        jobUpdateInterval = null;
        console.log('⏹️ Real-time job updates stopped');
    }
}

// Manual refresh function
function refreshJobs() {
    console.log('🔄 Manual refresh requested');
    showUpdateIndicator(true);
    loadJobs().finally(() => showUpdateIndicator(false));
}

// Show update indicator
function showUpdateIndicator(updating) {
    const refreshBtn = document.querySelector('button[onclick="refreshJobs()"]');
    if (!refreshBtn) {
        console.log('⚠️ Refresh button not found, skipping visual indicator');
        return;
    }
    
    const icon = refreshBtn.querySelector('i');
    if (!icon) {
        console.log('⚠️ Refresh button icon not found, skipping visual indicator');
        return;
    }
    
    if (updating) {
        icon.className = 'fas fa-sync-alt fa-spin';
        refreshBtn.disabled = true;
    } else {
        icon.className = 'fas fa-sync-alt';
        refreshBtn.disabled = false;
    }
}

// Toggle auto-updates
function toggleJobUpdates() {
    const btn = document.getElementById('autoUpdateBtn');
    if (!btn) {
        console.log('⚠️ Auto-update button not found');
        return;
    }
    
    const icon = btn.querySelector('i');
    if (!icon) {
        console.log('⚠️ Auto-update button icon not found');
        return;
    }
    
    if (jobUpdateInterval) {
        // Currently running - stop it
        stopJobUpdates();
        icon.className = 'fas fa-play';
        btn.title = 'Start Auto-Update';
        btn.classList.remove('btn-apple-success');
        btn.classList.add('btn-apple-warning');
        showNotification('Auto-updates stopped', 'info');
    } else {
        // Currently stopped - start it
        startJobUpdates();
        icon.className = 'fas fa-pause';
        btn.title = 'Stop Auto-Update';
        btn.classList.remove('btn-apple-warning');
        btn.classList.add('btn-apple-success');
        showNotification('Auto-updates started (every 5s)', 'success');
    }
}

// Video review functions
function viewVideo(videoUrl, jobId) {
    if (!videoUrl && !jobId) {
        showNotification('Video URL not available', 'error');
        return;
    }
    
    // If it's a GCS URL, get signed URL from API
    if (videoUrl && videoUrl.startsWith('gs://')) {
        // Extract job ID from URL if not provided
        if (!jobId) {
            const match = videoUrl.match(/videos\/([^\/]+)\//);
            if (match) {
                jobId = match[1];
            }
        }
        
        if (jobId) {
            // Get signed URL from API
            fetch(`/api/jobs/${jobId}/video`)
                .then(response => response.json())
                .then(data => {
                    if (data.video_url) {
                        window.open(data.video_url, '_blank');
                    } else {
                        showNotification('Failed to get video URL', 'error');
                    }
                })
                .catch(error => {
                    console.error('Error getting video URL:', error);
                    showNotification('Failed to get video URL', 'error');
                });
        } else {
            showNotification('Cannot determine job ID from video URL', 'error');
        }
    } else if (videoUrl) {
        // Direct URL - open immediately
        window.open(videoUrl, '_blank');
    } else {
        showNotification('Video URL not available', 'error');
    }
}

function viewJobDetails(jobId) {
    const job = jobs.find(j => j.id === jobId);
    if (!job) {
        showNotification('Job not found', 'error');
        return;
    }
    
    // Create modal for job details
    const modalHtml = `
        <div class="modal fade" id="jobDetailsModal" tabindex="-1">
            <div class="modal-dialog modal-lg">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">Job Details: ${job.id}</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <div class="row">
                            <div class="col-md-6">
                                <h6>Job Information</h6>
                                <table class="table table-sm">
                                    <tr><td><strong>Status:</strong></td><td><span class="job-status status-${job.status}">${job.status}</span></td></tr>
                                    <tr><td><strong>Progress:</strong></td><td>${job.progress || 0}%</td></tr>
                                    <tr><td><strong>Created:</strong></td><td>${new Date(job.createdAt || job.created_at).toLocaleString()}</td></tr>
                                    <tr><td><strong>Updated:</strong></td><td>${new Date(job.updatedAt || job.updated_at).toLocaleString()}</td></tr>
                                </table>
                            </div>
                            <div class="col-md-6">
                                <h6>Configuration</h6>
                                <table class="table table-sm">
                                    <tr><td><strong>Channel:</strong></td><td>${job.channel_id || 'N/A'}</td></tr>
                                    <tr><td><strong>Template:</strong></td><td>${job.template_id || 'N/A'}</td></tr>
                                    <tr><td><strong>Questions:</strong></td><td>${job.input_data?.questions?.length || 0}</td></tr>
                                </table>
                            </div>
                        </div>
                        
                        ${job.status === 'completed' && job.output?.video_url ? `
                            <div class="mt-3">
                                <h6>Generated Video</h6>
                                <div class="d-flex gap-2">
                                    <button class="btn btn-primary" onclick="viewVideo('${job.output.video_url}', '${job.id}')">
                                        <i class="fas fa-play"></i> Play Video
                                    </button>
                                    <a href="${job.output.video_url}" class="btn btn-success" download>
                                        <i class="fas fa-download"></i> Download
                                    </a>
                                </div>
                            </div>
                        ` : ''}
                        
                        ${job.error_message ? `
                            <div class="mt-3">
                                <h6>Error Details</h6>
                                <div class="alert alert-danger">
                                    <small>${job.error_message}</small>
                                </div>
                            </div>
                        ` : ''}
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Close</button>
                    </div>
                </div>
            </div>
        </div>
    `;
    
    // Remove existing modal if any
    const existingModal = document.getElementById('jobDetailsModal');
    if (existingModal) {
        existingModal.remove();
    }
    
    // Add modal to DOM
    document.body.insertAdjacentHTML('beforeend', modalHtml);
    
    // Show modal
    const modal = new bootstrap.Modal(document.getElementById('jobDetailsModal'));
    modal.show();
}

// Add CSS animations
const style = document.createElement('style');
style.textContent = `
    @keyframes slideIn {
        from { transform: translateX(100%); opacity: 0; }
        to { transform: translateX(0); opacity: 1; }
    }
    
    @keyframes slideOut {
        from { transform: translateX(0); opacity: 1; }
        to { transform: translateX(100%); opacity: 0; }
    }
    
    .notification-content {
        display: flex;
        align-items: center;
        gap: 8px;
    }
`;
document.head.appendChild(style);

// CSV + Manifest Upload Variables (YouTube Metadata)
let uploadedCSVsData = [];  // Array of {filename, questions}
let uploadedManifestData = null;  // Array of {title, description}

// Initialize CSV + Manifest upload handlers
function initializeManifestUpload() {
    // CSV + Manifest upload handlers for YouTube metadata
    const manifestCsvFiles = document.getElementById('manifestCsvFiles');
    const manifestFile = document.getElementById('manifestFile');
    const startManifestProcessingBtn = document.getElementById('startManifestProcessingBtn');
    
    if (manifestCsvFiles) {
        manifestCsvFiles.addEventListener('change', handleYouTubeManifestCsvSelection);
    }
    if (manifestFile) {
        manifestFile.addEventListener('change', handleYouTubeManifestSelection);
    }
    if (startManifestProcessingBtn) {
        startManifestProcessingBtn.addEventListener('click', createBulkJobsWithManifest);
    }
    
    // Remove the old upload buttons since we're doing direct job creation
    const uploadCsvsBtn = document.getElementById('uploadCsvsBtn');
    const uploadManifestBtn = document.getElementById('uploadManifestBtn');
    if (uploadCsvsBtn) uploadCsvsBtn.style.display = 'none';
    if (uploadManifestBtn) uploadManifestBtn.style.display = 'none';
    
    // Update button states
    updateYouTubeManifestButtonStates();
}

async function handleYouTubeManifestCsvSelection(event) {
    const files = Array.from(event.target.files);
    uploadedCSVsData = [];
    
    showManifestStatus('Processing CSV files...');
    
    // IMPORTANT: Process files in upload order (no sorting)
    // Files will be processed in the exact order you upload them
    
    for (const file of files) {
        try {
            const content = await file.text();
            const questions = parseCSV(content);
            
            if (!questions || questions.length === 0) {
                showManifestStatus(`❌ No valid questions found in ${file.name}`, 'error');
                uploadedCSVsData = [];
                updateYouTubeManifestButtonStates();
                return;
            }
            
            uploadedCSVsData.push({
                filename: file.name,
                questions: questions
            });
        } catch (error) {
            showManifestStatus(`❌ Error reading ${file.name}: ${error.message}`, 'error');
            uploadedCSVsData = [];
            updateYouTubeManifestButtonStates();
            return;
        }
    }
    
    showManifestStatus(`✅ Selected ${uploadedCSVsData.length} CSV files (in upload order)`, 'success');
    updateYouTubeManifestButtonStates();
}

async function handleYouTubeManifestSelection(event) {
    const file = event.target.files[0];
    
    if (!file) {
        uploadedManifestData = null;
        updateYouTubeManifestButtonStates();
        return;
    }
    
    try {
        showManifestStatus('Validating manifest...');
        
        const formData = new FormData();
        formData.append('manifest', file);
        
        const response = await fetch('/api/upload-youtube-manifest', {
            method: 'POST',
            body: formData
        });
        
        const result = await response.json();
        
        if (!response.ok || !result.success) {
            showManifestStatus(`❌ Manifest validation failed: ${result.error}`, 'error');
            uploadedManifestData = null;
            updateYouTubeManifestButtonStates();
            return;
        }
        
        uploadedManifestData = result.manifest_data;
        showManifestStatus(`✅ Manifest validated: ${result.manifest_count} entries`, 'success');
        updateYouTubeManifestButtonStates();
        
    } catch (error) {
        showManifestStatus(`❌ Manifest error: ${error.message}`, 'error');
        uploadedManifestData = null;
        updateYouTubeManifestButtonStates();
    }
}

function updateYouTubeManifestButtonStates() {
    const csvCount = uploadedCSVsData.length;
    const manifestCount = uploadedManifestData ? uploadedManifestData.length : 0;
    const channelSelected = document.getElementById('channelSelector')?.value !== '';
    const templateSelected = document.getElementById('templateSelector')?.value !== '';
    
    const startBtn = document.getElementById('startManifestProcessingBtn');
    
    // Enable button only if: CSVs uploaded, manifest uploaded, counts match, channel/template selected
    const countsMatch = csvCount > 0 && manifestCount > 0 && csvCount === manifestCount;
    const canCreate = countsMatch && channelSelected && templateSelected;
    
    if (startBtn) {
        startBtn.disabled = !canCreate;
        
        // Update button text based on state
        if (csvCount > 0 && manifestCount > 0 && csvCount !== manifestCount) {
            startBtn.textContent = `❌ Count Mismatch (${csvCount} CSVs vs ${manifestCount} Manifest Entries)`;
            startBtn.className = 'btn btn-danger btn-sm';
        } else if (canCreate) {
            startBtn.textContent = `✅ Create ${csvCount} Jobs with YouTube Metadata`;
            startBtn.className = 'btn btn-success btn-sm';
        } else {
            startBtn.textContent = 'Create Jobs (CSV + Manifest Required)';
            startBtn.className = 'btn btn-primary btn-sm';
        }
    }
    
    // Show count mismatch error
    if (csvCount > 0 && manifestCount > 0 && csvCount !== manifestCount) {
        showManifestStatus(`❌ Count mismatch: ${csvCount} CSVs but ${manifestCount} manifest entries. Must match exactly.`, 'error');
    }
}

function showManifestStatus(message, type = 'success') {
    const statusDiv = document.getElementById('manifestUploadStatus');
    const statusText = document.getElementById('manifestStatusText');
    
    if (!statusDiv || !statusText) return;
    
    statusText.textContent = message;
    statusDiv.style.display = 'block';
    
    const alertDiv = statusDiv.querySelector('.alert');
    if (type === 'success') {
        alertDiv.className = 'alert alert-success';
        alertDiv.style.background = '#E8F5E8';
        alertDiv.style.borderColor = '#4CAF50';
    } else if (type === 'error') {
        alertDiv.className = 'alert alert-danger';
        alertDiv.style.background = '#FFEBEE';
        alertDiv.style.borderColor = '#F44336';
    }
}

async function createBulkJobsWithManifest() {
    const channelId = document.getElementById('channelSelector')?.value;
    const templateId = document.getElementById('templateSelector')?.value;
    const outputMode = document.querySelector('input[name="outputMode"]:checked')?.value || 'test';
    const youtubeUpload = document.getElementById('youtubeUploadManifest')?.checked || false;
    const voiceSelector = document.getElementById('voiceSelector')?.value || 'ana_florence';
    
    if (!uploadedCSVsData || uploadedCSVsData.length === 0) {
        showManifestStatus('❌ Please upload CSV files first', 'error');
        return;
    }
    
    if (!uploadedManifestData || uploadedManifestData.length === 0) {
        showManifestStatus('❌ Please upload manifest JSON first', 'error');
        return;
    }
    
    if (uploadedCSVsData.length !== uploadedManifestData.length) {
        showManifestStatus(`❌ Count mismatch: ${uploadedCSVsData.length} CSVs but ${uploadedManifestData.length} manifest entries`, 'error');
        return;
    }
    
    // Check thumbnail count if YouTube upload is enabled
    if (youtubeUpload && uploadedManifestThumbnails.length !== uploadedCSVsData.length) {
        showManifestStatus(`❌ Thumbnail count mismatch: ${uploadedCSVsData.length} CSVs but ${uploadedManifestThumbnails.length} thumbnails`, 'error');
        return;
    }
    
    if (!channelId || !templateId) {
        showManifestStatus('❌ Please select channel and template', 'error');
        return;
    }
    
    try {
        let thumbnailUrls = [];
        
        // Upload thumbnails first if YouTube upload is enabled
        if (youtubeUpload && uploadedManifestThumbnails.length > 0) {
            showManifestStatus(`Uploading ${uploadedManifestThumbnails.length} thumbnails...`, 'success');
            
            for (let i = 0; i < uploadedManifestThumbnails.length; i++) {
                const thumbnailFile = uploadedManifestThumbnails[i];
                const formData = new FormData();
                formData.append('thumbnail', thumbnailFile);
                
                const uploadResponse = await fetch('/api/upload-thumbnail', {
                    method: 'POST',
                    body: formData
                });
                
                if (!uploadResponse.ok) {
                    throw new Error(`Failed to upload thumbnail ${i + 1}: ${uploadResponse.statusText}`);
                }
                
                const uploadResult = await uploadResponse.json();
                thumbnailUrls.push(uploadResult.thumbnail_url);
                
                showManifestStatus(`Uploaded thumbnail ${i + 1}/${uploadedManifestThumbnails.length}...`, 'success');
            }
        }
        
        showManifestStatus(`Creating ${uploadedCSVsData.length} jobs with YouTube metadata...`, 'success');
        
        const response = await fetch('/api/create-bulk-jobs-with-manifest', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                csv_list: uploadedCSVsData,  // Array of {filename, questions}
                manifest_data: uploadedManifestData,  // Array of {title, description}
                thumbnail_urls: thumbnailUrls,  // Array of thumbnail URLs in order
                channel_id: channelId,
                template_id: templateId,
                output_mode: outputMode,
                youtube_upload_test: youtubeUpload,
                tts_engine: 'custom',
                selected_voice: voiceSelector,
                music_enabled: true
            })
        });
        
        const result = await response.json();
        
        if (!response.ok || !result.success) {
            showManifestStatus(`❌ Job creation failed: ${result.error}`, 'error');
            return;
        }
        
        showManifestStatus(`✅ Successfully created ${result.jobs_created} jobs with YouTube metadata!`, 'success');
        
        // Reset form
        const manifestCsvFiles = document.getElementById('manifestCsvFiles');
        const manifestFile = document.getElementById('manifestFile');
        if (manifestCsvFiles) manifestCsvFiles.value = '';
        if (manifestFile) manifestFile.value = '';
        uploadedCSVsData = [];
        uploadedManifestData = null;
        updateYouTubeManifestButtonStates();
        
        // Show details
        console.log('Created jobs:', result.created_jobs);
        
        // Refresh jobs list
        if (typeof loadJobs === 'function') {
            loadJobs();
        }
        
    } catch (error) {
        showManifestStatus(`❌ Error: ${error.message}`, 'error');
        console.error('Bulk job creation error:', error);
    }
}

// Voice preview functionality
async function previewVoice() {
    const voiceSelector = document.getElementById('voiceSelector');
    const previewBtn = document.getElementById('previewVoiceBtn');
    const audioElement = document.getElementById('voicePreview');
    
    if (!voiceSelector || !previewBtn || !audioElement) {
        console.error('Voice preview elements not found');
        return;
    }
    
    const selectedVoice = voiceSelector.value;
    const previewText = "Hello! This is a preview of the selected voice. How does it sound?";
    
    // Show loading state
    previewBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Generating...';
    previewBtn.disabled = true;
    
    try {
        // Generate preview audio
        const response = await fetch('/api/tts-preview', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                text: previewText,
                voice: selectedVoice
            })
        });
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        
        const audioBlob = await response.blob();
        const audioUrl = URL.createObjectURL(audioBlob);
        
        // Set audio source and show controls
        audioElement.src = audioUrl;
        audioElement.style.display = 'inline-block';
        
        // Play the audio
        await audioElement.play();
        
        // Reset button
        previewBtn.innerHTML = '<i class="fas fa-play"></i> Preview Voice';
        previewBtn.disabled = false;
        
    } catch (error) {
        console.error('Voice preview failed:', error);
        showNotification(`Voice preview failed: ${error.message}`, 'error');
        
        // Reset button
        previewBtn.innerHTML = '<i class="fas fa-play"></i> Preview Voice';
        previewBtn.disabled = false;
    }
}

// Show/hide voice selection based on TTS engine
function toggleVoiceSelection() {
    const ttsEngine = document.querySelector('input[name="ttsEngine"]:checked').value;
    const voiceSelectionGroup = document.getElementById('voiceSelectionGroup');
    
    if (ttsEngine === 'custom' && voiceSelectionGroup) {
        voiceSelectionGroup.style.display = 'block';
    } else if (voiceSelectionGroup) {
        voiceSelectionGroup.style.display = 'none';
    }
}

// Initialize manifest upload when DOM is ready
document.addEventListener('DOMContentLoaded', function() {
    initializeManifestUpload();
    
    // Set up TTS engine change listeners
    document.querySelectorAll('input[name="ttsEngine"]').forEach(radio => {
        radio.addEventListener('change', toggleVoiceSelection);
    });
    
    // Initialize voice selection visibility
    toggleVoiceSelection();
});
