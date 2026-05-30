// ── Auth state ────────────────────────────────────────────────────────────────
const TOKEN_KEY = "chatbot_token";

function getToken() { return localStorage.getItem(TOKEN_KEY); }
function saveToken(t) { localStorage.setItem(TOKEN_KEY, t); }
function clearToken() { localStorage.removeItem(TOKEN_KEY); }

// ── DOM refs ──────────────────────────────────────────────────────────────────
const loginSection = document.getElementById("login-section");
const chatSection  = document.getElementById("chat-section");
const loginForm    = document.getElementById("login-form");
const loginError   = document.getElementById("login-error");
const logoutBtn    = document.getElementById("logout-btn");
const form         = document.getElementById("chat-form");
const input        = document.getElementById("query-input");
const messages     = document.getElementById("messages");
const sourcesEl    = document.getElementById("sources");

let conversationId = null;

// ── Show/hide sections ────────────────────────────────────────────────────────
function showChat() {
  loginSection.hidden = true;
  chatSection.hidden = false;
}

function showLogin() {
  loginSection.hidden = false;
  chatSection.hidden = true;
}

if (getToken()) {
  showChat();
} else {
  showLogin();
}

// ── Login ─────────────────────────────────────────────────────────────────────
loginForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  loginError.hidden = true;
  const username = document.getElementById("login-username").value.trim();
  const password = document.getElementById("login-password").value;
  try {
    const res = await fetch("/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      loginError.textContent = data.detail || "Error al iniciar sesión";
      loginError.hidden = false;
      return;
    }
    const data = await res.json();
    saveToken(data.token);
    showChat();
    loginForm.reset();
  } catch (err) {
    loginError.textContent = `Error de red: ${err}`;
    loginError.hidden = false;
  }
});

// ── Logout ────────────────────────────────────────────────────────────────────
logoutBtn.addEventListener("click", async () => {
  const token = getToken();
  clearToken();
  if (token) {
    await fetch("/auth/logout", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
    }).catch(() => {});
  }
  conversationId = null;
  messages.innerHTML = "";
  sourcesEl.innerHTML = "";
  showLogin();
});

// ── Chat helpers ──────────────────────────────────────────────────────────────
const USER_ICON = `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>`;
const BOT_ICON  = `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="10" rx="2"/><circle cx="12" cy="5" r="2"/><path d="M12 7v4"/><line x1="8" y1="16" x2="8" y2="16"/><line x1="16" y1="16" x2="16" y2="16"/></svg>`;

function nowTime() {
  return new Date().toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" });
}

function addMessage(role, text) {
  const el = document.createElement("div");
  el.className = `msg ${role}`;

  const avatar = document.createElement("div");
  avatar.className = "msg-avatar";
  avatar.innerHTML = role === "user" ? USER_ICON : BOT_ICON;

  const body = document.createElement("div");
  body.className = "msg-body";

  const bubble = document.createElement("div");
  bubble.className = "msg-bubble";
  if (role === "user") {
    bubble.textContent = text;
  } else {
    bubble.innerHTML = marked.parse(text);
  }

  const time = document.createElement("span");
  time.className = "msg-time";
  time.textContent = nowTime();

  body.appendChild(bubble);
  body.appendChild(time);
  el.appendChild(avatar);
  el.appendChild(body);

  messages.appendChild(el);
  messages.scrollTop = messages.scrollHeight;

  // expose bubble so callers can update it
  el._bubble = bubble;
  return el;
}

function renderSources(sources) {
  if (!sources || sources.length === 0) {
    sourcesEl.innerHTML = "";
    return;
  }
  const rows = sources.map(s => {
    const score = (s.score * 100).toFixed(2) + "%";
    const preview = s.text_preview.replace(/\n/g, " ");

    // Se deja comentado para versiones posteriores donde los archivos estén en línea  
    // const nameCell = s.file_url
    //   ? `<a href="${s.file_url}" target="_blank" rel="noopener">${s.source_name}</a>`
    //   : s.source_name;

    const nameCell = s.source_name;
    return `<tr><td>${nameCell}</td><td>${preview}</td><td>${score}</td></tr>`;
  }).join("");
  sourcesEl.innerHTML = `
    <table>
      <thead><tr><th>Archivo</th><th>Vista previa</th><th>Score</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
}

// ── Rating ────────────────────────────────────────────────────────────────────
function addRatingButtons(interactionId) {
  document.querySelectorAll(".rating-bar").forEach(el => el.remove());

  const bar = document.createElement("div");
  bar.className = "rating-bar";
  bar.innerHTML = `
    <button class="rate-btn" data-rating="positive" title="Buena respuesta">👍</button>
    <button class="rate-btn" data-rating="negative" title="Mala respuesta">👎</button>`;

  bar.querySelectorAll(".rate-btn").forEach(btn => {
    btn.addEventListener("click", () => handleRating(btn.dataset.rating, interactionId, bar));
  });

  const inputArea = document.querySelector(".chat-input-area");
  inputArea.parentNode.insertBefore(bar, inputArea);
}

async function handleRating(rating, interactionId, bar) {
  if (rating === "positive") {
    await postRating(interactionId, "positive", null);
    bar.remove();
  } else {
    showCorrectionDialog(interactionId, bar);
  }
}

function showCorrectionDialog(interactionId, bar) {
  if (bar.querySelector(".correction-dialog")) return;

  const dialog = document.createElement("div");
  dialog.className = "correction-dialog";
  dialog.innerHTML = `
    <p>¿Cuál debió haber sido la respuesta?</p>
    <textarea class="correction-text" rows="4"></textarea>
    <button class="correction-submit">Enviar</button>`;

  dialog.querySelector(".correction-submit").addEventListener("click", async () => {
    const correction = dialog.querySelector(".correction-text").value.trim();
    await postRating(interactionId, "negative", correction || null);
    dialog.remove();
    bar.remove();
  });

  bar.appendChild(dialog);
}

async function postRating(interactionId, rating, correction) {
  try {
    await fetch("/rate", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${getToken()}`,
      },
      body: JSON.stringify({ interaction_id: interactionId, rating, correction }),
    });
  } catch (_) {}
}

// ── Chat submit ───────────────────────────────────────────────────────────────
form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const query = input.value.trim();
  if (!query) return;
  input.value = "";

  addMessage("user", query);
  const assistant = addMessage("assistant", "...");
  sourcesEl.innerHTML = "";
  document.querySelectorAll(".rating-bar").forEach(el => el.remove());

  try {
    const res = await fetch("/chat", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${getToken()}`,
      },
      body: JSON.stringify({ query, conversation_id: conversationId }),
    });
    if (res.status === 401) {
      clearToken();
      showLogin();
      return;
    }
    if (!res.ok) {
      throw new Error(`chat ${res.status}`);
    }
    const data = await res.json();
    conversationId = data.conversation_id;
    assistant._bubble.innerHTML = marked.parse(data.answer);
    renderSources(data.sources);
    addRatingButtons(data.interaction_id);
  } catch (error) {
    assistant._bubble.textContent = `Error: ${String(error)}`;
  }
});
