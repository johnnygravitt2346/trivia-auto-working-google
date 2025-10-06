// Assets management JavaScript
// This file handles asset-related functionality for the dashboard

// Global asset state
let assets = [];
let assetCategories = {
    'backgrounds': [],
    'audio': [],
    'overlays': [],
    'intros': [],
    'outros': [],
    'transitions': [],
    'test-assets': []
};

// Load assets from API
async function loadAssets() {
    try {
        console.log('📁 Loading assets...');
        const response = await fetch('/api/assets');
        const data = await response.json();
        
        if (Array.isArray(data)) {
            assets = data || [];
            categorizeAssets();
            renderAssets();
        } else if (data.assets && Array.isArray(data.assets)) {
            assets = data.assets || [];
            categorizeAssets();
            renderAssets();
        } else {
            console.error('❌ No assets in response:', data);
            throw new Error(data.error || 'Failed to load assets');
        }
    } catch (error) {
        console.error('❌ Failed to load assets:', error);
        showNotification('Failed to load assets: ' + error.message, 'error');
    }
}

// Categorize assets by type
function categorizeAssets() {
    // Reset categories
    Object.keys(assetCategories).forEach(category => {
        assetCategories[category] = [];
    });
    
    // Categorize assets
    assets.forEach(asset => {
        const category = asset.category || 'test-assets';
        if (assetCategories[category]) {
            assetCategories[category].push(asset);
        } else {
            assetCategories['test-assets'].push(asset);
        }
    });
}

// Render assets in tables
function renderAssets() {
    // Render all assets
    renderAssetTable('allAssetsTableBody', assets);
    
    // Render category-specific tables
    Object.keys(assetCategories).forEach(category => {
        const tableBodyId = category + 'TableBody';
        renderAssetTable(tableBodyId, assetCategories[category]);
    });
}

// Render asset table
function renderAssetTable(tableBodyId, assetList) {
    const tableBody = document.getElementById(tableBodyId);
    if (!tableBody) return;
    
    if (assetList.length === 0) {
        tableBody.innerHTML = `
            <tr>
                <td colspan="6" class="text-center text-muted py-3">
                    <i class="fas fa-folder-open fa-2x mb-2"></i>
                    <p>No assets found</p>
                </td>
            </tr>
        `;
        return;
    }
    
    tableBody.innerHTML = assetList.map(asset => `
        <tr>
            <td>
                <div class="d-flex align-items-center">
                    <i class="fas fa-${getAssetIcon(asset.type)} me-2"></i>
                    <span>${asset.name || asset.filename || 'Unknown'}</span>
                </div>
            </td>
            <td>
                <span class="badge bg-secondary">${asset.type || 'unknown'}</span>
            </td>
            <td>
                <span class="badge bg-info">${asset.category || 'uncategorized'}</span>
            </td>
            <td>${formatFileSize(asset.size)}</td>
            <td>${formatDate(asset.uploaded_at || asset.created_at)}</td>
            <td>
                <div class="btn-group btn-group-sm">
                    ${asset.url ? `
                        <button class="btn btn-outline-primary" onclick="viewAsset('${asset.id}')" title="View">
                            <i class="fas fa-eye"></i>
                        </button>
                    ` : ''}
                    <button class="btn btn-outline-danger" onclick="deleteAsset('${asset.id}')" title="Delete">
                        <i class="fas fa-trash"></i>
                    </button>
                </div>
            </td>
        </tr>
    `).join('');
}

// Get asset icon based on type
function getAssetIcon(type) {
    const icons = {
        'video': 'video',
        'audio': 'music',
        'image': 'image',
        'png': 'image',
        'jpg': 'image',
        'jpeg': 'image',
        'gif': 'image',
        'mp4': 'video',
        'avi': 'video',
        'mov': 'video',
        'mp3': 'music',
        'wav': 'music',
        'ogg': 'music'
    };
    return icons[type?.toLowerCase()] || 'file';
}

// Format file size
function formatFileSize(bytes) {
    if (!bytes) return 'Unknown';
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(1024));
    return Math.round(bytes / Math.pow(1024, i) * 100) / 100 + ' ' + sizes[i];
}

// Format date
function formatDate(dateString) {
    if (!dateString) return 'Unknown';
    return new Date(dateString).toLocaleDateString();
}

// View asset
async function viewAsset(assetId) {
    try {
        const response = await fetch(`/api/assets/${assetId}/signed-url`);
        const data = await response.json();
        
        if (data.signed_url) {
            window.open(data.signed_url, '_blank');
        } else {
            showNotification('Failed to get asset URL', 'error');
        }
    } catch (error) {
        console.error('Failed to view asset:', error);
        showNotification('Failed to view asset: ' + error.message, 'error');
    }
}

// Delete asset
async function deleteAsset(assetId) {
    if (!confirm('Are you sure you want to delete this asset?')) {
        return;
    }
    
    try {
        const response = await fetch(`/api/assets/${assetId}`, {
            method: 'DELETE'
        });
        
        const data = await response.json();
        
        if (data.success) {
            showNotification('Asset deleted successfully', 'success');
            loadAssets(); // Refresh assets
        } else {
            throw new Error(data.error || 'Failed to delete asset');
        }
    } catch (error) {
        console.error('Failed to delete asset:', error);
        showNotification('Failed to delete asset: ' + error.message, 'error');
    }
}

// Show notification (reuse from dashboard)
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

// Initialize assets when DOM is ready
document.addEventListener('DOMContentLoaded', function() {
    // Only load assets if we're on a page that needs them
    if (document.getElementById('allAssetsTableBody')) {
        loadAssets();
    }
});
