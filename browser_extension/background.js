// FlashGet 浏览器下载接管 Service Worker
const FLASHGET_SERVER_URL = "http://127.0.0.1:9666/download";
let isEnabled = true;

// 初始化读取配置
chrome.storage.local.get({ enabled: true }, (res) => {
  isEnabled = res.enabled;
  console.log("[FlashGet Extension] Initialized, enabled =", isEnabled);
});

// 监听配置变化
chrome.storage.onChanged.addListener((changes) => {
  if (changes.enabled) {
    isEnabled = changes.enabled.newValue;
    console.log("[FlashGet Extension] Enabled changed to", isEnabled);
  }
});

// 核心：拦截 chrome.downloads.onCreated
chrome.downloads.onCreated.addListener(async (downloadItem) => {
  if (!isEnabled) {
    console.log("[FlashGet Extension] Disabled, ignoring download:", downloadItem.id);
    return;
  }

  const url = downloadItem.finalUrl || downloadItem.url;
  if (!url || !url.startsWith("http")) {
    console.log("[FlashGet Extension] Non-http download ignored:", url);
    return;
  }

  console.log("[FlashGet Extension] Intercepting download:", downloadItem.id, url);

  // 1. 立即暂停浏览器下载，防止浏览器自行拉取数据
  try {
    await chrome.downloads.pause(downloadItem.id);
  } catch (err) {
    console.log("[FlashGet Extension] Could not pause immediately:", err.message);
  }

  // 2. 尝试提取 Cookie
  let referer = downloadItem.referrer || "";
  let cookieStr = "";
  try {
    const cookies = await chrome.cookies.getAll({ url: url });
    if (cookies && cookies.length > 0) {
      cookieStr = cookies.map((c) => `${c.name}=${c.value}`).join("; ");
    }
  } catch (err) {
    console.warn("[FlashGet Extension] Cookie lookup error:", err);
  }

  // 提取原始文件名
  let origFilename = downloadItem.filename ? downloadItem.filename.split(/[\\/]/).pop() : "";

  const payload = {
    url: url,
    filename: origFilename,
    cookies: cookieStr,
    referer: referer,
    userAgent: navigator.userAgent
  };

  // 3. 向本地 FlashGet 发送任务请求
  try {
    const response = await fetch(FLASHGET_SERVER_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    if (response.ok) {
      console.log("[FlashGet Extension] FlashGet accepted download! Canceling browser download:", downloadItem.id);
      chrome.downloads.cancel(downloadItem.id, () => {
        chrome.downloads.erase({ id: downloadItem.id });
      });
    } else {
      console.warn("[FlashGet Extension] Server returned non-ok status:", response.status);
      chrome.downloads.resume(downloadItem.id).catch(() => {});
    }
  } catch (e) {
    console.log("[FlashGet Extension] Local FlashGet not responding, resuming browser download:", e.message);
    chrome.downloads.resume(downloadItem.id).catch(() => {});
  }
});
