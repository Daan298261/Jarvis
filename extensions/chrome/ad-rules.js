export async function adRules(tabId) {
  const response = await fetch(chrome.runtime.getURL("filters/easylist-domains.json"));
  if (!response.ok) throw new Error("Packaged ad filter list is unavailable");
  const list = await response.json();
  const rules = [];
  for (const [scope, domains] of Object.entries(list.domains)) {
    for (let offset = 0; offset < domains.length; offset += 500) {
      rules.push({id: 100 + rules.length, priority: 1, action: {type: "block"}, condition: {
        requestDomains: domains.slice(offset, offset + 500), tabIds: [tabId],
        resourceTypes: ["script", "image", "xmlhttprequest", "sub_frame", "media", "ping", "stylesheet", "font", "other"],
        ...(scope === "thirdParty" ? {domainType: "thirdParty"} : {})
      }});
    }
  }
  return {rules, count: Object.values(list.domains).reduce((count, domains) => count + domains.length, 0), source: list.source};
}
