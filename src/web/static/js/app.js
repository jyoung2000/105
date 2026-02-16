/* Wallpaper Scraper GUI — Vanilla JS */
let galleryOffset = 0;
const GALLERY_LIMIT = 50;
let galleryPolling = null;
let jobsPolling = null;
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
    if (tab === 'scrape') { checkBaserowStatus(); loadScrapeJobs(); }
    if (tab === 'sources') { loadSources(); loadQueries(); loadSchedulerStatus(); }
    if (tab === 'jobs') { loadJobs(); startJobsPolling(); }
    if (tab === 'settings') { loadSettings(); }
    if (tab === 'baserow') { loadBaserowConfig(); }
    if (tab === 'stats') { loadStats(); }
}

function stopPolling() {
    if (galleryPolling) { clearInterval(galleryPolling); galleryPolling = null; }
    if (jobsPolling) { clearInterval(jobsPolling); jobsPolling = null; }
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
            feed.innerHTML = '<div class="empty-state"><div class="empty-state-text">No activity yet</div><div class="empty-state-hint">Configure Baserow and start scraping!</div></div>';
            return;
        }
        feed.innerHTML = data.entries.map(e => `
            <div class="activity-item" onclick="showEntryDetail('${e.id}')">
                <img class="activity-thumb" src="/${e.thumbnail_path || ''}" alt="" loading="lazy" onerror="this.src='data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 width=%2250%22 height=%2250%22><rect fill=%22%231e2a4a%22 width=%2250%22 height=%2250%22/></svg>'">
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
        document.getElementById('gallery-grid').innerHTML = '<div class="empty-state"><div class="empty-state-icon">&#128444;</div><div class="empty-state-text">No wallpapers yet</div><div class="empty-state-hint">Go to the Baserow tab to connect, then start scraping!</div></div>';
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
        if (!append) grid.innerHTML = '<div class="empty-state"><div class="empty-state-icon">&#128444;</div><div class="empty-state-text">No wallpapers yet</div><div class="empty-state-hint">Go to the Baserow tab to connect, then start scraping!</div></div>';
        return;
    }
    const html = entries.map(e => `
        <div class="gallery-item" onclick="showEntryDetail('${e.id}')">
            <img src="/${e.thumbnail_path || ''}" alt="${esc(e.alt_text || '')}" loading="lazy"
                onerror="this.src='data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 width=%22200%22 height=%22200%22><rect fill=%22%231e2a4a%22 width=%22200%22 height=%22200%22/></svg>'">
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
            <div style="text-align:center;margin-bottom:1rem">
                <img src="/${e.thumbnail_path || ''}" style="max-width:100%;border-radius:6px" alt="">
            </div>
            <table>
                <tr><td style="color:var(--text-secondary)">Alt Text</td><td>${esc(e.alt_text || '')}</td></tr>
                <tr><td style="color:var(--text-secondary)">Tags</td><td>${esc(e.tags || '')}</td></tr>
                <tr><td style="color:var(--text-secondary)">Resolution</td><td>${e.width}x${e.height} (${e.aspect_ratio})</td></tr>
                <tr><td style="color:var(--text-secondary)">Mobile</td><td>${e.is_mobile ? 'Yes' : 'No'}</td></tr>
                <tr><td style="color:var(--text-secondary)">Source</td><td>${esc(e.source_name || '')}</td></tr>
                <tr><td style="color:var(--text-secondary)">File Size</td><td>${e.file_size_kb || 0} KB</td></tr>
                <tr><td style="color:var(--text-secondary)">Hash</td><td style="font-family:monospace;font-size:0.8rem">${esc(e.img_hash || '')}</td></tr>
                <tr><td style="color:var(--text-secondary)">Status</td><td><span class="badge badge-${e.status}">${e.status}</span></td></tr>
                <tr><td style="color:var(--text-secondary)">Baserow Row</td><td>${e.baserow_row_id || 'N/A'}</td></tr>
                <tr><td style="color:var(--text-secondary)">URL</td><td><a href="${esc(e.img_url || '')}" target="_blank" style="color:var(--accent)">${esc((e.img_url||'').substring(0,60))}...</a></td></tr>
                <tr><td style="color:var(--text-secondary)">Time</td><td>${e.timestamp || ''}</td></tr>
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
        if (jobs.length === 0) { el.innerHTML = '<div style="color:var(--text-muted)">No recent jobs</div>'; return; }
        el.innerHTML = jobs.map(j => `
            <div class="card" style="padding:0.8rem">
                <div style="display:flex;justify-content:space-between;align-items:center">
                    <div>
                        <strong>${esc(j.source_name || j.url || '')}</strong>
                        <span class="badge badge-${j.status === 'running' ? 'running' : j.status === 'completed' ? 'success' : 'error'}">${j.status}</span>
                    </div>
                    <span style="font-size:0.8rem;color:var(--text-muted)">${timeAgo(j.started_at)}</span>
                </div>
                ${j.status === 'running' ? `<div class="progress" style="margin-top:0.5rem"><div class="progress-bar" style="width:${j.progress||0}%"></div></div>` : ''}
                <div style="font-size:0.8rem;color:var(--text-secondary);margin-top:0.3rem">
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
            tbody.innerHTML = '<tr><td colspan="9" style="text-align:center;color:var(--text-muted)">No sources. Configure Baserow first.</td></tr>';
            return;
        }
        tbody.innerHTML = data.sources.map(s => `
            <tr>
                <td><label class="toggle"><input type="checkbox" ${s.enabled ? 'checked' : ''} onchange="toggleSource('${s.id}')"><span class="toggle-slider"></span></label></td>
                <td>${esc(s.name)}<br><span style="font-size:0.7rem;color:var(--text-muted)">${esc(s.domain || '')}</span></td>
                <td><span class="badge badge-${s.category}">${s.category}</span></td>
                <td>${s.schedule_hours}h</td>
                <td>${timeAgo(s.last_scraped)}</td>
                <td>${s.last_scrape_count || 0} uploaded</td>
                <td>${s.total_uploaded || 0} / ${s.total_dupes || 0} / ${s.total_errors || 0}</td>
                <td><span class="status-dot ${(s.consecutive_failures || 0) < 5 ? 'healthy' : 'unhealthy'}"></span></td>
                <td>
                    <button class="btn btn-sm btn-secondary" onclick="scrapeSource('${s.id}')">Scrape</button>
                    <button class="btn btn-sm btn-danger" onclick="deleteSource('${s.id}')">Del</button>
                </td>
            </tr>
        `).join('');
    } catch (e) {}
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
        <div class="modal-header"><h3>Add Source</h3><button class="modal-close" onclick="closeModal()">&times;</button></div>
        <div class="form-group"><label>URL</label><input type="text" id="add-source-url" placeholder="https://..."></div>
        <div class="form-group"><label>Name</label><input type="text" id="add-source-name" placeholder="Source name"></div>
        <div class="form-group"><label>Schedule (hours)</label><input type="number" id="add-source-schedule" value="12"></div>
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
            <div class="card" style="padding:0.8rem;margin-bottom:0.5rem">
                <div style="display:flex;justify-content:space-between;align-items:center">
                    <div>
                        <strong>${esc(j.source_name || j.url || 'Unknown')}</strong>
                        <span class="badge badge-${j.status === 'running' ? 'running' : j.status === 'completed' ? 'success' : 'error'}">${j.status}</span>
                    </div>
                    <span style="font-size:0.8rem;color:var(--text-muted)">${timeAgo(j.started_at)} ${j.completed_at ? '- ' + timeAgo(j.completed_at) : ''}</span>
                </div>
                ${j.status === 'running' ? `<div class="progress" style="margin-top:0.5rem"><div class="progress-bar" style="width:${j.progress||0}%"></div></div>` : ''}
                <div style="font-size:0.8rem;color:var(--text-secondary);margin-top:0.3rem">
                    Pages: ${j.pages_scraped || 0}/${j.max_pages || '?'} | Found: ${j.images_found || 0} | Downloaded: ${j.images_downloaded || 0} | Uploaded: ${j.images_uploaded || 0} | Dupes: ${j.duplicates || 0} | Errors: ${j.errors || 0}
                </div>
                ${(j.error_log && j.error_log.length > 0) ? `<div style="font-size:0.75rem;color:var(--error);margin-top:0.3rem;max-height:80px;overflow-y:auto">${j.error_log.map(e => esc(e)).join('<br>')}</div>` : ''}
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
            <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:1rem">
                <div><strong>${disc.total_queries || 0}</strong><br><span style="color:var(--text-secondary);font-size:0.8rem">Total Queries</span></div>
                <div><strong>${disc.builtin_queries || 0}</strong><br><span style="color:var(--text-secondary);font-size:0.8rem">Built-in</span></div>
                <div><strong>${disc.user_queries || 0}</strong><br><span style="color:var(--text-secondary);font-size:0.8rem">User Queries</span></div>
                <div><strong>${disc.total_sources_discovered || 0}</strong><br><span style="color:var(--text-secondary);font-size:0.8rem">Sources Discovered</span></div>
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

// === Init ===
window.addEventListener('DOMContentLoaded', () => {
    loadGallerySummary();
    loadGallery();
    startGalleryPolling();
});
