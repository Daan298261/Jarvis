import type { AgentAutonomyLevel, AgentPolicyDocument, InterviewAnswers } from "../api"
import { AGENT_AUTONOMY_LEVELS, emptyInterviewAnswers } from "../api"

export const AUTONOMY_COPY: Record<AgentAutonomyLevel, { title: string; body: string }> = {
  L0_OBSERVE: { title: "Watch only", body: "Look and report. Do not act." },
  L1_SUGGEST: { title: "Suggest", body: "Propose a next step. Wait for you." },
  L2_EXECUTE_SAFE: { title: "Do safe work", body: "Handle ordinary, low-risk steps on its own." },
  L3_EXECUTE_WITH_GATES: { title: "Act with gates", body: "Work, but ask before anything risky." },
  L4_AUTONOMOUS: { title: "Act independently", body: "Carry the mission without pausing for routine steps." },
  L5_OPERATOR: { title: "Full operator", body: "Highest freedom. Still cannot pass this PC’s caps." },
}

export const TONE_OPTIONS = [
  { value: "professional", title: "Professional", body: "Clear and composed." },
  { value: "concise", title: "Concise", body: "Short. Skip the preamble." },
  { value: "friendly", title: "Friendly", body: "Warm, still useful." },
  { value: "formal", title: "Formal", body: "Careful wording." },
  { value: "direct", title: "Direct", body: "Say the point first." },
  { value: "coaching", title: "Coaching", body: "Explain choices as it goes." },
] as const

export const CHANNEL_OPTIONS = [
  { value: "web_fetch", label: "Web research" },
  { value: "filesystem", label: "Files on this PC" },
  { value: "browser", label: "Browser" },
  { value: "terminal", label: "Terminal" },
  { value: "git", label: "Git" },
  { value: "office", label: "Office documents" },
  { value: "desktop", label: "Desktop apps" },
  { value: "email", label: "Email" },
  { value: "phone", label: "Phone" },
] as const

export const APPROVAL_OPTIONS = [
  { value: "terminal", label: "Running shell commands" },
  { value: "git push", label: "Pushing to git" },
  { value: "send", label: "Sending messages" },
  { value: "purchase", label: "Spending money" },
  { value: "credentials", label: "Changing passwords or keys" },
  { value: "filesystem.write", label: "Writing or deleting files" },
] as const

export const CAPABILITY_OPTIONS = [
  { key: "*", label: "Everything else" },
  { key: "web_fetch", label: "Web research" },
  { key: "filesystem", label: "Reading files" },
  { key: "filesystem.write", label: "Changing files" },
  { key: "terminal", label: "Terminal" },
  { key: "git", label: "Git" },
  { key: "git.push", label: "Git push" },
  { key: "browser", label: "Browser" },
  { key: "python", label: "Python" },
  { key: "office", label: "Office documents" },
  { key: "desktop", label: "Desktop apps" },
  { key: "external.send", label: "Sending messages" },
  { key: "spend.purchase", label: "Purchases" },
  { key: "credentials.change", label: "Credentials" },
] as const

export const INTERVIEW_STEPS = [
  { id: "identity", title: "Who is this?", hint: "A name and the job it exists to do." },
  { id: "success", title: "What is success?", hint: "How you will know the work is good." },
  { id: "tone", title: "How should it sound?", hint: "The voice it should keep." },
  { id: "channels", title: "Where may it work?", hint: "Places and tools it is allowed to use." },
  { id: "approvals", title: "What needs your OK?", hint: "Actions that must wait for you." },
  { id: "budgets", title: "How much may it use?", hint: "Spend, calls, and other limits." },
  { id: "privacy", title: "What stays private?", hint: "Data that must not wander." },
  { id: "schedule", title: "When should it act?", hint: "Proactivity and quiet hours." },
  { id: "escalation", title: "When should it come to you?", hint: "How it asks for help." },
  { id: "prohibitions", title: "What must it never do?", hint: "Hard lines, not suggestions." },
  { id: "autonomy", title: "How much freedom?", hint: "A default, then per kind of work." },
] as const

export type InterviewForm = {
  name: string
  mission: string
  success_criteria: string
  tone: string
  allowed_channels: string[]
  approval_required_actions: string[]
  budgetDaily: string
  budgetMonthly: string
  budgetToolCalls: string
  budgetNotes: string
  privacyLeaveNetwork: boolean
  privacyRetainMemory: boolean
  privacyNotes: string
  schedulingProactive: boolean
  schedulingInterval: string
  schedulingQuietHours: string
  schedulingNotifyWhen: string
  escalationNotifyOn: string
  escalationContact: string
  escalationAfterFailures: string
  hard_prohibitions: string[]
  default_autonomy: string
  capabilityLevels: { key: string; level: string }[]
}

export function emptyInterviewForm(): InterviewForm {
  return {
    name: "",
    mission: "",
    success_criteria: "",
    tone: "professional",
    allowed_channels: [],
    approval_required_actions: [],
    budgetDaily: "",
    budgetMonthly: "",
    budgetToolCalls: "",
    budgetNotes: "",
    privacyLeaveNetwork: false,
    privacyRetainMemory: true,
    privacyNotes: "",
    schedulingProactive: false,
    schedulingInterval: "",
    schedulingQuietHours: "",
    schedulingNotifyWhen: "",
    escalationNotifyOn: "",
    escalationContact: "",
    escalationAfterFailures: "",
    hard_prohibitions: [],
    default_autonomy: "L2_EXECUTE_SAFE",
    capabilityLevels: [{ key: "*", level: "L2_EXECUTE_SAFE" }],
  }
}

function asString(value: unknown): string {
  return typeof value === "string" ? value : value == null ? "" : String(value)
}

function asNumberString(value: unknown): string {
  if (value == null || value === "") return ""
  return String(value)
}

function asBool(value: unknown, fallback: boolean): boolean {
  if (typeof value === "boolean") return value
  if (typeof value === "string") return value === "true" || value === "1"
  return fallback
}

export function formFromAnswers(name: string, answers: InterviewAnswers, policy?: AgentPolicyDocument): InterviewForm {
  const budgets = answers.budgets || {}
  const privacy = answers.privacy || {}
  const scheduling = answers.scheduling || {}
  const escalation = answers.escalation || {}
  const autonomy = policy?.autonomy || {}
  const capabilityLevels = Object.keys(autonomy).length
    ? Object.entries(autonomy).map(([key, level]) => ({ key, level }))
    : [{ key: "*", level: answers.default_autonomy || "L2_EXECUTE_SAFE" }]
  return {
    name,
    mission: answers.mission || "",
    success_criteria: answers.success_criteria || "",
    tone: answers.tone || "professional",
    allowed_channels: [...(answers.allowed_channels || [])],
    approval_required_actions: [...(answers.approval_required_actions || [])],
    budgetDaily: asNumberString(budgets.daily_spend_usd),
    budgetMonthly: asNumberString(budgets.monthly_spend_usd),
    budgetToolCalls: asNumberString(budgets.max_tool_calls),
    budgetNotes: asString(budgets.notes),
    privacyLeaveNetwork: asBool(privacy.data_may_leave_network, false),
    privacyRetainMemory: asBool(privacy.retain_memory, true),
    privacyNotes: asString(privacy.private_notes),
    schedulingProactive: asBool(scheduling.proactive, false),
    schedulingInterval: asNumberString(scheduling.check_interval_minutes),
    schedulingQuietHours: asString(scheduling.quiet_hours),
    schedulingNotifyWhen: asString(scheduling.notify_when),
    escalationNotifyOn: asString(escalation.notify_on),
    escalationContact: asString(escalation.contact),
    escalationAfterFailures: asNumberString(escalation.after_failures),
    hard_prohibitions: [...(answers.hard_prohibitions || [])],
    default_autonomy: answers.default_autonomy || "L2_EXECUTE_SAFE",
    capabilityLevels,
  }
}

function optionalNumber(value: string): number | undefined {
  const trimmed = value.trim()
  if (!trimmed) return undefined
  const parsed = Number(trimmed)
  return Number.isFinite(parsed) ? parsed : undefined
}

function compactRecord(record: Record<string, unknown>): Record<string, unknown> {
  const next: Record<string, unknown> = {}
  for (const [key, value] of Object.entries(record)) {
    if (value === undefined || value === "") continue
    next[key] = value
  }
  return next
}

export function answersFromForm(form: InterviewForm): InterviewAnswers {
  const base = emptyInterviewAnswers()
  return {
    ...base,
    mission: form.mission.trim(),
    success_criteria: form.success_criteria.trim(),
    tone: form.tone || "professional",
    allowed_channels: [...form.allowed_channels],
    approval_required_actions: [...form.approval_required_actions],
    budgets: compactRecord({
      daily_spend_usd: optionalNumber(form.budgetDaily),
      monthly_spend_usd: optionalNumber(form.budgetMonthly),
      max_tool_calls: optionalNumber(form.budgetToolCalls),
      notes: form.budgetNotes.trim(),
    }),
    privacy: compactRecord({
      data_may_leave_network: form.privacyLeaveNetwork,
      retain_memory: form.privacyRetainMemory,
      private_notes: form.privacyNotes.trim(),
    }),
    scheduling: compactRecord({
      proactive: form.schedulingProactive,
      check_interval_minutes: optionalNumber(form.schedulingInterval),
      quiet_hours: form.schedulingQuietHours.trim(),
      notify_when: form.schedulingNotifyWhen.trim(),
    }),
    escalation: compactRecord({
      notify_on: form.escalationNotifyOn.trim(),
      contact: form.escalationContact.trim(),
      after_failures: optionalNumber(form.escalationAfterFailures),
    }),
    hard_prohibitions: [...form.hard_prohibitions],
    default_autonomy: form.default_autonomy || "L2_EXECUTE_SAFE",
  }
}

export function overlayAutonomy(
  policy: AgentPolicyDocument,
  form: InterviewForm,
): AgentPolicyDocument {
  const autonomy: Record<string, string> = { ...(policy.autonomy || {}) }
  for (const row of form.capabilityLevels) {
    const key = row.key.trim()
    if (!key) continue
    autonomy[key] = row.level
  }
  if (form.default_autonomy) autonomy["*"] = form.default_autonomy
  return { ...policy, autonomy }
}

export function autonomyTitle(level: string): string {
  if ((AGENT_AUTONOMY_LEVELS as readonly string[]).includes(level)) {
    return AUTONOMY_COPY[level as AgentAutonomyLevel].title
  }
  return level
}

export function channelLabel(value: string): string {
  return CHANNEL_OPTIONS.find((option) => option.value === value)?.label || value
}

export function approvalLabel(value: string): string {
  return APPROVAL_OPTIONS.find((option) => option.value === value)?.label || value
}

