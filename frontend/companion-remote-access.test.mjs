import assert from "node:assert/strict"
import { describe, test } from "node:test"

const remote = await import("./src/companionRemote.ts")

describe("remote connection body (Tailscale only)", () => {
  test("remote off sends only the switch", () => {
    assert.deepEqual(remote.remoteConnectionBody({ remote: false, tailscale: true }), { enabled: true, remote: false })
  })
  test("remote on carries the Tailscale choice and nothing else", () => {
    assert.deepEqual(remote.remoteConnectionBody({ remote: true, tailscale: false }), { enabled: true, remote: true, tailscale: false })
  })
  test("snapshot defaults keep remote off and Tailscale on", () => {
    assert.deepEqual(remote.remoteFormFromSnapshot(null), { remote: false, tailscale: true })
    assert.deepEqual(remote.remoteFormFromSnapshot({ remote: true, tailscale_enabled: false }), { remote: true, tailscale: false })
  })
})

describe("guidance and labels", () => {
  test("missing Tailscale gives install guidance", () => {
    const text = remote.tailscaleGuide({ installed: false, running: false, backend_state: "", dns_name: "", ips: [], hint: "" })
    assert.match(text, /tailscale\.com\/download/)
  })
  test("connected Tailscale names the MagicDNS host", () => {
    const text = remote.tailscaleGuide({ installed: true, running: true, backend_state: "Running", dns_name: "vrpc.tail1.ts.net", ips: ["100.64.0.2"], hint: "" })
    assert.match(text, /vrpc\.tail1\.ts\.net/)
  })
  test("labels", () => {
    assert.equal(remote.kindLabel("tailscale"), "Tailscale")
    assert.equal(remote.kindLabel("lan"), "Home network")
    assert.equal(remote.reachabilityLabel({ url: "u", kind: "lan", status: "failed", detail: "" }), "failed")
  })
})
