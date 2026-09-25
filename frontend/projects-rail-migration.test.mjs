import assert from "node:assert/strict"
import { test, before, describe } from "node:test"

const STORAGE_KEY = "jarvis_portal_projects"

/** @type {typeof import("./src/projects.ts")} */
let projects

before(async () => {
  projects = await import("./src/projects.ts")
})

function installStorage(raw) {
  const data = new Map()
  if (raw !== undefined) data.set(STORAGE_KEY, raw)
  const storage = {
    getItem(key) {
      return data.has(key) ? data.get(key) : null
    },
    setItem(key, value) {
      data.set(key, String(value))
    },
    removeItem(key) {
      data.delete(key)
    },
  }
  globalThis.window = { localStorage: storage }
  return data
}

function seed(rows) {
  return installStorage(JSON.stringify({ version: 1, projects: rows }))
}

describe("projects rail migration", { concurrency: 1 }, () => {
test("does not export a localStorage project loader", () => {
  assert.equal(projects.loadProjects, undefined)
  assert.equal(projects.loadProjectsLocal, undefined)
  assert.equal(projects.saveProjects, undefined)
  assert.equal(projects.persistProjects, undefined)
})

test("imports browser folders the Leader does not already have, then clears storage", async () => {
  const server = [{ id: "server", name: "Inbox", taskIds: ["t-server"], conversationIds: [], repoPaths: [] }]
  const browser = { id: "browser", name: "Work", taskIds: ["t-work"], conversationIds: ["chat-1"], repoPaths: ["C:/src/work"] }
  const data = seed([
    { id: "server", name: "Stale rename", taskIds: ["t-old"], conversationIds: [], repoPaths: [] },
    browser,
  ])
  /** @type {unknown} */
  let posted = null
  globalThis.__projectsApi = async (path, init) => {
    if (path === "/api/projects" && !init) return { projects: server }
    if (path === "/api/projects/import-local" && init?.method === "POST") {
      posted = JSON.parse(init.body)
      return { imported: 1, projects: [...server, browser] }
    }
    throw new Error(`unexpected ${path}`)
  }

  const result = await projects.fetchProjects()
  assert.deepEqual(
    posted.projects.map((row) => row.id),
    ["browser"],
  )
  assert.equal(result.migratedFromLocal, true)
  assert.deepEqual(
    result.projects.map((row) => row.id),
    ["server", "browser"],
  )
  assert.equal(result.projects.find((row) => row.id === "server")?.taskIds[0], "t-server")
  assert.equal(data.get(STORAGE_KEY), undefined)
})

test("does not import or clear when the browser has no project cache", async () => {
  installStorage(undefined)
  const calls = []
  globalThis.__projectsApi = async (path, init) => {
    calls.push(`${init?.method || "GET"} ${path}`)
    return { projects: [{ id: "server", name: "Inbox", taskIds: [], conversationIds: [], repoPaths: [] }] }
  }
  const result = await projects.fetchProjects()
  assert.deepEqual(calls, ["GET /api/projects"])
  assert.equal(result.migratedFromLocal, false)
  assert.equal(result.projects[0].id, "server")
})

test("drops a browser cache whose ids are already on the Leader without rewriting links", async () => {
  const server = [{ id: "server", name: "Inbox", taskIds: ["t-server"], conversationIds: [], repoPaths: [] }]
  const data = seed([{ id: "server", name: "Old", taskIds: ["t-old"], conversationIds: [], repoPaths: [] }])
  const calls = []
  globalThis.__projectsApi = async (path, init) => {
    calls.push(`${init?.method || "GET"} ${path}`)
    return { projects: server }
  }
  const result = await projects.fetchProjects()
  assert.deepEqual(calls, ["GET /api/projects"])
  assert.equal(result.migratedFromLocal, false)
  assert.equal(result.projects[0].taskIds[0], "t-server")
  assert.equal(data.get(STORAGE_KEY), undefined)
})

test("keeps the browser cache and rejects when import does not echo the new folder", async () => {
  const raw = JSON.stringify({
    version: 1,
    projects: [{ id: "browser", name: "Work", taskIds: ["t-work"], conversationIds: [], repoPaths: [] }],
  })
  const data = installStorage(raw)
  globalThis.__projectsApi = async (path, init) => {
    if (!init) return { projects: [{ id: "server", name: "Inbox", taskIds: [], conversationIds: [], repoPaths: [] }] }
    return { imported: 0, projects: [{ id: "server", name: "Inbox", taskIds: [], conversationIds: [], repoPaths: [] }] }
  }
  await assert.rejects(() => projects.fetchProjects(), /Could not import browser project folders/)
  assert.equal(data.get(STORAGE_KEY), raw)
})

test("does not fall back to browser storage when the Leader list fails", async () => {
  const raw = JSON.stringify({
    version: 1,
    projects: [{ id: "browser", name: "Work", taskIds: ["t-work"], conversationIds: [], repoPaths: [] }],
  })
  const data = installStorage(raw)
  globalThis.__projectsApi = async () => {
    throw new Error("offline")
  }
  await assert.rejects(() => projects.fetchProjects(), /offline/)
  assert.equal(data.get(STORAGE_KEY), raw)
})

test("create does not write the browser project cache", async () => {
  const raw = JSON.stringify({
    version: 1,
    projects: [{ id: "browser", name: "Work", taskIds: [], conversationIds: [], repoPaths: [] }],
  })
  const data = installStorage(raw)
  globalThis.__projectsApi = async (path, init) => {
    assert.equal(path, "/api/projects")
    assert.equal(init?.method, "POST")
    assert.deepEqual(JSON.parse(init.body), { name: "New" })
    return { id: "new", name: "New", taskIds: [], conversationIds: [], repoPaths: [] }
  }
  const created = await projects.createProjectRemote("New")
  assert.equal(created.id, "new")
  assert.equal(data.get(STORAGE_KEY), raw)
})
})
