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

// Initialize
document.body.setAttribute("data-theme", state.theme);
themeToggle.textContent = state.theme === "light" ? "🌙" : "☀️";

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

function connectWebSocket() {
    const protocol = location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${location.host}/ws/chat`;
    
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

async function pollStatus() {
    try {
        const headers = state.apiKey ? { "X-API-Key": state.apiKey } : {};
        const res = await fetch("/status", { headers });
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

// Start
connectWebSocket();
setInterval(pollStatus, 30000);
pollStatus();
