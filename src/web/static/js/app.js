/* Wallpaper Scraper GUI — Vanilla JS */
let galleryOffset = 0;
const GALLERY_LIMIT = 50;
let galleryPolling = null;
let jobsPolling = null;
let sourcesPolling = null;
let globalStatusPolling = null;
let lastGlobalStatus = null;
let tableFieldsCache = [];
let currentMapping = {};

// === Tab Navigation ===
document.querySelectorAll('.nav-tab').forEach(tab => {
    tab.addEventListener('click', () => {
        document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
        tab.classList.add('active');
        document.getElementById('tab-' + tab.dataset.tab).classList.add('active');
        onTabSwitch(tab.dataset.tab);
    });
});

function onTabSwitch(tab) {
    stopPolling();
    if (tab === 'gallery') { loadGallerySummary(); loadGallery(); startGalleryPolling(); }
    if (tab === 'scrape') { checkBaserowStatus(); loadScrapeJobs(); startScrapePolling(); }
    if (tab === 'sources') { loadSources(); loadQueries(); loadSchedulerStatus(); loadLiveStatus(); startSourcesPolling(); }
    if (tab === 'jobs') { loadJobs(); startJobsPolling(); }
    if (tab === 'settings') { loadSettings(); }
    if (tab === 'baserow') { loadBaserowConfig(); }
    if (tab === 'browse') { loadBrowse(); }
    if (tab === 'stats') { loadStats(); }
    if (tab === 'logs') { loadLogs(); startLogsPolling(); }
}

function stopPolling() {
    if (galleryPolling) { clearInterval(galleryPolling); galleryPolling = null; }
    if (jobsPolling) { clearInterval(jobsPolling); jobsPolling = null; }
    if (sourcesPolling) { clearInterval(sourcesPolling); sourcesPolling = null; }
    if (typeof scrapePolling !== 'undefined' && scrapePolling) { clearInterval(scrapePolling); scrapePolling = null; }
    if (typeof logsPolling !== 'undefined' && logsPolling) { clearInterval(logsPolling); logsPolling = null; }
}

// ==================== GLOBAL STATUS (always running) ====================
function startGlobalStatusPolling() {
    if (globalStatusPolling) return;
    updateGlobalStatus(); // immediate first call
    globalStatusPolling = setInterval(updateGlobalStatus, 3000);
}

async function updateGlobalStatus() {
    try {
        const data = await api('/api/status/live');
        lastGlobalStatus = data;
        renderNavStatus(data);
    } catch (e) {
        // Silently fail — don't spam errors for the always-on poller
    }
}

function renderNavStatus(data) {
    const el = document.getElementById('nav-status');
    if (!el) return;

    const job = data.current_job;
    const discoveryRunning = data.discovery_running;
    const scheduler = data.scheduler || {};

    if (job && job.status === 'running') {
        const name = job.source_name || 'Unknown';
        const progress = job.progress || 0;
        const found = job.images_found || 0;
        const uploaded = job.images_uploaded || 0;
        const page = job.pages_scraped || 0;
        const maxPages = job.max_pages || '?';
        el.innerHTML = `
            <div class="nav-status-active" title="Scraping ${esc(name)}: page ${page}/${maxPages}, ${found} found, ${uploaded} uploaded">
                <span class="nav-status-dot"></span>
                <span>Scraping: ${esc(name)} (${progress}%)</span>
            </div>
        `;
    } else if (discoveryRunning) {
        el.innerHTML = `
            <div class="nav-status-discovery">
                <span class="nav-status-dot"></span>
                <span>Discovering sources...</span>
            </div>
        `;
    } else if (scheduler.paused) {
        el.innerHTML = '<span class="nav-status-idle">Paused</span>';
    } else {
        el.innerHTML = '<span class="nav-status-idle">Idle</span>';
    }

    // Also update gallery live banner if gallery tab is active
    updateGalleryLiveBanner(job);
}

function updateGalleryLiveBanner(job) {
    const banner = document.getElementById('gallery-live-banner');
    if (!banner) return;

    if (job && job.status === 'running') {
        banner.style.display = '';
        const name = job.source_name || job.url || 'Unknown';
        const titleEl = document.getElementById('gallery-live-title');
        const detailEl = document.getElementById('gallery-live-detail');
        const progressEl = document.getElementById('gallery-live-progress');
        const statsEl = document.getElementById('gallery-live-stats');
        if (titleEl) titleEl.textContent = 'Scraping: ' + name;
        if (detailEl) detailEl.textContent = 'Page ' + (job.pages_scraped || 0) + '/' + (job.max_pages || '?') + ' \u2022 ' + (job.images_found || 0) + ' images found';
        if (progressEl) progressEl.style.width = (job.progress || 0) + '%';
        if (statsEl) statsEl.textContent = (job.images_uploaded || 0) + ' uploaded, ' + (job.duplicates || 0) + ' dupes';
    } else {
        banner.style.display = 'none';
    }
}

// === API Helper ===
async function api(path, opts = {}) {
    const url = path.startsWith('http') ? path : path;
    const options = { headers: { 'Content-Type': 'application/json' }, ...opts };
    if (opts.body && typeof opts.body === 'object') options.body = JSON.stringify(opts.body);
    try {
        const res = await fetch(url, options);
        if (!res.ok) {
            const err = await res.text();
            throw new Error(err);
        }
        return await res.json();
    } catch (e) {
        console.error('API error:', path, e);
        throw e;
    }
}

// === Toast ===
function toast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    const t = document.createElement('div');
    t.className = 'toast toast-' + type;
    t.textContent = message;
    container.appendChild(t);
    setTimeout(() => t.remove(), 4000);
}

// === Modal ===
function showModal(html) {
    document.getElementById('modal-content').innerHTML = html;
    document.getElementById('modal-overlay').classList.add('active');
}
function closeModal() {
    document.getElementById('modal-overlay').classList.remove('active');
}
document.getElementById('modal-overlay').addEventListener('click', (e) => {
    if (e.target === document.getElementById('modal-overlay')) closeModal();
});

// === Time formatting ===
function timeAgo(iso) {
    if (!iso) return 'Never';
    const diff = (Date.now() - new Date(iso).getTime()) / 1000;
    if (diff < 60) return 'Just now';
    if (diff < 3600) return Math.floor(diff/60) + 'm ago';
    if (diff < 86400) return Math.floor(diff/3600) + 'h ago';
    return Math.floor(diff/86400) + 'd ago';
}

// === Collapsible ===
function toggleCollapsible(id) {
    const el = document.getElementById(id);
    el.classList.toggle('open');
    const arrow = document.getElementById(id + '-arrow');
    if (arrow) arrow.innerHTML = el.classList.contains('open') ? '&#9650;' : '&#9660;';
}

// ==================== GALLERY ====================
function startGalleryPolling() {
    galleryPolling = setInterval(() => {
        loadGallerySummary();
        loadActivityFeed();
    }, 5000);
}

async function loadGallerySummary() {
    try {
        const data = await api('/api/gallery/summary');
        document.getElementById('gallery-stats').innerHTML = `
            <div class="stat-card"><div class="stat-value">${data.today || 0}</div><div class="stat-label">Today</div></div>
            <div class="stat-card"><div class="stat-value">${data.total || 0}</div><div class="stat-label">Total</div></div>
            <div class="stat-card"><div class="stat-value">${data.duplicates || 0}</div><div class="stat-label">Duplicates</div></div>
            <div class="stat-card"><div class="stat-value">${data.errors || 0}</div><div class="stat-label">Errors</div></div>
        `;
    } catch (e) {}
}

async function loadActivityFeed() {
    try {
        const data = await api('/api/gallery?limit=20');
        const feed = document.getElementById('activity-feed');
        if (!data.entries || data.entries.length === 0) {
            feed.innerHTML = '<div class="empty-state"><div class="empty-state-text">No activity yet</div><div class="empty-state-hint">Start scraping to see activity here.</div></div>';
            return;
        }
        feed.innerHTML = data.entries.map(e => `
            <div class="activity-item" onclick="showEntryDetail('${e.id}')">
                <img class="activity-thumb" src="/${e.thumbnail_path || ''}" alt="" loading="lazy" onerror="this.src='data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 width=%2250%22 height=%2250%22><rect fill=%22%231c1c1e%22 width=%2250%22 height=%2250%22/></svg>'">
                <div class="activity-info">
                    <div class="activity-title">${esc(e.title || 'Untitled')}</div>
                    <div class="activity-meta">
                        <span class="badge badge-${e.status}">${e.status}</span>
                        ${esc(e.source_name || '')} &middot; ${timeAgo(e.timestamp)}
                    </div>
                </div>
            </div>
        `).join('');
    } catch (e) {}
}

async function loadGallery() {
    galleryOffset = 0;
    const search = document.getElementById('gallery-search').value;
    const sourceId = document.getElementById('gallery-source-filter').value;
    const status = document.getElementById('gallery-status-filter').value;
    let url = `/api/gallery?limit=${GALLERY_LIMIT}&offset=0`;
    if (search) url += `&search=${encodeURIComponent(search)}`;
    if (sourceId) url += `&source_id=${encodeURIComponent(sourceId)}`;
    if (status) url += `&status=${encodeURIComponent(status)}`;
    try {
        const data = await api(url);
        renderGalleryGrid(data.entries, false);
        document.getElementById('load-more-btn').style.display = data.entries.length >= GALLERY_LIMIT ? '' : 'none';
        loadActivityFeed();
        loadSourceFilter();
    } catch (e) {
        document.getElementById('gallery-grid').innerHTML = '<div class="empty-state"><div class="empty-state-icon">&#128444;</div><div class="empty-state-text">No wallpapers yet</div><div class="empty-state-hint">No wallpapers yet. Start scraping from the Sources tab!</div></div>';
    }
}

async function loadMoreGallery() {
    galleryOffset += GALLERY_LIMIT;
    const search = document.getElementById('gallery-search').value;
    const sourceId = document.getElementById('gallery-source-filter').value;
    const status = document.getElementById('gallery-status-filter').value;
    let url = `/api/gallery?limit=${GALLERY_LIMIT}&offset=${galleryOffset}`;
    if (search) url += `&search=${encodeURIComponent(search)}`;
    if (sourceId) url += `&source_id=${encodeURIComponent(sourceId)}`;
    if (status) url += `&status=${encodeURIComponent(status)}`;
    try {
        const data = await api(url);
        renderGalleryGrid(data.entries, true);
        document.getElementById('load-more-btn').style.display = data.entries.length >= GALLERY_LIMIT ? '' : 'none';
    } catch (e) {}
}

function renderGalleryGrid(entries, append) {
    const grid = document.getElementById('gallery-grid');
    if (!entries || entries.length === 0) {
        if (!append) grid.innerHTML = '<div class="empty-state"><div class="empty-state-icon">&#128444;</div><div class="empty-state-text">No wallpapers yet</div><div class="empty-state-hint">No wallpapers yet. Start scraping from the Sources tab!</div></div>';
        return;
    }
    const html = entries.map(e => `
        <div class="gallery-item" onclick="showEntryDetail('${e.id}')">
            <img src="/${e.thumbnail_path || ''}" alt="${esc(e.alt_text || '')}" loading="lazy"
                onerror="this.src='data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 width=%22200%22 height=%22200%22><rect fill=%22%231c1c1e%22 width=%22200%22 height=%22200%22/></svg>'">
            <div class="gallery-badge">${e.width}x${e.height}</div>
            <div class="gallery-overlay">
                <div class="gallery-overlay-title">${esc(e.title || 'Untitled')}</div>
            </div>
        </div>
    `).join('');
    if (append) grid.innerHTML += html;
    else grid.innerHTML = html;
}

async function showEntryDetail(id) {
    try {
        const e = await api(`/api/gallery/${id}`);
        showModal(`
            <div class="modal-header">
                <h3>${esc(e.title || 'Untitled')}</h3>
                <button class="modal-close" onclick="closeModal()">&times;</button>
            </div>
            <div style="text-align:center;margin-bottom:1.5rem">
                <img src="/${e.thumbnail_path || ''}" style="max-width:100%;border-radius:var(--radius-md)" alt="">
            </div>
            <table>
                <tr><td style="color:var(--text-tertiary);width:120px">Alt Text</td><td>${esc(e.alt_text || '')}</td></tr>
                <tr><td style="color:var(--text-tertiary)">Tags</td><td>${esc(e.tags || '')}</td></tr>
                <tr><td style="color:var(--text-tertiary)">Resolution</td><td>${e.width}x${e.height} (${e.aspect_ratio})</td></tr>
                <tr><td style="color:var(--text-tertiary)">Mobile</td><td>${e.is_mobile ? 'Yes' : 'No'}</td></tr>
                <tr><td style="color:var(--text-tertiary)">Source</td><td>${esc(e.source_name || '')}</td></tr>
                <tr><td style="color:var(--text-tertiary)">File Size</td><td>${e.file_size_kb || 0} KB</td></tr>
                <tr><td style="color:var(--text-tertiary)">Hash</td><td style="font-family:'SF Mono',SFMono-Regular,Menlo,monospace;font-size:12px">${esc(e.img_hash || '')}</td></tr>
                <tr><td style="color:var(--text-tertiary)">Status</td><td><span class="badge badge-${e.status}">${e.status}</span></td></tr>
                <tr><td style="color:var(--text-tertiary)">Baserow Row</td><td>${e.baserow_row_id || 'N/A'}</td></tr>
                <tr><td style="color:var(--text-tertiary)">URL</td><td><a href="${esc(e.img_url || '')}" target="_blank" style="color:var(--accent)">${esc((e.img_url||'').substring(0,60))}...</a></td></tr>
                <tr><td style="color:var(--text-tertiary)">Time</td><td>${e.timestamp || ''}</td></tr>
                ${e.error_message ? `<tr><td style="color:var(--error)">Error</td><td>${esc(e.error_message)}</td></tr>` : ''}
            </table>
        `);
    } catch (e) { toast('Failed to load details', 'error'); }
}

async function loadSourceFilter() {
    try {
        const data = await api('/api/sources');
        const sel = document.getElementById('gallery-source-filter');
        const val = sel.value;
        sel.innerHTML = '<option value="">All Sources</option>' +
            (data.sources || []).map(s => `<option value="${s.id}">${esc(s.name)}</option>`).join('');
        sel.value = val;
    } catch (e) {}
}

// Gallery search debounce
let searchTimeout;
document.getElementById('gallery-search').addEventListener('input', () => {
    clearTimeout(searchTimeout);
    searchTimeout = setTimeout(() => loadGallery(), 500);
});
document.getElementById('gallery-source-filter').addEventListener('change', () => loadGallery());
document.getElementById('gallery-status-filter').addEventListener('change', () => loadGallery());

// ==================== SCRAPE ====================
let scrapePolling = null;
function startScrapePolling() {
    scrapePolling = setInterval(loadScrapeJobs, 3000);
}
function stopScrapePolling() {
    if (scrapePolling) { clearInterval(scrapePolling); scrapePolling = null; }
}

async function checkBaserowStatus() {
    try {
        const data = await api('/api/baserow/status');
        document.getElementById('baserow-warning').style.display = data.configured ? 'none' : '';
    } catch (e) {}
}

async function startScrape() {
    const url = document.getElementById('scrape-url').value.trim();
    if (!url) { toast('Enter a URL', 'error'); return; }
    const btn = document.getElementById('scrape-btn');
    btn.disabled = true;
    try {
        await api('/api/scrape', {
            method: 'POST',
            body: {
                url: url,
                source_name: document.getElementById('scrape-name').value.trim(),
                max_pages: parseInt(document.getElementById('scrape-pages').value) || 5,
            }
        });
        toast('Scrape job started!', 'success');
        loadScrapeJobs();
    } catch (e) {
        toast('Failed to start scrape: ' + e.message, 'error');
    }
    btn.disabled = false;
}

async function loadScrapeJobs() {
    try {
        const data = await api('/api/jobs');
        const el = document.getElementById('scrape-jobs');
        const jobs = [data.current, ...(data.history || [])].filter(Boolean).slice(0, 10);
        if (jobs.length === 0) { el.innerHTML = '<div style="color:var(--text-tertiary);padding:1rem 0">No recent jobs</div>'; return; }
        el.innerHTML = jobs.map(j => `
            <div class="card" style="padding:1rem">
                <div style="display:flex;justify-content:space-between;align-items:center">
                    <div style="display:flex;align-items:center;gap:0.5rem">
                        <strong style="font-size:13px">${esc(j.source_name || j.url || '')}</strong>
                        <span class="badge badge-${j.status === 'running' ? 'running' : j.status === 'completed' ? 'success' : 'error'}">${j.status}</span>
                    </div>
                    <span style="font-size:12px;color:var(--text-tertiary)">${timeAgo(j.started_at)}</span>
                </div>
                ${j.status === 'running' ? `<div class="progress" style="margin-top:0.75rem"><div class="progress-bar" style="width:${j.progress||0}%"></div></div>` : ''}
                <div style="font-size:12px;color:var(--text-tertiary);margin-top:0.5rem">
                    Pages: ${j.pages_scraped || 0} | Found: ${j.images_found || 0} | Uploaded: ${j.images_uploaded || 0} | Dupes: ${j.duplicates || 0} | Errors: ${j.errors || 0}
                </div>
            </div>
        `).join('');
    } catch (e) {}
}

// ==================== SOURCES ====================
async function loadSources() {
    try {
        const data = await api('/api/sources');
        const tbody = document.getElementById('sources-table');
        if (!data.sources || data.sources.length === 0) {
            tbody.innerHTML = '<tr><td colspan="11" style="text-align:center;color:var(--text-muted)">No sources configured. Add sources or wait for discovery.</td></tr>';
            return;
        }
        tbody.innerHTML = data.sources.map(s => `
            <tr draggable="true" data-source-id="${s.id}"
                ondragstart="onSourceDragStart(event)" ondragend="onSourceDragEnd(event)"
                ondragover="onSourceDragOver(event)" ondrop="onSourceDrop(event)"
                ondragleave="onSourceDragLeave(event)">
                <td><span class="drag-handle" title="Drag to reorder">&#9776;</span></td>
                <td><label class="toggle"><input type="checkbox" ${s.enabled ? 'checked' : ''} onchange="toggleSource('${s.id}')"><span class="toggle-slider"></span></label></td>
                <td><span class="badge badge-idle" id="source-status-${s.id}">idle</span></td>
                <td>${esc(s.name)}<br><span style="font-size:11px;color:var(--text-muted)">${esc(s.domain || '')}</span></td>
                <td><span class="badge badge-${s.category}">${s.category}</span></td>
                <td>${s.schedule_hours}h</td>
                <td>${timeAgo(s.last_scraped)}</td>
                <td><span class="countdown" id="source-next-${s.id}">--</span></td>
                <td>${s.total_uploaded || 0} / ${s.total_dupes || 0} / ${s.total_errors || 0}</td>
                <td><span class="status-dot ${(s.consecutive_failures || 0) < 5 ? 'healthy' : 'unhealthy'}"></span></td>
                <td>
                    <button class="btn btn-sm btn-secondary" onclick="scrapeSource('${s.id}')">Scrape</button>
                    <button class="btn btn-sm btn-danger" onclick="deleteSource('${s.id}')">Del</button>
                </td>
            </tr>
        `).join('');
        // Immediately populate live status badges
        loadLiveStatus();
    } catch (e) {}
}

// ==================== DRAG & DROP (SOURCE REORDER) ====================
let dragSourceId = null;

function onSourceDragStart(e) {
    const row = e.target.closest('tr');
    if (!row) return;
    dragSourceId = row.dataset.sourceId;
    row.classList.add('dragging');
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', dragSourceId);
}

function onSourceDragEnd(e) {
    const row = e.target.closest('tr');
    if (row) row.classList.remove('dragging');
    // Clean up all drag-over highlights
    document.querySelectorAll('tr.drag-over').forEach(r => r.classList.remove('drag-over'));
    dragSourceId = null;
}

function onSourceDragOver(e) {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    const row = e.target.closest('tr');
    if (row && row.dataset.sourceId !== dragSourceId) {
        row.classList.add('drag-over');
    }
}

function onSourceDragLeave(e) {
    const row = e.target.closest('tr');
    if (row) row.classList.remove('drag-over');
}

function onSourceDrop(e) {
    e.preventDefault();
    const targetRow = e.target.closest('tr');
    if (!targetRow) return;
    targetRow.classList.remove('drag-over');

    const targetId = targetRow.dataset.sourceId;
    if (!targetId || targetId === dragSourceId) return;

    // Reorder the DOM rows, then save new order
    const tbody = document.getElementById('sources-table');
    const rows = Array.from(tbody.querySelectorAll('tr[data-source-id]'));
    const ids = rows.map(r => r.dataset.sourceId);

    const fromIdx = ids.indexOf(dragSourceId);
    const toIdx = ids.indexOf(targetId);
    if (fromIdx < 0 || toIdx < 0) return;

    // Move the dragged id to the target position
    ids.splice(fromIdx, 1);
    ids.splice(toIdx, 0, dragSourceId);

    // Visually reorder the rows
    const draggedRow = rows[fromIdx];
    if (fromIdx < toIdx) {
        tbody.insertBefore(draggedRow, targetRow.nextSibling);
    } else {
        tbody.insertBefore(draggedRow, targetRow);
    }

    saveSourceOrder(ids);
}

async function saveSourceOrder(sourceIds) {
    try {
        await api('/api/sources/reorder', {
            method: 'PUT',
            body: { source_ids: sourceIds }
        });
        toast('Source order saved', 'success');
    } catch (e) {
        toast('Failed to save order', 'error');
        loadSources(); // Reload to reset order
    }
}

async function toggleSource(id) {
    try { await api(`/api/sources/${id}/toggle`, { method: 'POST' }); } catch (e) { toast('Toggle failed', 'error'); }
}

async function scrapeSource(id) {
    try {
        await api(`/api/sources/${id}/scrape`, { method: 'POST' });
        toast('Scrape started', 'success');
    } catch (e) { toast('Scrape failed: ' + e.message, 'error'); }
}

async function deleteSource(id) {
    if (!confirm('Delete this source?')) return;
    try {
        await api(`/api/sources/${id}`, { method: 'DELETE' });
        toast('Source deleted', 'success');
        loadSources();
    } catch (e) { toast('Delete failed', 'error'); }
}

function showAddSourceModal() {
    showModal(`
        <div class="modal-header">
            <h3>Add Source</h3>
            <button class="modal-close" onclick="closeModal()">&times;</button>
        </div>
        <div class="form-group">
            <label>URL</label>
            <input type="text" id="add-source-url" placeholder="https://...">
        </div>
        <div class="form-group">
            <label>Name</label>
            <input type="text" id="add-source-name" placeholder="Source name">
        </div>
        <div class="form-group">
            <label>Schedule (hours)</label>
            <input type="number" id="add-source-schedule" value="12">
        </div>
        <button class="btn btn-primary" onclick="addSource()">Add Source</button>
    `);
}

async function addSource() {
    const url = document.getElementById('add-source-url').value.trim();
    if (!url) { toast('Enter a URL', 'error'); return; }
    try {
        await api('/api/sources', {
            method: 'POST',
            body: {
                url: url,
                name: document.getElementById('add-source-name').value.trim(),
                schedule_hours: parseInt(document.getElementById('add-source-schedule').value) || 12,
            }
        });
        toast('Source added', 'success');
        closeModal();
        loadSources();
    } catch (e) { toast('Failed to add source', 'error'); }
}

// ==================== QUERIES ====================
async function loadQueries() {
    try {
        const data = await api('/api/discovery/queries');
        const tbody = document.getElementById('queries-table');
        if (!data.queries || data.queries.length === 0) {
            tbody.innerHTML = '<tr><td colspan="7" style="color:var(--text-muted)">No queries</td></tr>';
            return;
        }
        tbody.innerHTML = data.queries.map(q => `
            <tr>
                <td><label class="toggle"><input type="checkbox" ${q.enabled ? 'checked' : ''} onchange="toggleQuery('${q.id}', this.checked)"><span class="toggle-slider"></span></label></td>
                <td>${esc(q.query)}</td>
                <td><span class="badge badge-${q.builtin ? 'builtin' : 'user'}">${q.builtin ? 'Built-in' : 'User'}</span></td>
                <td>${q.times_used || 0}</td>
                <td>${q.sources_found || 0}</td>
                <td>${timeAgo(q.last_used)}</td>
                <td>${q.builtin ? '' : `<button class="btn btn-sm btn-danger" onclick="deleteQuery('${q.id}')">Del</button>`}</td>
            </tr>
        `).join('');
    } catch (e) {}
}

async function addQuery() {
    const input = document.getElementById('new-query-input');
    const text = input.value.trim();
    if (!text) return;
    try {
        await api('/api/discovery/queries', { method: 'POST', body: { query: text } });
        input.value = '';
        toast('Query added', 'success');
        loadQueries();
    } catch (e) { toast('Failed to add query', 'error'); }
}

async function toggleQuery(id, enabled) {
    try {
        await api(`/api/discovery/queries/${id}`, { method: 'PUT', body: { enabled } });
    } catch (e) { toast('Toggle failed', 'error'); }
}

async function deleteQuery(id) {
    try {
        await api(`/api/discovery/queries/${id}`, { method: 'DELETE' });
        toast('Query deleted', 'success');
        loadQueries();
    } catch (e) { toast('Cannot delete (built-in?)', 'error'); }
}

async function runDiscovery() {
    try {
        await api('/api/discovery/run', { method: 'POST' });
        toast('Discovery started', 'success');
    } catch (e) { toast('Discovery failed: ' + e.message, 'error'); }
}

// ==================== SCHEDULER ====================
async function loadSchedulerStatus() {
    try {
        const data = await api('/api/scheduler/status');
        const dot = document.getElementById('scheduler-dot');
        const text = document.getElementById('scheduler-text');
        const btn = document.getElementById('scheduler-toggle-btn');
        if (data.paused) {
            dot.className = 'status-dot idle';
            text.textContent = 'Scheduler: Paused';
            btn.textContent = 'Resume';
        } else if (data.running) {
            dot.className = 'status-dot healthy';
            text.textContent = 'Scheduler: Running';
            btn.textContent = 'Pause';
        } else {
            dot.className = 'status-dot idle';
            text.textContent = 'Scheduler: Stopped';
            btn.textContent = 'Resume';
        }
    } catch (e) {}
}

async function toggleScheduler() {
    const btn = document.getElementById('scheduler-toggle-btn');
    const isPaused = btn.textContent === 'Resume';
    try {
        await api(`/api/scheduler/${isPaused ? 'resume' : 'pause'}`, { method: 'POST' });
        toast(`Scheduler ${isPaused ? 'resumed' : 'paused'}`, 'success');
        loadSchedulerStatus();
    } catch (e) { toast('Failed', 'error'); }
}

// ==================== LIVE STATUS ====================
function startSourcesPolling() {
    sourcesPolling = setInterval(loadLiveStatus, 5000);
}

async function loadLiveStatus() {
    try {
        const data = await api('/api/status/live');

        // Update scraping banner
        const banner = document.getElementById('scraping-banner');
        if (banner) {
            if (data.current_job && data.current_job.status === 'running') {
                banner.style.display = '';
                const j = data.current_job;
                document.getElementById('scraping-banner-title').textContent =
                    'Currently Scraping: ' + (j.source_name || j.url || 'Unknown');
                document.getElementById('scraping-banner-detail').textContent =
                    'Page ' + (j.pages_scraped || 0) + '/' + (j.max_pages || '?') + ' | ' + (j.images_found || 0) + ' images found';
                document.getElementById('scraping-banner-progress-bar').style.width = (j.progress || 0) + '%';
                document.getElementById('scraping-banner-stats').textContent =
                    (j.images_uploaded || 0) + ' uploaded, ' + (j.duplicates || 0) + ' dupes, ' + (j.errors || 0) + ' errors';
            } else {
                banner.style.display = 'none';
            }
        }

        // Update discovery banner
        const discDot = document.getElementById('discovery-dot');
        const discText = document.getElementById('discovery-text');
        const discNext = document.getElementById('discovery-next');
        if (discDot && discText) {
            if (data.discovery_running) {
                discDot.className = 'status-dot healthy';
                discText.textContent = 'Discovery: Running...';
                if (discNext) discNext.textContent = '';
            } else {
                discDot.className = 'status-dot idle';
                const browserOk = data.browser_available;
                discText.textContent = browserOk ? 'Discovery: Idle' : 'Discovery: Browser not available';
                if (discNext) {
                    if (data.next_discovery) {
                        discNext.textContent = 'Next run: ' + formatCountdown(data.next_discovery);
                    } else {
                        discNext.textContent = 'Next run: Pending (first run)';
                    }
                }
            }
        }

        // Update per-source status badges
        if (data.sources_status) {
            for (const ss of data.sources_status) {
                const badge = document.getElementById('source-status-' + ss.id);
                if (badge) {
                    badge.className = 'badge badge-' + ss.status;
                    badge.textContent = ss.status;
                }
                const nextEl = document.getElementById('source-next-' + ss.id);
                if (nextEl) {
                    if (ss.next_scrape) {
                        nextEl.textContent = formatCountdown(ss.next_scrape);
                    } else {
                        nextEl.textContent = 'Pending';
                    }
                }
            }
        }
    } catch (e) { console.error('Live status error:', e); }
}

function formatCountdown(isoDate) {
    if (!isoDate) return '';
    const diff = (new Date(isoDate).getTime() - Date.now()) / 1000;
    if (diff <= 0) return 'Due now';
    if (diff < 60) return Math.ceil(diff) + 's';
    if (diff < 3600) return Math.ceil(diff / 60) + 'm';
    if (diff < 86400) return Math.floor(diff / 3600) + 'h ' + Math.ceil((diff % 3600) / 60) + 'm';
    return Math.floor(diff / 86400) + 'd ' + Math.floor((diff % 86400) / 3600) + 'h';
}

// ==================== JOBS ====================
function startJobsPolling() {
    jobsPolling = setInterval(loadJobs, 3000);
}

async function loadJobs() {
    try {
        const data = await api('/api/jobs');
        const el = document.getElementById('jobs-list');
        const allJobs = [data.current, ...(data.history || []), ...(data.saved || [])].filter(Boolean);
        const statusFilter = document.getElementById('jobs-status-filter').value;
        const filtered = statusFilter ? allJobs.filter(j => j.status === statusFilter) : allJobs;
        if (filtered.length === 0) {
            el.innerHTML = '<div class="empty-state"><div class="empty-state-text">No jobs yet</div></div>';
            return;
        }
        el.innerHTML = filtered.map(j => `
            <div class="card" style="padding:1rem">
                <div style="display:flex;justify-content:space-between;align-items:center">
                    <div style="display:flex;align-items:center;gap:0.5rem">
                        <strong style="font-size:13px">${esc(j.source_name || j.url || 'Unknown')}</strong>
                        <span class="badge badge-${j.status === 'running' ? 'running' : j.status === 'completed' ? 'success' : 'error'}">${j.status}</span>
                    </div>
                    <span style="font-size:12px;color:var(--text-tertiary)">${timeAgo(j.started_at)} ${j.completed_at ? '- ' + timeAgo(j.completed_at) : ''}</span>
                </div>
                ${j.status === 'running' ? `<div class="progress" style="margin-top:0.75rem"><div class="progress-bar" style="width:${j.progress||0}%"></div></div>` : ''}
                <div style="font-size:12px;color:var(--text-tertiary);margin-top:0.5rem">
                    Pages: ${j.pages_scraped || 0}/${j.max_pages || '?'} | Found: ${j.images_found || 0} | Downloaded: ${j.images_downloaded || 0} | Uploaded: ${j.images_uploaded || 0} | Dupes: ${j.duplicates || 0} | Errors: ${j.errors || 0}
                </div>
                ${(j.error_log && j.error_log.length > 0) ? `<div style="font-size:11px;color:var(--error);margin-top:0.5rem;max-height:80px;overflow-y:auto;line-height:1.5">${j.error_log.map(e => esc(e)).join('<br>')}</div>` : ''}
            </div>
        `).join('');
    } catch (e) {}
}

// ==================== SETTINGS ====================
async function loadSettings() {
    try {
        const data = await api('/api/settings');
        if (data.scraping) {
            document.getElementById('set-min-width').value = data.scraping.min_width || 800;
            document.getElementById('set-min-height').value = data.scraping.min_height || 600;
            document.getElementById('set-max-pages').value = data.scraping.max_pages || 10;
            document.getElementById('set-page-delay').value = data.scraping.page_delay_seconds || 2;
            document.getElementById('set-max-dl').value = data.scraping.max_concurrent_downloads || 3;
            // Aspect ratio filters
            const allowedAspects = data.scraping.allowed_aspects || [];
            document.querySelectorAll('.aspect-cb').forEach(cb => {
                cb.checked = allowedAspects.includes(cb.value);
            });
            document.getElementById('set-allow-mobile').checked = data.scraping.allow_mobile !== false;
            document.getElementById('set-watermark-detection').checked = data.scraping.watermark_detection !== false;
            document.getElementById('set-allow-nsfw').checked = !!data.scraping.allow_nsfw;
        }
        if (data.jpeg) document.getElementById('set-jpeg-quality').value = data.jpeg.quality || 85;
        if (data.scheduler) document.getElementById('set-check-interval').value = data.scheduler.check_interval_minutes || 5;
        if (data.gallery) {
            document.getElementById('set-max-entries').value = data.gallery.max_entries || 5000;
            document.getElementById('set-max-thumbs').value = data.gallery.max_thumbnails || 5000;
        }
    } catch (e) {}
}

async function saveSettings() {
    try {
        await api('/api/settings', {
            method: 'PUT',
            body: {
                scraping: {
                    min_width: parseInt(document.getElementById('set-min-width').value),
                    min_height: parseInt(document.getElementById('set-min-height').value),
                    max_pages: parseInt(document.getElementById('set-max-pages').value),
                    page_delay_seconds: parseInt(document.getElementById('set-page-delay').value),
                    max_concurrent_downloads: parseInt(document.getElementById('set-max-dl').value),
                    allowed_aspects: Array.from(document.querySelectorAll('.aspect-cb:checked')).map(cb => cb.value),
                    allow_mobile: document.getElementById('set-allow-mobile').checked,
                    watermark_detection: document.getElementById('set-watermark-detection').checked,
                    allow_nsfw: document.getElementById('set-allow-nsfw').checked,
                },
                jpeg: { quality: parseInt(document.getElementById('set-jpeg-quality').value) },
                scheduler: { check_interval_minutes: parseInt(document.getElementById('set-check-interval').value) },
                gallery: {
                    max_entries: parseInt(document.getElementById('set-max-entries').value),
                    max_thumbnails: parseInt(document.getElementById('set-max-thumbs').value),
                },
            }
        });
        toast('Settings saved', 'success');
    } catch (e) { toast('Failed to save settings', 'error'); }
}

// ==================== FAVICON ====================
async function uploadFavicon() {
    const input = document.getElementById('favicon-file');
    if (!input.files || input.files.length === 0) {
        toast('Select a file first', 'error');
        return;
    }
    const file = input.files[0];
    if (file.size > 512000) {
        toast('File too large (max 500KB)', 'error');
        return;
    }
    const formData = new FormData();
    formData.append('file', file);
    try {
        const res = await fetch('/api/favicon', { method: 'POST', body: formData });
        if (!res.ok) throw new Error(await res.text());
        toast('Favicon uploaded', 'success');
        // Refresh favicon in browser
        document.getElementById('favicon-preview').src = '/favicon.ico?' + Date.now();
        const link = document.querySelector('link[rel="icon"]');
        if (link) link.href = '/favicon.ico?' + Date.now();
        document.getElementById('favicon-status').textContent = 'Custom favicon active';
    } catch (e) {
        toast('Upload failed: ' + e.message, 'error');
    }
}

async function deleteFavicon() {
    try {
        await api('/api/favicon', { method: 'DELETE' });
        toast('Favicon reset to default', 'success');
        document.getElementById('favicon-preview').src = '/favicon.ico?' + Date.now();
        const link = document.querySelector('link[rel="icon"]');
        if (link) link.href = '/favicon.ico?' + Date.now();
        document.getElementById('favicon-status').textContent = 'Using default favicon';
    } catch (e) {
        toast('Reset failed', 'error');
    }
}

// ==================== BASEROW ====================
async function loadBaserowConfig() {
    try {
        const data = await api('/api/baserow/status');
        document.getElementById('br-url').value = data.api_url || '';
        document.getElementById('br-table-id').value = data.table_id || '';
        if (data.configured && data.field_mapping_verified) {
            document.getElementById('field-mapping-section').style.display = '';
            loadFieldMapping();
        }
    } catch (e) {}
}

function toggleTokenVisibility() {
    const input = document.getElementById('br-token');
    input.type = input.type === 'password' ? 'text' : 'password';
}

async function testBaserow() {
    const resultEl = document.getElementById('br-test-result');
    resultEl.innerHTML = '<span class="spinner"></span> Testing...';
    try {
        // Save first
        await api('/api/baserow/config', {
            method: 'PUT',
            body: {
                api_url: document.getElementById('br-url').value.trim(),
                api_token: document.getElementById('br-token').value.trim(),
                table_id: parseInt(document.getElementById('br-table-id').value) || 0,
            }
        });
        const result = await api('/api/baserow/test', { method: 'POST' });
        if (result.success) {
            resultEl.innerHTML = `<span style="color:var(--success)">&#10003; Connected! ${result.fields_count} fields found.</span>`;
            document.getElementById('field-mapping-section').style.display = '';
            autoMatchFields();
        } else {
            resultEl.innerHTML = `<span style="color:var(--error)">&#10007; ${esc(result.error || 'Connection failed')}</span>`;
        }
    } catch (e) {
        resultEl.innerHTML = `<span style="color:var(--error)">&#10007; ${esc(e.message)}</span>`;
    }
}

async function saveBaserow() {
    try {
        await api('/api/baserow/config', {
            method: 'PUT',
            body: {
                api_url: document.getElementById('br-url').value.trim(),
                api_token: document.getElementById('br-token').value.trim(),
                table_id: parseInt(document.getElementById('br-table-id').value) || 0,
            }
        });
        toast('Baserow config saved! Seeds loaded. Scheduler starting.', 'success');
    } catch (e) { toast('Save failed', 'error'); }
}

async function autoMatchFields() {
    try {
        const data = await api('/api/baserow/fields');
        tableFieldsCache = data.table_fields || [];
        currentMapping = data.suggested_mapping || {};
        renderMappingTable(data);
    } catch (e) { toast('Failed to fetch fields: ' + e.message, 'error'); }
}

async function refreshFields() { await autoMatchFields(); }

function renderMappingTable(data) {
    const tbody = document.getElementById('mapping-table');
    const results = data.match_results || [];
    const allFields = (data.table_fields || []).map(f => f.name);
    let matched = 0;

    tbody.innerHTML = results.map(r => {
        const isMatched = r.match_type !== 'none';
        if (isMatched) matched++;
        const current = currentMapping[r.scraper_field] || '';
        const statusIcon = r.match_type === 'exact' ? '&#10003;' :
            r.match_type === 'case_insensitive' ? '&#128260;' :
            r.match_type === 'fuzzy' ? '&#128269;' : '&#9888;';
        const statusClass = r.match_type === 'none' ? 'color:var(--warning)' : 'color:var(--success)';
        return `
            <tr>
                <td><code>${esc(r.scraper_field)}</code></td>
                <td style="text-align:center">&rarr;</td>
                <td>
                    <select onchange="currentMapping['${r.scraper_field}']=this.value">
                        <option value="">-- Not mapped --</option>
                        ${allFields.map(f => `<option value="${esc(f)}" ${f === current ? 'selected' : ''}>${esc(f)}</option>`).join('')}
                    </select>
                </td>
                <td class="mapping-status" style="${statusClass}">${statusIcon} ${r.match_type}</td>
            </tr>
        `;
    }).join('');

    const total = results.length;
    const bar = document.getElementById('mapping-bar');
    const allGood = matched === total;
    bar.innerHTML = `
        <span>${matched}/${total} mapped ${allGood ? '&#10003; Ready' : '&#9888; ' + (total-matched) + ' need attention'}</span>
        <span style="color:${allGood ? 'var(--success)' : 'var(--warning)'}">${allGood ? 'All fields mapped' : 'Some fields unmatched'}</span>
    `;
}

async function loadFieldMapping() {
    try {
        const data = await api('/api/baserow/field-mapping');
        currentMapping = data.field_mapping || {};
        if (tableFieldsCache.length === 0) {
            await autoMatchFields();
        }
    } catch (e) {}
}

async function saveMapping() {
    try {
        await api('/api/baserow/field-mapping', { method: 'PUT', body: { field_mapping: currentMapping } });
        toast('Field mapping saved', 'success');
    } catch (e) { toast('Failed to save mapping', 'error'); }
}

async function resetMapping() {
    try {
        await api('/api/baserow/field-mapping/reset', { method: 'POST' });
        toast('Mapping reset to defaults', 'info');
        autoMatchFields();
    } catch (e) { toast('Reset failed', 'error'); }
}

// ==================== BROWSE BASEROW ====================
let browsePage = 1;
const BROWSE_PAGE_SIZE = 40;
let browseFieldMapping = {};
let browseApiUrl = '';

async function loadBrowse(page) {
    if (page !== undefined) browsePage = page;
    else browsePage = 1;

    // Check if Baserow is configured
    try {
        const status = await api('/api/baserow/status');
        if (!status.configured) {
            document.getElementById('browse-unconfigured').style.display = '';
            document.getElementById('browse-main').style.display = 'none';
            return;
        }
        document.getElementById('browse-unconfigured').style.display = 'none';
        document.getElementById('browse-main').style.display = '';
    } catch (e) {
        document.getElementById('browse-unconfigured').style.display = '';
        document.getElementById('browse-main').style.display = 'none';
        return;
    }

    const search = document.getElementById('browse-search').value.trim();
    const sort = document.getElementById('browse-sort').value;

    let url = `/api/baserow/rows?page=${browsePage}&size=${BROWSE_PAGE_SIZE}`;
    if (search) url += `&search=${encodeURIComponent(search)}`;
    if (sort) url += `&order_by=${encodeURIComponent(sort)}`;

    // Show loading state
    const loadBtn = document.getElementById('browse-load-btn');
    const loadingBanner = document.getElementById('browse-loading-banner');
    if (loadBtn) { loadBtn.disabled = true; loadBtn.textContent = 'Loading...'; }
    if (loadingBanner) loadingBanner.style.display = '';

    try {
        const data = await api(url);
        browseFieldMapping = data.field_mapping || {};
        browseApiUrl = data.api_url || '';
        const rows = data.results || [];
        const total = data.count || 0;
        const totalPages = Math.ceil(total / BROWSE_PAGE_SIZE);

        document.getElementById('browse-count').textContent = `${total} wallpapers`;
        renderBrowseGrid(rows);
        renderBrowsePagination(browsePage, totalPages, total);
    } catch (e) {
        document.getElementById('browse-grid').innerHTML =
            '<div class="empty-state"><div class="empty-state-icon">&#9888;</div><div class="empty-state-text">Failed to load</div><div class="empty-state-hint">' + esc(e.message) + '</div></div>';
        document.getElementById('browse-pagination').innerHTML = '';
        document.getElementById('browse-count').textContent = '';
    } finally {
        if (loadBtn) { loadBtn.disabled = false; loadBtn.textContent = 'Load from Baserow'; }
        if (loadingBanner) loadingBanner.style.display = 'none';
    }
}

function retryAllBrowseImages() {
    const errorDivs = document.querySelectorAll('.browse-img-error');
    if (errorDivs.length === 0) {
        toast('No failed images to retry', 'info');
        return;
    }
    errorDivs.forEach(div => {
        const retryBtn = div.querySelector('.browse-retry-btn');
        if (retryBtn) retryBtn.click();
    });
    toast(`Retrying ${errorDivs.length} images...`, 'info');
}

function browseField(row, scraperField) {
    const colName = browseFieldMapping[scraperField] || scraperField;
    return row[colName];
}

function directFileUrl(mediaPath) {
    // Build a URL via the direct /api/baserow/file/ endpoint.
    // This avoids all URL encoding/hostname issues — just pass the media path.
    // e.g. "/media/user_files/abc.jpg" -> "/api/baserow/file/user_files/abc.jpg"
    //      "http://baserow:8080/media/thumbnails/small/abc.jpg"
    //        -> "/api/baserow/file/thumbnails/small/abc.jpg"
    if (!mediaPath) return '';

    // Extract the path after /media/
    let path = mediaPath;
    const mediaIdx = path.indexOf('/media/');
    if (mediaIdx >= 0) {
        path = path.substring(mediaIdx + 7); // after "/media/"
    } else if (path.startsWith('/')) {
        // Relative path like /media/... already handled, try stripping leading /
        path = path.replace(/^\/+/, '');
    } else if (path.startsWith('http')) {
        // Full URL — extract path component
        try {
            const u = new URL(path);
            const mi = u.pathname.indexOf('/media/');
            if (mi >= 0) {
                path = u.pathname.substring(mi + 7);
            } else {
                path = u.pathname.replace(/^\/+/, '');
            }
        } catch (e) { /* keep as-is */ }
    }
    return '/api/baserow/file/' + path;
}

function proxyImgUrl(rawUrl) {
    // Fallback: route through the image-proxy endpoint (handles URL rewriting)
    if (!rawUrl) return '';
    if (rawUrl.startsWith('/')) {
        rawUrl = browseApiUrl.replace(/\/+$/, '') + rawUrl;
    }
    if (browseApiUrl && rawUrl.startsWith('http')) {
        try {
            const urlObj = new URL(rawUrl);
            const apiObj = new URL(browseApiUrl);
            if (urlObj.host !== apiObj.host) {
                rawUrl = apiObj.origin + urlObj.pathname + urlObj.search;
            }
        } catch (e) { /* keep rawUrl as-is */ }
    }
    if (rawUrl && !rawUrl.startsWith('http') && !rawUrl.startsWith('/')) {
        rawUrl = browseApiUrl.replace(/\/+$/, '') + '/' + rawUrl;
    }
    return '/api/baserow/image-proxy?url=' + encodeURIComponent(rawUrl);
}

function browseFileUrl(file) {
    // Extract best URL from a Baserow file object.
    if (!file) return '';
    if (file.url) return file.url;
    if (file.name) return '/media/user_files/' + file.name;
    return '';
}

function browseThumbnailUrl(row) {
    // Primary: use direct file endpoint (most reliable for Docker setups).
    // Tries thumbnail variants first, then full image.
    const fileField = browseField(row, 'imageFile');
    if (!fileField || !Array.isArray(fileField) || fileField.length === 0) return '';
    const file = fileField[0];

    // Try Baserow thumbnail variants via direct endpoint
    if (file.thumbnails) {
        const thumb = file.thumbnails.small || file.thumbnails.tiny || file.thumbnails.card_cover;
        if (thumb && thumb.url) return directFileUrl(thumb.url);
    }

    // Fall back to full image via direct endpoint
    const fileUrl = browseFileUrl(file);
    if (fileUrl) return directFileUrl(fileUrl);

    return '';
}

function browseImageUrl(row) {
    const fileField = browseField(row, 'imageFile');
    if (!fileField || !Array.isArray(fileField) || fileField.length === 0) return '';
    const fileUrl = browseFileUrl(fileField[0]);
    return fileUrl ? directFileUrl(fileUrl) : '';
}

function renderBrowseGrid(rows) {
    const grid = document.getElementById('browse-grid');
    if (!rows || rows.length === 0) {
        grid.innerHTML = '<div class="empty-state"><div class="empty-state-icon">&#128444;</div><div class="empty-state-text">No wallpapers found</div><div class="empty-state-hint">Upload wallpapers by scraping sources, or adjust your search.</div></div>';
        return;
    }
    // Stash rows for retry logic
    window._browseRows = rows;

    grid.innerHTML = rows.map((row, idx) => {
        const title = browseField(row, 'wallpaperTitle') || 'Untitled';
        const width = browseField(row, 'Width') || 0;
        const height = browseField(row, 'Height') || 0;
        const thumb = browseThumbnailUrl(row);
        const isMobile = browseField(row, 'isMobile');
        const rowId = row.id;
        const hasThumb = !!thumb;
        return `
            <div class="browse-item ${hasThumb ? 'browse-item-loading' : ''}" id="browse-item-${rowId}" onclick="showBrowseDetail(${rowId})">
                ${hasThumb ? `
                    <img src="${esc(thumb)}" alt="${esc(title)}" loading="lazy"
                        onload="this.parentElement.classList.remove('browse-item-loading')"
                        onerror="handleBrowseImgError(this, ${rowId}, ${idx})">
                ` : `
                    <div class="browse-img-error">
                        <span class="browse-img-error-icon">&#128444;</span>
                        <span>No image file</span>
                    </div>
                `}
                <div class="browse-badge">${width}x${height}${isMobile ? ' M' : ''}</div>
                <div class="browse-overlay">
                    <div class="browse-overlay-title">${esc(title)}</div>
                </div>
            </div>
        `;
    }).join('');
}

function handleBrowseImgError(img, rowId, idx) {
    // Cascading fallback: direct full -> proxy thumbnail -> proxy full
    const row = window._browseRows && window._browseRows[idx];
    const retryCount = parseInt(img.dataset.retried || '0');

    if (row && retryCount === 0) {
        // Attempt 1: direct endpoint with full image
        img.dataset.retried = '1';
        const fullUrl = browseImageUrl(row);
        if (fullUrl && fullUrl !== img.src) { img.src = fullUrl; return; }
    }
    if (row && retryCount <= 1) {
        // Attempt 2: proxy endpoint with thumbnail
        img.dataset.retried = '2';
        const fileField = browseField(row, 'imageFile');
        if (fileField && Array.isArray(fileField) && fileField.length > 0) {
            const file = fileField[0];
            const thumbObj = file.thumbnails && (file.thumbnails.small || file.thumbnails.tiny);
            const tryUrl = thumbObj ? proxyImgUrl(thumbObj.url) : proxyImgUrl(browseFileUrl(file));
            if (tryUrl && tryUrl !== img.src) { img.src = tryUrl; return; }
        }
    }
    if (row && retryCount <= 2) {
        // Attempt 3: proxy endpoint with full image
        img.dataset.retried = '3';
        const fileField = browseField(row, 'imageFile');
        if (fileField && Array.isArray(fileField) && fileField.length > 0) {
            const tryUrl = proxyImgUrl(browseFileUrl(fileField[0]));
            if (tryUrl && tryUrl !== img.src) { img.src = tryUrl; return; }
        }
    }
    // All fallbacks exhausted — show error state with retry button
    img.style.display = 'none';
    const container = img.parentElement;
    container.classList.remove('browse-item-loading');
    const errorDiv = document.createElement('div');
    errorDiv.className = 'browse-img-error';
    errorDiv.innerHTML = `
        <span class="browse-img-error-icon">&#128444;</span>
        <span>Image unavailable</span>
        <button class="browse-retry-btn" onclick="retryBrowseImage(event, ${rowId}, ${idx})">Retry</button>
    `;
    container.insertBefore(errorDiv, container.firstChild);
}

function retryBrowseImage(event, rowId, idx) {
    event.stopPropagation();
    const container = document.getElementById('browse-item-' + rowId);
    if (!container) return;
    const row = window._browseRows && window._browseRows[idx];
    if (!row) return;

    // Remove error state
    const errorDiv = container.querySelector('.browse-img-error');
    if (errorDiv) errorDiv.remove();

    // Re-create img with cache-busting
    const thumb = browseThumbnailUrl(row);
    const title = browseField(row, 'wallpaperTitle') || '';
    const cacheBust = thumb + (thumb.includes('?') ? '&' : '?') + '_t=' + Date.now();

    const existingImg = container.querySelector('img');
    if (existingImg) existingImg.remove();

    container.classList.add('browse-item-loading');
    const newImg = document.createElement('img');
    newImg.src = cacheBust;
    newImg.alt = title;
    newImg.loading = 'lazy';
    newImg.onload = () => container.classList.remove('browse-item-loading');
    newImg.onerror = () => handleBrowseImgError(newImg, rowId, idx);
    container.insertBefore(newImg, container.firstChild);
}

function renderBrowsePagination(current, totalPages, total) {
    const el = document.getElementById('browse-pagination');
    if (totalPages <= 1) { el.innerHTML = ''; return; }

    let html = '';
    // Previous button
    if (current > 1) {
        html += `<button class="btn btn-sm btn-secondary" onclick="loadBrowse(${current - 1})">&laquo; Prev</button>`;
    }

    // Page numbers (show max 7 pages around current)
    const start = Math.max(1, current - 3);
    const end = Math.min(totalPages, current + 3);
    if (start > 1) {
        html += `<button class="btn btn-sm btn-secondary" onclick="loadBrowse(1)">1</button>`;
        if (start > 2) html += `<span class="browse-page-ellipsis">...</span>`;
    }
    for (let i = start; i <= end; i++) {
        if (i === current) {
            html += `<button class="btn btn-sm btn-primary browse-page-active">${i}</button>`;
        } else {
            html += `<button class="btn btn-sm btn-secondary" onclick="loadBrowse(${i})">${i}</button>`;
        }
    }
    if (end < totalPages) {
        if (end < totalPages - 1) html += `<span class="browse-page-ellipsis">...</span>`;
        html += `<button class="btn btn-sm btn-secondary" onclick="loadBrowse(${totalPages})">${totalPages}</button>`;
    }

    // Next button
    if (current < totalPages) {
        html += `<button class="btn btn-sm btn-secondary" onclick="loadBrowse(${current + 1})">Next &raquo;</button>`;
    }

    el.innerHTML = html;
}

async function showBrowseDetail(rowId) {
    try {
        const row = await api(`/api/baserow/rows/${rowId}`);
        const fm = row.field_mapping || browseFieldMapping;
        const detailApiUrl = row.api_url || browseApiUrl;
        const getF = (key) => { const col = fm[key] || key; return row[col]; };

        const title = getF('wallpaperTitle') || 'Untitled';
        const width = getF('Width') || 0;
        const height = getF('Height') || 0;
        const imgUrl = getF('imgUrl') || '';
        const altText = getF('altText') || '';
        const artist = getF('artistText') || '';
        const artistLink = getF('artistLink') || '';
        const tags = getF('categoryTags') || '';
        const isMobile = getF('isMobile');
        const imgHash = getF('imgHash') || '';

        // Get full image URL from file field via direct endpoint
        const fileField = getF('imageFile');
        let fullImgUrl = '';
        if (fileField && Array.isArray(fileField) && fileField.length > 0) {
            fullImgUrl = directFileUrl(browseFileUrl(fileField[0]));
        }

        showModal(`
            <div class="modal-header">
                <h3>${esc(title)}</h3>
                <button class="modal-close" onclick="closeModal()">&times;</button>
            </div>
            <div style="text-align:center;margin-bottom:1.5rem">
                <a href="${esc(fullImgUrl)}" target="_blank">
                    <img src="${esc(fullImgUrl)}" style="max-width:100%;max-height:60vh;border-radius:var(--radius-md);cursor:zoom-in" alt="${esc(altText)}">
                </a>
            </div>
            <table>
                <tr><td style="color:var(--text-tertiary);width:120px">Title</td><td>${esc(title)}</td></tr>
                <tr><td style="color:var(--text-tertiary)">Alt Text</td><td>${esc(altText)}</td></tr>
                <tr><td style="color:var(--text-tertiary)">Tags</td><td>${esc(tags)}</td></tr>
                <tr><td style="color:var(--text-tertiary)">Resolution</td><td>${width}x${height}</td></tr>
                <tr><td style="color:var(--text-tertiary)">Mobile</td><td>${isMobile ? 'Yes' : 'No'}</td></tr>
                ${artist ? `<tr><td style="color:var(--text-tertiary)">Artist</td><td>${artistLink ? `<a href="${esc(artistLink)}" target="_blank" style="color:var(--accent)">${esc(artist)}</a>` : esc(artist)}</td></tr>` : ''}
                <tr><td style="color:var(--text-tertiary)">Hash</td><td style="font-family:'SF Mono',SFMono-Regular,Menlo,monospace;font-size:12px">${esc(imgHash)}</td></tr>
                ${imgUrl ? `<tr><td style="color:var(--text-tertiary)">Source URL</td><td><a href="${esc(imgUrl)}" target="_blank" style="color:var(--accent)">${esc(imgUrl.substring(0, 60))}...</a></td></tr>` : ''}
                <tr><td style="color:var(--text-tertiary)">Baserow Row</td><td>#${rowId}</td></tr>
            </table>
            <div style="margin-top:1.5rem;text-align:center">
                <a href="${esc(fullImgUrl)}" download class="btn btn-primary btn-sm" target="_blank">Download Full Size</a>
            </div>
        `);
    } catch (e) { toast('Failed to load wallpaper details', 'error'); }
}

// Browse search debounce
let browseSearchTimeout;
document.getElementById('browse-search').addEventListener('input', () => {
    clearTimeout(browseSearchTimeout);
    browseSearchTimeout = setTimeout(() => loadBrowse(), 500);
});
document.getElementById('browse-sort').addEventListener('change', () => loadBrowse());

// ==================== STATS ====================
async function loadStats() {
    try {
        const data = await api('/api/stats');
        const summary = data.summary || {};
        document.getElementById('stats-summary').innerHTML = `
            <div class="stat-card"><div class="stat-value">${summary.total || 0}</div><div class="stat-label">Total Processed</div></div>
            <div class="stat-card"><div class="stat-value">${summary.uploaded || 0}</div><div class="stat-label">Uploaded</div></div>
            <div class="stat-card"><div class="stat-value">${summary.duplicates || 0}</div><div class="stat-label">Duplicates</div></div>
            <div class="stat-card"><div class="stat-value">${summary.errors || 0}</div><div class="stat-label">Errors</div></div>
            <div class="stat-card"><div class="stat-value">${data.total_sources || 0}</div><div class="stat-label">Total Sources</div></div>
            <div class="stat-card"><div class="stat-value">${data.enabled_sources || 0}</div><div class="stat-label">Enabled Sources</div></div>
        `;

        const sourcesTbody = document.getElementById('stats-sources');
        const sources = data.sources || [];
        sourcesTbody.innerHTML = sources.map(s => `
            <tr>
                <td>${esc(s.name)}</td>
                <td><span class="badge badge-${s.category}">${s.category}</span></td>
                <td>${s.total_uploaded || 0}</td>
                <td>${s.total_dupes || 0}</td>
                <td>${s.total_errors || 0}</td>
                <td>${timeAgo(s.last_scraped)}</td>
            </tr>
        `).join('') || '<tr><td colspan="6" style="color:var(--text-muted)">No source data</td></tr>';

        const disc = data.discovery || {};
        document.getElementById('stats-discovery').innerHTML = `
            <div class="stat-grid" style="margin-bottom:0">
                <div class="stat-card">
                    <div class="stat-value" style="font-size:1.5rem">${disc.total_queries || 0}</div>
                    <div class="stat-label">Total Queries</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value" style="font-size:1.5rem">${disc.builtin_queries || 0}</div>
                    <div class="stat-label">Built-in</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value" style="font-size:1.5rem">${disc.user_queries || 0}</div>
                    <div class="stat-label">User Queries</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value" style="font-size:1.5rem">${disc.total_sources_discovered || 0}</div>
                    <div class="stat-label">Sources Discovered</div>
                </div>
            </div>
        `;
    } catch (e) {}
}

// === Utilities ===
function esc(s) {
    if (!s) return '';
    const div = document.createElement('div');
    div.textContent = String(s);
    return div.innerHTML;
}

// ==================== ARROW KEY GALLERY NAVIGATION ====================
let galleryEntries = [];   // Cached entry IDs for keyboard navigation
let gallerySelectedIdx = -1; // Currently selected gallery item index

// Update cached entries when gallery renders
function updateGalleryEntries() {
    const items = document.querySelectorAll('.gallery-item');
    galleryEntries = Array.from(items);
    // Clear selection if gallery was reloaded
    gallerySelectedIdx = -1;
}

function selectGalleryItem(idx) {
    if (galleryEntries.length === 0) return;
    // Clamp index
    idx = Math.max(0, Math.min(idx, galleryEntries.length - 1));

    // Remove previous selection highlight
    if (gallerySelectedIdx >= 0 && gallerySelectedIdx < galleryEntries.length) {
        galleryEntries[gallerySelectedIdx].classList.remove('gallery-selected');
    }

    gallerySelectedIdx = idx;
    const item = galleryEntries[idx];
    item.classList.add('gallery-selected');

    // Scroll item into view smoothly
    item.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'nearest' });
}

document.addEventListener('keydown', (e) => {
    // Only handle arrow keys when gallery tab is active and no modal is open
    const galleryTab = document.getElementById('tab-gallery');
    if (!galleryTab || !galleryTab.classList.contains('active')) return;
    const modal = document.getElementById('modal-overlay');
    if (modal && modal.classList.contains('active')) {
        // In modal: Escape closes it
        if (e.key === 'Escape') { closeModal(); e.preventDefault(); }
        return;
    }

    // Don't intercept when typing in inputs
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT') return;

    updateGalleryEntries();
    if (galleryEntries.length === 0) return;

    if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
        e.preventDefault();
        if (gallerySelectedIdx < 0) {
            selectGalleryItem(0);
        } else {
            selectGalleryItem(gallerySelectedIdx + 1);
        }
    } else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
        e.preventDefault();
        if (gallerySelectedIdx < 0) {
            selectGalleryItem(0);
        } else {
            selectGalleryItem(gallerySelectedIdx - 1);
        }
    } else if (e.key === 'Enter') {
        // Open detail view for selected item
        if (gallerySelectedIdx >= 0 && gallerySelectedIdx < galleryEntries.length) {
            e.preventDefault();
            galleryEntries[gallerySelectedIdx].click();
        }
    }
});

// ==================== LOGS VIEWER ====================
let logsPolling = null;

function startLogsPolling() {
    logsPolling = setInterval(loadLogs, 5000);
}

async function loadLogs() {
    const level = document.getElementById('logs-level-filter').value;
    const lines = document.getElementById('logs-line-count').value;
    let url = `/api/logs?lines=${lines}`;
    if (level) url += `&level=${encodeURIComponent(level)}`;

    try {
        const data = await api(url);
        const container = document.getElementById('logs-container');
        const totalEl = document.getElementById('logs-total');

        if (totalEl) totalEl.textContent = `${data.total || 0} total lines`;

        if (!data.lines || data.lines.length === 0) {
            container.innerHTML = '<div style="color:var(--text-muted);padding:2rem;text-align:center">No log entries found</div>';
            return;
        }

        container.innerHTML = data.lines.map(line => {
            const parsed = parseLogLine(line);
            return `<div class="log-line ${parsed.levelClass}">${parsed.html}</div>`;
        }).join('');

        // Auto-scroll to bottom
        const autoScroll = document.getElementById('logs-auto-scroll');
        if (autoScroll && autoScroll.checked) {
            container.scrollTop = container.scrollHeight;
        }
    } catch (e) {
        const container = document.getElementById('logs-container');
        container.innerHTML = `<div style="color:var(--error);padding:2rem;text-align:center">Failed to load logs: ${esc(e.message)}</div>`;
    }
}

function parseLogLine(line) {
    // Log format: 2024-01-15 12:30:45,123 | INFO     | scraper.engine | Some message
    const match = line.match(/^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}[,\.]\d+)\s*\|\s*(\w+)\s*\|\s*([^\|]+)\|\s*(.*)/);
    if (match) {
        const timestamp = match[1];
        const level = match[2].trim();
        const name = match[3].trim();
        const message = match[4];
        const levelLower = level.toLowerCase();
        const levelClass = 'log-level-' + levelLower;
        const html = `<span class="log-timestamp">${esc(timestamp)}</span> | <span class="${levelClass}">${esc(level.padEnd(8))}</span> | <span class="log-name">${esc(name)}</span> | ${esc(message)}`;
        return { html, levelClass };
    }
    // Unstructured line — return as-is
    return { html: esc(line), levelClass: '' };
}

// === Init ===
window.addEventListener('DOMContentLoaded', () => {
    loadGallerySummary();
    loadGallery();
    startGalleryPolling();
    startGlobalStatusPolling();
});
