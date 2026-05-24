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
};

const themeToggle = document.getElementById("theme-toggle");
const statusIndicator = document.getElementById("status-indicator");
const statusText = document.getElementById("status-text");
const onboardingPanel = document.getElementById("onboarding-panel");
const chatShell = document.getElementById("chat-shell");
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

function apiHeaders(jsonBody = false, dashboardConfirm = false) {
    const h = {};
    if (jsonBody) h["Content-Type"] = "application/json";
    if (state.apiKey) h["X-API-Key"] = state.apiKey;
    if (dashboardConfirm) h["X-Dashboard-Confirm"] = "yes";
    return h;
}

let statusPollStarted = false;
let bootstrapPollTimer = null;

function escapeHtml(text) {
    return String(text ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

function compareStrings(a, b) {
    const sa = String(a ?? "").toLowerCase();
    const sb = String(b ?? "").toLowerCase();
    if (sa < sb) return -1;
    if (sa > sb) return 1;
    return 0;
}

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

function sortRows(items, sort, getters) {
    if (!sort || !getters[sort.key]) return items;
    const mult = sort.direction === "desc" ? -1 : 1;
    return [...items].sort((a, b) => mult * getters[sort.key](a, b));
}

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

function handleSortClick(currentSort, sortKey) {
    if (currentSort?.key === sortKey) {
        return {
            key: sortKey,
            direction: currentSort.direction === "asc" ? "desc" : "asc",
        };
    }
    return { key: sortKey, direction: "asc" };
}

function fileOpenUrl(driveFileId) {
    const encodedId = encodeURIComponent(String(driveFileId || ""));
    const params = new URLSearchParams();
    if (state.apiKey) {
        params.set("api_key", state.apiKey);
    }
    const qs = params.toString();
    return `/files/${encodedId}/open${qs ? `?${qs}` : ""}`;
}

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

function ingestingFileLabel(files) {
    const inProgress = files.find((file) => ["pending", "downloaded", "converted"].includes(file.status || ""));
    if (!inProgress) return "Waiting for pipeline updates...";
    const name = inProgress.name || inProgress.drive_file_id || "Unknown file";
    const status = inProgress.status || "pending";
    return `Current file: ${name} (${status})`;
}

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

function filteredDocumentStatusFiles() {
    if (state.documentStatusFilter === "raw-text-missing") {
        return state.documentStatusFiles.filter((file) => file.raw_text_available !== true);
    }
    return state.documentStatusFiles;
}

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

function refreshRawDataTable() {
    const sorted = sortRows(state.rawDataItems, state.rawDataSort, rawDataSortGetters);
    const meta = paginateSlice(sorted, state.rawDataPageSize, state.rawDataPage);
    state.rawDataPage = meta.page;
    if (rawDataEmpty) rawDataEmpty.hidden = meta.totalItems > 0;
    updateSortHeaderUI(rawDataTable, state.rawDataSort);
    updatePaginationUI(meta, rawDataPageInfo, rawDataPrevBtn, rawDataNextBtn);
    renderRawDataRows(meta.rows);
}

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

function metricRow(label, value) {
    return `<div class="dash-metric"><span>${escapeHtml(label)}</span><strong>${escapeHtml(String(value))}</strong></div>`;
}

function minioConsoleUrl(bucket, key) {
    if (!key) return null;
    return `http://${window.location.hostname}:9001/browser/${encodeURIComponent(bucket)}/${encodeURIComponent(key)}`;
}

function inflightFileRow(file) {
    if (!file || !file.name) return "";
    const url = minioConsoleUrl(file.minio_bucket, file.minio_key);
    const nameHtml = url
        ? `<a class="inflight-file-link" href="${url}" target="_blank" rel="noopener">${escapeHtml(file.name)}</a>`
        : escapeHtml(file.name);
    return `<div class="dash-inflight-file">${nameHtml}</div>`;
}

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
        const li = document.getElementById("label-ingest");
        const lt = document.getElementById("label-transform");
        const lv = document.getElementById("label-vectorize");
        if (li) li.textContent = data.ingest_processing ? "Processing" : "Idle";
        if (lt) lt.textContent = data.transform_processing ? "Processing" : "Idle";
        if (lv) lv.textContent = data.vectorize_processing ? "Processing" : "Idle";

        const iconRaw = document.getElementById("file-icon-raw");
        const iconTf = document.getElementById("file-icon-transform");
        const iconMv = document.getElementById("file-icon-milvus");
        if (iconRaw) iconRaw.classList.toggle("is-blinking", !!data.ingest_processing);
        if (iconTf) iconTf.classList.toggle("is-blinking", !!data.transform_processing);
        if (iconMv) iconMv.classList.toggle("is-blinking", !!data.vectorize_processing);

        if (updated && data.updated_at) {
            updated.textContent = `Updated: ${data.updated_at}`;
        }
    } catch (err) {
        const msg = err?.message || String(err);
        if (elRaw) elRaw.innerHTML = `<div class="dash-error">${escapeHtml(msg)}</div>`;
    }
}

function setActiveTab(nextTab) {
    state.activeTab = nextTab;
    const dashboardIsActive = nextTab === "dashboard";
    const statusIsActive = nextTab === "document-status";
    const rawDataIsActive = nextTab === "raw-data";
    tabDashboard?.classList.toggle("active", dashboardIsActive);
    tabDocumentStatus?.classList.toggle("active", statusIsActive);
    tabRawData?.classList.toggle("active", rawDataIsActive);
    if (dashboardPanel) dashboardPanel.hidden = !dashboardIsActive;
    if (documentStatusPanel) documentStatusPanel.hidden = !statusIsActive;
    if (rawDataPanel) rawDataPanel.hidden = !rawDataIsActive;
    if (statusIsActive) {
        loadDocumentStatus().catch((e) => console.error("document status", e));
    }
    if (rawDataIsActive) {
        loadRawData().catch((e) => console.error("raw data", e));
    }
    if (dashboardIsActive) {
        loadDashboard().catch((e) => console.error("dashboard", e));
        if (state.dashboardPollTimer) clearInterval(state.dashboardPollTimer);
        state.dashboardPollTimer = setInterval(() => {
            loadDashboard().catch((err) => console.error("dashboard poll", err));
        }, 5000);
    } else if (state.dashboardPollTimer) {
        clearInterval(state.dashboardPollTimer);
        state.dashboardPollTimer = null;
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

async function fetchBootstrap() {
    const res = await fetch("/drive/bootstrap", { credentials: "include", headers: apiHeaders() });
    if (!res.ok) throw new Error(`bootstrap ${res.status}`);
    return res.json();
}

function renderOnboarding(b) {
    if (b.ingest_source === "local") {
        showMainApp();
        return;
    }

    onboardingPanel.hidden = false;
    chatShell.hidden = true;
    const msg = document.getElementById("onboarding-message");
    const actions = document.getElementById("onboarding-actions");
    const folderList = document.getElementById("folder-list");
    const progress = document.getElementById("onboarding-progress");
    actions.innerHTML = "";
    folderList.hidden = true;
    progress.hidden = true;
    folderList.innerHTML = "";

    if (!b.oauth_configured && !b.service_account_ready) {
        msg.textContent =
            "Configure Google Drive: set GOOGLE_OAUTH_CLIENT_ID for browser sign-in, or GOOGLE_APPLICATION_CREDENTIALS plus DRIVE_FOLDER_ID for a service account.";
        return;
    }

    if (b.oauth_configured && b.onboarding_phase === "disconnected") {
        msg.textContent = "Connect your Google account (read-only) to choose a folder to index.";
        const a = document.createElement("a");
        a.href = "/auth/google/start";
        a.className = "onboarding-btn onboarding-btn--primary";
        a.textContent = "Connect Google Drive";
        actions.appendChild(a);
        return;
    }

    if (b.oauth_configured && b.onboarding_phase === "awaiting_folder") {
        msg.textContent = "Select a folder to index:";
        loadFolderList();
        return;
    }

    progress.hidden = false;
    const labels = {
        downloading: "Downloading files from Drive…",
        preparing: "Preparing documents…",
        embedding: "Embedding into the vector index…",
        ready: "Finishing…",
        error: "Pipeline error. Check logs or /status.",
    };
    document.getElementById("onboarding-progress-label").textContent =
        labels[b.onboarding_phase] || b.onboarding_phase;
}

async function loadFolderList() {
    const folderList = document.getElementById("folder-list");
    folderList.hidden = false;
    folderList.innerHTML = "<li>Loading…</li>";
    try {
        const res = await fetch("/drive/folders?parent_id=root", { credentials: "include", headers: apiHeaders() });
        if (!res.ok) throw new Error(await res.text());
        const folders = await res.json();
        folderList.innerHTML = "";
        folders.forEach((f) => {
            const li = document.createElement("li");
            const btn = document.createElement("button");
            btn.type = "button";
            btn.className = "folder-item-btn";
            btn.textContent = f.name || f.id;
            btn.onclick = () => {
                selectFolder(f.id).catch((err) => {
                    folderList.innerHTML = `<li class="onboarding-error">${String(err.message || err)}</li>`;
                });
            };
            li.appendChild(btn);
            folderList.appendChild(li);
        });
        if (folders.length === 0) {
            folderList.innerHTML = "<li>No folders found in Drive root.</li>";
        }
    } catch (e) {
        folderList.innerHTML = `<li class="onboarding-error">${String(e.message)}</li>`;
    }
}

async function selectFolder(folderId) {
    const res = await fetch("/drive/select-folder", {
        method: "POST",
        credentials: "include",
        headers: apiHeaders(true),
        body: JSON.stringify({ folder_id: folderId }),
    });
    if (!res.ok) {
        const t = await res.text();
        throw new Error(t || res.statusText);
    }
    const b = await fetchBootstrap();
    renderOnboarding({ ...b, onboarding_phase: b.onboarding_phase || "downloading" });
    startBootstrapPoll();
}

function startBootstrapPoll() {
    if (bootstrapPollTimer) clearInterval(bootstrapPollTimer);
    bootstrapPollTimer = setInterval(async () => {
        try {
            const b = await fetchBootstrap();
            if (b.chat_ready) {
                clearInterval(bootstrapPollTimer);
                bootstrapPollTimer = null;
                showMainApp();
            } else {
                renderOnboarding(b);
            }
        } catch (e) {
            console.error("bootstrap poll", e);
        }
    }, 2000);
}

function showMainApp() {
    if (onboardingPanel) onboardingPanel.hidden = true;
    if (chatShell) chatShell.hidden = false;
    setActiveTab("dashboard");
    if (!statusPollStarted) {
        statusPollStarted = true;
        setInterval(pollStatus, 30000);
        pollStatus();
    }
}

async function initApp() {
    try {
        const b = await fetchBootstrap();
        if (b.ingest_source === "local" || b.chat_ready) {
            showMainApp();
        } else {
            renderOnboarding(b);
            if (
                b.folder_selected &&
                ["downloading", "preparing", "embedding", "error"].includes(b.onboarding_phase)
            ) {
                startBootstrapPoll();
            }
        }
    } catch (e) {
        console.warn("Drive bootstrap unavailable, showing main app:", e);
        showMainApp();
    }
}

initApp();
