"""Host-side microphone capture and OpenAI-compatible transcription."""

from __future__ import annotations

from io import BytesIO
import json
import secrets
from urllib import request
from urllib.parse import urlparse
import wave


SAMPLE_RATE = 16000
MAX_SECONDS = 15


def validate_speech_endpoint(endpoint: str) -> str:
    clean = endpoint.strip().rstrip("/")
    parsed = urlparse(clean)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("语音 Endpoint 必须是有效的 http(s) 地址")
    if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("公网语音 Endpoint 必须使用 HTTPS")
    return clean if clean.endswith("/audio/transcriptions") else clean + "/audio/transcriptions"


def record_wav(seconds: float = 6.0) -> bytes:
    if not 1 <= seconds <= MAX_SECONDS:
        raise ValueError(f"录音时长必须是 1..{MAX_SECONDS} 秒")
    try:
        import sounddevice as sd
    except ImportError as error:
        raise RuntimeError("缺少麦克风组件 sounddevice，请重新安装 V1 桌面包") from error
    frames = round(SAMPLE_RATE * seconds)
    audio = sd.rec(frames, samplerate=SAMPLE_RATE, channels=1, dtype="int16")
    sd.wait()
    output = BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(audio.tobytes())
    return output.getvalue()


def transcribe_wav(wav_data: bytes, endpoint: str, model: str, api_key: str,
                   language: str = "zh") -> str:
    if not api_key.strip():
        raise ValueError("请先填写语音转写 API Key")
    if not model.strip():
        raise ValueError("语音转写模型不能为空")
    if len(wav_data) < 100 or len(wav_data) > 10 * 1024 * 1024:
        raise ValueError("录音数据大小异常")
    url = validate_speech_endpoint(endpoint)
    boundary = "----LabCapsule" + secrets.token_hex(12)
    chunks: list[bytes] = []

    def field(name: str, value: str) -> None:
        chunks.extend((f"--{boundary}\r\n".encode(),
                       f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                       value.encode("utf-8"), b"\r\n"))

    field("model", model.strip())
    field("language", language)
    chunks.extend((f"--{boundary}\r\n".encode(),
                   b'Content-Disposition: form-data; name="file"; filename="voice.wav"\r\n',
                   b"Content-Type: audio/wav\r\n\r\n", wav_data, b"\r\n",
                   f"--{boundary}--\r\n".encode()))
    call = request.Request(url, data=b"".join(chunks), method="POST",
                           headers={"Authorization": "Bearer " + api_key.strip(),
                                    "Content-Type": "multipart/form-data; boundary=" + boundary,
                                    "Accept": "application/json",
                                    "User-Agent": "LabCapsule-Studio/1.0"})
    with request.urlopen(call, timeout=90) as response:
        raw = response.read(2 * 1024 * 1024 + 1)
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError("语音转写响应过大")
    value = json.loads(raw.decode("utf-8"))
    text = str(value.get("text", "")).strip()
    if not text:
        raise RuntimeError("语音服务没有返回文本")
    return text[:4000]
