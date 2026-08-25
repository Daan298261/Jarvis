# Home IoT — Mansion JARVIS House Control

Status: **separate specification** referenced by `JARVIS_MASTER_PLAN.md`. **Not implemented.** Architect-owned.

Jarvis manages **home IoT on the user’s LAN**: discover devices, show status, safe control, scenes, and the same voice / phone / portal surfaces as the rest of Jarvis. This is mansion-JARVIS house control, not a second product and not P3 swarm.

## 1. Local-first

Prefer:

- Home Assistant (local)
- Matter / Thread (local fabric)
- Local vendor APIs / LAN protocols the household already runs

Cloud vendor lock (Alexa/Google-only cloud, vendor apps that cannot work if the vendor dies) is a fallback, not the architecture. Canonical device identity and scene state live in **Jarvis** (and/or the local HA instance Jarvis talks to), not a SaaS hub Jarvis cannot inspect.

## 2. Capabilities

- **Discover** devices on the LAN / HA / Matter fabric (lights, plugs, climate, locks, sensors, cameras as sensors, garage if present).
- **Status:** on/off, brightness, setpoint, lock state, online/offline, last seen.
- **Safe control:** lights, plugs, climate. **Locks, garage, and safety-critical actuators** require extra confirmation under Interactive/Trusted; Autonomous profile may proceed only if the user has explicitly allowed that device class.
- **Scenes:** “movie”, “away”, “sleep”, named by the user; composed of allowed devices.
- **Surfaces:** Command portal, `/phone`, Speak. Same private-key auth as the Leader API.

Autonomy profiles from `JARVIS_MASTER_PLAN.md` §45 apply. House control is not exempt.

## 3. Safety

- Do not unlock doors or open garage without an explicit confirm unless the user has set Autonomous + that device class allowed.
- Do not disable alarms, cameras, or safety sensors as a side effect of a lighting scene.
- Destructive or irreversible IoT (factory reset, unpair, firmware flash) always asks.
- Credentials for HA / local APIs: local secret storage on the Leader (same rules as router passwords in `ANDROID_CLIENT.md`). Never git, never logs, never chat.

## 4. Relation to other specs

- Phone/voice: `ANDROID_CLIENT.md` — IoT commands are Leader API calls, not a cloud-only phone skill.
- Blue team: `BLUE_TEAM.md` — new unknown IoT MACs are security events; house control does not silently trust a new device.
- P5 domain packs may later include a Home/Facilities pack; this file remains the house-control spec.
- Not P3 swarm: bulbs are not Jarvis Nodes.

## 5. Acceptance (when implemented)

- [ ] Discover and list local devices (HA/Matter/local API)
- [ ] Control lights/plugs/climate with autonomy gates
- [ ] Locks/garage require extra confirm unless explicitly allowed
- [ ] Scenes run through Jarvis and are visible on portal + phone
- [ ] Secrets only in local storage
