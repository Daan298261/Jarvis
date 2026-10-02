import assert from "node:assert/strict"
import { before, describe, test } from "node:test"

/** @type {typeof import("./src/companionWan.ts")} */
let wan

before(async () => {
  wan = await import("./src/companionWan.ts")
})

describe("companion WAN prepare body", () => {
  test("LAN prepare does not send SSH secrets", () => {
    const body = wan.connectionPrepareBody(true, false, {
      ...wan.EMPTY_WAN_FORM,
      ssh_host: "vpn.example.test",
      gateway_password: "secret",
    })
    assert.deepEqual(body, { enabled: true, remote: false })
  })

  test("remote auto includes only filled fields and never blank password", () => {
    const body = wan.connectionPrepareBody(true, true, {
      ...wan.EMPTY_WAN_FORM,
      wan_method: "ssh_reverse",
      ssh_host: "vpn.example.test",
      ssh_user: "taco",
      ssh_identity_file: "C:\\Users\\taco\\.ssh\\id_ed25519",
      ssh_port: "22",
      gateway_password: "  ",
    })
    assert.equal(body.wan_method, "ssh_reverse")
    assert.equal(body.ssh_host, "vpn.example.test")
    assert.equal(body.ssh_user, "taco")
    assert.equal(body.ssh_port, 22)
    assert.equal("gateway_password" in body, false)
  })

  test("remote reverse tunnel includes ssh port", () => {
    const body = wan.connectionPrepareBody(true, true, {
      ...wan.EMPTY_WAN_FORM,
      wan_method: "ssh_reverse",
      ssh_host: "vpn.example.test",
      ssh_user: "taco",
      ssh_port: "2222",
    })
    assert.equal(body.ssh_port, 2222)
  })

  test("gateway ssh prepare includes password and omits blank host", () => {
    const body = wan.connectionPrepareBody(true, true, {
      ...wan.EMPTY_WAN_FORM,
      wan_method: "gateway_ssh",
      gateway_user: "root",
      gateway_password: "secret",
    })
    assert.equal(body.wan_method, "gateway_ssh")
    assert.equal(body.gateway_password, "secret")
    assert.equal("gateway_host" in body, false)
  })

  test("snapshot hydrate never copies a stored password", () => {
    const form = wan.wanFormFromSnapshot({
      wan: { wan_method: "gateway_ssh", gateway_host: "192.168.1.1", gateway_password: "nope" },
    })
    assert.equal(form.wan_method, "gateway_ssh")
    assert.equal(form.gateway_host, "192.168.1.1")
    assert.equal(form.gateway_password, "")
  })
})
