import os
from io import BytesIO
from elevenlabs.client import ElevenLabs
from pydub import AudioSegment
from dotenv import load_dotenv

load_dotenv()

class AudioGeneratorTool:
    def __init__(self):
        api_key = os.getenv("ELEVENLABS_API_KEY")
        if not api_key:
            raise ValueError("ELEVENLABS_API_KEY not found in environment variables")
        self.client = ElevenLabs(api_key=api_key)
        
        # script host names don't depend on video language, so accept both spellings
        self.voices = {
            "Алекс": "pNInz6obpgDQGcFmaJgB", "Alex": "pNInz6obpgDQGcFmaJgB",
            "Марина": "EXAVITQu4vr4xnSDxMaL", "Marina": "EXAVITQu4vr4xnSDxMaL",
        }

    def generate_podcast_audio(self, script: str, language: str) -> bytes:
        voices = self.voices
        lines = script.strip().split("\n")
        combined_audio = AudioSegment.empty()
        count = 0

        print(f"🎙️ Инструмент: Начало генерации на языке '{language}'...")

        for line in lines:
            if ":" not in line:
                continue

            name, text = line.split(":", 1)
            name = name.strip(" *")  # "**Алекс:** текст" -> "Алекс"
            text = text.strip(" *")

            if not text or name not in voices:
                print(f"  ⚠️ Пропуск реплики: {name}")
                continue

            try:
                audio_stream = self.client.text_to_speech.convert(
                    text=text,
                    voice_id=voices[name],
                    model_id="eleven_multilingual_v2",
                    output_format="mp3_44100_128",
                )

                audio_bytes = b"".join(audio_stream)
                segment = AudioSegment.from_mp3(BytesIO(audio_bytes))
                combined_audio += segment
                count += 1
            except Exception as e:
                print(f"  ❌ Ошибка на реплике {name}: {e}")

        if len(combined_audio) > 0:
            buf = BytesIO()
            combined_audio.export(buf, format="mp3")
            print(f"✅ Аудио сгенерировано (реплик: {count})")
            return buf.getvalue()
        else:
            raise Exception("Аудио не было сгенерировано.")