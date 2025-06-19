import os
import json
import base64
import asyncio
import websockets
import requests
from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import PlainTextResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
ELEVENLABS_AGENT_ID = os.getenv("ELEVENLABS_AGENT_ID")
VOICE_ID = os.getenv("VOICE_ID")
TELECMI_APP_ID = int(os.getenv("TELECMI_APP_ID"))
TELECMI_SECRET = os.getenv("TELECMI_SECRET")
TELECMI_FROM_NUMBER = os.getenv("TELECMI_FROM_NUMBER")

@app.get("/")
async def root():
    return PlainTextResponse("✅ WebSocket server is ready.")

@app.post("/make-outbound-call")
async def make_outbound_call(request: Request):
    body = await request.json()
    to = body.get("to")

    if not to:
        return JSONResponse(status_code=400, content={"error": "Missing 'to' number"})

    ws_url = "wss://your-deployed-url.onrender.com/ws"

    payload = {
        "appid": TELECMI_APP_ID,
        "secret": TELECMI_SECRET,
        "from": TELECMI_FROM_NUMBER,
        "to": to,
        "pcmo": [
            {
                "action": "stream",
                "ws_url": ws_url,
                "listen_mode": "callee"
            }
        ]
    }

    try:
        response = requests.post("https://rest.telecmi.com/v2/ind_pcmo_make_call", json=payload)
        response.raise_for_status()
        return {"message": "📞 Call initiated!", "telecmi_response": response.json()}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    print("🔌 WebSocket: TeleCMI connected")

    try:
        async with websockets.connect(
            f"wss://api.elevenlabs.io/v1/convai/conversation?agent_id={ELEVENLABS_AGENT_ID}",
            extra_headers={"xi-api-key": ELEVENLABS_API_KEY}
        ) as eleven_ws:
            print("🧠 Connected to ElevenLabs")

            await eleven_ws.send(json.dumps({
                "text": "Hello! How can I assist you?",
                "voice_id": VOICE_ID,
                "start_conversation": True
            }))

            async def handle_from_eleven():
                async for msg in eleven_ws:
                    data = json.loads(msg)
                    if data.get("type") == "ping":
                        await eleven_ws.send(json.dumps({
                            "type": "pong",
                            "event_id": data["ping_event"]["event_id"]
                        }))
                    elif data.get("type") == "audio":
                        audio = data["audio_event"]["audio_base_64"]
                        await websocket.send_text(json.dumps({
                            "event": "media",
                            "media": {"payload": audio}
                        }))
                        print("🔊 Audio sent to TeleCMI")
                    elif data.get("type") == "interruption":
                        await websocket.send_text(json.dumps({"event": "clear"}))

            async def handle_from_telecmi():
                async for msg in websocket.iter_text():
                    print("📥 TeleCMI said:", msg)
                    data = json.loads(msg)
                    if data.get("event") == "media":
                        chunk = data["media"]["payload"]
                        await eleven_ws.send(json.dumps({
                            "user_audio_chunk": chunk
                        }))
                    elif data.get("event") == "stop":
                        await eleven_ws.close()

            await asyncio.gather(handle_from_telecmi(), handle_from_eleven())

    except Exception as e:
        print("❌ WebSocket error:", e)
        await websocket.send_text(f"❌ Error: {str(e)}")

    finally:
        await websocket.close()
        print("🔴 WebSocket closed")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8500, reload=True)
