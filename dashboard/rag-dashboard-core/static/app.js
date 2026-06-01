const state = {
    apiKey: localStorage.getItem("rag_api_key") || "",
    theme: localStorage.getItem("rag_theme") || "dark",
    activeTab: "dashboard",
    documentStatusFilter: "all",
    documentStatusFiles: [],
    documentStatusPageSize: 25,
    documentStatusPage: 1,
    documentStatusSort: null,
    rawDataItems: [],
    rawDataPageSize: 25,
    rawDataPage: 1,
    rawDataSort: null,
    ingestRunning: false,
    ingestPollTimer: null,
    dashboardPollTimer: null,
    elapsedTimerInterval: null,
    processingStartTimes: { ingest: null, transform: null, vectorize: null },
};

const themeToggle = document.getElementById("theme-toggle");
const statusIndicator = document.getElementById("status-indicator");
const statusText = document.getElementById("status-text");
const tabDashboard = document.getElementById("tab-dashboard");
const tabDocumentStatus = document.getElementById("tab-document-status");
const tabRawData = document.getElementById("tab-raw-data");
const dashboardPanel = document.getElementById("dashboard-panel");
const documentStatusPanel = document.getElementById("document-status-panel");
const documentStatusTableBody = document.querySelector("#document-status-table tbody");
const documentStatusEmpty = document.getElementById("document-status-empty");
const refreshDocumentStatusBtn = document.getElementById("refresh-document-status");
const ingestBtn = document.getElementById("ingest-btn");
const restartIngestBtn = document.getElementById("restart-ingest-btn");
const ingestStatus = document.getElementById("ingest-status");
const ingestStatusLabel = document.getElementById("ingest-status-label");
const ingestStatusCurrentFile = document.getElementById("ingest-status-current-file");
const documentStatusFilterButtons = document.querySelectorAll(".document-status-filter");
const rawDataPanel = document.getElementById("raw-data-panel");
const rawDataTableBody = document.querySelector("#raw-data-table tbody");
const rawDataEmpty = document.getElementById("raw-data-empty");
const refreshRawDataBtn = document.getElementById("refresh-raw-data");
const documentStatusPageSizeSelect = document.getElementById("document-status-page-size");
const documentStatusPageInfo = document.getElementById("document-status-page-info");
const documentStatusPrevBtn = document.getElementById("document-status-prev");
const documentStatusNextBtn = document.getElementById("document-status-next");
const rawDataPageSizeSelect = document.getElementById("raw-data-page-size");
const rawDataPageInfo = document.getElementById("raw-data-page-info");
const rawDataPrevBtn = document.getElementById("raw-data-prev");
const rawDataNextBtn = document.getElementById("raw-data-next");
const documentStatusTable = document.getElementById("document-status-table");
const rawDataTable = document.getElementById("raw-data-table");

// Initialize
document.body.setAttribute("data-theme", state.theme);
themeToggle.textContent = state.theme === "light" ? "🌙" : "☀️";

/**
 * Build common HTTP request headers for API calls.
 *
 * @param {boolean} [jsonBody=false] - Include Content-Type: application/json.
 * @param {boolean} [dashboardConfirm=false] - Include X-Dashboard-Confirm: yes for destructive actions.
 * @returns {Object} Headers object ready for use with fetch().
 */
function apiHeaders(jsonBody = false, dashboardConfirm = false) {
    const h = {};
    if (jsonBody) h["Content-Type"] = "application/json";
    if (state.apiKey) h["X-API-Key"] = state.apiKey;
    if (dashboardConfirm) h["X-Dashboard-Confirm"] = "yes";
    return h;
}

let statusPollStarted = false;

/**
 * Escape special HTML characters to prevent XSS injection.
 *
 * @param {*} text - Value to escape; null/undefined are coerced to empty string.
 * @returns {string} HTML-safe string.
 */
function escapeHtml(text) {
    return String(text ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

/**
 * Locale-insensitive case-insensitive string comparator for sorting.
 *
 * @param {*} a - First value to compare.
 * @param {*} b - Second value to compare.
 * @returns {number} -1, 0, or 1 suitable for Array.prototype.sort().
 */
function compareStrings(a, b) {
    const sa = String(a ?? "").toLowerCase();
    const sb = String(b ?? "").toLowerCase();
    if (sa < sb) return -1;
    if (sa > sb) return 1;
    return 0;
}

/**
 * Numeric comparator that sorts non-finite values (null, undefined, NaN) to the end.
 *
 * @param {*} a - First value to compare.
 * @param {*} b - Second value to compare.
 * @returns {number} -1, 0, or 1 suitable for Array.prototype.sort().
 */
function compareNullableNumber(a, b) {
    const na = Number(a);
    const nb = Number(b);
    const aValid = Number.isFinite(na);
    const bValid = Number.isFinite(nb);
    if (!aValid && !bValid) return 0;
    if (!aValid) return 1;
    if (!bValid) return -1;
    if (na < nb) return -1;
    if (na > nb) return 1;
    return 0;
}

/**
 * Return a sorted copy of an item array using a key-based comparator registry.
 *
 * @param {Array} items - Array of objects to sort.
 * @param {{key: string, direction: 'asc'|'desc'}|null} sort - Active sort state, or null for no sort.
 * @param {Object.<string, function>} getters - Map of sort key → comparator function(a, b).
 * @returns {Array} New sorted array (original is not mutated).
 */
function sortRows(items, sort, getters) {
    if (!sort || !getters[sort.key]) return items;
    const mult = sort.direction === "desc" ? -1 : 1;
    return [...items].sort((a, b) => mult * getters[sort.key](a, b));
}

/**
 * Slice an array to a single page and compute pagination metadata.
 *
 * @param {Array} items - Full sorted dataset.
 * @param {number|'all'} pageSize - Rows per page, or 'all' to return all rows.
 * @param {number} page - Requested 1-based page number.
 * @returns {{rows: Array, page: number, totalPages: number, totalItems: number, start: number, end: number}}
 */
function paginateSlice(items, pageSize, page) {
    const totalItems = items.length;
    if (pageSize === "all" || totalItems === 0) {
        return {
            rows: items,
            page: 1,
            totalPages: 1,
            totalItems,
            start: totalItems ? 1 : 0,
            end: totalItems,
        };
    }
    const size = Number(pageSize) || 25;
    const totalPages = Math.max(1, Math.ceil(totalItems / size));
    const clampedPage = Math.min(Math.max(1, page), totalPages);
    const startIndex = (clampedPage - 1) * size;
    const endIndex = Math.min(startIndex + size, totalItems);
    return {
        rows: items.slice(startIndex, endIndex),
        page: clampedPage,
        totalPages,
        totalItems,
        start: totalItems ? startIndex + 1 : 0,
        end: endIndex,
    };
}

/**
 * Update pagination info text and Prev/Next button disabled states.
 *
 * @param {{totalItems: number, page: number, totalPages: number, start: number, end: number}} meta
 *   Pagination metadata from paginateSlice().
 * @param {HTMLElement|null} infoEl - Element displaying the "Showing X–Y of Z" text.
 * @param {HTMLButtonElement|null} prevBtn - Previous page button.
 * @param {HTMLButtonElement|null} nextBtn - Next page button.
 */
function updatePaginationUI(meta, infoEl, prevBtn, nextBtn) {
    if (!infoEl) return;
    if (meta.totalItems === 0) {
        infoEl.textContent = "No rows";
    } else {
        infoEl.textContent = `Showing ${meta.start}–${meta.end} of ${meta.totalItems} (page ${meta.page} of ${meta.totalPages})`;
    }
    if (prevBtn) prevBtn.disabled = meta.page <= 1 || meta.totalPages <= 1;
    if (nextBtn) nextBtn.disabled = meta.page >= meta.totalPages || meta.totalPages <= 1;
}

/**
 * Update sort indicator CSS classes and aria-sort attributes in a table header.
 *
 * @param {HTMLElement|null} tableEl - The table element whose .sortable-th headers are updated.
 * @param {{key: string, direction: 'asc'|'desc'}|null} sort - Current sort state, or null for no sort.
 */
function updateSortHeaderUI(tableEl, sort) {
    if (!tableEl) return;
    tableEl.querySelectorAll(".sortable-th").forEach((th) => {
        const key = th.dataset.sortKey;
        th.classList.remove("sort-asc", "sort-desc");
        if (sort && sort.key === key) {
            th.classList.add(sort.direction === "desc" ? "sort-desc" : "sort-asc");
            th.setAttribute("aria-sort", sort.direction === "desc" ? "descending" : "ascending");
        } else {
            th.setAttribute("aria-sort", "none");
        }
    });
}

/**
 * Compute the next sort state after a header click, toggling direction on the same key.
 *
 * @param {{key: string, direction: 'asc'|'desc'}|null} currentSort - Current sort state.
 * @param {string} sortKey - Column key that was clicked.
 * @returns {{key: string, direction: 'asc'|'desc'}} New sort state.
 */
function handleSortClick(currentSort, sortKey) {
    if (currentSort?.key === sortKey) {
        return {
            key: sortKey,
            direction: currentSort.direction === "asc" ? "desc" : "asc",
        };
    }
    return { key: sortKey, direction: "asc" };
}

/**
 * Build the URL for opening a raw file via the dashboard API.
 *
 * @param {string} driveFileId - Unique identifier of the file record.
 * @returns {string} Relative URL with optional api_key query parameter.
 */
function fileOpenUrl(driveFileId) {
    const encodedId = encodeURIComponent(String(driveFileId || ""));
    const params = new URLSearchParams();
    if (state.apiKey) {
        params.set("api_key", state.apiKey);
    }
    const qs = params.toString();
    return `/files/${encodedId}/open${qs ? `?${qs}` : ""}`;
}

/**
 * Map a pipeline status string to a simplified extraction status label.
 *
 * @param {string} pipelineStatus - File record status value (e.g. 'embedded', 'failed').
 * @returns {'completed'|'failed'|'pending'} Simplified extraction status.
 */
function extractionStatusForPipelineStatus(pipelineStatus) {
    if (pipelineStatus === "embedded" || pipelineStatus === "converted") return "completed";
    if (pipelineStatus === "failed") return "failed";
    return "pending";
}

const documentStatusSortGetters = {
    name: (a, b) => compareStrings(a.name || a.drive_file_id, b.name || b.drive_file_id),
    mime_type: (a, b) => compareStrings(a.mime_type, b.mime_type),
    status: (a, b) => compareStrings(a.status, b.status),
    extraction: (a, b) =>
        compareStrings(
            extractionStatusForPipelineStatus(a.status),
            extractionStatusForPipelineStatus(b.status)
        ),
    raw_text: (a, b) => {
        const av = a.raw_text_available === true ? 1 : 0;
        const bv = b.raw_text_available === true ? 1 : 0;
        if (av < bv) return -1;
        if (av > bv) return 1;
        return 0;
    },
    chunks: (a, b) => compareNullableNumber(a.chunk_count, b.chunk_count),
    last_processed: (a, b) => compareStrings(a.last_processed_at, b.last_processed_at),
    error: (a, b) => compareStrings(a.error_message, b.error_message),
};

const rawDataSortGetters = {
    name: (a, b) => compareStrings(a.name || a.drive_file_id, b.name || b.drive_file_id),
    mime_type: (a, b) => compareStrings(a.mime_type, b.mime_type),
    status: (a, b) => compareStrings(a.status, b.status),
    last_processed: (a, b) => compareStrings(a.last_processed_at, b.last_processed_at),
    extracted_text: (a, b) => {
        const la = (a.extracted_text || "").length;
        const lb = (b.extracted_text || "").length;
        if (la < lb) return -1;
        if (la > lb) return 1;
        return 0;
    },
};

/**
 * Render a page of file status rows into the document status table body.
 *
 * @param {Array<Object>} files - Array of file status objects from the /status/files endpoint.
 */
function renderDocumentStatusRows(files) {
    if (!documentStatusTableBody) return;
    documentStatusTableBody.innerHTML = "";

    files.forEach((file) => {
        const row = document.createElement("tr");
        const extractionStatus = extractionStatusForPipelineStatus(file.status);
        const rawTextAvailable = file.raw_text_available === true;
        if (!rawTextAvailable) {
            row.classList.add("row-missing-text");
        }
        const rawTextStatus = rawTextAvailable ? "Yes" : "No";
        const rawTextMissingReason = !rawTextAvailable && file.raw_text_missing_reason
            ? `<div class="raw-text-missing-reason">${escapeHtml(file.raw_text_missing_reason)}</div>`
            : "";
        row.innerHTML = `
            <td><a class="file-link" href="${fileOpenUrl(file.drive_file_id)}" target="_blank" rel="noopener noreferrer">${escapeHtml(file.name || file.drive_file_id)}</a></td>
            <td>${escapeHtml(file.mime_type || "-")}</td>
            <td><span class="status-pill">${escapeHtml(file.status || "pending")}</span></td>
            <td><span class="status-pill">${escapeHtml(extractionStatus)}</span></td>
            <td><span class="status-pill">${rawTextStatus}</span>${rawTextMissingReason}</td>
            <td>${Number.isFinite(file.chunk_count) ? file.chunk_count : "-"}</td>
            <td>${escapeHtml(file.last_processed_at || "-")}</td>
            <td>${escapeHtml(file.error_message || "-")}</td>
        `;
        documentStatusTableBody.appendChild(row);
    });
}

/**
 * Return a human-readable label for the file currently in the ingestion pipeline.
 *
 * @param {Array<Object>} files - Document status file objects.
 * @returns {string} Label string for the currently processing file, or a waiting message.
 */
function ingestingFileLabel(files) {
    const inProgress = files.find((file) => ["pending", "downloaded", "converted"].includes(file.status || ""));
    if (!inProgress) return "Waiting for pipeline updates...";
    const name = inProgress.name || inProgress.drive_file_id || "Unknown file";
    const status = inProgress.status || "pending";
    return `Current file: ${name} (${status})`;
}

/**
 * Poll the pipeline status and update the ingest status bar.
 * Clears the poll timer when all files have finished processing.
 */
async function refreshIngestStatus() {
    try {
        const statusRes = await fetch("/status", { headers: apiHeaders() });
        if (!statusRes.ok) throw new Error(`status ${statusRes.status}`);
        const status = await statusRes.json();
        await loadDocumentStatus();

        if (!ingestStatus || !ingestStatusLabel || !ingestStatusCurrentFile) return;
        const processingCount = Number(status.pending || 0) + Number(status.downloaded || 0) + Number(status.converted || 0);
        const failed = Number(status.failed || 0);
        ingestStatusLabel.textContent = `Ingestion running... ${processingCount} files in pipeline${failed > 0 ? `, ${failed} failed` : ""}.`;
        ingestStatusCurrentFile.textContent = ingestingFileLabel(state.documentStatusFiles);

        if (processingCount === 0) {
            state.ingestRunning = false;
            if (state.ingestPollTimer) {
                clearInterval(state.ingestPollTimer);
                state.ingestPollTimer = null;
            }
            ingestStatusLabel.textContent = "Ingestion finished.";
            ingestStatusCurrentFile.textContent = failed > 0
                ? "Review the table for failed files and missing extracted text."
                : "All files finished processing.";
            if (ingestBtn) ingestBtn.disabled = false;
            if (restartIngestBtn) restartIngestBtn.disabled = false;
            setTimeout(() => {
                if (!state.ingestRunning && ingestStatus) ingestStatus.hidden = true;
            }, 4000);
        }
    } catch (err) {
        if (ingestStatusLabel) {
            ingestStatusLabel.textContent = `Could not refresh ingestion status: ${err.message || String(err)}`;
        }
        if (ingestStatusCurrentFile) {
            ingestStatusCurrentFile.textContent = "Check API availability and worker logs.";
        }
        if (ingestBtn) ingestBtn.disabled = false;
        if (restartIngestBtn) restartIngestBtn.disabled = false;
        state.ingestRunning = false;
        if (state.ingestPollTimer) {
            clearInterval(state.ingestPollTimer);
            state.ingestPollTimer = null;
        }
    }
}

/**
 * Prompt for confirmation, then POST /ingest to queue an incremental sync job,
 * and start polling ingest status every 2.5 s.
 */
async function triggerIngest() {
    const confirmed = window.confirm(
        "Esta acción iniciará una nueva ingesta y los cambios anteriores se perderán. ¿Deseas continuar?"
    );
    if (!confirmed) return;

    const res = await fetch("/ingest", {
        method: "POST",
        headers: apiHeaders(),
    });
    if (!res.ok) {
        throw new Error(`ingest ${res.status}`);
    }

    state.ingestRunning = true;
    if (ingestBtn) ingestBtn.disabled = true;
    if (restartIngestBtn) restartIngestBtn.disabled = true;
    if (ingestStatus) ingestStatus.hidden = false;
    if (ingestStatusLabel) ingestStatusLabel.textContent = "Ingestion queued. Waiting for worker...";
    if (ingestStatusCurrentFile) ingestStatusCurrentFile.textContent = "Preparing first file...";

    if (state.ingestPollTimer) clearInterval(state.ingestPollTimer);
    state.ingestPollTimer = setInterval(() => {
        refreshIngestStatus().catch((e) => console.error("ingest status", e));
    }, 2500);
    await refreshIngestStatus();
}

/**
 * Prompt for confirmation, then POST /ingest/restart to clear artifacts and queue a full re-ingestion,
 * and start polling ingest status every 2.5 s.
 */
async function triggerRestartIngest() {
    const confirmed = window.confirm(
        "Esta acción reiniciará la ingesta: intentará limpiar MinIO/Milvus/metadata y luego lanzará una nueva ingesta. ¿Deseas continuar?"
    );
    if (!confirmed) return;

    const res = await fetch("/ingest/restart", {
        method: "POST",
        headers: apiHeaders(),
    });
    if (!res.ok) {
        throw new Error(`ingest/restart ${res.status}`);
    }

    state.ingestRunning = true;
    if (ingestBtn) ingestBtn.disabled = true;
    if (restartIngestBtn) restartIngestBtn.disabled = true;
    if (ingestStatus) ingestStatus.hidden = false;
    if (ingestStatusLabel) ingestStatusLabel.textContent = "Restart ingestion queued. Cleaning previous artifacts...";
    if (ingestStatusCurrentFile) ingestStatusCurrentFile.textContent = "Waiting for worker tasks...";

    if (state.ingestPollTimer) clearInterval(state.ingestPollTimer);
    state.ingestPollTimer = setInterval(() => {
        refreshIngestStatus().catch((e) => console.error("ingest status", e));
    }, 2500);
    await refreshIngestStatus();
}

/**
 * Return the current file status list filtered by the active filter button selection.
 *
 * @returns {Array<Object>} Filtered subset of state.documentStatusFiles.
 */
function filteredDocumentStatusFiles() {
    if (state.documentStatusFilter === "raw-text-missing") {
        return state.documentStatusFiles.filter((file) => file.raw_text_available !== true);
    }
    return state.documentStatusFiles;
}

/**
 * Re-render the document status table with current filter, sort, and pagination state.
 * Updates the sort header UI and pagination controls without fetching new data.
 */
function refreshDocumentStatusTable() {
    const filtered = filteredDocumentStatusFiles();
    const sorted = sortRows(filtered, state.documentStatusSort, documentStatusSortGetters);
    const meta = paginateSlice(sorted, state.documentStatusPageSize, state.documentStatusPage);
    state.documentStatusPage = meta.page;
    if (documentStatusEmpty) documentStatusEmpty.hidden = meta.totalItems > 0;
    updateSortHeaderUI(documentStatusTable, state.documentStatusSort);
    updatePaginationUI(meta, documentStatusPageInfo, documentStatusPrevBtn, documentStatusNextBtn);
    renderDocumentStatusRows(meta.rows);
}

/**
 * Fetch document status files from the API and refresh the table.
 * Resets the page to 1 and shows an error row on fetch failure.
 */
async function loadDocumentStatus() {
    if (!documentStatusTableBody || !documentStatusEmpty) return;
    state.documentStatusPage = 1;
    try {
        const res = await fetch("/status/files", { headers: apiHeaders() });
        if (!res.ok) throw new Error(`status/files ${res.status}`);
        const files = await res.json();
        state.documentStatusFiles = Array.isArray(files) ? files : [];
        refreshDocumentStatusTable();
    } catch (err) {
        state.documentStatusFiles = [];
        if (documentStatusEmpty) documentStatusEmpty.hidden = true;
        renderDocumentStatusRows([]);
        const row = document.createElement("tr");
        row.innerHTML = `<td colspan="8">Could not load document status: ${escapeHtml(err.message || String(err))}</td>`;
        documentStatusTableBody.appendChild(row);
        updatePaginationUI(
            { totalItems: 0, page: 1, totalPages: 1, start: 0, end: 0 },
            documentStatusPageInfo,
            documentStatusPrevBtn,
            documentStatusNextBtn
        );
    }
}

/**
 * Render a page of raw data rows into the raw data table body.
 * Long extracted text is collapsed behind a "Show more" toggle button.
 *
 * @param {Array<Object>} items - Raw data objects from the /status/raw-data endpoint.
 */
function renderRawDataRows(items) {
    if (!rawDataTableBody) return;
    rawDataTableBody.innerHTML = "";
    const previewThreshold = 280;

    items.forEach((item) => {
        const row = document.createElement("tr");
        const extractedText = item.extracted_text?.trim() || "No extracted text available yet.";
        const isLongText = extractedText.length > previewThreshold;
        row.innerHTML = `
            <td><a class="file-link" href="${fileOpenUrl(item.drive_file_id)}" target="_blank" rel="noopener noreferrer">${escapeHtml(item.name || item.drive_file_id)}</a></td>
            <td>${escapeHtml(item.mime_type || "-")}</td>
            <td><span class="status-pill">${escapeHtml(item.status || "pending")}</span></td>
            <td>${escapeHtml(item.last_processed_at || "-")}</td>
            <td>
                <pre class="raw-data-preview ${isLongText ? "is-collapsed" : ""}">${escapeHtml(extractedText)}</pre>
                ${isLongText ? '<button type="button" class="raw-data-toggle">Show more</button>' : ""}
            </td>
        `;
        if (isLongText) {
            const toggleBtn = row.querySelector(".raw-data-toggle");
            const preview = row.querySelector(".raw-data-preview");
            toggleBtn?.addEventListener("click", () => {
                const expanded = preview?.classList.toggle("is-expanded");
                preview?.classList.toggle("is-collapsed", !expanded);
                toggleBtn.textContent = expanded ? "Show less" : "Show more";
            });
        }
        rawDataTableBody.appendChild(row);
    });
}

/**
 * Re-render the raw data table with current sort and pagination state without fetching new data.
 */
function refreshRawDataTable() {
    const sorted = sortRows(state.rawDataItems, state.rawDataSort, rawDataSortGetters);
    const meta = paginateSlice(sorted, state.rawDataPageSize, state.rawDataPage);
    state.rawDataPage = meta.page;
    if (rawDataEmpty) rawDataEmpty.hidden = meta.totalItems > 0;
    updateSortHeaderUI(rawDataTable, state.rawDataSort);
    updatePaginationUI(meta, rawDataPageInfo, rawDataPrevBtn, rawDataNextBtn);
    renderRawDataRows(meta.rows);
}

/**
 * Fetch raw data items from the API and refresh the table.
 * Resets the page to 1 and shows an error row on fetch failure.
 */
async function loadRawData() {
    if (!rawDataTableBody || !rawDataEmpty) return;
    state.rawDataPage = 1;
    try {
        const res = await fetch("/status/raw-data", { headers: apiHeaders() });
        if (!res.ok) throw new Error(`status/raw-data ${res.status}`);
        const items = await res.json();
        state.rawDataItems = Array.isArray(items) ? items : [];
        refreshRawDataTable();
    } catch (err) {
        state.rawDataItems = [];
        if (rawDataEmpty) rawDataEmpty.hidden = true;
        renderRawDataRows([]);
        const row = document.createElement("tr");
        row.innerHTML = `<td colspan="5">Could not load extracted data: ${escapeHtml(err.message || String(err))}</td>`;
        rawDataTableBody.appendChild(row);
        updatePaginationUI(
            { totalItems: 0, page: 1, totalPages: 1, start: 0, end: 0 },
            rawDataPageInfo,
            rawDataPrevBtn,
            rawDataNextBtn
        );
    }
}

/**
 * Generate an HTML string for a single dashboard metric tile.
 *
 * @param {string} label - Human-readable label for the metric.
 * @param {string|number} value - Metric value to display.
 * @returns {string} HTML string for the metric row element.
 */
function metricRow(label, value) {
    return `<div class="dash-metric"><span>${escapeHtml(label)}</span><strong>${escapeHtml(String(value))}</strong></div>`;
}

/**
 * Build a MinIO web console URL for a given bucket and object key.
 *
 * @param {string} bucket - MinIO bucket name.
 * @param {string|null|undefined} key - Object key within the bucket.
 * @returns {string|null} Full MinIO console URL, or null if key is falsy.
 */
function minioConsoleUrl(bucket, key) {
    if (!key) return null;
    return `http://${window.location.hostname}:9001/browser/${encodeURIComponent(bucket)}/${encodeURIComponent(key)}`;
}

/**
 * Generate an HTML string for the currently in-flight file row in a dashboard card.
 *
 * @param {{name: string, minio_bucket: string, minio_key: string}|null} file
 *   In-flight file descriptor, or null/undefined if no file is in-flight.
 * @returns {string} HTML string with a MinIO link, or empty string if file is absent.
 */
function inflightFileRow(file) {
    if (!file || !file.name) return "";
    const url = minioConsoleUrl(file.minio_bucket, file.minio_key);
    const nameHtml = url
        ? `<a class="inflight-file-link" href="${url}" target="_blank" rel="noopener">${escapeHtml(file.name)}</a>`
        : escapeHtml(file.name);
    return `<div class="dash-inflight-file">${nameHtml}</div>`;
}

/**
 * Format a millisecond duration as HH:MM:SS.
 *
 * @param {number} ms - Elapsed milliseconds.
 * @returns {string} Zero-padded time string in HH:MM:SS format.
 */
function formatElapsed(ms) {
    const s = Math.floor(ms / 1000);
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const sec = s % 60;
    return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
}

/**
 * Update the text and data-paused attribute of a pause/resume toggle button.
 *
 * @param {string} btnId - ID of the button element to update.
 * @param {boolean} isPaused - True if the pipeline stage is currently paused.
 */
function updatePauseButton(btnId, isPaused) {
    const btn = document.getElementById(btnId);
    if (!btn) return;
    btn.dataset.paused = isPaused ? "true" : "false";
    btn.textContent = isPaused ? "▶ Resume" : "⏸ Pause";
}

/**
 * Update a pipeline stage label element with 'Processing HH:MM:SS' or 'Idle'.
 * Records the start time in state when a stage transitions to active.
 *
 * @param {HTMLElement|null} el - Label element to update.
 * @param {string} key - State key ('ingest', 'transform', 'vectorize').
 * @param {boolean} isProcessing - True if the stage is currently active.
 */
function setProcessingLabel(el, key, isProcessing) {
    if (!el) return;
    if (isProcessing) {
        if (state.processingStartTimes[key] === null) state.processingStartTimes[key] = Date.now();
        const elapsed = formatElapsed(Date.now() - state.processingStartTimes[key]);
        el.innerHTML = `Processing <span class="elapsed-time">${elapsed}</span>`;
    } else {
        state.processingStartTimes[key] = null;
        el.textContent = "Idle";
    }
}

/**
 * Tick all active pipeline stage labels to show the current elapsed time.
 * Called by a 1-second interval while the dashboard tab is visible.
 */
function updateElapsedLabels() {
    const now = Date.now();
    for (const [key, id] of [["ingest", "label-ingest"], ["transform", "label-transform"], ["vectorize", "label-vectorize"]]) {
        if (state.processingStartTimes[key] !== null) {
            const el = document.getElementById(id);
            if (el) {
                const elapsed = formatElapsed(now - state.processingStartTimes[key]);
                el.innerHTML = `Processing <span class="elapsed-time">${elapsed}</span>`;
            }
        }
    }
}

/**
 * Fetch the dashboard state from the API and update all metric cards, processing indicators,
 * pause buttons, and the source URL link.
 */
async function loadDashboard() {
    const elRaw = document.getElementById("dash-metrics-raw");
    const elTf = document.getElementById("dash-metrics-transform");
    const elPg = document.getElementById("dash-metrics-postgres");
    const elMv = document.getElementById("dash-metrics-milvus");
    const elSs = document.getElementById("dash-metrics-sessions");
    const srcLink = document.getElementById("dash-source-url");
    const updated = document.getElementById("dashboard-updated");
    try {
        const res = await fetch("/dashboard/state", { headers: apiHeaders() });
        if (!res.ok) throw new Error(`dashboard ${res.status}`);
        const data = await res.json();
        const c = data.cards || {};

        const folderLabel = c.source_total == null ? "—" : c.source_total;
        const notIngestedYet = c.source_total == null
            ? "—"
            : Math.max(0, c.source_total - (c.minio_raw_total ?? 0));
        elRaw.innerHTML = [
            metricRow("Folder files", folderLabel),
            metricRow("MinIO RAW objects", c.minio_raw_total ?? 0),
            metricRow("Not ingested yet", notIngestedYet),
            metricRow("RAW pending (DB)", c.raw_pending ?? 0),
        ].join("");

        elTf.innerHTML = [
            metricRow("Total (raw synced)", c.transform_total ?? 0),
            metricRow("Transformed (text ready)", c.transform_done ?? 0),
            metricRow("Vision OCR (waiting)", (c.vision_pending_files ?? 0) - (c.vision_processing_files ?? 0)),
            metricRow("Vision OCR (running)", c.vision_processing_files ?? 0),
            metricRow("Text failed", c.text_failed ?? 0),
            metricRow("In-flight (extract)", c.text_processing_now ?? 0),
            inflightFileRow(data.transform_inflight_file),
        ].join("");

        elPg.innerHTML = [
            metricRow("Rows", c.postgres_total ?? 0),
            metricRow("Missing vs source", c.postgres_missing ?? 0),
            metricRow("To reprocess", c.postgres_to_reprocess ?? 0),
        ].join("");

        elMv.innerHTML = [
            metricRow("Vectors (entities)", c.milvus_vectors ?? 0),
            metricRow("Files embedded", c.milvus_files_vectorized ?? 0),
            metricRow("Pending embed", c.milvus_pending_files ?? 0),
            inflightFileRow(data.milvus_inflight_file),
        ].join("");

        elSs.innerHTML = [
            metricRow("Legacy (conv:*)", c.sessions_legacy ?? 0),
            metricRow("Chatbot v2", c.sessions_chatbot_v2 ?? 0),
        ].join("");

        if (srcLink && data.source_url) {
            srcLink.href = data.source_url;
            srcLink.textContent = data.source_url.length > 60 ? data.source_url.slice(0, 60) + "…" : data.source_url;
        }

        const dotIn = document.getElementById("dot-ingest");
        const dotTf = document.getElementById("dot-transform");
        const dotV = document.getElementById("dot-vectorize");
        if (dotIn) {
            dotIn.setAttribute("data-state", data.ingest_processing ? "running" : "idle");
        }
        if (dotTf) {
            dotTf.setAttribute("data-state", data.transform_processing ? "running" : "idle");
        }
        if (dotV) {
            dotV.setAttribute("data-state", data.vectorize_processing ? "running" : "idle");
        }
        setProcessingLabel(document.getElementById("label-ingest"), "ingest", data.ingest_processing);
        setProcessingLabel(document.getElementById("label-transform"), "transform", data.transform_processing);
        setProcessingLabel(document.getElementById("label-vectorize"), "vectorize", data.vectorize_processing);

        const iconRaw = document.getElementById("file-icon-raw");
        const iconTf = document.getElementById("file-icon-transform");
        const iconMv = document.getElementById("file-icon-milvus");
        if (iconRaw) iconRaw.classList.toggle("is-blinking", !!data.ingest_processing);
        if (iconTf) iconTf.classList.toggle("is-blinking", !!data.transform_processing);
        if (iconMv) iconMv.classList.toggle("is-blinking", !!data.vectorize_processing);

        updatePauseButton("btn-pause-ingest", !!data.ingest_paused);
        updatePauseButton("btn-pause-transform", !!data.transform_paused);
        updatePauseButton("btn-pause-vectorize", !!data.vectorize_paused);

        if (updated && data.updated_at) {
            updated.textContent = `Updated: ${data.updated_at}`;
        }
    } catch (err) {
        const msg = err?.message || String(err);
        if (elRaw) elRaw.innerHTML = `<div class="dash-error">${escapeHtml(msg)}</div>`;
    }
}

const tabUsers          = document.getElementById("tab-users");
const usersPanel        = document.getElementById("users-panel");
const tabResponses      = document.getElementById("tab-responses");
const responsesPanel    = document.getElementById("responses-panel");
const responsesTableBody = document.getElementById("responses-table-body");
const responsesEmpty    = document.getElementById("responses-empty");
const usersTableBody   = document.getElementById("users-table-body");
const usersEmpty       = document.getElementById("users-empty");
const createUserBtn    = document.getElementById("create-user-btn");
const newUsernameEl    = document.getElementById("new-username");
const newPasswordEl    = document.getElementById("new-password");
const usersCreateError = document.getElementById("users-create-error");
const usersCreateOk    = document.getElementById("users-create-ok");
const refreshUsersBtn  = document.getElementById("refresh-users-btn");

/**
 * Fetch the list of chat users from the API and populate the users table.
 * Each row has a delete button that calls DELETE /users/{username} with a confirmation prompt.
 */
async function loadUsers() {
    if (usersEmpty) usersEmpty.hidden = true;
    if (usersTableBody) usersTableBody.innerHTML = "";
    const res = await fetch("/users", { headers: apiHeaders() });
    if (!res.ok) throw new Error(`users ${res.status}`);
    const users = await res.json();
    if (users.length === 0) {
        if (usersEmpty) usersEmpty.hidden = false;
        return;
    }
    users.forEach((u) => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
            <td>${escapeHtml(u.username)}</td>
            <td><button type="button" class="danger" data-username="${escapeHtml(u.username)}">Borrar</button></td>
        `;
        tr.querySelector("button").addEventListener("click", async () => {
            if (!confirm(`¿Eliminar usuario "${u.username}"?`)) return;
            const delRes = await fetch(`/users/${encodeURIComponent(u.username)}`, {
                method: "DELETE",
                headers: apiHeaders(),
            });
            if (!delRes.ok) { alert("Error al eliminar usuario"); return; }
            await loadUsers();
        });
        if (usersTableBody) usersTableBody.appendChild(tr);
    });
}

if (createUserBtn) {
    createUserBtn.addEventListener("click", async () => {
        if (usersCreateError) usersCreateError.hidden = true;
        if (usersCreateOk) usersCreateOk.hidden = true;
        const username = newUsernameEl?.value.trim() || "";
        const password = newPasswordEl?.value || "";
        if (!/^[a-z0-9]{1,10}$/.test(username)) {
            if (usersCreateError) {
                usersCreateError.textContent = "Usuario inválido: solo letras minúsculas y números, máx 10 caracteres.";
                usersCreateError.hidden = false;
            }
            return;
        }
        if (!password) {
            if (usersCreateError) {
                usersCreateError.textContent = "La contraseña no puede estar vacía.";
                usersCreateError.hidden = false;
            }
            return;
        }
        try {
            const res = await fetch("/users", {
                method: "POST",
                headers: apiHeaders(true),
                body: JSON.stringify({ username, password }),
            });
            if (res.status === 409) {
                if (usersCreateError) {
                    usersCreateError.textContent = "El usuario ya existe.";
                    usersCreateError.hidden = false;
                }
                return;
            }
            if (!res.ok) throw new Error(await res.text());
            if (usersCreateOk) {
                usersCreateOk.textContent = `Usuario "${username}" creado.`;
                usersCreateOk.hidden = false;
            }
            if (newUsernameEl) newUsernameEl.value = "";
            if (newPasswordEl) newPasswordEl.value = "";
            await loadUsers();
        } catch (e) {
            if (usersCreateError) {
                usersCreateError.textContent = `Error: ${e.message || String(e)}`;
                usersCreateError.hidden = false;
            }
        }
    });
}

refreshUsersBtn?.addEventListener("click", () => {
    loadUsers().catch((e) => console.error("users refresh", e));
});

/**
 * Fetch the 500 most recent chat interactions from the API and populate the responses table
 * with question, answer, rating emoji, and optional correction text.
 */
async function loadResponses() {
    if (responsesEmpty) responsesEmpty.hidden = true;
    if (responsesTableBody) responsesTableBody.innerHTML = "";
    try {
        const res = await fetch("/responses", { headers: apiHeaders() });
        if (!res.ok) throw new Error(`responses ${res.status}`);
        const items = await res.json();
        if (items.length === 0) {
            if (responsesEmpty) responsesEmpty.hidden = false;
            return;
        }
        items.forEach((item) => {
            const ratingIcon = item.rating === "positive" ? "👍" : item.rating === "negative" ? "👎" : "—";
            const tr = document.createElement("tr");
            tr.innerHTML = `
                <td class="responses-cell">${escapeHtml(item.username || "—")}</td>
                <td class="responses-cell">${escapeHtml(item.question)}</td>
                <td class="responses-cell">${escapeHtml(item.answer)}</td>
                <td class="responses-rating">${ratingIcon}</td>
                <td class="responses-cell">${escapeHtml(item.correction || "—")}</td>
            `;
            if (responsesTableBody) responsesTableBody.appendChild(tr);
        });
    } catch (err) {
        if (responsesTableBody) {
            const tr = document.createElement("tr");
            tr.innerHTML = `<td colspan="5">Error al cargar respuestas: ${escapeHtml(err.message || String(err))}</td>`;
            responsesTableBody.appendChild(tr);
        }
    }
}

/**
 * Switch the visible tab and trigger lazy loading of its data.
 * Starts the dashboard poll and elapsed-time ticker when switching to the dashboard tab,
 * and clears them when leaving it.
 *
 * @param {'dashboard'|'document-status'|'raw-data'|'users'|'responses'} nextTab - Tab identifier.
 */
function setActiveTab(nextTab) {
    state.activeTab = nextTab;
    const dashboardIsActive = nextTab === "dashboard";
    const statusIsActive = nextTab === "document-status";
    const rawDataIsActive = nextTab === "raw-data";
    const usersIsActive = nextTab === "users";
    const responsesIsActive = nextTab === "responses";
    tabDashboard?.classList.toggle("active", dashboardIsActive);
    tabDocumentStatus?.classList.toggle("active", statusIsActive);
    tabRawData?.classList.toggle("active", rawDataIsActive);
    tabUsers?.classList.toggle("active", usersIsActive);
    tabResponses?.classList.toggle("active", responsesIsActive);
    if (dashboardPanel) dashboardPanel.hidden = !dashboardIsActive;
    if (documentStatusPanel) documentStatusPanel.hidden = !statusIsActive;
    if (rawDataPanel) rawDataPanel.hidden = !rawDataIsActive;
    if (usersPanel) usersPanel.hidden = !usersIsActive;
    if (responsesPanel) responsesPanel.hidden = !responsesIsActive;
    if (statusIsActive) {
        loadDocumentStatus().catch((e) => console.error("document status", e));
    }
    if (rawDataIsActive) {
        loadRawData().catch((e) => console.error("raw data", e));
    }
    if (usersIsActive) {
        loadUsers().catch((e) => console.error("users", e));
    }
    if (responsesIsActive) {
        loadResponses().catch((e) => console.error("responses", e));
    }
    if (dashboardIsActive) {
        loadDashboard().catch((e) => console.error("dashboard", e));
        if (state.dashboardPollTimer) clearInterval(state.dashboardPollTimer);
        state.dashboardPollTimer = setInterval(() => {
            loadDashboard().catch((err) => console.error("dashboard poll", err));
        }, 5000);
        if (state.elapsedTimerInterval) clearInterval(state.elapsedTimerInterval);
        state.elapsedTimerInterval = setInterval(updateElapsedLabels, 1000);
    } else if (state.dashboardPollTimer) {
        clearInterval(state.dashboardPollTimer);
        state.dashboardPollTimer = null;
        if (state.elapsedTimerInterval) {
            clearInterval(state.elapsedTimerInterval);
            state.elapsedTimerInterval = null;
        }
    }
}


themeToggle.onclick = () => {
    state.theme = state.theme === "light" ? "dark" : "light";
    document.body.setAttribute("data-theme", state.theme);
    themeToggle.textContent = state.theme === "light" ? "🌙" : "☀️";
    localStorage.setItem("rag_theme", state.theme);
};

tabDashboard?.addEventListener("click", () => setActiveTab("dashboard"));
tabDocumentStatus?.addEventListener("click", () => setActiveTab("document-status"));
tabRawData?.addEventListener("click", () => setActiveTab("raw-data"));
tabUsers?.addEventListener("click", () => setActiveTab("users"));
tabResponses?.addEventListener("click", () => setActiveTab("responses"));
document.getElementById("refresh-responses-btn")?.addEventListener("click", () => {
    loadResponses().catch((e) => console.error("responses refresh", e));
});
refreshDocumentStatusBtn?.addEventListener("click", () => {
    loadDocumentStatus().catch((e) => console.error("document status", e));
});
ingestBtn?.addEventListener("click", () => {
    triggerIngest().catch((e) => {
        if (ingestStatus) ingestStatus.hidden = false;
        if (ingestStatusLabel) ingestStatusLabel.textContent = `Ingestion error: ${e.message || String(e)}`;
        if (ingestStatusCurrentFile) ingestStatusCurrentFile.textContent = "Please retry and check worker logs.";
        if (ingestBtn) ingestBtn.disabled = false;
        if (restartIngestBtn) restartIngestBtn.disabled = false;
    });
});
restartIngestBtn?.addEventListener("click", () => {
    triggerRestartIngest().catch((e) => {
        if (ingestStatus) ingestStatus.hidden = false;
        if (ingestStatusLabel) ingestStatusLabel.textContent = `Restart ingestion error: ${e.message || String(e)}`;
        if (ingestStatusCurrentFile) ingestStatusCurrentFile.textContent = "Please retry and check worker logs.";
        if (ingestBtn) ingestBtn.disabled = false;
        if (restartIngestBtn) restartIngestBtn.disabled = false;
    });
});
documentStatusFilterButtons.forEach((button) => {
    button.addEventListener("click", () => {
        state.documentStatusFilter = button.dataset.filter || "all";
        documentStatusFilterButtons.forEach((b) =>
            b.classList.toggle("active", b.dataset.filter === state.documentStatusFilter)
        );
        state.documentStatusPage = 1;
        refreshDocumentStatusTable();
    });
});
refreshRawDataBtn?.addEventListener("click", () => {
    loadRawData().catch((e) => console.error("raw data", e));
});

documentStatusPageSizeSelect?.addEventListener("change", () => {
    state.documentStatusPageSize =
        documentStatusPageSizeSelect.value === "all" ? "all" : Number(documentStatusPageSizeSelect.value);
    state.documentStatusPage = 1;
    refreshDocumentStatusTable();
});
documentStatusPrevBtn?.addEventListener("click", () => {
    if (state.documentStatusPage > 1) {
        state.documentStatusPage -= 1;
        refreshDocumentStatusTable();
    }
});
documentStatusNextBtn?.addEventListener("click", () => {
    state.documentStatusPage += 1;
    refreshDocumentStatusTable();
});
rawDataPageSizeSelect?.addEventListener("change", () => {
    state.rawDataPageSize = rawDataPageSizeSelect.value === "all" ? "all" : Number(rawDataPageSizeSelect.value);
    state.rawDataPage = 1;
    refreshRawDataTable();
});
rawDataPrevBtn?.addEventListener("click", () => {
    if (state.rawDataPage > 1) {
        state.rawDataPage -= 1;
        refreshRawDataTable();
    }
});
rawDataNextBtn?.addEventListener("click", () => {
    state.rawDataPage += 1;
    refreshRawDataTable();
});

documentStatusTable?.querySelector("thead")?.addEventListener("click", (e) => {
    const btn = e.target.closest(".th-sort-btn");
    if (!btn) return;
    const th = btn.closest(".sortable-th");
    const sortKey = th?.dataset.sortKey;
    if (!sortKey) return;
    state.documentStatusSort = handleSortClick(state.documentStatusSort, sortKey);
    state.documentStatusPage = 1;
    refreshDocumentStatusTable();
});
rawDataTable?.querySelector("thead")?.addEventListener("click", (e) => {
    const btn = e.target.closest(".th-sort-btn");
    if (!btn) return;
    const th = btn.closest(".sortable-th");
    const sortKey = th?.dataset.sortKey;
    if (!sortKey) return;
    state.rawDataSort = handleSortClick(state.rawDataSort, sortKey);
    state.rawDataPage = 1;
    refreshRawDataTable();
});

/**
 * Toggle the pause/resume state of a pipeline stage by calling the appropriate dashboard endpoint.
 *
 * @param {'ingest'|'transform'|'vectorize'} stage - Pipeline stage to pause or resume.
 */
async function togglePause(stage) {
    const btn = document.getElementById(`btn-pause-${stage}`);
    if (!btn) return;
    const isPaused = btn.dataset.paused === "true";
    const endpoint = isPaused ? `/dashboard/${stage}_resume` : `/dashboard/${stage}_pause`;
    btn.disabled = true;
    try {
        const res = await fetch(endpoint, { method: "POST", headers: apiHeaders() });
        if (!res.ok) throw new Error(await res.text());
        await loadDashboard();
    } catch (e) {
        alert(e.message || String(e));
    } finally {
        btn.disabled = false;
    }
}

document.getElementById("btn-pause-ingest")?.addEventListener("click", () => togglePause("ingest"));
document.getElementById("btn-pause-transform")?.addEventListener("click", () => togglePause("transform"));
document.getElementById("btn-pause-vectorize")?.addEventListener("click", () => togglePause("vectorize"));

document.querySelector("#dash-card-raw .btn-re-ingest")?.addEventListener("click", async () => {
    if (!confirm("Re-ingest: clear MinIO RAW and reset pipeline rows. Continue?")) return;
    const btn = document.querySelector("#dash-card-raw .btn-re-ingest");
    if (btn) btn.disabled = true;
    try {
        const res = await fetch("/dashboard/re-ingest", { method: "POST", headers: apiHeaders(false, true) });
        if (!res.ok) throw new Error(await res.text());
        await loadDashboard();
    } catch (e) {
        alert(e.message || String(e));
    } finally {
        if (btn) btn.disabled = false;
    }
});

document.querySelector("#dash-card-transform .btn-run-transform")?.addEventListener("click", async () => {
    const btn = document.querySelector("#dash-card-transform .btn-run-transform");
    if (btn) btn.disabled = true;
    try {
        const res = await fetch("/dashboard/trigger-transform", { method: "POST", headers: apiHeaders() });
        if (!res.ok) throw new Error(await res.text());
        await loadDashboard();
    } catch (e) {
        alert(e.message || String(e));
    } finally {
        if (btn) btn.disabled = false;
    }
});

document.querySelector("#dash-card-transform .btn-re-transform")?.addEventListener("click", async () => {
    if (!confirm("Re-transform: clear extracted TEXT in MinIO and reset text stage. Continue?")) return;
    const btn = document.querySelector("#dash-card-transform .btn-re-transform");
    if (btn) btn.disabled = true;
    try {
        const res = await fetch("/dashboard/re-transform", { method: "POST", headers: apiHeaders(false, true) });
        if (!res.ok) throw new Error(await res.text());
        await loadDashboard();
    } catch (e) {
        alert(e.message || String(e));
    } finally {
        if (btn) btn.disabled = false;
    }
});

document.querySelector("#dash-card-postgres .btn-clear-data")?.addEventListener("click", async () => {
    if (!confirm("Clear data: delete all Redis conversation/cache keys and drop Milvus vectors. Continue?")) return;
    const btn = document.querySelector("#dash-card-postgres .btn-clear-data");
    if (btn) btn.disabled = true;
    try {
        const res = await fetch("/dashboard/clear-data", { method: "POST", headers: apiHeaders(false, true) });
        if (!res.ok) throw new Error(await res.text());
        await loadDashboard();
    } catch (e) {
        alert(e.message || String(e));
    } finally {
        if (btn) btn.disabled = false;
    }
});

document.querySelector("#dash-card-postgres .btn-erase-all")?.addEventListener("click", async () => {
    if (!confirm("Erase all: permanently delete every file record, extracted text, vectors, MinIO objects, and Redis keys. This cannot be undone. Continue?")) return;
    const btn = document.querySelector("#dash-card-postgres .btn-erase-all");
    if (btn) btn.disabled = true;
    try {
        const res = await fetch("/dashboard/erase-all", { method: "POST", headers: apiHeaders(false, true) });
        if (!res.ok) throw new Error(await res.text());
        await loadDashboard();
    } catch (e) {
        alert(e.message || String(e));
    } finally {
        if (btn) btn.disabled = false;
    }
});

document.querySelector("#dash-card-milvus .btn-re-vectorize")?.addEventListener("click", async () => {
    if (!confirm("Re-vectorize: drop Milvus collection and re-queue embeddings. Continue?")) return;
    const btn = document.querySelector("#dash-card-milvus .btn-re-vectorize");
    if (btn) btn.disabled = true;
    try {
        const res = await fetch("/dashboard/re-vectorize", { method: "POST", headers: apiHeaders(false, true) });
        if (!res.ok) throw new Error(await res.text());
        await loadDashboard();
    } catch (e) {
        alert(e.message || String(e));
    } finally {
        if (btn) btn.disabled = false;
    }
});

/**
 * Poll the pipeline status endpoint and update the connection indicator in the header.
 * Called every 30 seconds via setInterval.
 */
async function pollStatus() {
    try {
        const res = await fetch("/status", { headers: apiHeaders() });
        if (res.ok) {
            const data = await res.json();
            if (data.failed > 0) {
                statusIndicator.className = "warning";
                statusText.textContent = `Online (${data.failed} failed)`;
            } else {
                statusIndicator.className = "online";
                statusText.textContent = "Online";
            }
        }
    } catch (e) {
        console.error("Status poll failed", e);
    }
}

/**
 * Initialize the main application by showing the dashboard tab and starting the status poll.
 * The status poll is started only once per page load.
 */
function showMainApp() {
    setActiveTab("dashboard");
    if (!statusPollStarted) {
        statusPollStarted = true;
        setInterval(pollStatus, 30000);
        pollStatus();
    }
}

showMainApp();
