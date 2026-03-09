import { bootstrap } from "/assets/app-main.js";

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

bootstrap().catch((error) => {
  const statusWrap = document.getElementById("statusWrap");
  const statusDot = document.getElementById("statusDot");
  const statusText = document.getElementById("statusText");
  if (statusWrap && statusDot && statusText) {
    statusWrap.className = "status status--error";
    statusDot.className = "status-dot status-dot--error";
    statusText.textContent = "初始化失败";
  }

  const chat = document.getElementById("chat");
  if (chat) {
    const row = document.createElement("article");
    row.className = "msg assistant";
    row.innerHTML = [
      '<div class="message-column">',
      '  <div class="message-card message-card--assistant">',
      `    <div class="message-rich rich-content"><p>${escapeHtml(error instanceof Error ? error.message : error)}</p></div>`,
      "  </div>",
      "</div>",
    ].join("\n");
    chat.appendChild(row);
  }
});
