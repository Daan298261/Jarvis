import { useEffect, useState } from "react"
import type { NamedPersonaId } from "./namedPersonas"

export type PersonaSetupStatus = "not_started" | "in_progress" | "complete" | "skipped"

export type PersonaSetupStep = {
  id: string
  label: string
  detail: string
  route: string
}

export type PersonaToolPack = {
  title: string
  summary: string
  tools: string[]
  steps: PersonaSetupStep[]
}

export type PersonaSetupProgress = {
  status: PersonaSetupStatus
  stepIndex: number
  updatedAt: string
}

const STORAGE_KEY = "jarvis.named-persona-setup.v1"
const SETUP_CHANGED_EVENT = "jarvis:named-persona-setup-changed"

const step = (id: string, label: string, detail: string, route: string): PersonaSetupStep => ({
  id, label, detail, route,
})

/** Job-specific launch surfaces. The guide connects access; it never stores credentials. */
export const PERSONA_TOOL_PACKS: Record<NamedPersonaId, PersonaToolPack> = {
  anzu: {
    title: "Command and orchestration",
    summary: "Coordinate specialists, agents, and the local model fleet.",
    tools: ["Swarm", "Agents", "Model routing"],
    steps: [
      step("swarm", "Check swarm control", "Review available nodes and orchestration status.", "/swarm"),
      step("agents", "Choose the agent roster", "Enable the specialists Anzu may coordinate.", "/agents"),
      step("models", "Confirm model routing", "Keep the fast local model ready for normal commands.", "/model"),
    ],
  },
  mestor: {
    title: "Planning and operations",
    summary: "Turn missions into repeatable workflows and delegated work.",
    tools: ["Workflows", "Delegation", "Agent rooms"],
    steps: [
      step("workflows", "Review workflows", "Create or select the workflows used for recurring missions.", "/workflows"),
      step("delegation", "Set delegation defaults", "Review how plans hand work to specialists.", "/delegation"),
      step("rooms", "Prepare an operations room", "Use a room for shared mission context.", "/rooms"),
    ],
  },
  nabu: {
    title: "Knowledge and memory",
    summary: "Connect durable memory, research context, and your knowledge vault.",
    tools: ["Memory", "Obsidian", "Context repository"],
    steps: [
      step("memory", "Review memory", "Confirm the memories Nabu may use.", "/memory"),
      step("obsidian", "Connect the knowledge vault", "Bind or inspect the Obsidian vault used for durable notes.", "/obsidian"),
      step("context", "Prepare research context", "Choose repositories and documents for grounded answers.", "/context"),
    ],
  },
  enki: {
    title: "Coding and automation",
    summary: "Prepare coding workspaces, tools, and execution environments.",
    tools: ["Coding", "Tools", "Environments"],
    steps: [
      step("coding", "Open the coding workspace", "Review active coding tasks and repositories.", "/coding"),
      step("tools", "Check development tools", "Confirm terminal, filesystem, Git, and browser tools.", "/tools"),
      step("environments", "Select an environment", "Choose where Enki may build and test.", "/environments"),
    ],
  },
  veles: {
    title: "Threat analysis",
    summary: "Prepare defensive, authorized analysis tools and capability checks.",
    tools: ["Security tools", "Capability lab", "Permissions"],
    steps: [
      step("tools", "Review security tools", "Confirm only the authorized tools required for the task.", "/tools"),
      step("capabilities", "Run capability checks", "Validate the analysis capabilities before use.", "/capability-lab"),
      step("permissions", "Review permissions", "Check approval boundaries for sensitive operations.", "/settings/permissions"),
    ],
  },
  themis: {
    title: "Defence and audit",
    summary: "Configure evidence-led system review and approval boundaries.",
    tools: ["System health", "Capability lab", "Permissions"],
    steps: [
      step("system", "Inspect system health", "Review current service and security status.", "/system"),
      step("capabilities", "Validate defensive checks", "Confirm the checks used for audits and defence.", "/capability-lab"),
      step("permissions", "Review policy gates", "Verify approvals and owner-only boundaries.", "/settings/permissions"),
    ],
  },
  aegir: {
    title: "Media and communications",
    summary: "Connect voice, cameras, companion devices, and media integrations.",
    tools: ["Voice", "Phone", "MCP integrations"],
    steps: [
      step("voice", "Tune voice and audio", "Confirm the neural voice and audio devices.", "/settings/voice"),
      step("phone", "Connect a companion", "Pair the phone used for camera and media capture.", "/phone"),
      step("integrations", "Connect media integrations", "Add the services Aegir should use.", "/mcp"),
    ],
  },
  bragi: {
    title: "Writing and creativity",
    summary: "Prepare source context, writing skills, and document integrations.",
    tools: ["Skill forge", "Context", "MCP integrations"],
    steps: [
      step("skills", "Choose writing skills", "Enable the writing and document skills Bragi needs.", "/skills"),
      step("context", "Add source context", "Connect manuscripts, notes, and reference material.", "/context"),
      step("integrations", "Connect document services", "Add supported document and storage integrations.", "/mcp"),
    ],
  },
  hermes: {
    title: "Messaging and APIs",
    summary: "Connect communications, browser tools, and API services.",
    tools: ["Integrations", "MCP", "Browser tools"],
    steps: [
      step("integrations", "Connect messaging", "Set up Gmail, WhatsApp, or another supported channel.", "/setup"),
      step("mcp", "Connect API services", "Add and verify MCP-backed services.", "/mcp"),
      step("tools", "Check browser tools", "Confirm web and browser capabilities.", "/tools"),
    ],
  },
  heimdall: {
    title: "Monitoring and alerts",
    summary: "Connect system status, sensors, cameras, and alert channels.",
    tools: ["System monitor", "Phone sensors", "MCP integrations"],
    steps: [
      step("system", "Review monitoring", "Confirm the services and runtimes being watched.", "/system"),
      step("phone", "Connect sensors", "Pair the companion used for mobile sensors or cameras.", "/phone"),
      step("integrations", "Connect alert channels", "Add the service that should receive alerts.", "/mcp"),
    ],
  },
  eir: {
    title: "Routines and household care",
    summary: "Prepare gentle routines, household integrations, and companion access.",
    tools: ["Workflows", "Settings", "Companion"],
    steps: [
      step("routines", "Choose care routines", "Create or review recurring household workflows.", "/workflows"),
      step("settings", "Review privacy settings", "Confirm what Eir may remember and control.", "/settings"),
      step("phone", "Connect the companion", "Pair the device used for household access.", "/phone"),
    ],
  },
  maia: {
    title: "Audience and campaigns",
    summary: "Connect social services and reusable content workflows.",
    tools: ["MCP integrations", "Skills", "Workflows"],
    steps: [
      step("integrations", "Connect social services", "Add supported publishing and analytics integrations.", "/mcp"),
      step("skills", "Choose campaign skills", "Enable the content and analysis skills Maia needs.", "/skills"),
      step("workflows", "Prepare campaign workflows", "Create repeatable review and publishing flows.", "/workflows"),
    ],
  },
  vulcan: {
    title: "Infrastructure and hardware",
    summary: "Prepare runtimes, worker environments, and system diagnostics.",
    tools: ["System", "Environments", "Models"],
    steps: [
      step("system", "Inspect the host", "Review hardware and local service health.", "/system"),
      step("environments", "Configure workers", "Choose local or remote execution environments.", "/environments"),
      step("models", "Check model runtimes", "Confirm the model used for infrastructure tasks.", "/model"),
    ],
  },
  umi: {
    title: "Deep reasoning",
    summary: "Prepare the reasoning model, memory, and supporting tools.",
    tools: ["Model routing", "Memory", "Tools"],
    steps: [
      step("models", "Choose the reasoning model", "Review the model and context budget used by Umi.", "/model"),
      step("memory", "Review long-term context", "Confirm the memories available for deeper reasoning.", "/memory"),
      step("tools", "Check supporting tools", "Enable only the tools needed for the problem.", "/tools"),
    ],
  },
}

function blankProgress(): PersonaSetupProgress {
  return { status: "not_started", stepIndex: 0, updatedAt: "" }
}

function readAll(): Partial<Record<NamedPersonaId, PersonaSetupProgress>> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? JSON.parse(raw) : {}
  } catch {
    return {}
  }
}

export function readPersonaSetup(id: NamedPersonaId): PersonaSetupProgress {
  const value = readAll()[id]
  const max = PERSONA_TOOL_PACKS[id].steps.length - 1
  if (!value || !["not_started", "in_progress", "complete", "skipped"].includes(value.status)) return blankProgress()
  return {
    status: value.status,
    stepIndex: Math.max(0, Math.min(max, Number(value.stepIndex) || 0)),
    updatedAt: typeof value.updatedAt === "string" ? value.updatedAt : "",
  }
}

function writePersonaSetup(id: NamedPersonaId, progress: PersonaSetupProgress): PersonaSetupProgress {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...readAll(), [id]: progress }))
  } catch {
    // The guide still works for this session when storage is unavailable.
  }
  window.dispatchEvent(new CustomEvent(SETUP_CHANGED_EVENT, { detail: { id, progress } }))
  return progress
}

function save(id: NamedPersonaId, status: PersonaSetupStatus, stepIndex: number): PersonaSetupProgress {
  return writePersonaSetup(id, { status, stepIndex, updatedAt: new Date().toISOString() })
}

export function beginPersonaSetup(id: NamedPersonaId): PersonaSetupProgress {
  const current = readPersonaSetup(id)
  if (current.status === "in_progress") return current
  return save(id, "in_progress", current.status === "not_started" ? 0 : current.stepIndex)
}

export function offerPersonaSetup(id: NamedPersonaId): PersonaSetupProgress {
  const current = readPersonaSetup(id)
  return current.status === "not_started" ? save(id, "in_progress", 0) : current
}

export function advancePersonaSetup(id: NamedPersonaId): PersonaSetupProgress {
  const current = readPersonaSetup(id)
  const last = PERSONA_TOOL_PACKS[id].steps.length - 1
  if (current.stepIndex >= last) return save(id, "complete", last)
  return save(id, "in_progress", current.stepIndex + 1)
}

export function skipPersonaSetup(id: NamedPersonaId): PersonaSetupProgress {
  const current = readPersonaSetup(id)
  return save(id, "skipped", current.stepIndex)
}

export function restartPersonaSetup(id: NamedPersonaId): PersonaSetupProgress {
  return save(id, "in_progress", 0)
}

export function usePersonaSetup(id: NamedPersonaId): PersonaSetupProgress {
  const [progress, setProgress] = useState(() => readPersonaSetup(id))
  useEffect(() => {
    const onChanged = (event: Event) => {
      const detail = (event as CustomEvent<{ id: NamedPersonaId; progress: PersonaSetupProgress }>).detail
      if (detail?.id === id) setProgress(detail.progress)
    }
    window.addEventListener(SETUP_CHANGED_EVENT, onChanged)
    return () => window.removeEventListener(SETUP_CHANGED_EVENT, onChanged)
  }, [id])
  return progress
}
