# Security agents — Blue, Purple, Red-gated

Status: **separate specification** referenced by `JARVIS_MASTER_PLAN.md`. **Not implemented.** Architect-owned.

This file is the canonical home-network security spec (renamed from a Blue-only write-up). `BLUE_TEAM.md` remains as a pointer so that name is not lost.

Three **Jarvis workers / profiles**, not separate products. All run on the Leader like other workers. Identify, isolate, and evidence stay with **Blue**. This spec does **not** contain exploits, exploit PoCs, payloads, attack procedures, or hacking-back how-tos.

| Profile | Default | Role |
| --- | --- | --- |
| **Blue** | On (home/consumer) | Detect, alert, contain, evidence on the **user’s own** LAN/SIEM |
| **Purple** | Off until explicit confirm | Authorized adversary *simulation* on **owned** lab/home only, to test Blue |
| **Red** | Disabled; no consumer toggle | Locked future counter-response worker. Spec the **gate**, not the attacks. Stub refuses until an LE authorization module Taco provides exists. |

## 0. Common rules

- Canonical SIEM state is **Jarvis**, not a SaaS SOC.
- Secrets: router credentials from link-device (`ANDROID_CLIENT.md`) live in local secret storage only.
- **Blue** (and **Purple** on owned net) may use those router credentials.
- **Red** does **not** receive router (or other) credentials unless the law-enforcement gate is on **and** the action is inside the authorized case scope.
- Autonomy profiles cannot silently enable Purple or Red.
- Out of scope for all three: attacking third-party systems, police-colleague devices **off** Taco’s authorized network, ISP core, or “unleash malware on the sniffer.”

---

## 1. Blue (home, default on)

Household path. Defensive security on the **user’s own LAN**.

Taco wants to know if the LAN is being sniffed (including by colleagues **on that LAN**) and to have Jarvis **investigate, identify, contain, and keep evidence** on gear he owns. That is Blue. It is not a license to attack anyone off his LAN.

### 1.1 Allowed

- Home LAN, Wi-Fi, routers/APs/switches the user owns or is authorized to administer
- Leader PC and enrolled endpoints
- Optional packet **metadata** from a SPAN/mirror **the user owns** (full payload opt-in, stored locally)

### 1.2 Forbidden (do not spec or ship)

- Exploits, PoCs, malware, attack payloads
- Attacking a suspected sniffer **off this LAN**
- Hacking police, ISP core, or anyone else’s systems
- Brute-force of third-party accounts

If a colleague’s phone is on **this** Wi-Fi: **owned-network containment** (guest VLAN, client isolation, DHCP deny, AP kick) plus evidence — not an offensive payload against that phone.

### 1.3 SIEM ingest

- DNS / DHCP / ARP / new-MAC / Wi-Fi client lists
- Router logs (link-device credentials; AI-guided admin UI if needed)
- Optional flow/metadata from a user-owned mirror
- Endpoint logs from the Leader PC

Compact facts only. No hidden chain-of-thought.

### 1.4 Detect and respond

Detect (heuristics, not exploits): new devices, promiscuous/monitor hints **visible from owned infrastructure**, ARP spoof, rogue DHCP, unexpected port-mirror, odd DNS, authorized device behaving newly strangely.

Alert on **portal + phone**. Then: identify MAC/vendor/role → contain via **owned** router/AP with user confirm unless Autonomous plus an explicit contain-this-class policy → keep evidence in the SIEM.

Use existing browser/computer-use tools on the gateway admin UI. Do not disable the household firewall as a whole. Do not add WAN forwards as a “response.”

### 1.5 Acceptance (Blue)

- [ ] Local SIEM ingest; alerts on portal + phone
- [ ] Containment only on owned gear, autonomy-gated
- [ ] Evidence retained locally
- [ ] Default on in the consumer/home build
- [ ] No exploit/PoC/offensive payload

---

## 2. Purple (owned-network only)

Authorized **adversary simulation** against the user’s **own** lab/home to **test Blue**. Goal is to improve detection, not to attack anyone else.

- Requires **explicit user confirm** plus a compatible autonomy profile (never silent).
- Scope: assets the user owns and lists for the exercise (home LAN segments, lab VMs, enrolled test hosts).
- Purple may use link-device router credentials **only** to exercise owned-network controls (e.g. confirm Blue sees a guest-VLAN change the user approved).
- Purple must produce an exercise record in the SIEM (start/end, scope, what Blue did or missed).
- If Blue is not running, Purple still must not leave the owned scope.

This spec does **not** describe simulation techniques, payloads, or exploit steps. Implementation of Purple is a later ticket that still must not ship offensive recipes in the consumer tree. Until implemented, Purple is unspecified-as-code and must refuse any request that names a non-owned target.

### 2.1 Acceptance (Purple)

- [ ] Explicit confirm + autonomy gate before any exercise
- [ ] Owned-asset allowlist required
- [ ] SIEM exercise record
- [ ] Refuses non-owned targets
- [ ] No exploit/PoC text in product or this spec

---

## 3. Red / counter-response — LAW ENFORCEMENT GATE ONLY

Taco wants **limited counterhacking-as-defense**, gated for **law enforcement use only**. This section specs the **GATE**, not the attacks.

Red is a **locked future worker**, not a shipped hack-back kit. Identify / isolate / evidence remain **Blue**.

### 3.1 Default disabled

- **Disabled** in the consumer/home build.
- **No UI toggle** a normal user can flip (Settings, phone, swarm page, env var in the home docs — none of these enable Red).

### 3.2 Enablement module (does not exist yet)

Enablement requires a **distinct LE authorization module**:

- Identity + an **authorization artifact Taco must provide** (do **not** invent a fake badge check, a “type LE in this box,” or a hidden settings flag).
- Until that module exists and is satisfied, the **red worker is a stub that refuses to run**.

Even when the gate is on:

- a **case / authorization record** is required
- **human confirm** is required
- **full audit log** in the SIEM is required
- **autonomy profile cannot silently enable Red**

### 3.3 In-scope vs out-of-scope (gate language only)

**In-scope when gated on:** defensive response on a network Taco is **legally authorized** to operate (his home remains Blue/Purple; LE systems only with this gate).

**Out of scope in this spec (do not write):**

- exploit recipes, payload development, attack procedures
- attacking third-party or police-colleague devices **off** his LAN
- “unleash malware on the sniffer”
- hacking-back how-tos

Red **does not get router credentials** unless the LE gate is on **and** the action is in authorized case scope.

### 3.4 Acceptance (Red gate)

- [ ] Home build: Red stub refuses; no consumer toggle
- [ ] No run without LE authorization module + case record + human confirm + SIEM audit
- [ ] Autonomy cannot enable Red
- [ ] Credentials withheld unless gate + authorized scope
- [ ] This file still contains no attack recipes

---

## 4. Relation to other specs

- Router passwords: `ANDROID_CLIENT.md` link-device. Blue/Purple (owned net) may use them; Red only under §3.
- Unknown IoT MAC: `HOME_IOT.md` inventory vs Blue event.
- `JARVIS_2.0.md` §81 high-autonomy security remains. Swarm SIEM/forensics roles stay separately specified and are not promoted by this file alone.

## 5. Filter

New ideas that make home-network JARVIS more real may be added here. Do not delete Taco-approved Blue household behavior to “simplify.” Do not fill Red with attack content.
