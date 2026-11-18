from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from nightshift.core.bus import sse_format
from nightshift.core.deps import get_plant, get_rt
from nightshift.features.df16_copilot import copilot as C
from nightshift.features.df23_rbac.rbac import Identity, require
from nightshift.plant.runtime import PlantRuntime

router = APIRouter(prefix="/api/copilot", tags=["DF-16 copilot"])


class Msg(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(max_length=2000)


class ChatBody(BaseModel):
    messages: list[Msg] = Field(min_length=1, max_length=12)


@router.get("/tools")
async def tools() -> list[dict[str, Any]]:
    return [t["function"] for t in C.TOOLS]


@router.post("/chat")
async def chat(
    body: ChatBody,
    request: Request,
    pr: PlantRuntime = Depends(get_plant),
    rt=Depends(get_rt),
    ident: Identity = Depends(require("copilot", "copilot.chat")),
) -> StreamingResponse:
    msgs = [m.model_dump() for m in body.messages]

    async def gen():
        try:
            async for event, data in C.chat_stream(rt, pr, msgs, actor=f"copilot:{ident.role}"):
                yield sse_format(event, data)
                if await request.is_disconnected():
                    break
        except Exception as exc:
            yield sse_format("error", {"message": f"{type(exc).__name__}"})

    return StreamingResponse(
        gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


@router.post("/ask")
async def ask(
    body: ChatBody,
    pr: PlantRuntime = Depends(get_plant),
    rt=Depends(get_rt),
    ident: Identity = Depends(require("copilot", "copilot.ask")),
) -> dict[str, Any]:
    """Non-streaming variant (used by the smoke test): returns the final text, citations and the tool trace."""
    text, cites, tools, done = [], [], [], {}
    async for event, data in C.chat_stream(
        rt, pr, [m.model_dump() for m in body.messages], actor=f"copilot:{ident.role}"
    ):
        if event == "token":
            text.append(data["text"])
        elif event == "citations":
            cites = data["citations"]
        elif event == "tool_call":
            tools.append(data["name"])
        elif event == "done":
            done = data
    return {"answer": "".join(text), "citations": cites, "tools": tools, **done}
