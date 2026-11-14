/**
 * AI Document Generator - task pane logic.
 *
 * Runs inside Word (desktop, Mac, web). It also opens in a normal browser for
 * testing; features that need the open document are disabled there.
 */
'use strict';

const $ = id => document.getElementById(id);
const passages = n => `${n} passage${n === 1 ? '' : 's'}`;
const PLACEHOLDER_RE = /\{\{\s*([A-Za-z0-9_][A-Za-z0-9_ .\-]*?)\s*\}\}/g;

let inWord = false;
let generatedText = '';
let lastGeneratedFile = null;
/** name -> Set of raw tokens as typed in the document, e.g. "{{ DATE }}" */
let documentTokens = new Map();
let serverTemplates = [];

// ==================== Startup ====================

function start(info) {
    inWord = !!(info && window.Office && info.host === Office.HostType.Word);
    if (!inWord) {
        document.querySelectorAll('[data-needs-word]').forEach(button => {
            button.disabled = true;
            button.title = 'Available when this pane is opened inside Word';
        });
    }

    document.querySelectorAll('.tab-button').forEach(button => {
        button.addEventListener('click', () => switchTab(button.dataset.tab));
    });

    const actions = {
        btnIngestText: ingestText,
        btnIngestDocument: ingestCurrentDocument,
        btnIngestFile: () => $('fileInput').click(),
        btnRefreshDocs: refreshDocuments,
        btnGenerate: generateContent,
        btnInsert: insertGenerated,
        btnCopy: copyGenerated,
        btnScan: scanDocument,
        btnAiFill: aiFill,
        btnApply: applyToDocument,
        btnUploadTemplate: () => $('templateInput').click(),
        btnE2E: generateFromTemplate,
        btnOpenDoc: openGeneratedInWord,
        btnDownloadDoc: downloadGenerated,
        btnSaveSettings: saveSettings
    };
    Object.entries(actions).forEach(([id, handler]) => {
        $(id).addEventListener('click', () => run($(id), handler));
    });
    $('fileInput').addEventListener('change', () => run($('btnIngestFile'), ingestFile));
    $('templateInput').addEventListener('change', () => run($('btnUploadTemplate'), uploadTemplate));
    $('templateSelect').addEventListener('change', showTemplateFields);
    $('docList').addEventListener('click', event => {
        const id = event.target.dataset.deleteId;
        if (id) run(event.target, () => deleteDocument(id));
    });

    $('backendUrl').value = CONFIG.backendUrl;
    $('apiKey').value = CONFIG.apiKey;
    connect();
}

/** Run an async action with the button disabled and errors surfaced. */
async function run(button, action) {
    if (button.disabled) return;
    button.disabled = true;
    try {
        await action();
    } catch (error) {
        console.error(error);
        showStatus(describeError(error), 'error', 10000);
    } finally {
        button.disabled = false;
    }
}

function describeError(error) {
    if (window.OfficeExtension && error instanceof OfficeExtension.Error) {
        return `Word error: ${error.message}`;
    }
    return error.message || String(error);
}

function switchTab(name) {
    document.querySelectorAll('.tab-content').forEach(tab => {
        tab.classList.toggle('active', tab.id === name);
    });
    document.querySelectorAll('.tab-button').forEach(button => {
        button.classList.toggle('active', button.dataset.tab === name);
    });
}

async function connect() {
    const badge = $('connection');
    try {
        const health = await fetchAPI('/health');
        badge.textContent = health.status === 'healthy' ? 'connected' : 'needs setup';
        badge.className = `connection ${health.status === 'healthy' ? 'ok' : 'warn'}`;
        badge.title = health.message;
        if (health.status !== 'healthy') showStatus(health.message, 'error', 12000);
        await Promise.all([refreshDocuments(), refreshTemplates()]);
        return health;
    } catch (error) {
        badge.textContent = 'offline';
        badge.className = 'connection bad';
        badge.title = error.message;
        throw error;
    }
}

// ==================== Knowledge base ====================

async function ingestText() {
    const name = $('docName').value.trim();
    const content = $('docContent').value.trim();
    if (!content) throw new Error('Paste some text first.');

    showStatus('Adding to the knowledge base…', 'loading');
    const result = await fetchAPI('/ingest-document', {
        body: { content, document_name: name || 'Pasted text', metadata: { source: 'word_plugin' } }
    });
    $('docName').value = '';
    $('docContent').value = '';
    await ingested(result);
}

async function ingestCurrentDocument() {
    showStatus('Reading the document…', 'loading');
    const content = await Word.run(async context => {
        const body = context.document.body;
        body.load('text');
        await context.sync();
        return body.text;
    });
    if (!content.trim()) throw new Error('The document is empty.');

    const result = await fetchAPI('/ingest-document', {
        body: {
            content,
            document_name: $('docName').value.trim() || 'Word document',
            metadata: { source: 'word_document' }
        }
    });
    $('docName').value = '';
    await ingested(result);
}

async function ingestFile() {
    const input = $('fileInput');
    const file = input.files[0];
    if (!file) return;
    try {
        const form = new FormData();
        form.append('file', file);
        const name = $('docName').value.trim();
        if (name) form.append('document_name', name);

        showStatus(`Uploading ${file.name}…`, 'loading');
        const result = await fetchAPI('/ingest-document-file', { formData: form });
        $('docName').value = '';
        await ingested(result);
    } finally {
        input.value = ''; // allow choosing the same file again
    }
}

async function ingested(result) {
    showStatus(`Added "${result.document_name}" (${passages(result.chunks)}).`, 'success');
    await refreshDocuments();
}

async function refreshDocuments() {
    const documents = await fetchAPI('/documents');
    $('docList').innerHTML = documents.length
        ? documents.map(d => `
            <li>
                <span>${escapeHtml(d.document_name)} <small>${passages(d.chunks)}</small></span>
                <button class="link danger" data-delete-id="${escapeHtml(d.document_id)}">remove</button>
            </li>`).join('')
        : '<li class="empty">Nothing yet.</li>';
}

async function deleteDocument(id) {
    await fetchAPI(`/documents/${encodeURIComponent(id)}`, { method: 'DELETE' });
    showStatus('Removed.', 'success', 2500);
    await refreshDocuments();
}

// ==================== Generate ====================

function retrievalCount() {
    const value = parseInt($('retrievalK').value, 10);
    return Number.isNaN(value) ? 3 : Math.min(20, Math.max(0, value));
}

async function generateContent() {
    const prompt = $('prompt').value.trim();
    if (!prompt) throw new Error('Describe what should be written.');

    showStatus('Generating…', 'loading');
    const result = await fetchAPI('/generate-content', {
        body: { prompt, context_retrieval_k: retrievalCount() }
    });
    generatedText = result.content;
    $('generatedText').textContent = result.content;
    $('generatedSources').textContent = result.sources && result.sources.length
        ? `Sources: ${result.sources.join(', ')}`
        : 'No knowledge-base context was used.';
    $('generateResult').hidden = false;
    showStatus('Done.', 'success', 2500);
}

async function insertGenerated() {
    if (!generatedText) throw new Error('Generate something first.');
    await Word.run(async context => {
        // Replaces the selection, or inserts at the cursor if nothing is selected.
        context.document.getSelection().insertText(generatedText, Word.InsertLocation.replace);
        await context.sync();
    });
    showStatus('Inserted into the document.', 'success', 2500);
}

async function copyGenerated() {
    if (!generatedText) throw new Error('Nothing to copy.');
    try {
        await navigator.clipboard.writeText(generatedText);
    } catch (e) {
        // The async clipboard API is often blocked inside add-in frames.
        const area = document.createElement('textarea');
        area.value = generatedText;
        document.body.appendChild(area);
        area.select();
        const copied = document.execCommand('copy');
        area.remove();
        if (!copied) throw new Error('Copy was blocked. Select the text and copy it manually.');
    }
    showStatus('Copied.', 'success', 2500);
}

// ==================== Template: this document ====================

/** Body plus every header and footer of every section. */
async function documentRanges(context) {
    const ranges = [context.document.body];
    const sections = context.document.sections;
    sections.load('items');
    await context.sync();
    const types = [
        Word.HeaderFooterType.primary,
        Word.HeaderFooterType.firstPage,
        Word.HeaderFooterType.evenPages
    ];
    sections.items.forEach(section => {
        types.forEach(type => {
            ranges.push(section.getHeader(type));
            ranges.push(section.getFooter(type));
        });
    });
    return ranges;
}

async function scanDocument() {
    showStatus('Scanning the document…', 'loading');
    const text = await Word.run(async context => {
        const ranges = await documentRanges(context);
        ranges.forEach(range => range.load('text'));
        await context.sync();
        return ranges.map(range => range.text).join('\n');
    });

    documentTokens = new Map();
    for (const match of text.matchAll(PLACEHOLDER_RE)) {
        if (!documentTokens.has(match[1])) documentTokens.set(match[1], new Set());
        documentTokens.get(match[1]).add(match[0]);
    }

    if (documentTokens.size === 0) {
        $('placeholderPanel').hidden = true;
        showStatus('No {{PLACEHOLDER}} tokens found in this document.', 'info');
        return;
    }

    $('placeholderInputs').innerHTML = [...documentTokens.keys()].map((name, index) => `
        <div class="placeholder-input-group">
            <label for="ph_${index}">{{${escapeHtml(name)}}}</label>
            <textarea id="ph_${index}" data-placeholder="${escapeHtml(name)}" rows="2"></textarea>
        </div>`).join('');
    $('placeholderPanel').hidden = false;
    showStatus(`Found ${documentTokens.size} placeholders.`, 'success', 2500);
}

function placeholderFields() {
    return [...document.querySelectorAll('#placeholderInputs textarea')];
}

async function aiFill() {
    const prompt = $('fillPrompt').value.trim();
    if (!prompt) throw new Error('Describe the document so the AI knows what to write.');

    const fields = placeholderFields();
    const known = {};
    fields.forEach(field => {
        if (field.value.trim()) known[field.dataset.placeholder] = field.value;
    });

    showStatus('Writing values…', 'loading');
    const result = await fetchAPI('/fill-placeholders', {
        body: {
            prompt,
            placeholders: fields.map(field => field.dataset.placeholder),
            known_values: known,
            context_retrieval_k: retrievalCount()
        }
    });
    fields.forEach(field => {
        if (!field.value.trim()) {
            field.value = result.values[field.dataset.placeholder] || '';
            field.rows = Math.min(8, Math.max(2, Math.ceil(field.value.length / 40)));
        }
    });
    const sources = result.sources.length ? ` Sources: ${result.sources.join(', ')}.` : '';
    showStatus(`Filled. Review the values, then apply.${sources}`, 'success', 8000);
}

async function applyToDocument() {
    const replacements = [];
    placeholderFields().forEach(field => {
        if (field.value === '') return; // leave unfilled tokens in place
        documentTokens.get(field.dataset.placeholder).forEach(token => {
            replacements.push({ token, value: field.value });
        });
    });
    if (replacements.length === 0) throw new Error('Enter at least one value.');

    showStatus('Updating the document…', 'loading');
    const replaced = await Word.run(async context => {
        const ranges = await documentRanges(context);
        const searches = [];
        replacements.forEach(({ token, value }) => {
            ranges.forEach(range => {
                const results = range.search(token, { matchCase: true });
                results.load('items');
                searches.push({ results, value });
            });
        });
        await context.sync();

        let count = 0;
        searches.forEach(({ results, value }) => {
            results.items.forEach(item => {
                // "Replace" keeps the token's character formatting.
                item.insertText(value, Word.InsertLocation.replace);
                count += 1;
            });
        });
        await context.sync();
        return count;
    });
    showStatus(`Replaced ${replaced} placeholder${replaced === 1 ? '' : 's'}.`, 'success');
}

// ==================== Template: server side ====================

async function refreshTemplates() {
    const data = await fetchAPI('/templates');
    serverTemplates = data.templates;
    const select = $('templateSelect');
    const previous = select.value;
    select.innerHTML = serverTemplates.length
        ? serverTemplates.map(t => `<option>${escapeHtml(t.name)}</option>`).join('')
        : '<option value="">No templates on the server</option>';
    if (serverTemplates.some(t => t.name === previous)) select.value = previous;
    showTemplateFields();
}

function showTemplateFields() {
    const template = serverTemplates.find(t => t.name === $('templateSelect').value);
    $('templateFields').textContent = template
        ? `${template.placeholders.length} fields: ${template.placeholders.join(', ')}`
        : '';
}

async function uploadTemplate() {
    const input = $('templateInput');
    const file = input.files[0];
    if (!file) return;
    try {
        const form = new FormData();
        form.append('file', file);
        showStatus(`Uploading ${file.name}…`, 'loading');
        const result = await fetchAPI('/templates', { formData: form });
        await refreshTemplates();
        $('templateSelect').value = result.name;
        showTemplateFields();
        showStatus(`Template added (${result.placeholders.length} placeholders).`, 'success');
    } finally {
        input.value = '';
    }
}

async function generateFromTemplate() {
    const template = $('templateSelect').value;
    const prompt = $('e2ePrompt').value.trim();
    if (!template) throw new Error('Upload a template first.');
    if (!prompt) throw new Error('Describe the document.');

    showStatus('Writing and filling the template…', 'loading');
    const result = await fetchAPI('/end-to-end-generation', {
        body: { prompt, template_path: template, context_retrieval_k: retrievalCount() }
    });
    lastGeneratedFile = result.output_path;
    const sources = result.sources.length ? ` Sources: ${result.sources.join(', ')}.` : '';
    $('e2eSummary').textContent =
        `${result.output_path}: ${result.placeholders_filled.length} fields filled.${sources}`;
    $('e2eResult').hidden = false;
    showStatus('Document ready.', 'success', 2500);
}

async function fetchGeneratedBlob() {
    if (!lastGeneratedFile) throw new Error('Generate a document first.');
    const response = await fetchAPI(`/download/${encodeURIComponent(lastGeneratedFile)}`, { raw: true });
    return response.blob();
}

async function openGeneratedInWord() {
    const blob = await fetchGeneratedBlob();
    const base64 = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result.split(',')[1]);
        reader.onerror = () => reject(reader.error);
        reader.readAsDataURL(blob);
    });
    await Word.run(async context => {
        context.application.createDocument(base64).open();
        await context.sync();
    });
    showStatus('Opened as a new document.', 'success', 2500);
}

async function downloadGenerated() {
    const blob = await fetchGeneratedBlob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = lastGeneratedFile;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
}

// ==================== Settings ====================

async function saveSettings() {
    saveConfig($('backendUrl').value, $('apiKey').value);
    $('backendUrl').value = CONFIG.backendUrl;
    await connect();
    const status = await fetchAPI('/status');
    $('statusDump').textContent = JSON.stringify(status, null, 2);
    $('statusDump').hidden = false;
    showStatus('Connected.', 'success', 2500);
}

// Office.onReady also resolves in a plain browser (with host = null). If the
// Office script could not load at all, start anyway in browser mode.
if (window.Office && Office.onReady) {
    Office.onReady(info => start(info));
} else {
    document.addEventListener('DOMContentLoaded', () => start(null));
}
