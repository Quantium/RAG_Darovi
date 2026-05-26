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
function addMessage(role, text) {
  const el = document.createElement("div");
  el.className = `msg ${role}`;
  if (role === "user") {
    el.textContent = text;
  } else {
    el.innerHTML = marked.parse(text);
  }
  messages.appendChild(el);
  messages.scrollTop = messages.scrollHeight;
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
    const nameCell = s.file_url
      ? `<a href="${s.file_url}" target="_blank" rel="noopener">${s.source_name}</a>`
      : s.source_name;
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

  form.parentNode.insertBefore(bar, form);
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
    assistant.innerHTML = marked.parse(data.answer);
    renderSources(data.sources);
    addRatingButtons(data.interaction_id);
  } catch (error) {
    assistant.textContent = `Error: ${String(error)}`;
  }
});
