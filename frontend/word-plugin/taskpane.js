/**
 * AI Document Generator - Main Plugin Logic
 * Handles user interactions and backend communication
 */

// ==================== TAB NAVIGATION ====================

function switchTab(tabName) {
    // Hide all tabs
    document.querySelectorAll('.tab-content').forEach(tab => {
        tab.classList.remove('active');
    });
    
    // Deactivate all buttons
    document.querySelectorAll('.tab-button').forEach(btn => {
        btn.classList.remove('active');
    });
    
    // Show selected tab
    document.getElementById(tabName).classList.add('active');
    
    // Activate selected button
    event.target.classList.add('active');
}


// ==================== TAB 1: INGEST DOCUMENT ====================

async function ingestDocument() {
    const docName = document.getElementById('docName').value.trim();
    const docContent = document.getElementById('docContent').value.trim();
    
    if (!docName || !docContent) {
        showStatus('Please enter document name and content', 'error');
        return;
    }
    
    try {
        showStatus('📤 Uploading document...', 'loading');
        
        const response = await fetchAPI('/ingest-document', {
            method: 'POST',
            body: {
                content: docContent,
                document_name: docName,
                metadata: {
                    source: 'word_plugin',
                    timestamp: new Date().toISOString()
                }
            }
        });
        
        // Show result
        const resultEl = document.getElementById('ingestResult');
        resultEl.innerHTML = `
            <div style="color: #28a745; font-weight: 500;">✓ Document Ingested Successfully</div>
            <p style="font-size: 12px; margin-top: 8px;">
                <strong>Document ID:</strong> ${response.document_id}<br>
                <strong>Name:</strong> ${response.document_name}
            </p>
        `;
        resultEl.classList.add('show');
        
        showStatus('✓ Document ingested successfully!', 'success');
        
        // Clear inputs
        document.getElementById('docName').value = '';
        document.getElementById('docContent').value = '';
        
    } catch (error) {
        showStatus(`Error: ${error.message}`, 'error');
        console.error(error);
    }
}


// ==================== TAB 2: GENERATE CONTENT ====================

let generatedContentCache = '';

async function generateContent() {
    const prompt = document.getElementById('prompt').value.trim();
    const retrievalK = parseInt(document.getElementById('retrievalK').value);
    
    if (!prompt) {
        showStatus('Please enter a prompt', 'error');
        return;
    }
    
    try {
        showStatus('✨ Generating content...', 'loading');
        
        const response = await fetchAPI('/generate-content', {
            method: 'POST',
            body: {
                prompt: prompt,
                context_retrieval_k: retrievalK
            }
        });
        
        generatedContentCache = response.content;
        
        // Display result
        const resultEl = document.getElementById('generateResult');
        document.getElementById('generatedText').textContent = response.content;
        resultEl.classList.add('show');
        
        // Show sources if available
        if (response.sources && response.sources.length > 0) {
            showStatus(`✓ Generated! Sources: ${response.sources.join(', ')}`, 'success', 10000);
        } else {
            showStatus('✓ Content generated successfully!', 'success');
        }
        
    } catch (error) {
        showStatus(`Error: ${error.message}`, 'error');
        console.error(error);
    }
}

function copyGenerated() {
    if (!generatedContentCache) {
        showStatus('No content to copy', 'error');
        return;
    }
    
    navigator.clipboard.writeText(generatedContentCache).then(() => {
        showStatus('✓ Copied to clipboard!', 'success');
    }).catch(() => {
        showStatus('Failed to copy', 'error');
    });
}


// ==================== TAB 3: POPULATE TEMPLATE ====================

let currentPlaceholders = [];

async function findPlaceholders() {
    try {
        showStatus('🔍 Reading document...', 'loading');
        
        // Try to get document body text (Word API)
        await Word.run(async (context) => {
            const body = context.document.body;
            body.load('text');
            await context.sync();
            
            // For now, we'll use a simplified approach
            // In production, extract from actual Word document
            showStatus('Document loaded. Please specify placeholders to fill.', 'info');
        });
        
    } catch (error) {
        showStatus(`Note: Word API may not be fully available in test mode. ${error.message}`, 'info');
        
        // Fallback: use template file path
        const templatePath = prompt('Enter path to Word template file:\n(e.g., ./templates/sample_template.docx)');
        if (templatePath) {
            await findPlaceholdersFromFile(templatePath);
        }
    }
}

async function findPlaceholdersFromFile(templatePath) {
    try {
        showStatus('🔍 Finding placeholders...', 'loading');
        
        const response = await fetchAPI(`/find-placeholders?template_path=${encodeURIComponent(templatePath)}`, {
            method: 'POST'
        });
        
        currentPlaceholders = response.placeholders_found;
        
        // Display found placeholders
        const container = document.getElementById('placeholdersContainer');
        container.innerHTML = currentPlaceholders
            .map(p => `<span class="placeholder-tag">{{${p}}}</span>`)
            .join('');
        
        document.getElementById('placeholdersList').classList.add('show');
        
        // Show input form
        renderPlaceholderInputs(currentPlaceholders);
        
        showStatus(`✓ Found ${currentPlaceholders.length} placeholders!`, 'success');
        
    } catch (error) {
        showStatus(`Error: ${error.message}`, 'error');
        console.error(error);
    }
}

function renderPlaceholderInputs(placeholders) {
    const inputsContainer = document.getElementById('placeholderInputs');
    
    inputsContainer.innerHTML = placeholders
        .map(placeholder => `
            <div class="placeholder-input-group">
                <label for="ph_${placeholder}">{{${placeholder}}}</label>
                <textarea 
                    id="ph_${placeholder}" 
                    placeholder="Enter value for ${placeholder}"
                    rows="2"
                ></textarea>
            </div>
        `)
        .join('');
    
    document.getElementById('placeholdersForm').classList.add('show');
}

async function populateTemplate() {
    if (currentPlaceholders.length === 0) {
        showStatus('No placeholders found. Please find placeholders first.', 'error');
        return;
    }
    
    try {
        // Collect placeholder values
        const placeholdersData = {};
        currentPlaceholders.forEach(ph => {
            const value = document.getElementById(`ph_${ph}`).value;
            placeholdersData[ph] = value;
        });
        
        const templatePath = prompt('Enter path to Word template file:\n(e.g., ./templates/sample_template.docx)');
        if (!templatePath) return;
        
        showStatus('📋 Populating template...', 'loading');
        
        const response = await fetchAPI('/populate-template', {
            method: 'POST',
            body: {
                template_path: templatePath,
                placeholders_data: placeholdersData
            }
        });
        
        // Try to open the populated document
        try {
            await Word.run(async (context) => {
                const fileUrl = response.output_path;
                showStatus(`✓ Template populated! Check: ${response.output_path}`, 'success', 10000);
            });
        } catch (e) {
            showStatus(`✓ Template populated! Check: ${response.output_path}`, 'success', 10000);
        }
        
    } catch (error) {
        showStatus(`Error: ${error.message}`, 'error');
        console.error(error);
    }
}


// ==================== SETTINGS ====================

async function testConnection() {
    try {
        const response = await fetchAPI('/health');
        
        if (response.status === 'healthy') {
            showStatus('✓ Backend connected and healthy!', 'success', 3000);
            return true;
        } else {
            showStatus('⚠ Backend returned unhealthy status', 'error');
            return false;
        }
    } catch (error) {
        showStatus('❌ Cannot reach backend server. Check URL in settings.', 'error');
        console.error(error);
        return false;
    }
}

// Optionally allow user to update backend URL in settings
document.addEventListener('DOMContentLoaded', () => {
    const backendUrlInput = document.getElementById('backendUrl');
    if (backendUrlInput) {
        backendUrlInput.addEventListener('change', (e) => {
            updateBackendUrl(e.target.value);
            testConnection();
        });
    }
});
