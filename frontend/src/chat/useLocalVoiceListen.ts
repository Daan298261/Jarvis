import { useEffect, useRef, useState } from "react"
import { api, apiForm, type Task } from "../api"
import { isAuthFailureMessage } from "../setup/ownerFacing"
import { attachStreamAnalyser, detachVoiceAnalyser } from "../tts/voiceAnalyser"

type VoiceStatus = {
  stt_ready?: boolean
  tts_ready?: boolean
  detail?: string
}

type ListenHandlers = {
  setBusy: (busy: boolean) => void
  onResult: (result: { transcript?: string; taskId?: string }) => void
  onAuthFailure: () => Promise<boolean>
  onError: (message: string) => void
}

/** Classic and HUD share the existing local `/api/voice/listen` recorder. */
export function useLocalVoiceListen(handlers: ListenHandlers) {
  const [voice, setVoice] = useState<VoiceStatus | null>(null)
  const [recording, setRecording] = useState(false)
  const [transcribing, setTranscribing] = useState(false)
  const recorderRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const handlersRef = useRef(handlers)

  useEffect(() => {
    handlersRef.current = handlers
  }, [handlers])

  useEffect(() => {
    api<VoiceStatus>("/api/voice/status").then(setVoice).catch(() => undefined)
  }, [])

  async function toggleRecord() {
    if (recording) {
      recorderRef.current?.stop()
      return
    }
    if (!voice?.stt_ready) {
      handlersRef.current.onError(voice?.detail || "Local Whisper is not installed. Voice stays on this machine; cloud speech APIs are not used.")
      return
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      attachStreamAnalyser(stream)
      const recorder = new MediaRecorder(stream)
      chunksRef.current = []
      recorder.ondataavailable = (event) => {
        if (event.data.size) chunksRef.current.push(event.data)
      }
      recorder.onstop = async () => {
        detachVoiceAnalyser()
        stream.getTracks().forEach((track) => track.stop())
        setRecording(false)
        setTranscribing(true)
        handlersRef.current.setBusy(true)
        try {
          const blob = new Blob(chunksRef.current, { type: recorder.mimeType || "audio/webm" })
          const body = new FormData()
          body.append("audio", blob, "command.webm")
          const created = await apiForm<Task & { transcript?: string; task_id?: string }>("/api/voice/listen", body)
          handlersRef.current.onResult({
            transcript: created.transcript,
            taskId: created.id || created.task_id,
          })
        } catch (err: unknown) {
          const message = err instanceof Error ? err.message : String(err)
          if (message && isAuthFailureMessage(message)) {
            await handlersRef.current.onAuthFailure()
          } else {
            handlersRef.current.onError(message)
          }
        } finally {
          setTranscribing(false)
          handlersRef.current.setBusy(false)
        }
      }
      recorder.start()
      recorderRef.current = recorder
      setRecording(true)
    } catch (err: unknown) {
      detachVoiceAnalyser()
      const message = err instanceof Error ? err.message : "Microphone permission was denied."
      handlersRef.current.onError(message || "Microphone permission was denied.")
    }
  }

  return {
    recording,
    listening: recording || transcribing,
    voice,
    toggleRecord,
  }
}
