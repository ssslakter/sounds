from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
import aiofiles
import asyncio

app = FastAPI()

async def wav_streamer(file_path: str):
    try:
        async with aiofiles.open(file_path, mode='rb') as f:
            chunk_size = 1024
            while True:
                data = await f.read(chunk_size)
                if not data:
                    break
                yield data
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")

@app.get("/stream")
async def stream_audio():
    file_path = "../data/thanos_message.mp3"  # Replace with your WAV file path
    headers = {
        "Content-Disposition": f'inline; filename="{file_path}"',
        "Content-Type": "audio/wav"
    }
    return StreamingResponse(wav_streamer(file_path), headers=headers, media_type="audio/wav")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
