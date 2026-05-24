const form = document.getElementById("chat-form");
const input = document.getElementById("query-input");
const messages = document.getElementById("messages");
const sourcesEl = document.getElementById("sources");

let conversationId = null;

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
      <thead><tr><th>File</th><th>Text Preview</th><th>Score</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const query = input.value.trim();
  if (!query) return;
  input.value = "";

  addMessage("user", query);
  const assistant = addMessage("assistant", "...");
  sourcesEl.innerHTML = "";

  try {
    const response = await fetch("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        query,
        conversation_id: conversationId
      })
    });
    if (!response.ok) {
      throw new Error(`chat ${response.status}`);
    }
    const data = await response.json();
    conversationId = data.conversation_id;
    assistant.innerHTML = marked.parse(data.answer);
    renderSources(data.sources);
  } catch (error) {
    assistant.textContent = `Error: ${String(error)}`;
  }
});
