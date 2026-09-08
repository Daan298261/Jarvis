from __future__ import annotations

import asyncio
import io
import time
import uuid
import wave
from fractions import Fraction

import av
import numpy as np
from aiortc import AudioStreamTrack
from aiortc.mediastreams import MediaStreamError

from . import calls, service
from .store import database, get
from ..workers.voice import synthesize_speech, transcribe_audio


class Speaker(AudioStreamTrack):
    def __init__(self):
        super().__init__()
        self.queue = asyncio.Queue(maxsize=3000)
        self.samples = 0
        self.started = time.monotonic()

    def interrupt(self):
        while not self.queue.empty():
            self.queue.get_nowait()

    async def speak(self, text):
        wav = await synthesize_speech(text[:6000])
        resampler = av.AudioResampler(format="s16", layout="mono", rate=48000)
        container = av.open(io.BytesIO(wav))
        data = bytearray()
        for frame in container.decode(audio=0):
            for converted in resampler.resample(frame):
                data.extend(converted.to_ndarray().tobytes())
        for index in range(0, len(data), 1920):
            await self.queue.put(bytes(data[index:index + 1920]).ljust(1920, b"\0"))
        container.close()

    async def recv(self):
        await asyncio.sleep(max(0, self.started + self.samples / 48000 - time.monotonic()))
        data = self.queue.get_nowait() if not self.queue.empty() else bytes(1920)
        frame = av.AudioFrame(format="s16", layout="mono", samples=960)
        frame.planes[0].update(data)
        frame.sample_rate = 48000
        frame.pts = self.samples
        frame.time_base = Fraction(1, 48000)
        self.samples += 960
        return frame


class VoiceBridge:
    def __init__(self, call):
        self.call = call
        self.output = Speaker()
        self.reader = None
        self.turn = None

    def start(self, track):
        self.reader = asyncio.create_task(self.listen(track))

    def stop(self):
        for task in (self.reader, self.turn):
            if task:
                task.cancel()
        self.output.interrupt()
        self.output.stop()

    async def listen(self, track):
        resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
        data = bytearray()
        silence = 0
        while True:
            try:
                frame = await track.recv()
            except MediaStreamError:
                return
            with database() as db:
                device = get(db, "device", self.call["device_id"])
            if not device or device["status"] != "active":
                self.stop()
                return
            for part in resampler.resample(frame):
                samples = part.to_ndarray().astype(np.int16).flatten()
                loud = float(np.sqrt(np.mean(samples.astype(np.float32) ** 2))) > 450
                if loud:
                    self.output.interrupt()
                    silence = 0
                elif data:
                    silence += len(samples)
                if loud or data:
                    data.extend(samples.tobytes())
                if data and (silence >= 14400 or len(data) >= 16000 * 2 * 30):
                    if not self.turn or self.turn.done():
                        self.turn = asyncio.create_task(self.respond(bytes(data)))
                    data.clear()
                    silence = 0

    async def respond(self, pcm):
        try:
            buffer = io.BytesIO()
            with wave.open(buffer, "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(16000)
                wav.writeframes(pcm)
            text = (await transcribe_audio(buffer.getvalue(), "call.wav")).strip()
            if not text:
                return
            if text.lower().strip(".!?") in {"stop", "cancel", "stoppen", "annuleer"}:
                if self.call.get("task_id"):
                    from ..agent.loop import AGENT
                    AGENT.cancel(self.call["task_id"])
                self.output.interrupt()
                return
            result = await service.submit(self.call["device_id"], str(uuid.uuid4()), text,
                                          conversation_id=self.call.get("conversation_id"))
            self.call.update(result)
            calls.update(self.call["id"], **result)
            spoken = ""
            while True:
                snapshot = await service.task_snapshot(result["task_id"])
                response = snapshot.get("result", "")
                if response.startswith(spoken) and len(response) > len(spoken):
                    remainder = response[len(spoken):]
                    if snapshot["status"] in service.TERMINAL or remainder.endswith((".", "!", "?", "\n")):
                        await self.output.speak(remainder)
                        spoken = response
                if snapshot["status"] in service.TERMINAL:
                    break
                await asyncio.sleep(.3)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            calls.update(self.call["id"], detail=str(getattr(exc, "detail", type(exc).__name__))[:200])
