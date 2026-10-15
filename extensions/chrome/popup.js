const status = document.getElementById("status");
function render(result) {
  status.textContent = result.error || (result.shared ? `Shared: ${result.shared.url}` : "No tab shared");
}
document.getElementById("share").addEventListener("click", async () => {
  try {
    const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
    const url = new URL(tab.url);
    if (!["http:", "https:"].includes(url.protocol)) throw new Error("Open a website first");
    const origins = new Set([`${url.origin}/*`]);
    if (document.getElementById("frames").checked) {
      const frames = await chrome.webNavigation.getAllFrames({tabId: tab.id});
      for (const frame of frames) if (/^https?:/.test(frame.url)) origins.add(`${new URL(frame.url).origin}/*`);
    }
    const allowed = await chrome.permissions.request({origins: [...origins]});
    if (!allowed) throw new Error("Site access was declined");
    render(await chrome.runtime.sendMessage({action: "share", tabId: tab.id, include_frames:document.getElementById("frames").checked}));
  } catch (error) {render({error: error.message});}
});
document.getElementById("revoke").addEventListener("click", async () => render(await chrome.runtime.sendMessage({action: "revoke"})));
render(await chrome.runtime.sendMessage({action: "status"}));
