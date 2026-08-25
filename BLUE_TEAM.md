# Blue team — home-network SIEM and sniffer response

Status: **separate specification** referenced by `JARVIS_MASTER_PLAN.md`. **Not implemented.** Architect-owned.

Defensive security on the **user’s own home network only**.

Taco wants to know if the LAN is being sniffed (including by colleagues on that LAN) and to have Jarvis **investigate, identify, contain, and keep evidence** on gear he owns. Metaphor: unleash Jarvis on that sniffer **on his network**. This is not a license to attack other people’s systems, law-enforcement infrastructure, or anything **off his LAN**.

The blue-team agent is a **Jarvis worker/profile**, not a second product. It may reuse **router admin credentials** stored during link-device (`ANDROID_CLIENT.md`).

## 1. Scope (allowed)

- The home LAN, Wi-Fi, and routers/APs/switches **the user owns or is authorized to administer**.
- The Leader PC and other endpoints the user enrolls.
- Optional packet **metadata** (headers, flows) from a SPAN/mirror port **the user owns**. Full-payload capture is opt-in and stored locally.

## 2. Scope (forbidden)

Do **not** spec, implement, or document:

- exploits, exploit PoCs, malware, or attack payloads
- attacking a suspected sniffer **off this LAN**
- hacking police, ISP core, or anyone else’s systems
- brute-force of third-party accounts
- disabling lawful intercept or attacking investigators

If a colleague’s phone is on **this** Wi-Fi, response is **owned-network containment** (guest VLAN, client isolation, DHCP deny, AP kick) with evidence — not an offensive payload against that phone.

## 3. Local SIEM

Canonical state is **Jarvis**, not a SaaS SOC.

Ingest (local):

- DNS / DHCP / ARP / new-MAC / Wi-Fi client lists
- **Router logs** (using the same router credentials from link-device; AI-guided admin UI if needed)
- Optional flow/metadata from a user-owned SPAN/mirror
- Endpoint logs from the Leader PC

Store compact facts: timestamp, source, device identity, event type, evidence pointers, confidence. No hidden chain-of-thought. Retention is local and user-configurable.

## 4. Detect

Examples of **defensive detections** (signatures and heuristics, not exploits):

- new devices / unknown MACs
- hints of promiscuous or monitor-mode behavior **visible from owned infrastructure** (e.g. AP flags, DHCP fingerprint oddity, ARP table fights)
- ARP spoof / gateway impersonation on this LAN
- rogue DHCP
- unexpected port-mirror / extra admin sessions on the user’s router
- odd DNS (newly seen resolvers, flood, known-bad names the user has listed)
- an **authorized** device talking in a new, strange way (new ports, new peers)

Alerts go to the **portal and phone**. Autonomy profile gates what happens next.

## 5. Response on the owned network

1. **Identify** MAC, vendor OUI, hostname, last AP, role guess (phone, laptop, IoT).
2. **Alert Taco** with evidence links.
3. **Contain** via the **user’s router/AP** (guest VLAN, client isolation, DHCP deny, disable a switch port the user owns) — **with user confirm** unless the Autonomous profile plus an explicit “contain this device class” policy is set.
4. **Keep evidence** in the SIEM (logs, before/after ARP/DHCP, router config diff).

Use existing browser / computer-use tools to drive the gateway admin UI (same pattern as `ANDROID_CLIENT.md`). Do not disable the household firewall as a whole. Do not forward extra WAN ports as a “response.”

## 6. Relation to other specs

- Router passwords: `ANDROID_CLIENT.md` link-device. Same secret store.
- New IoT MAC: correlate with `HOME_IOT.md` inventory; unknown device is a blue-team event until the user accepts it.
- High-autonomy security in `JARVIS_2.0.md` §81 remains; this file is the **home-LAN SIEM** slice. Future SIEM/forensics roles in `SWARM_ARCHITECTURE.md` stay separately specified and are not promoted by this file alone.

## 7. Acceptance (when implemented)

- [ ] Local SIEM ingest from router + Leader (and optional user-owned mirror)
- [ ] Alerts on portal + phone for new device / ARP / rogue DHCP / odd DNS classes above
- [ ] Containment actions only on owned network gear, gated by autonomy profile
- [ ] Evidence retained locally
- [ ] No exploit/PoC/offensive payload in the product or this spec
