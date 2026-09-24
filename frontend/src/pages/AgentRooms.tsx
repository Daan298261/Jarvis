import { useCallback, useEffect, useState, type FormEvent } from "react"
import { AdvancedDisclosure } from "../components/AdvancedDisclosure"
import { Link, useNavigate, useParams } from "react-router-dom"
import {
  createAgentRoom,
  formatAgentRoomsError,
  getAgentRoom,
  getAgentRoomAudit,
  getAgentRoomBlackboard,
  handoffAgentRoom,
  listAgentRoomMessages,
  listAgentRooms,
  postAgentRoomMessage,
  publicRoomFields,
  publishAgentRoomBlackboard,
  synthesizeAgentRoom,
  terminateAgentRoom,
  type AgentRoomAudit,
  type AgentRoomBlackboard,
  type AgentRoomMessage,
  type AgentRoomRosterEntry,
  type AgentRoomSummary,
} from "../api"

const MESSAGE_KINDS = ["REQUEST", "RESULT", "QUESTION", "CHALLENGE", "BLOCKED"] as const
const BOARD_KINDS = ["fact", "artifact", "decision", "citation"] as const
const COST_MODES = [
  { id: "frugal", label: "Frugal" },
  { id: "balanced", label: "Balanced" },
  { id: "performance", label: "Performance" },
] as const
const PRIVACY_MODES = [
  { id: "local_only", label: "Local only" },
  { id: "require_local", label: "Require local" },
  { id: "allow_cloud", label: "Allow cloud" },
] as const

function labelFor(id: string, roster: AgentRoomRosterEntry[]): string {
  if (id === "anzu") return "Anzu"
  return roster.find((row) => row.id === id)?.label || id
}

function statusClass(status: string): string {
  if (status === "open" || status === "done" || status === "RESULT" || status === "FINAL") return "badge completed"
  if (status === "terminated" || status === "escalated" || status === "cancelled" || status === "blocked" || status === "BLOCKED") {
    return "badge failed"
  }
  if (status === "running" || status === "HANDOFF" || status === "QUESTION" || status === "CHALLENGE") return "badge waiting"
  return "badge queued"
}

function shortId(value: string): string {
  return value.length > 8 ? value.slice(0, 8) : value
}

export function AgentRoomsPage() {
  const { roomId } = useParams<{ roomId?: string }>()
  const navigate = useNavigate()
  const [rooms, setRooms] = useState<AgentRoomSummary[] | null>(null)
  const [roster, setRoster] = useState<AgentRoomRosterEntry[] | null>(null)
  const [listReady, setListReady] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [goal, setGoal] = useState("")
  const [selected, setSelected] = useState<string[]>([])
  const [costMode, setCostMode] = useState<string>("balanced")
  const [privacyMode, setPrivacyMode] = useState<string>("local_only")
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const [actionOk, setActionOk] = useState<string | null>(null)
  const [detailNonce, setDetailNonce] = useState(0)

  const refreshList = useCallback(async () => {
    try {
      const index = await listAgentRooms()
      if (!index || !Array.isArray(index.rooms) || !Array.isArray(index.roster)) {
        throw new Error("Agent rooms response did not include rooms and the Anzu roster")
      }
      setRooms(index.rooms)
      setRoster(index.roster)
      if (index.roster.length === 0) {
        setLoadError("Anzu specialist roster came back empty. A room needs at least one specialist.")
      } else {
        setLoadError(null)
      }
    } catch (err: unknown) {
      setLoadError(formatAgentRoomsError(err))
    } finally {
      setListReady(true)
    }
  }, [])

  useEffect(() => {
    void refreshList()
  }, [refreshList])

  function toggleSpecialist(id: string) {
    setSelected((current) => (current.includes(id) ? current.filter((item) => item !== id) : [...current, id]))
  }

  async function onCreate(event: FormEvent) {
    event.preventDefault()
    setActionError(null)
    setActionOk(null)
    const goalText = goal.trim()
    if (!goalText) {
      setActionError("A goal is required.")
      return
    }
    if (selected.length === 0) {
      setActionError("Choose at least one specialist from the Anzu roster.")
      return
    }
    setBusy(true)
    try {
      const created = await createAgentRoom({
        goal: goalText,
        specialists: selected,
        cost_mode: costMode,
        privacy_mode: privacyMode,
      })
      if (!created?.id) throw new Error("Create room did not return a room id")
      setActionOk(`Opened room ${shortId(created.id)}. Anzu assigned one task per specialist.`)
      setGoal("")
      await refreshList()
      navigate(`/rooms/${created.id}`)
    } catch (err: unknown) {
      setActionError(formatAgentRoomsError(err))
    } finally {
      setBusy(false)
    }
  }

  const rosterReady = Array.isArray(roster) && roster.length > 0

  return (
    <div className="agent-rooms-page">
      <h1>Agent rooms</h1>
      <p className="lede">
        Anzu 1.0 collaboration. Anzu supervises named specialists. Messages are typed
        (request, result, question, challenge, handoff, blocked, final). The blackboard
        holds shared facts, artifacts, decisions, and citations. Hidden chain-of-thought
        is not shown — only the concise rationale on each handoff.
      </p>

      {loadError && (
        <div className="card coding-banner bad" role="alert">
          <p className="license-kicker">Could not load agent rooms</p>
          <p className="lede" style={{ margin: 0 }}>{loadError}</p>
        </div>
      )}
      {actionError && (
        <div className="card coding-banner bad" role="alert">
          <p className="license-kicker">Action failed</p>
          <p className="lede" style={{ margin: 0 }}>{actionError}</p>
        </div>
      )}
      {actionOk && (
        <div className="card" style={{ marginBottom: 16, borderLeft: "4px solid var(--ok)", padding: "12px 16px" }}>
          <p className="lede" style={{ margin: 0 }}>{actionOk}</p>
        </div>
      )}

      <form className="card" style={{ marginBottom: 16 }} onSubmit={(event) => void onCreate(event)}>
        <div className="rail-heading" style={{ padding: "0 0 8px" }}>
          <span>Open a room</span>
        </div>
        <p className="lede">
          Anzu joins as supervisor. Pick specialists from the named roster. The resource
          governor uses the cost and privacy mode you choose.
        </p>
        {!listReady ? (
          <p className="lede">Loading the Anzu roster…</p>
        ) : !rosterReady ? (
          <p className="lede" style={{ margin: 0 }}>
            Specialists are unavailable until the roster loads. This is not an empty room list.
          </p>
        ) : (
          <>
            <label>
              Goal
              <textarea
                value={goal}
                onChange={(event) => setGoal(event.target.value)}
                rows={3}
                aria-label="Room goal"
                placeholder="What should this room finish?"
              />
            </label>
            <p className="lede" style={{ marginBottom: 4 }}>Specialists</p>
            <div className="agent-room-roster">
              {roster!.map((row) => (
                <label key={row.id}>
                  <input
                    type="checkbox"
                    checked={selected.includes(row.id)}
                    onChange={() => toggleSpecialist(row.id)}
                  />
                  <span>
                    <strong>{row.label}</strong>
                    <span className="lede" style={{ display: "block", margin: 0 }}>
                      {row.phrase}. {row.role}
                    </span>
                  </span>
                </label>
              ))}
            </div>
            <AdvancedDisclosure>
              <div className="row" style={{ flexWrap: "wrap", gap: 12 }}>
                <label style={{ flex: "1 1 180px" }}>
                  Cost mode
                  <select aria-label="Cost mode" value={costMode} onChange={(event) => setCostMode(event.target.value)}>
                    {COST_MODES.map((mode) => (
                      <option key={mode.id} value={mode.id}>{mode.label}</option>
                    ))}
                  </select>
                </label>
                <label style={{ flex: "1 1 180px" }}>
                  Privacy mode
                  <select aria-label="Privacy mode" value={privacyMode} onChange={(event) => setPrivacyMode(event.target.value)}>
                    {PRIVACY_MODES.map((mode) => (
                      <option key={mode.id} value={mode.id}>{mode.label}</option>
                    ))}
                  </select>
                </label>
              </div>
            </AdvancedDisclosure>
            <div className="row" style={{ gap: 8, marginTop: 12 }}>
              <button className="btn" type="submit" disabled={busy}>Open room</button>
              <button className="btn secondary" type="button" disabled={busy} onClick={() => void refreshList()}>
                Refresh
              </button>
            </div>
          </>
        )}
      </form>

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="rail-heading" style={{ padding: "0 0 8px" }}>
          <span>Rooms</span>
        </div>
        {!listReady ? (
          <p className="lede" style={{ margin: 0 }}>Loading rooms…</p>
        ) : rooms === null ? (
          <p className="lede" style={{ margin: 0 }}>
            Rooms did not load. Fix the error above — this is not an empty room list.
          </p>
        ) : rooms.length === 0 ? (
          <p className="lede" style={{ margin: 0 }}>No agent rooms yet. Open one with a goal and at least one specialist.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Goal</th>
                <th>Status</th>
                <th>Participants</th>
                <th>Messages</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {rooms.map((room) => (
                <tr key={room.id}>
                  <td>
                    <strong>{room.goal}</strong>
                    <div className="lede" style={{ margin: "4px 0 0" }}>{shortId(room.id)}</div>
                  </td>
                  <td><span className={statusClass(room.status)}>{room.status}</span></td>
                  <td>{room.participants.map((p) => labelFor(p.agent_id, roster || [])).join(", ")}</td>
                  <td>{room.message_count}</td>
                  <td>
                    <Link to={`/rooms/${room.id}`}>Open</Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {roomId && (
        <RoomDetail
          roomId={roomId}
          roster={roster || []}
          nonce={detailNonce}
          busy={busy}
          onBusy={setBusy}
          onActionError={setActionError}
          onActionOk={setActionOk}
          onChanged={() => {
            setDetailNonce((value) => value + 1)
            void refreshList()
          }}
        />
      )}
    </div>
  )
}

type RoomDetailProps = {
  roomId: string
  roster: AgentRoomRosterEntry[]
  nonce: number
  busy: boolean
  onBusy: (busy: boolean) => void
  onActionError: (message: string | null) => void
  onActionOk: (message: string | null) => void
  onChanged: () => void
}

function RoomDetail({
  roomId,
  roster,
  nonce,
  busy,
  onBusy,
  onActionError,
  onActionOk,
  onChanged,
}: RoomDetailProps) {
  const [room, setRoom] = useState<AgentRoomSummary | null>(null)
  const [messages, setMessages] = useState<AgentRoomMessage[] | null>(null)
  const [board, setBoard] = useState<AgentRoomBlackboard | null>(null)
  const [audit, setAudit] = useState<AgentRoomAudit | null>(null)
  const [roomError, setRoomError] = useState<string | null>(null)
  const [messagesError, setMessagesError] = useState<string | null>(null)
  const [boardError, setBoardError] = useState<string | null>(null)
  const [auditError, setAuditError] = useState<string | null>(null)
  const [detailStatus, setDetailStatus] = useState<"loading" | "ready">("loading")

  const [kind, setKind] = useState<string>("REQUEST")
  const [fromAgent, setFromAgent] = useState("anzu")
  const [toAgent, setToAgent] = useState("")
  const [messageBody, setMessageBody] = useState("")
  const [messageRationale, setMessageRationale] = useState("")
  const [taskId, setTaskId] = useState("")
  const [handoffFrom, setHandoffFrom] = useState("anzu")
  const [handoffTo, setHandoffTo] = useState("")
  const [handoffBody, setHandoffBody] = useState("")
  const [handoffRationale, setHandoffRationale] = useState("")
  const [boardKind, setBoardKind] = useState<string>("fact")
  const [boardKey, setBoardKey] = useState("")
  const [boardContent, setBoardContent] = useState("")
  const [boardAuthor, setBoardAuthor] = useState("anzu")
  const [terminateReason, setTerminateReason] = useState("terminated by owner")

  useEffect(() => {
    let cancelled = false
    setDetailStatus("loading")
    setRoom(null)
    setMessages(null)
    setBoard(null)
    setAudit(null)
    setRoomError(null)
    setMessagesError(null)
    setBoardError(null)
    setAuditError(null)
    void (async () => {
      const [roomResult, messagesResult, boardResult, auditResult] = await Promise.allSettled([
        getAgentRoom(roomId),
        listAgentRoomMessages(roomId),
        getAgentRoomBlackboard(roomId),
        getAgentRoomAudit(roomId),
      ])
      if (cancelled) return
      if (roomResult.status === "fulfilled" && roomResult.value?.id) {
        const loaded = roomResult.value
        setRoom(loaded)
        const specialists = loaded.participants
          .filter((participant) => participant.role === "specialist")
          .map((participant) => participant.agent_id)
        setFromAgent("anzu")
        setToAgent(specialists[0] || "")
        setHandoffFrom(specialists[0] || "anzu")
        setHandoffTo(specialists[1] || specialists[0] || "")
        setBoardAuthor("anzu")
        setTaskId(loaded.task_graph?.tasks?.[0]?.id || "")
      } else if (roomResult.status === "fulfilled") {
        setRoomError("Room response did not include a room")
      } else {
        setRoomError(formatAgentRoomsError(roomResult.reason))
      }
      if (messagesResult.status === "fulfilled") {
        if (!Array.isArray(messagesResult.value?.messages)) {
          setMessagesError("Messages response did not include a messages list")
        } else {
          setMessages(messagesResult.value.messages)
        }
      } else {
        setMessagesError(formatAgentRoomsError(messagesResult.reason))
      }
      if (boardResult.status === "fulfilled") {
        if (!boardResult.value || !Array.isArray(boardResult.value.entries)) {
          setBoardError("Blackboard response did not include entries")
        } else {
          setBoard(boardResult.value)
        }
      } else {
        setBoardError(formatAgentRoomsError(boardResult.reason))
      }
      if (auditResult.status === "fulfilled") {
        if (!auditResult.value || !Array.isArray(auditResult.value.events)) {
          setAuditError("Audit replay did not include events")
        } else {
          setAudit(auditResult.value)
        }
      } else {
        setAuditError(formatAgentRoomsError(auditResult.reason))
      }
      setDetailStatus("ready")
    })()
    return () => {
      cancelled = true
    }
  }, [roomId, nonce])

  const participants = room?.participants || []
  const open = room?.status === "open"
  const name = (id: string) => labelFor(id, roster)
  const participantOptions = participants.map((participant) => ({
    id: participant.agent_id,
    label: name(participant.agent_id),
  }))

  async function runAction(work: () => Promise<string>) {
    onActionError(null)
    onActionOk(null)
    onBusy(true)
    try {
      const ok = await work()
      onActionOk(ok)
      onChanged()
    } catch (err: unknown) {
      onActionError(formatAgentRoomsError(err))
    } finally {
      onBusy(false)
    }
  }

  return (
    <section aria-label="Room detail">
      <div className="row" style={{ justifyContent: "space-between", alignItems: "baseline" }}>
        <h2 style={{ marginBottom: 8 }}>Room {shortId(roomId)}</h2>
        <Link to="/rooms">All rooms</Link>
      </div>

      {detailStatus === "loading" && <p className="lede">Loading room…</p>}

      {roomError && (
        <div className="card coding-banner bad" role="alert">
          <p className="license-kicker">Could not load this room</p>
          <p className="lede" style={{ margin: 0 }}>{roomError}</p>
        </div>
      )}

      {detailStatus === "ready" && !room && (
        <p className="lede">Room detail is unavailable. The error above is the result — participants were not loaded.</p>
      )}

      {room && (
        <>
          <div className="card" style={{ marginBottom: 16 }}>
            <p className="lede" style={{ marginTop: 0 }}>{room.goal}</p>
            <p>
              <span className={statusClass(room.status)}>{room.status}</span>
            </p>
            {open ? (
              <form
                className="row"
                style={{ gap: 8, flexWrap: "wrap", alignItems: "flex-end" }}
                onSubmit={(event) => {
                  event.preventDefault()
                  const reason = terminateReason.trim()
                  if (!reason) {
                    onActionError("A termination reason is required.")
                    return
                  }
                  void runAction(async () => {
                    await terminateAgentRoom(room.id, { reason })
                    return "Room terminated."
                  })
                }}
              >
                <label style={{ flex: "1 1 240px" }}>
                  Termination reason
                  <input
                    value={terminateReason}
                    onChange={(event) => setTerminateReason(event.target.value)}
                    aria-label="Termination reason"
                  />
                </label>
                <button className="btn secondary" type="submit" disabled={busy}>Terminate</button>
              </form>
            ) : (
              <p className="lede" style={{ marginBottom: 0 }}>This room is closed. New messages, handoffs, and blackboard writes are rejected.</p>
            )}
          </div>

          <div className="card" style={{ marginBottom: 16 }}>
            <h3 className="env-subhead">Participants</h3>
            {participants.length === 0 ? (
              <p className="lede" style={{ margin: 0 }}>This room has no participants.</p>
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>Agent</th>
                    <th>Role</th>
                    <th>Model</th>
                    <th>Provider</th>
                  </tr>
                </thead>
                <tbody>
                  {participants.map((p) => (
                    <tr key={p.agent_id}>
                      <td>{name(p.agent_id)}</td>
                      <td>{p.role}</td>
                      <td>{p.model ? p.model : "No model assigned"}</td>
                      <td>{p.provider || "local"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          <div className="card" style={{ marginBottom: 16 }}>
            <h3 className="env-subhead">Task graph</h3>
            {!room.task_graph || !Array.isArray(room.task_graph.tasks) ? (
              <p className="lede" style={{ margin: 0 }}>Task graph was missing from the room.</p>
            ) : room.task_graph.tasks.length === 0 ? (
              <p className="lede" style={{ margin: 0 }}>No tasks assigned.</p>
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>Task</th>
                    <th>Assignee</th>
                    <th>Status</th>
                    <th>Why</th>
                  </tr>
                </thead>
                <tbody>
                  {room.task_graph.tasks.map((task) => (
                    <tr key={task.id}>
                      <td>
                        {task.title}
                        <div className="lede" style={{ margin: "4px 0 0" }}>{shortId(task.id)}</div>
                      </td>
                      <td>{task.assignee ? name(task.assignee) : "Unassigned"}</td>
                      <td><span className={statusClass(task.status)}>{task.status}</span></td>
                      <td>{task.rationale || "No rationale recorded"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          <div className="card" style={{ marginBottom: 16 }}>
            <h3 className="env-subhead">Typed timeline</h3>
            {messagesError && (
              <div className="card coding-banner bad" role="alert">
                <p className="license-kicker">Could not load messages</p>
                <p className="lede" style={{ margin: 0 }}>{messagesError}</p>
              </div>
            )}
            {messagesError ? (
              <p className="lede" style={{ margin: 0 }}>Timeline unavailable until messages load.</p>
            ) : messages === null ? (
              <p className="lede" style={{ margin: 0 }}>Loading messages…</p>
            ) : messages.length === 0 ? (
              <p className="lede" style={{ margin: 0 }}>No typed messages yet.</p>
            ) : (
              <ol className="agent-room-timeline">
                {messages.map((message) => (
                  <li key={message.id}>
                    <span className={statusClass(message.kind)}>{message.kind}</span>{" "}
                    <strong>{name(message.from_agent)}</strong>
                    {message.to_agent ? ` → ${name(message.to_agent)}` : ""}
                    <p style={{ margin: "6px 0" }}>{message.body}</p>
                    {message.kind === "HANDOFF" && (
                      <p className="lede" style={{ margin: 0 }}>
                        Handoff rationale: {message.rationale || "No rationale recorded"}
                      </p>
                    )}
                    {message.kind !== "HANDOFF" && message.rationale ? (
                      <p className="lede" style={{ margin: 0 }}>Rationale: {message.rationale}</p>
                    ) : null}
                  </li>
                ))}
              </ol>
            )}

            {open && (
              <AdvancedDisclosure>
              <form
                style={{ marginTop: 16 }}
                onSubmit={(event) => {
                  event.preventDefault()
                  const body = messageBody.trim()
                  if (!body) {
                    onActionError("Message body is required.")
                    return
                  }
                  void runAction(async () => {
                    await postAgentRoomMessage(room.id, {
                      kind,
                      from_agent: fromAgent,
                      to_agent: toAgent || null,
                      body,
                      rationale: messageRationale.trim(),
                      task_id: taskId || null,
                    })
                    setMessageBody("")
                    return "Message posted."
                  })
                }}
              >
                <h3 className="env-subhead">Post a typed message</h3>
                <div className="row" style={{ gap: 12, flexWrap: "wrap" }}>
                  <label style={{ flex: "1 1 140px" }}>
                    Kind
                    <select aria-label="Message kind" value={kind} onChange={(event) => setKind(event.target.value)}>
                      {MESSAGE_KINDS.map((item) => (
                        <option key={item} value={item}>{item}</option>
                      ))}
                    </select>
                  </label>
                  <AgentSelect label="From" value={fromAgent} options={participantOptions} onChange={setFromAgent} />
                  <AgentSelect label="To" value={toAgent} options={participantOptions} onChange={setToAgent} allowEmpty />
                </div>
                <label>
                  Body
                  <textarea aria-label="Message body" rows={3} value={messageBody} onChange={(event) => setMessageBody(event.target.value)} />
                </label>
                <label>
                  Rationale
                  <input aria-label="Message rationale" value={messageRationale} onChange={(event) => setMessageRationale(event.target.value)} />
                </label>
                <button className="btn" type="submit" disabled={busy}>Post message</button>
              </form>
              </AdvancedDisclosure>
            )}
          </div>

          {open && (
            <form
              className="card"
              style={{ marginBottom: 16 }}
              onSubmit={(event) => {
                event.preventDefault()
                const body = handoffBody.trim()
                const rationale = handoffRationale.trim()
                if (!handoffFrom || !handoffTo) {
                  onActionError("Handoff needs a sender and a recipient in this room.")
                  return
                }
                if (!body) {
                  onActionError("Handoff body is required.")
                  return
                }
                if (!rationale) {
                  onActionError("Handoff rationale is required so the room can show why it happened.")
                  return
                }
                void runAction(async () => {
                  await handoffAgentRoom(room.id, {
                    from_agent: handoffFrom,
                    to_agent: handoffTo,
                    body,
                    rationale,
                    task_id: taskId || null,
                  })
                  setHandoffBody("")
                  return "Handoff recorded."
                })
              }}
            >
              <h3 className="env-subhead">Handoff</h3>
              <p className="lede">The rationale is stored with the handoff and shown on the timeline and in the audit replay.</p>
              <div className="row" style={{ gap: 12, flexWrap: "wrap" }}>
                <AgentSelect label="From" value={handoffFrom} options={participantOptions} onChange={setHandoffFrom} />
                <AgentSelect label="To" value={handoffTo} options={participantOptions} onChange={setHandoffTo} />
                <label style={{ flex: "1 1 220px" }}>
                  Task
                  <select aria-label="Handoff task" value={taskId} onChange={(event) => setTaskId(event.target.value)}>
                    <option value="">No task</option>
                    {(room.task_graph?.tasks || []).map((task) => (
                      <option key={task.id} value={task.id}>{task.title}</option>
                    ))}
                  </select>
                </label>
              </div>
              <label>
                Body
                <textarea aria-label="Handoff body" rows={2} value={handoffBody} onChange={(event) => setHandoffBody(event.target.value)} />
              </label>
              <label>
                Why this handoff
                <input aria-label="Handoff rationale" value={handoffRationale} onChange={(event) => setHandoffRationale(event.target.value)} />
              </label>
              <button className="btn" type="submit" disabled={busy}>Hand off</button>
            </form>
          )}

          <div className="card" style={{ marginBottom: 16 }}>
            <h3 className="env-subhead">Blackboard</h3>
            {boardError && (
              <div className="card coding-banner bad" role="alert">
                <p className="license-kicker">Could not load the blackboard</p>
                <p className="lede" style={{ margin: 0 }}>{boardError}</p>
              </div>
            )}
            {boardError ? (
              <p className="lede">Blackboard unavailable. An empty board is not shown in place of this failure.</p>
            ) : board === null ? (
              <p className="lede">Loading blackboard…</p>
            ) : (
              <>
                <p className="lede">
                  {board.counts.total} entries · {board.counts.facts} facts · {board.counts.artifacts} artifacts ·{" "}
                  {board.counts.decisions} decisions · {board.counts.citations} citations · {board.bounds.used_chars} / {board.bounds.max_total_chars} characters
                </p>
                {board.entries.length === 0 ? (
                  <p className="lede" style={{ margin: 0 }}>No shared blackboard entries yet.</p>
                ) : (
                  <table>
                    <thead>
                      <tr>
                        <th>Kind</th>
                        <th>Key</th>
                        <th>Author</th>
                        <th>Content</th>
                      </tr>
                    </thead>
                    <tbody>
                      {board.entries.map((entry) => (
                        <tr key={entry.id}>
                          <td>{entry.kind}</td>
                          <td>{entry.key}</td>
                          <td>{name(entry.author)}</td>
                          <td>{entry.content}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </>
            )}
            {open && (
              <AdvancedDisclosure>
              <form
                style={{ marginTop: 16 }}
                onSubmit={(event) => {
                  event.preventDefault()
                  const key = boardKey.trim()
                  const content = boardContent.trim()
                  if (!key || !content) {
                    onActionError("Blackboard key and content are required.")
                    return
                  }
                  void runAction(async () => {
                    await publishAgentRoomBlackboard(room.id, {
                      kind: boardKind,
                      key,
                      content,
                      author: boardAuthor,
                    })
                    setBoardKey("")
                    setBoardContent("")
                    return "Blackboard entry published."
                  })
                }}
              >
                <div className="row" style={{ gap: 12, flexWrap: "wrap" }}>
                  <label style={{ flex: "1 1 140px" }}>
                    Kind
                    <select aria-label="Blackboard kind" value={boardKind} onChange={(event) => setBoardKind(event.target.value)}>
                      {BOARD_KINDS.map((item) => (
                        <option key={item} value={item}>{item}</option>
                      ))}
                    </select>
                  </label>
                  <AgentSelect label="Author" value={boardAuthor} options={participantOptions} onChange={setBoardAuthor} />
                  <label style={{ flex: "2 1 180px" }}>
                    Key
                    <input aria-label="Blackboard key" value={boardKey} onChange={(event) => setBoardKey(event.target.value)} />
                  </label>
                </div>
                <label>
                  Content
                  <textarea aria-label="Blackboard content" rows={2} value={boardContent} onChange={(event) => setBoardContent(event.target.value)} />
                </label>
                <button className="btn" type="submit" disabled={busy}>Publish</button>
              </form>
              </AdvancedDisclosure>
            )}
          </div>

          <AdvancedDisclosure>
            <div className="card" style={{ marginBottom: 0 }}>
              <h3 className="env-subhead">Resource governor</h3>
              <GovernorPanel governor={room.governor} />
            </div>
          </AdvancedDisclosure>

          <div className="card" style={{ marginBottom: 16 }}>
            <h3 className="env-subhead">Synthesis</h3>
            {room.synthesis ? (
              <SynthesisBlock synthesis={room.synthesis} name={name} />
            ) : (
              <p className="lede">No synthesis yet. Anzu writes one when you synthesize and finalize.</p>
            )}
            {open && (
              <button
                className="btn"
                type="button"
                disabled={busy}
                onClick={() => void runAction(async () => {
                  await synthesizeAgentRoom(room.id)
                  return "Synthesis posted and the room was finalized."
                })}
              >
                Synthesize and finalize
              </button>
            )}
          </div>
        </>
      )}

      <AdvancedDisclosure>
      <div className="card" style={{ marginBottom: 0 }}>
        <h3 className="env-subhead">Audit replay</h3>
        {auditError && (
          <div className="card coding-banner bad" role="alert">
            <p className="license-kicker">Could not replay the audit</p>
            <p className="lede" style={{ margin: 0 }}>{auditError}</p>
          </div>
        )}
        {auditError ? (
          <p className="lede" style={{ margin: 0 }}>Replay unavailable. An empty event list is not shown in place of this failure.</p>
        ) : audit === null ? (
          <p className="lede" style={{ margin: 0 }}>{detailStatus === "loading" ? "Loading audit…" : "Audit replay did not load."}</p>
        ) : (
          <>
            <p className="lede">
              {audit.event_count} events
              {audit.terminated ? " · terminated" : ""}
              {audit.escalated ? " · escalated to owner" : ""}
            </p>
            <h3 className="env-subhead">Handoff rationale</h3>
            {audit.handoffs.length === 0 ? (
              <p className="lede">No handoffs in this replay.</p>
            ) : (
              <ul className="env-file-list">
                {audit.handoffs.map((handoff, index) => (
                  <li key={handoff.message_id || `${handoff.from_agent}-${index}`}>
                    <strong>{name(handoff.from_agent || "")}</strong>
                    {" → "}
                    <strong>{name(handoff.to_agent || "")}</strong>
                    {": "}
                    {handoff.rationale || "No rationale recorded"}
                  </li>
                ))}
              </ul>
            )}
            {audit.deadlocks.length > 0 && (
              <>
                <h3 className="env-subhead">Deadlock resolutions</h3>
                <ul className="env-file-list">
                  {audit.deadlocks.map((issue, index) => {
                    const clean = publicRoomFields(issue)
                    const detail = typeof clean.detail === "string" ? clean.detail : typeof clean.summary === "string" ? clean.summary : clean.kind
                    return <li key={index}>{String(detail || "Deadlock event")}</li>
                  })}
                </ul>
              </>
            )}
            {audit.events.length === 0 ? (
              <p className="lede" style={{ margin: 0 }}>No audit events recorded.</p>
            ) : (
              <ol className="agent-room-timeline">
                {audit.events.map((event) => {
                  const payload = publicRoomFields(event.payload)
                  const rationale = typeof payload.rationale === "string" ? payload.rationale : ""
                  return (
                    <li key={event.id}>
                      <span className="badge queued">{event.kind}</span> {event.summary}
                      {rationale ? <div className="lede">Rationale: {rationale}</div> : null}
                    </li>
                  )
                })}
              </ol>
            )}
          </>
        )}
      </div>
      </AdvancedDisclosure>
    </section>
  )
}

function AgentSelect({
  label,
  value,
  options,
  onChange,
  allowEmpty = false,
}: {
  label: string
  value: string
  options: { id: string; label: string }[]
  onChange: (value: string) => void
  allowEmpty?: boolean
}) {
  return (
    <label style={{ flex: "1 1 160px" }}>
      {label}
      <select aria-label={label} value={value} onChange={(event) => onChange(event.target.value)}>
        {allowEmpty && <option value="">Anyone</option>}
        {options.map((option) => (
          <option key={option.id} value={option.id}>{option.label}</option>
        ))}
      </select>
    </label>
  )
}

function GovernorPanel({ governor }: { governor: AgentRoomSummary["governor"] | undefined }) {
  if (!governor || !governor.budget) {
    return <p className="lede" style={{ margin: 0 }}>Governor usage was missing from the room.</p>
  }
  const budget = governor.budget
  return (
    <p className="lede" style={{ margin: 0 }}>
      Cost {budget.cost_mode}, privacy {budget.privacy_mode}. Active leases {governor.active_leases}.
      Local {governor.parallel_local}/{budget.max_parallel_local}, cloud {governor.parallel_cloud}/{budget.max_parallel_cloud}.
      CPU {governor.cpu_slots}/{budget.cpu_slots}, GPU {governor.gpu_slots}/{budget.gpu_slots}, VRAM {governor.vram_mib}/{budget.vram_mib} MiB.
    </p>
  )
}

function SynthesisBlock({
  synthesis,
  name,
}: {
  synthesis: NonNullable<AgentRoomSummary["synthesis"]>
  name: (id: string) => string
}) {
  return (
    <>
      <p>{synthesis.summary}</p>
      <p className="lede">Rationale: {synthesis.rationale || "No rationale recorded"}</p>
      <p className="lede">
        Cited agents: {synthesis.cited_agents.length ? synthesis.cited_agents.map(name).join(", ") : "none"}
      </p>
      <p className="lede">
        Cited artifacts: {synthesis.cited_artifact_ids.length ? synthesis.cited_artifact_ids.map(shortId).join(", ") : "none"}
      </p>
    </>
  )
}
