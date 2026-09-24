/** The chat ribbon is in the document only while speech or the mic is actually live. */
export function voiceWaveformVisible(state: { speaking: boolean; listening: boolean }): boolean {
  return Boolean(state.speaking || state.listening)
}
