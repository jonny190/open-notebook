"""
Gradio TTS Model - Custom TextToSpeechModel for Gradio-based TTS servers.

Implements a duck-typed TextToSpeechModel that communicates with Gradio TTS
servers (e.g., Spark TTS) using the raw Gradio REST API via httpx.

Supports two modes:
- **Custom Voice**: Predefined speakers (e.g., "Ryan", "Serena")
  → uses /generate_custom_voice endpoint
- **Voice Clone**: Clone from a reference audio file
  → uses /generate_voice_clone endpoint

The mode is auto-detected from the `voice` parameter: if it looks like a
file path (contains path separators or ends with an audio extension), voice
cloning is used. Otherwise, it's treated as a predefined speaker name.

Gradio API protocol:
1. POST /gradio_api/call/{endpoint} with {"data": [...]} → returns event_id
2. GET /gradio_api/call/{endpoint}/{event_id} → SSE stream with result
"""

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import httpx
from loguru import logger


@dataclass
class SpeechResult:
    """Result container matching Esperanto's TTS response interface."""

    content: bytes


# Available speakers for Spark TTS
GRADIO_SPEAKERS = [
    "Aiden",
    "Dylan",
    "Eric",
    "Ono_anna",
    "Ryan",
    "Serena",
    "Sohee",
    "Uncle_fu",
    "Vivian",
]

GRADIO_LANGUAGES = [
    "Auto",
    "English",
    "Chinese",
    "Japanese",
    "Korean",
    "French",
    "German",
    "Spanish",
    "Portuguese",
    "Russian",
    "Italian",
]

_AUDIO_EXTENSIONS = {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac", ".wma", ".opus"}


def _is_audio_file_path(voice: str) -> bool:
    """Check if a voice string looks like a file path to an audio file."""
    if os.sep in voice or "/" in voice:
        return True
    ext = Path(voice).suffix.lower()
    return ext in _AUDIO_EXTENSIONS


class GradioTextToSpeechModel:
    """
    TTS model that calls a Gradio server for speech generation.

    Supports two modes based on the `voice` parameter:
    - Speaker name (e.g., "Ryan") → /generate_custom_voice
    - Audio file path (e.g., "/data/ref.wav") → /generate_voice_clone

    Duck-types Esperanto's TextToSpeechModel interface so it can be used
    by both ModelManager and podcast-creator (via AIFactory monkey-patch).
    """

    def __init__(
        self,
        model_name: str = "default",
        base_url: str = "http://localhost:7860",
        language: str = "English",
        model_size: str = "1.7B",
        **kwargs,
    ):
        self.model_name = model_name
        self.base_url = base_url.rstrip("/")
        self.language = language
        self.model_size = model_size
        self.provider = "gradio"

    async def agenerate_speech(
        self,
        text: str,
        voice: str = "Ryan",
        language: Optional[str] = None,
        model_size: Optional[str] = None,
        instruct: str = "",
        seed: int = -1,
        **kwargs,
    ) -> SpeechResult:
        """
        Generate speech using the appropriate Gradio endpoint.

        If `voice` is a file path to an audio file, voice cloning is used.
        Otherwise, `voice` is treated as a predefined speaker name.

        Args:
            text: Text to synthesize
            voice: Speaker name (e.g., "Ryan") OR path to reference audio file
            language: Language override (default: instance language)
            model_size: Model size override ("0.6B" or "1.7B")
            instruct: Style instruction for custom voice generation
            seed: Random seed (-1 for random)

        Returns:
            SpeechResult with .content containing audio bytes
        """
        lang = language or self.language
        size = model_size or self.model_size

        if _is_audio_file_path(voice):
            return await self._generate_clone(text, voice, lang, **kwargs)
        else:
            return await self._generate_custom_voice(text, voice, lang, size, instruct, seed, **kwargs)

    async def _generate_custom_voice(
        self,
        text: str,
        speaker: str,
        language: str,
        model_size: str,
        instruct: str,
        seed: int,
        **kwargs,
    ) -> SpeechResult:
        """Generate speech using a predefined speaker via /generate_custom_voice."""
        logger.info(f"Gradio TTS: custom voice for speaker={speaker}, lang={language}, text_len={len(text)}")

        api_url = f"{self.base_url}/gradio_api/call/generate_custom_voice"
        payload = {"data": [text, language, speaker, instruct, model_size, seed]}

        async with httpx.AsyncClient(timeout=300.0) as client:
            audio_path = await self._call_gradio_endpoint(client, api_url, payload)
            return await self._download_audio(client, audio_path)

    async def _generate_clone(
        self,
        text: str,
        reference_audio_path: str,
        language: str,
        **kwargs,
    ) -> SpeechResult:
        """Generate speech by cloning a voice from a reference audio file via /generate_voice_clone."""
        if not os.path.isfile(reference_audio_path):
            raise FileNotFoundError(
                f"Gradio TTS: reference audio file not found: {reference_audio_path}"
            )

        logger.info(
            f"Gradio TTS: voice clone from {reference_audio_path}, "
            f"lang={language}, text_len={len(text)}"
        )

        async with httpx.AsyncClient(timeout=300.0) as client:
            # Step 1: Upload the reference audio to the Gradio server
            uploaded_path = await self._upload_file(client, reference_audio_path)

            # Step 2: Call the voice clone endpoint
            api_url = f"{self.base_url}/gradio_api/call/generate_voice_clone"
            payload = {"data": [text, {"path": uploaded_path}, language]}

            audio_path = await self._call_gradio_endpoint(client, api_url, payload)
            return await self._download_audio(client, audio_path)

    async def _upload_file(self, client: httpx.AsyncClient, local_path: str) -> str:
        """Upload a local file to the Gradio server, return the server-side path."""
        upload_url = f"{self.base_url}/gradio_api/upload"
        filename = os.path.basename(local_path)

        with open(local_path, "rb") as f:
            files = [("files", (filename, f, "audio/wav"))]
            response = await client.post(upload_url, files=files)
            response.raise_for_status()

        paths = response.json()
        if not paths or not isinstance(paths, list):
            raise RuntimeError(f"Gradio upload returned unexpected response: {response.text[:200]}")

        uploaded = paths[0]
        logger.debug(f"Gradio TTS: uploaded {filename} → {uploaded}")
        return uploaded

    async def _call_gradio_endpoint(
        self, client: httpx.AsyncClient, api_url: str, payload: dict
    ) -> str:
        """Call a Gradio API endpoint (POST + GET SSE) and return the result file path."""
        # POST to start generation
        response = await client.post(api_url, json=payload)
        response.raise_for_status()
        event_id = response.json().get("event_id")

        if not event_id:
            raise RuntimeError(f"Gradio API did not return event_id: {response.text}")

        logger.debug(f"Gradio TTS: got event_id={event_id}")

        # GET SSE stream to poll result
        result_url = f"{api_url}/{event_id}"
        result_response = await client.get(result_url)
        result_response.raise_for_status()

        file_path = self._parse_sse_response(result_response.text)
        if not file_path:
            raise RuntimeError(
                f"Gradio TTS: no file path in response: {result_response.text[:500]}"
            )

        return file_path

    async def _download_audio(self, client: httpx.AsyncClient, file_path: str) -> SpeechResult:
        """Download an audio file from the Gradio server."""
        if file_path.startswith("/"):
            download_url = f"{self.base_url}{file_path}"
        elif file_path.startswith("http"):
            download_url = file_path
        else:
            download_url = f"{self.base_url}/gradio_api/file={file_path}"

        logger.debug(f"Gradio TTS: downloading audio from {download_url}")
        audio_response = await client.get(download_url)
        audio_response.raise_for_status()

        audio_bytes = audio_response.content
        logger.info(f"Gradio TTS: generated {len(audio_bytes)} bytes of audio")
        return SpeechResult(content=audio_bytes)

    def _parse_sse_response(self, text: str) -> Optional[str]:
        """
        Parse the SSE response from Gradio to extract the audio file path.

        Gradio SSE format:
            event: ...
            data: ["/gradio_api/file=...", "status text"]
        """
        for line in text.strip().split("\n"):
            line = line.strip()
            if line.startswith("data:"):
                data_str = line[len("data:"):].strip()
                try:
                    data = json.loads(data_str)
                    if isinstance(data, list) and len(data) > 0:
                        file_info = data[0]
                        if isinstance(file_info, dict):
                            return file_info.get("url") or file_info.get("path")
                        elif isinstance(file_info, str):
                            return file_info
                except (json.JSONDecodeError, TypeError):
                    continue
        return None
