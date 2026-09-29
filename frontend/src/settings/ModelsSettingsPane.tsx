import { useState } from "react"
import { Link } from "react-router-dom"
import { api } from "../api"
import { DecisionTierSettings } from "./DecisionTierSettings"

type ModelsSettingsPaneProps = {
  settings: Record<string, unknown>
  inferenceKeyDraft: string
  setInferenceKeyDraft: (value: string) => void
  setSettings: (value: Record<string, unknown>) => void
  save: (patch: Record<string, unknown>) => Promise<void>
  setMsg: (msg: string) => void
}

export function ModelsSettingsPane({
  settings,
  inferenceKeyDraft,
  setInferenceKeyDraft,
  setSettings,
  save,
  setMsg,
}: ModelsSettingsPaneProps) {
  const [discoverBusy, setDiscoverBusy] = useState(false)
  const [discoverSummary, setDiscoverSummary] = useState("")
  const inference = (settings.inference && typeof settings.inference === "object"
    ? settings.inference
    : {}) as Record<string, unknown>
  const imageGen =
    (settings.image_generation && typeof settings.image_generation === "object"
      ? settings.image_generation
      : {}) as Record<string, unknown>

  async function discoverLocalModels() {
    setDiscoverBusy(true)
    setDiscoverSummary("")
    try {
      const payload = await api<Record<string, unknown>>("/api/model/discover-local", {
        method: "POST",
        body: JSON.stringify({ deep: true, import_new: true }),
      })
      const registered = (payload.registered || {}) as Record<string, unknown>
      const scan = (payload.scan || registered.scan || {}) as Record<string, unknown>
      const added = Array.isArray(registered.added) ? registered.added.length : 0
      const scanned = typeof scan.count === "number" ? scan.count : 0
      setDiscoverSummary(`Scan found ${scanned} GGUF file(s); registered ${added} new model(s) in Jarvis.`)
      setMsg("Local model discovery finished.")
    } catch (err) {
      setDiscoverSummary(err instanceof Error ? err.message : "Discovery failed")
    } finally {
      setDiscoverBusy(false)
    }
  }

  return (
    <>
      <div className="card grid settings-pane-card">
        <h2>Models / Inference</h2>
        <p className="lede" style={{ margin: "0 0 12px" }}>
          Your models, your PC or LAN box — this is not the Jarvis subscription. Local llama.cpp is started by Jarvis.
          A dedicated LAN GPU box, LM Studio, Ollama, vLLM, or SGLang is health-checked only — point host/port at its
          OpenAI-compatible <code>/v1</code> endpoint.{" "}
          <Link to="/model">Open Model page</Link> for LM Studio catalog and runtime profiles.
        </p>
        <label>Backend
          <select
            value={String(inference.backend || "llama.cpp")}
            onChange={(e) => save({ inference_backend: e.target.value })}
          >
            <option value="llama.cpp">llama.cpp (this PC)</option>
            <option value="remote">Remote OpenAI-compatible</option>
            <option value="ollama">Ollama</option>
            <option value="lmstudio">LM Studio</option>
            <option value="vllm">vLLM</option>
            <option value="sglang">SGLang</option>
          </select>
        </label>
        <label>Host
          <input
            value={String(inference.host || "127.0.0.1")}
            onBlur={(e) => save({ inference_host: e.target.value.trim() || "127.0.0.1" })}
            onChange={(e) =>
              setSettings({
                ...settings,
                inference: { ...inference, host: e.target.value },
              })
            }
          />
        </label>
        <label>Port
          <input
            type="number"
            value={Number(inference.port || 8088)}
            onChange={(e) => save({ inference_port: Number(e.target.value) })}
          />
        </label>
        <label>Remote model name (optional)
          <input
            value={String(inference.remote_model || "")}
            placeholder="Leave blank to use the first advertised model"
            onBlur={(e) => save({ inference_remote_model: e.target.value.trim() })}
            onChange={(e) =>
              setSettings({
                ...settings,
                inference: { ...inference, remote_model: e.target.value },
              })
            }
          />
        </label>
        <label>Front chat model (optional)
          <input
            value={String(
              ((settings.front_responder && typeof settings.front_responder === "object"
                ? settings.front_responder
                : {}) as Record<string, unknown>).model || "",
            )}
            placeholder="Same host/port as above. Blank uses the loaded model id"
            onBlur={(e) => save({ front_responder_model: e.target.value.trim() })}
            onChange={(e) =>
              setSettings({
                ...settings,
                front_responder: {
                  ...((settings.front_responder && typeof settings.front_responder === "object"
                    ? settings.front_responder
                    : {}) as Record<string, unknown>),
                  model: e.target.value,
                },
              })
            }
          />
        </label>
        <label className="row">
          <input
            type="checkbox"
            checked={
              ((settings.front_responder && typeof settings.front_responder === "object"
                ? settings.front_responder
                : { enabled: true }) as Record<string, unknown>).enabled !== false
            }
            onChange={(e) => save({ front_responder_enabled: e.target.checked })}
          />
          Tiny front-chat responder (fast first reply while the larger model continues)
        </label>
        <label className="row">
          <input
            type="checkbox"
            checked={
              ((settings.front_responder && typeof settings.front_responder === "object"
                ? settings.front_responder
                : { speak_immediately: true }) as Record<string, unknown>).speak_immediately !== false
            }
            onChange={(e) => save({ front_responder_speak_immediately: e.target.checked })}
          />
          Speak the front reply immediately (do not wait for the larger model)
        </label>
        <label>Inference API key (optional)
          <input
            type="password"
            value={inferenceKeyDraft}
            placeholder="Type to replace. Jarvis will not show a saved key."
            autoComplete="new-password"
            onChange={(e) => setInferenceKeyDraft(e.target.value)}
            onBlur={() => {
              const next = inferenceKeyDraft.trim()
              if (!next) return
              save({ inference_api_key: next }).then(() => {
                setInferenceKeyDraft("")
                setMsg("Inference key saved. It will not be shown again.")
              })
            }}
          />
        </label>
      </div>

      <DecisionTierSettings save={save} setMsg={setMsg} />

      <div className="card grid settings-pane-card">
        <h2>Discover local models</h2>
        <p className="lede" style={{ margin: "0 0 12px" }}>
          Scan standard folders (Jarvis <code>models/</code>, LM Studio, Downloads, and bounded drive paths on Windows)
          for <code>.gguf</code> files and register new weights as loadable profiles.
        </p>
        <button type="button" disabled={discoverBusy} onClick={() => void discoverLocalModels()}>
          {discoverBusy ? "Scanning…" : "Discover models on this PC"}
        </button>
        {discoverSummary && <p className="settings-note">{discoverSummary}</p>}
      </div>

      <div className="card grid settings-pane-card">
        <h2>Image generation</h2>
        <p className="lede" style={{ margin: "0 0 12px" }}>
          HyImage 2.5 is not shipped as local weights; Hy Image 3.5 Preview is cloud/API only. Local options use
          Hunyuan Image 2.1/3.0 when installed on this PC.
        </p>
        <label>Backend
          <select
            value={String(imageGen.backend || "off")}
            onChange={(e) => save({ image_generation_backend: e.target.value })}
          >
            <option value="off">Off</option>
            <option value="hunyuan_2_1">Hunyuan Image 2.1 (local pip hyimage)</option>
            <option value="hunyuan_3_local">Hunyuan Image 3.0 (local vLLM server)</option>
            <option value="hyimage_35_api">Hy Image 3.5 Preview (Tencent Cloud API)</option>
          </select>
        </label>
      </div>

      <div className="card grid settings-pane-card">
        <h2>Model profile &amp; vision</h2>
        <p className="lede" style={{ margin: "0 0 12px" }}>
          Quality vs speed tradeoffs and vision projector loading.
        </p>
        <label>Model profile
          <select value={String(inference.profile || "balanced")} onChange={(e) => save({ profile: e.target.value })}>
            <option value="fast">Fast</option>
            <option value="balanced">Balanced</option>
            <option value="quality">Quality (9B thinking on)</option>
            <option value="expert">Expert (27B)</option>
          </select>
        </label>
        <label>Vision
          <select
            value={String(inference.vision_mode || "lazy")}
            onChange={(e) => save({ vision_mode: e.target.value })}
          >
            <option value="lazy">Lazy (load projector only when needed)</option>
            <option value="always">Always load mmproj</option>
            <option value="off">Off</option>
          </select>
        </label>
        <label className="row">
          <input
            type="checkbox"
            checked={!!inference.vision}
            onChange={(e) => save({ inference_vision: e.target.checked })}
          />
          Load vision projector (uses extra VRAM; leave off for text/tool work)
        </label>
      </div>
    </>
  )
}
