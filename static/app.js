const state = {
    ws: null,
    conversationId: crypto.randomUUID(),
    documentType: "",
    messages: [],
    apiKey: localStorage.getItem("rag_api_key") || "",
    theme: localStorage.getItem("rag_theme") || "light",
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

// Initialize
document.body.setAttribute("data-theme", state.theme);
themeToggle.textContent = state.theme === "light" ? "🌙" : "☀️";

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
            renderSources(msg.sources);
            state.conversationId = msg.conversation_id;
            finalizeAssistantMessage();
        } else if (msg.type === "error") {
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

    if (state.ws.readyState === WebSocket.OPEN) {
        state.ws.send(JSON.stringify({
            type: "query",
            query: query,
            document_type: state.documentType || undefined,
            conversation_id: state.conversationId,
        }));
    } else {
        renderError("Not connected to server. Please wait.");
        finalizeAssistantMessage();
    }
};

clearBtn.onclick = () => {
    messagesContainer.innerHTML = `
        <div class="message assistant">
            <div class="bubble">History cleared. How can I help you today?</div>
        </div>
    `;
    state.conversationId = crypto.randomUUID();
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
