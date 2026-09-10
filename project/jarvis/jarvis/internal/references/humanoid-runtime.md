# Humanoid Runtime

## Availability

The base Jarvis humanoid presence is included with Jarvis. It is an original, locally rendered 3D avatar and does not require a separate account, character download, or cloud service.

## Activate it

1. Open **Appearance & Presence** in the Jarvis HUD or Settings.
2. Choose **Humanoid HUD**.
3. Choose a rendering preset. **Auto** is recommended; use **Efficient** if the interface affects model performance.

The change is immediate. It does not restart Jarvis or interrupt the current conversation.

## Requirements and fallback

The humanoid uses the PC's WebGL-capable graphics driver. If WebGL is unavailable or the renderer cannot start, Jarvis keeps chat operational and falls back to Neural HUD, then to the static presence if necessary.

Camera attention is not required and is never enabled merely by selecting the humanoid. Pointer attention stays local to the interface.

## Troubleshooting

- Update the graphics driver if Humanoid HUD falls back to Neural.
- Select **Efficient** rendering on lower-powered hardware.
- Select **Reduce motion** for a calm, accessibility-friendly presentation.
- A custom avatar pack is optional; the built-in `jarvis_base` avatar is always the default.
