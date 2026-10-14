const status = document.getElementById("status");
function render(result) {
  status.textContent = result.error || (result.shared ? `Shared: ${result.shared.url}` : "No tab shared");
}
document.getElementById("share").addEventListener("click", async () => {
  try {
    const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
    const url = new URL(tab.url);
    if (!["http:", "https:"].includes(url.protocol)) throw new Error("Open a website first");
    const allowed = await chrome.permissions.request({origins: [`${url.origin}/*`]});
    if (!allowed) throw new Error("Site access was declined");
    render(await chrome.runtime.sendMessage({action: "share", tabId: tab.id}));
  } catch (error) {render({error: error.message});}
});
document.getElementById("revoke").addEventListener("click", async () => render(await chrome.runtime.sendMessage({action: "revoke"})));
render(await chrome.runtime.sendMessage({action: "status"}));
