import { Link } from "react-router-dom"

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
  const inference = (settings.inference && typeof settings.inference === "object"
    ? settings.inference
    : {}) as Record<string, unknown>

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
