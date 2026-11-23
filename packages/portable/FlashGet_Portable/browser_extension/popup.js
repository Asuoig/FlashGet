const enableToggle = document.getElementById("enableToggle");
const connStatus = document.getElementById("connStatus");

// 读取当前拦截开关
chrome.storage.local.get({ enabled: true }, (res) => {
  enableToggle.checked = res.enabled;
});

enableToggle.addEventListener("change", () => {
  chrome.storage.local.set({ enabled: enableToggle.checked });
});

// 检测与本地 FlashGet 的连通状态
async function checkHealth() {
  try {
    const res = await fetch("http://127.0.0.1:9666/ping", { method: "GET" });
    if (res.ok) {
      connStatus.textContent = "已连接";
      connStatus.className = "online";
      return;
    }
  } catch (e) {}
  connStatus.textContent = "未启动";
  connStatus.className = "offline";
}

checkHealth();
