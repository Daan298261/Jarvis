"""Help guide catalog for distinguished Jarvis features (RFC-0078)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HelpTopic:
    id: str
    title: str
    summary: str
    href: str
    keywords: tuple[str, ...]
    body: str


TOPICS: tuple[HelpTopic, ...] = (
    HelpTopic(
        id="phone-pairing",
        title="Phone pairing",
        summary="Pair the Android companion with a six-digit code or QR from this PC.",
        href="/phone",
        keywords=("phone", "pairing", "companion", "android", "qr", "apk"),
        body=(
            "Open **Phone** in the portal. On the PC, start companion pairing to show a "
            "six-digit code and QR. On the phone, install the companion APK from this PC "
            "(Download to Desktop or the on-device build panel), then enter the code or "
            "scan the QR. The private key stays on the PC — do not email or screenshot it. "
            "LAN pairing uses the PC address on port 4780/4781; WAN follow `ANDROID_CLIENT.md`."
        ),
    ),
    HelpTopic(
        id="custom-models",
        title="Custom models",
        summary="Use local GGUFs, LM Studio catalogs, and the HUD ModelSelector.",
        href="/model",
        keywords=("model", "gguf", "lm studio", "hotswap", "qwen", "local"),
        body=(
            "Jarvis loads local GGUFs through llama.cpp. Everyday default is Qwen3.5-9B "
            "Abliterated, or **Qwen3.8-9B uncensored** when that file is already installed "
            "under `models/` or `~/.lmstudio/models`. Open the HUD ModelSelector (top right) "
            "to pin slots, mark **local** LM Studio rows, and press Play to load. **More** "
            "opens the full Model page. Conversation context survives hotswap."
        ),
    ),
    HelpTopic(
        id="swarms",
        title="Swarms",
        summary="Multi-node workers, roles, and the Swarm admin page.",
        href="/swarm",
        keywords=("swarm", "nodes", "workers", "roles", "lease"),
        body=(
            "Swarm is Jarvis’s multi-node worker fabric. The local PC is the Leader. "
            "Open **Swarm** to see nodes, roles, budgets, and leases. Workers inherit "
            "the parent’s tools, freedom, and privacy — they cannot exceed them. "
            "Detailed role rules live in `SWARM_ARCHITECTURE.md`; the portal page is "
            "the operator surface."
        ),
    ),
    HelpTopic(
        id="autonomy",
        title="Autonomy",
        summary="How much Jarvis may do without asking, including Away Mode.",
        href="/settings",
        keywords=("autonomy", "away", "approval", "trusted", "proactive"),
        body=(
            "Autonomy is set per install and per agent (trusted / guided / strict). "
            "Routine work can auto-approve; destructive or irreversible actions still "
            "gate. Away Mode and long unattended jobs are specified in `JARVIS_2.0.md` "
            "and Settings. You can always stop a task from the HUD Activity panel."
        ),
    ),
    HelpTopic(
        id="voice",
        title="Voice and talk-back",
        summary="Chat replies can be spoken; social answers start earlier.",
        href="/settings",
        keywords=("voice", "tts", "speak", "kokoro", "listen"),
        body=(
            "When speak-chat-replies is on, Jarvis reads the final conversational reply. "
            "Social answers are filtered (no markdown or stack traces) and can start on "
            "the first safe sentence. Thought / plan chrome stays behind **Show work**. "
            "Kokoro is the everyday TTS engine when installed (RFC-0070 / RFC-0075)."
        ),
    ),
    HelpTopic(
        id="companion-apk",
        title="Companion APK",
        summary="Build or download the Android companion and send it when configured.",
        href="/phone",
        keywords=("apk", "android", "download", "whatsapp", "email"),
        body=(
            "From Phone / companion setup you can build a personalized APK, download it "
            "to the Desktop, and send it via WhatsApp or email when those integrations "
            "are configured (RFC-0076). Use the latest build from this PC rather than an "
            "old debug snapshot."
        ),
    ),
)


def list_topics() -> list[HelpTopic]:
    return list(TOPICS)


def get_topic(topic_id: str) -> HelpTopic | None:
    key = (topic_id or "").strip().lower()
    for topic in TOPICS:
        if topic.id == key:
            return topic
    return None


def topic_as_dict(topic: HelpTopic) -> dict:
    return {
        "id": topic.id,
        "title": topic.title,
        "summary": topic.summary,
        "href": topic.href,
        "keywords": list(topic.keywords),
        "body": topic.body,
    }
