"""Channel adapters (CC-01): one `ChannelAdapter` contract for web chat, a generic webhook and tested SMS / WhatsApp / e-mail stubs.
Inbound payloads are normalised (idempotent message ids), outbound replies are rendered in the provider's shape."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class InboundMessage:
    external_id: str
    conversation_key: str
    text: str
    sender: str
    channel: str
    language: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


class ChannelAdapter(Protocol):
    name: str
    description: str
    simulated: bool

    def parse_inbound(self, payload: dict[str, Any]) -> InboundMessage: ...

    def render_outbound(self, text: str, conversation_key: str, meta: dict[str, Any] | None = None) -> dict[str, Any]: ...

    def delivery_receipt(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    def sample_inbound(self) -> dict[str, Any]: ...


def _msg_id(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:20]


class WebChatAdapter:
    name, description, simulated = "web_chat", "Browser widget (REST / SSE / WebSocket).", False

    def parse_inbound(self, payload: dict[str, Any]) -> InboundMessage:
        text = str(payload.get("text", "")).strip()
        if not text:
            raise ValueError("text is required")
        sid = str(payload.get("session_id") or payload.get("conversation_key") or "")
        return InboundMessage(str(payload.get("message_id") or _msg_id(sid, text, str(payload.get("client_ts", "")))), sid, text, str(payload.get("sender", "visitor")), self.name, payload.get("language"))

    def render_outbound(self, text: str, conversation_key: str, meta: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"type": "message", "session_id": conversation_key, "text": text, "meta": meta or {}}

    def delivery_receipt(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {"message_id": payload.get("message_id"), "status": payload.get("status", "delivered")}

    def sample_inbound(self) -> dict[str, Any]:
        return {"session_id": "cv_demo", "message_id": "m-1", "text": "Where is my order?"}


class GenericWebhookAdapter:
    name, description, simulated = "webhook", "Generic JSON webhook for any messaging platform (id, from, text, lang).", False

    def parse_inbound(self, payload: dict[str, Any]) -> InboundMessage:
        for key in ("id", "from", "text"):
            if not payload.get(key):
                raise ValueError(f"'{key}' is required")
        return InboundMessage(str(payload["id"]), str(payload["from"]), str(payload["text"]).strip(), str(payload["from"]), self.name, payload.get("lang"), {"thread": payload.get("thread")})

    def render_outbound(self, text: str, conversation_key: str, meta: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"to": conversation_key, "text": text, "meta": meta or {}}

    def delivery_receipt(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {"message_id": payload.get("id"), "status": payload.get("status", "delivered")}

    def sample_inbound(self) -> dict[str, Any]:
        return {"id": "evt-1", "from": "user-42", "text": "Hi, I need to reschedule my delivery", "lang": "en"}


class SmsAdapter:
    name, description, simulated = "sms", "SMS (Twilio-style form fields). Tested stub - no carrier account.", True

    def parse_inbound(self, payload: dict[str, Any]) -> InboundMessage:
        body = str(payload.get("Body", "")).strip()
        if not body or not payload.get("From"):
            raise ValueError("Body and From are required")
        return InboundMessage(str(payload.get("MessageSid") or _msg_id(str(payload["From"]), body)), str(payload["From"]), body, str(payload["From"]), self.name, None, {"to": payload.get("To")})

    def render_outbound(self, text: str, conversation_key: str, meta: dict[str, Any] | None = None) -> dict[str, Any]:
        # SMS segments: 160 GSM chars; longer replies are split (concatenated SMS)
        parts = [text[i : i + 150] for i in range(0, len(text), 150)] or [""]
        return {"To": conversation_key, "Body": parts[0], "segments": len(parts), "extra_segments": parts[1:]}

    def delivery_receipt(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {"message_id": payload.get("MessageSid"), "status": str(payload.get("MessageStatus", "delivered")).lower()}

    def sample_inbound(self) -> dict[str, Any]:
        return {"MessageSid": "SM1", "From": "+4915550001111", "To": "+4930555000", "Body": "Mein Paket ist nicht angekommen"}


class WhatsAppAdapter:
    name, description, simulated = "whatsapp", "WhatsApp Business (Cloud API webhook shape). Tested stub - no WABA.", True

    def parse_inbound(self, payload: dict[str, Any]) -> InboundMessage:
        try:
            value = payload["entry"][0]["changes"][0]["value"]
            m = value["messages"][0]
            return InboundMessage(str(m["id"]), str(m["from"]), str(m["text"]["body"]).strip(), str(m["from"]), self.name, None, {"phone_number_id": value.get("metadata", {}).get("phone_number_id")})
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError("not a WhatsApp text message payload") from exc

    def render_outbound(self, text: str, conversation_key: str, meta: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"messaging_product": "whatsapp", "to": conversation_key, "type": "text", "text": {"preview_url": False, "body": text[:4096]}}

    def delivery_receipt(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            st = payload["entry"][0]["changes"][0]["value"]["statuses"][0]
            return {"message_id": st["id"], "status": st["status"]}
        except (KeyError, IndexError, TypeError):
            return {"message_id": None, "status": "unknown"}

    def sample_inbound(self) -> dict[str, Any]:
        return {"entry": [{"changes": [{"value": {"metadata": {"phone_number_id": "100"}, "messages": [{"id": "wamid.1", "from": "491555000222", "text": {"body": "Hola, mi colchón llegó dañado"}}]}}]}]}


class EmailAdapter:
    name, description, simulated = "email", "E-mail (inbound parse webhook shape; replies threaded with In-Reply-To). Tested stub - no mailbox.", True

    def parse_inbound(self, payload: dict[str, Any]) -> InboundMessage:
        if not payload.get("from") or not (payload.get("text") or payload.get("subject")):
            raise ValueError("from and text/subject are required")
        text = (str(payload.get("subject", "")) + "\n" + str(payload.get("text", ""))).strip()
        return InboundMessage(str(payload.get("message_id") or _msg_id(str(payload["from"]), text)), str(payload["from"]).lower(), text[:4000], str(payload["from"]), self.name, None, {"subject": payload.get("subject"), "references": payload.get("references")})

    def render_outbound(self, text: str, conversation_key: str, meta: dict[str, Any] | None = None) -> dict[str, Any]:
        subj = (meta or {}).get("subject") or "Your request to Contoso Home"
        return {"to": conversation_key, "subject": subj if subj.lower().startswith("re:") else f"Re: {subj}", "text": text, "headers": {"In-Reply-To": (meta or {}).get("message_id", "")}}

    def delivery_receipt(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {"message_id": payload.get("message_id"), "status": {"delivered": "delivered", "bounce": "failed", "dropped": "failed"}.get(str(payload.get("event", "delivered")), "unknown")}

    def sample_inbound(self) -> dict[str, Any]:
        return {"message_id": "<abc@mail>", "from": "Kunde@example.com", "subject": "Beschädigte Lieferung", "text": "Mein Sofa ist beschädigt."}


ADAPTERS: dict[str, ChannelAdapter] = {a.name: a for a in (WebChatAdapter(), GenericWebhookAdapter(), SmsAdapter(), WhatsAppAdapter(), EmailAdapter())}  # type: ignore[misc]
