/**
 * Shared helpers: configuration, status messages and backend requests.
 * (Microsoft's Office JavaScript API is loaded separately from the CDN.)
 */
'use strict';

const servedByBackend = window.location.pathname.startsWith('/addin/');

function readSetting(key) {
    try { return window.localStorage.getItem(key); } catch (e) { return null; }
}

function writeSetting(key, value) {
    try { window.localStorage.setItem(key, value); } catch (e) { /* storage disabled */ }
}

const CONFIG = {
    // When the task pane is served by the backend itself, talk to that origin.
    backendUrl: readSetting('backendUrl')
        || (servedByBackend ? window.location.origin : 'http://localhost:8000'),
    apiKey: readSetting('apiKey') || '',
    timeoutMs: 180000 // LLM calls can be slow
};

function saveConfig(backendUrl, apiKey) {
    CONFIG.backendUrl = backendUrl.trim().replace(/\/+$/, '');
    CONFIG.apiKey = apiKey.trim();
    writeSetting('backendUrl', CONFIG.backendUrl);
    writeSetting('apiKey', CONFIG.apiKey);
}

let statusTimer = null;

/** type: info | success | error | loading. Loading messages stay until replaced. */
function showStatus(message, type = 'info', duration = 6000) {
    const el = document.getElementById('statusMessage');
    el.textContent = message;
    el.className = `status-message show ${type}`;
    clearTimeout(statusTimer);
    if (type !== 'loading') {
        statusTimer = setTimeout(() => el.classList.remove('show'), duration);
    }
}

function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, c => (
        { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
    ));
}

/**
 * Call the backend.
 *   options.body      object, sent as JSON
 *   options.formData  FormData, sent as multipart (file uploads)
 *   options.raw       return the Response instead of parsed JSON
 */
async function fetchAPI(endpoint, options = {}) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), CONFIG.timeoutMs);
    const headers = {};
    if (CONFIG.apiKey) headers['X-API-Key'] = CONFIG.apiKey;

    let body;
    if (options.formData) {
        body = options.formData; // browser sets the multipart boundary
    } else if (options.body !== undefined) {
        headers['Content-Type'] = 'application/json';
        body = JSON.stringify(options.body);
    }

    let response;
    try {
        response = await fetch(`${CONFIG.backendUrl}${endpoint}`, {
            method: options.method || (body ? 'POST' : 'GET'),
            headers,
            body,
            signal: controller.signal
        });
    } catch (error) {
        if (error.name === 'AbortError') throw new Error('The server took too long to respond.');
        throw new Error(`Cannot reach the backend at ${CONFIG.backendUrl}. Is it running?`);
    } finally {
        clearTimeout(timer);
    }

    if (!response.ok) {
        let detail = `HTTP ${response.status}`;
        try {
            const data = await response.json();
            if (typeof data.detail === 'string') detail = data.detail;
            else if (Array.isArray(data.detail)) detail = data.detail.map(d => d.msg).join('; ');
        } catch (e) { /* not JSON */ }
        throw new Error(detail);
    }
    return options.raw ? response : response.json();
}
