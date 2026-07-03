/**
 * Office Plugin Initialization
 * Initialize Office JavaScript API when document is ready
 */

if (!window.Word) {
    console.log("Word JavaScript API not available. This must be run within a Word document.");
}

// Global configuration
const CONFIG = {
    backendUrl: localStorage.getItem('backendUrl') || 'http://localhost:8000',
    timeout: 30000,
    retryAttempts: 3
};

/**
 * Update backend URL
 */
function updateBackendUrl(newUrl) {
    CONFIG.backendUrl = newUrl.replace(/\/$/, ''); // Remove trailing slash
    localStorage.setItem('backendUrl', CONFIG.backendUrl);
}

/**
 * Show status message
 */
function showStatus(message, type = 'info', duration = 5000) {
    const statusEl = document.getElementById('statusMessage');
    
    statusEl.textContent = message;
    statusEl.className = `status-message show ${type}`;
    
    setTimeout(() => {
        statusEl.classList.remove('show');
    }, duration);
}

/**
 * Make API request with error handling
 */
async function fetchAPI(endpoint, options = {}) {
    const url = `${CONFIG.backendUrl}${endpoint}`;
    
    try {
        const response = await fetch(url, {
            method: options.method || 'GET',
            headers: {
                'Content-Type': 'application/json',
                ...options.headers
            },
            body: options.body ? JSON.stringify(options.body) : undefined,
            timeout: CONFIG.timeout
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || `HTTP ${response.status}`);
        }

        return await response.json();
    } catch (error) {
        console.error('API Error:', error);
        throw error;
    }
}

/**
 * Initialize Office add-in
 */
Office.onReady((reason) => {
    if (reason === Office.OfficeApp.EventType.DocumentReady) {
        console.log('✓ Office Add-in initialized');
        testConnection();
    }
});
