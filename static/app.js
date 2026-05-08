/** UUID v4. crypto.randomUUID() is only available in secure contexts (HTTPS or localhost). */
function randomUUID() {
    if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
        return crypto.randomUUID();
    }
    const bytes = new Uint8Array(16);
    if (typeof crypto !== "undefined" && typeof crypto.getRandomValues === "function") {
        crypto.getRandomValues(bytes);
    } else {
        for (let i = 0; i < 16; i++) bytes[i] = (Math.random() * 256) | 0;
    }
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    const hex = [...bytes].map((b) => b.toString(16).padStart(2, "0")).join("");
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20, 32)}`;
}

const state = {
    ws: null,
    conversationId: randomUUID(),
    documentType: "",
    messages: [],
    apiKey: localStorage.getItem("rag_api_key") || "",
    theme: localStorage.getItem("rag_theme") || "dark",
    activeTab: "chat",
    documentStatusFilter: "all",
    documentStatusFiles: [],
    ingestRunning: false,
    ingestPollTimer: null,
};

// UI Elements
const messagesContainer = document.getElementById("messages");
const chatForm = document.getElementById("chat-form");
const queryInput = document.getElementById("query-input");
const sendBtn = document.getElementById("send-btn");
const clearBtn = document.getElementById("clear-chat");
const themeToggle = document.getElementById("theme-toggle");
const filterBtns = document.querySelectorAll(".filter-btn");
const statusIndicator = document.getElementById("status-indicator");
const statusText = document.getElementById("status-text");
const chatInputStatus = document.getElementById("chat-input-status");
const onboardingPanel = document.getElementById("onboarding-panel");
const chatShell = document.getElementById("chat-shell");
const tabChat = document.getElementById("tab-chat");
const tabDocumentStatus = document.getElementById("tab-document-status");
const tabRawData = document.getElementById("tab-raw-data");
const chatPanel = document.getElementById("chat-panel");
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
const chatFooter = document.querySelector("footer");

// Initialize
document.body.setAttribute("data-theme", state.theme);
themeToggle.textContent = state.theme === "light" ? "🌙" : "☀️";

function apiHeaders(jsonBody = false) {
    const h = {};
    if (jsonBody) h["Content-Type"] = "application/json";
    if (state.apiKey) h["X-API-Key"] = state.apiKey;
    return h;
}

let statusPollStarted = false;
let bootstrapPollTimer = null;

const ICON_ERROR_SVG = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>`;

function showThinkingStatus() {
    chatInputStatus.hidden = false;
    chatInputStatus.className = "chat-input-status chat-input-status--thinking";
    chatInputStatus.innerHTML = `
        <span class="chat-input-status__spinner" aria-hidden="true"></span>
        <span class="chat-input-status__text">Thinking...</span>
    `;
    chatForm.setAttribute("aria-busy", "true");
}

function showErrorStatus(message) {
    chatInputStatus.hidden = false;
    chatInputStatus.className = "chat-input-status chat-input-status--error";
    const safe = String(message || "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
    chatInputStatus.innerHTML = `
        <span class="chat-input-status__icon">${ICON_ERROR_SVG}</span>
        <span class="chat-input-status__text">Error${safe ? `<span class="chat-input-status__detail">${safe}</span>` : ""}</span>
    `;
    chatForm.setAttribute("aria-busy", "false");
}

function hideChatInputStatus() {
    chatInputStatus.hidden = true;
    chatInputStatus.className = "chat-input-status";
    chatInputStatus.innerHTML = "";
    chatForm.setAttribute("aria-busy", "false");
}

function escapeHtml(text) {
    return String(text ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
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

function renderDocumentStatusRows(files) {
    if (!documentStatusTableBody || !documentStatusEmpty) return;
    documentStatusTableBody.innerHTML = "";
    documentStatusEmpty.hidden = files.length > 0;

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

function applyDocumentStatusFilter() {
    renderDocumentStatusRows(filteredDocumentStatusFiles());
}

async function loadDocumentStatus() {
    if (!documentStatusTableBody || !documentStatusEmpty) return;
    try {
        const res = await fetch("/status/files", { headers: apiHeaders() });
        if (!res.ok) throw new Error(`status/files ${res.status}`);
        const files = await res.json();
        state.documentStatusFiles = Array.isArray(files) ? files : [];
        applyDocumentStatusFilter();
    } catch (err) {
        state.documentStatusFiles = [];
        renderDocumentStatusRows([]);
        const row = document.createElement("tr");
        row.innerHTML = `<td colspan="8">Could not load document status: ${escapeHtml(err.message || String(err))}</td>`;
        documentStatusTableBody.appendChild(row);
        documentStatusEmpty.hidden = true;
    }
}

function renderRawDataRows(items) {
    if (!rawDataTableBody || !rawDataEmpty) return;
    rawDataTableBody.innerHTML = "";
    rawDataEmpty.hidden = items.length > 0;
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

async function loadRawData() {
    if (!rawDataTableBody || !rawDataEmpty) return;
    try {
        const res = await fetch("/status/raw-data", { headers: apiHeaders() });
        if (!res.ok) throw new Error(`status/raw-data ${res.status}`);
        const items = await res.json();
        renderRawDataRows(Array.isArray(items) ? items : []);
    } catch (err) {
        renderRawDataRows([]);
        const row = document.createElement("tr");
        row.innerHTML = `<td colspan="5">Could not load extracted data: ${escapeHtml(err.message || String(err))}</td>`;
        rawDataTableBody.appendChild(row);
        rawDataEmpty.hidden = true;
    }
}

function setActiveTab(nextTab) {
    state.activeTab = nextTab;
    const chatIsActive = nextTab === "chat";
    const statusIsActive = nextTab === "document-status";
    const rawDataIsActive = nextTab === "raw-data";
    tabChat?.classList.toggle("active", chatIsActive);
    tabDocumentStatus?.classList.toggle("active", statusIsActive);
    tabRawData?.classList.toggle("active", rawDataIsActive);
    if (chatPanel) chatPanel.hidden = !chatIsActive;
    if (documentStatusPanel) documentStatusPanel.hidden = !statusIsActive;
    if (rawDataPanel) rawDataPanel.hidden = !rawDataIsActive;
    if (chatFooter) chatFooter.hidden = !chatIsActive;
    if (statusIsActive) {
        loadDocumentStatus().catch((e) => console.error("document status", e));
    }
    if (rawDataIsActive) {
        loadRawData().catch((e) => console.error("raw data", e));
    }
}

function connectWebSocket() {
    const protocol = location.protocol === "https:" ? "wss:" : "ws:";
    let wsUrl = `${protocol}//${location.host}/ws/chat`;
    if (state.apiKey) {
        wsUrl += `?api_key=${encodeURIComponent(state.apiKey)}`;
    }

    state.ws = new WebSocket(wsUrl);

    state.ws.onopen = () => {
        console.log("WebSocket connected");
        statusIndicator.className = "online";
        statusText.textContent = "Online";
    };

    state.ws.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        if (msg.type === "token") {
            appendToken(msg.content);
        } else if (msg.type === "done") {
            hideChatInputStatus();
            renderSources(msg.sources);
            state.conversationId = msg.conversation_id;
            finalizeAssistantMessage();
        } else if (msg.type === "error") {
            showErrorStatus(msg.message);
            renderError(msg.message);
            finalizeAssistantMessage();
        }
    };

    state.ws.onclose = () => {
        statusIndicator.className = "error";
        statusText.textContent = "Disconnected. Retrying...";
        setTimeout(connectWebSocket, 3000);
    };
}

function appendToken(token) {
    let lastMsg = messagesContainer.lastElementChild;
    if (!lastMsg || !lastMsg.classList.contains("assistant") || lastMsg.querySelector(".sources")) {
        createAssistantBubble();
        lastMsg = messagesContainer.lastElementChild;
    }
    const bubble = lastMsg.querySelector(".bubble");
    bubble.textContent += token;
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

function createAssistantBubble() {
    const div = document.createElement("div");
    div.className = "message assistant";
    div.innerHTML = `<div class="bubble"></div>`;
    messagesContainer.appendChild(div);
}

function renderSources(sources) {
    if (!sources || sources.length === 0) return;
    
    const lastMsg = messagesContainer.lastElementChild;
    const sourcesDiv = document.createElement("div");
    sourcesDiv.className = "sources";
    
    sources.forEach(src => {
        const card = document.createElement("div");
        card.className = "source-card";
        const icon = src.document_type === "pdf" ? "📄" : (src.document_type === "sheet" ? "📊" : "📝");
        
        card.innerHTML = `
            <div class="source-header">
                <span>${icon} ${src.source_name} | ${src.section_title}</span>
                <span>${(src.score * 100).toFixed(0)}%</span>
            </div>
            <div class="source-preview">${src.text_preview}...</div>
        `;
        sourcesDiv.appendChild(card);
    });
    
    lastMsg.appendChild(sourcesDiv);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

function renderError(error) {
    appendToken(`\n\nError: ${error}`);
}

function finalizeAssistantMessage() {
    sendBtn.disabled = false;
    queryInput.focus();
}

function addUserMessage(text) {
    const div = document.createElement("div");
    div.className = "message user";
    div.innerHTML = `<div class="bubble">${text}</div>`;
    messagesContainer.appendChild(div);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

chatForm.onsubmit = (e) => {
    e.preventDefault();
    const query = queryInput.value.trim();
    if (!query || sendBtn.disabled) return;

    addUserMessage(query);
    queryInput.value = "";
    sendBtn.disabled = true;
    hideChatInputStatus();

    if (state.ws.readyState === WebSocket.OPEN) {
        showThinkingStatus();
        state.ws.send(JSON.stringify({
            type: "query",
            query: query,
            document_type: state.documentType || undefined,
            conversation_id: state.conversationId,
        }));
    } else {
        showErrorStatus("Not connected to server. Please wait.");
        renderError("Not connected to server. Please wait.");
        finalizeAssistantMessage();
    }
};

clearBtn.onclick = () => {
    hideChatInputStatus();
    messagesContainer.innerHTML = `
        <div class="message assistant">
            <div class="bubble">History cleared. How can I help you today?</div>
        </div>
    `;
    state.conversationId = randomUUID();
};

themeToggle.onclick = () => {
    state.theme = state.theme === "light" ? "dark" : "light";
    document.body.setAttribute("data-theme", state.theme);
    themeToggle.textContent = state.theme === "light" ? "🌙" : "☀️";
    localStorage.setItem("rag_theme", state.theme);
};

filterBtns.forEach(btn => {
    btn.onclick = () => {
        filterBtns.forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        state.documentType = btn.dataset.type;
    };
});

tabChat?.addEventListener("click", () => setActiveTab("chat"));
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
        applyDocumentStatusFilter();
    });
});
refreshRawDataBtn?.addEventListener("click", () => {
    loadRawData().catch((e) => console.error("raw data", e));
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
        showChatApp();
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
                showChatApp();
            } else {
                renderOnboarding(b);
            }
        } catch (e) {
            console.error("bootstrap poll", e);
        }
    }, 2000);
}

function showChatApp() {
    if (onboardingPanel) onboardingPanel.hidden = true;
    if (chatShell) chatShell.hidden = false;
    setActiveTab(state.activeTab);
    connectWebSocket();
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
            showChatApp();
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
        console.warn("Drive bootstrap unavailable, showing chat:", e);
        showChatApp();
    }
}

initApp();
