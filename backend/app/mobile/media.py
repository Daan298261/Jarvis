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
        self.generation = 0

    def interrupt(self):
        self.generation += 1
        while not self.queue.empty():
            self.queue.get_nowait()

    async def speak(self, text):
        generation = self.generation
        wav = await synthesize_speech(text[:6000])
        if generation != self.generation:
            return
        resampler = av.AudioResampler(format="s16", layout="mono", rate=48000)
        data = bytearray()
        with av.open(io.BytesIO(wav)) as container:
            for frame in container.decode(audio=0):
                for converted in resampler.resample(frame):
                    data.extend(converted.to_ndarray().tobytes())
        for index in range(0, len(data), 1920):
            if generation != self.generation:
                return
            await self.queue.put((generation, bytes(data[index:index + 1920]).ljust(1920, b"\0")))

    async def recv(self):
        await asyncio.sleep(max(0, self.started + self.samples / 48000 - time.monotonic()))
        data = bytes(1920)
        while not self.queue.empty():
            generation, candidate = self.queue.get_nowait()
            if generation == self.generation:
                data = candidate
                break
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
        self.transcriber = None
        self.audio = asyncio.Queue(maxsize=4)
        self.utterances = asyncio.Queue(maxsize=8)

    def start(self, track):
        self.reader = asyncio.create_task(self.listen(track))
        self.transcriber = asyncio.create_task(self.transcribe())
        self.turn = asyncio.create_task(self.respond())

    def stop(self):
        for task in (self.reader, self.transcriber, self.turn):
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
                    try:
                        self.audio.put_nowait(bytes(data))
                    except asyncio.QueueFull:
                        calls.update(self.call["id"], detail="Speech queue is full; please repeat your last message")
                    data.clear()
                    silence = 0

    async def transcribe(self):
        while True:
            pcm = await self.audio.get()
            try:
                await self.accept_audio(pcm)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                calls.update(self.call["id"], detail=str(getattr(exc, "detail", type(exc).__name__))[:200])

    async def accept_audio(self, pcm):
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
            while not self.utterances.empty():
                self.utterances.get_nowait()
            self.output.interrupt()
            return
        try:
            self.utterances.put_nowait(text)
        except asyncio.QueueFull:
            calls.update(self.call["id"], detail="Message queue is full; please wait for the current answer")

    async def respond(self):
        while True:
            text = await self.utterances.get()
            await self.respond_text(text)

    async def respond_text(self, text):
        try:
            result = await service.submit(self.call["device_id"], str(uuid.uuid4()), text,
                                          conversation_id=self.call.get("conversation_id"))
            self.call.update(result)
            calls.update(self.call["id"], **result)
            spoken = ""
            generation = self.output.generation
            while True:
                snapshot = await service.task_snapshot(result["task_id"])
                response = snapshot.get("result", "")
                if response.startswith(spoken) and len(response) > len(spoken):
                    remainder = response[len(spoken):]
                    if snapshot["status"] in service.TERMINAL or remainder.endswith((".", "!", "?", "\n")):
                        if self.output.generation == generation:
                            await self.output.speak(remainder)
                        spoken = response
                if snapshot["status"] in service.TERMINAL:
                    break
                await asyncio.sleep(.3)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            calls.update(self.call["id"], detail=str(getattr(exc, "detail", type(exc).__name__))[:200])
