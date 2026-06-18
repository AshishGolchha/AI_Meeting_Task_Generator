import speech_recognition as sr
from pydub import AudioSegment
import tempfile
import requests
import os
import uuid

AudioSegment.converter = "ffmpeg"


def transcribe_audio(audio_url):
    """
    Accepts Supabase public URL
    Downloads audio → converts → transcribes
    """

    print("\n🎙️ Starting transcription...")
    print("Audio URL:", audio_url)

    # ==============================
    # 1️⃣ DOWNLOAD AUDIO
    # ==============================

    response = requests.get(audio_url)

    if response.status_code != 200:
        raise Exception("Failed to download audio file")

    temp_input = tempfile.NamedTemporaryFile(
        delete=False,
        suffix=".mp3"
    )

    temp_input.write(response.content)
    temp_input.close()

    input_path = temp_input.name

    print("📁 Temp audio saved:", input_path)

    # ==============================
    # 2️⃣ CONVERT TO WAV
    # ==============================

    wav_path = f"temp_{uuid.uuid4()}.wav"

    audio = AudioSegment.from_file(input_path)
    audio.export(wav_path, format="wav")

    print("🔄 Converted to WAV")

    # ==============================
    # 3️⃣ SPEECH RECOGNITION
    # ==============================

    recognizer = sr.Recognizer()

    with sr.AudioFile(wav_path) as source:
        audio_data = recognizer.record(source)

    transcript = recognizer.recognize_google(audio_data)

    print("✅ Transcription completed")

    # ==============================
    # 4️⃣ CLEANUP
    # ==============================

    os.remove(input_path)
    os.remove(wav_path)

    return transcript
