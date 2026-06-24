import os
import tempfile
import time
import requests
from shutil import which
from flask import current_app
from pydub import AudioSegment
from google import genai
from ..config import Config

ffmpeg_path = which("ffmpeg")
if ffmpeg_path:
    AudioSegment.converter = ffmpeg_path

class PartialTranscriptionError(Exception):
    """Custom exception raised when transcription fails mid-way, holding the partial text transcript."""
    def __init__(self, message, partial_transcript):
        super().__init__(message)
        self.partial_transcript = partial_transcript


def transcribe_audio(audio_url, status_callback=None):
    """
    Accepts Supabase public URL.
    Downloads audio -> loads using pydub -> chunks (if duration > threshold) ->
    transcribes via Gemini File API with retries/backoff -> deletes files -> returns transcript.
    """
    print("\n[Speech Service] Starting transcription...")
    print("Audio URL:", audio_url)

    if ffmpeg_path is None:
        raise Exception("FFmpeg is not installed or not available in PATH")

    # ==========================================
    # 1️⃣ DOWNLOAD AUDIO
    # ==========================================
    response = requests.get(audio_url)
    if response.status_code != 200:
        raise Exception(f"Failed to download audio file: HTTP {response.status_code}")

    temp_input = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
    temp_input.write(response.content)
    temp_input.close()
    input_path = temp_input.name

    print("File downloaded to temp path:", input_path)

    try:
        # ==========================================
        # 2️⃣ LOAD USING PYDUB & ASSESS STATS
        # ==========================================
        audio = AudioSegment.from_file(input_path)
        duration_seconds = len(audio) / 1000.0
        file_size_bytes = os.path.getsize(input_path)
        
        print(f"Audio loaded. Duration: {duration_seconds:.2f}s, File Size: {file_size_bytes} bytes")

        # Reject recordings longer than 4 hours (14400 seconds)
        if duration_seconds > 14400:
            raise Exception(f"Recording exceeds the maximum allowed duration of 4 hours (duration: {duration_seconds}s)")

        # Retrieve thresholds from Config
        try:
            threshold = current_app.config.get("TRANSCRIBE_CHUNK_THRESHOLD_SEC", 600)
            chunk_size_sec = current_app.config.get("TRANSCRIBE_CHUNK_SIZE_SEC", 300)
            max_chunk_count = current_app.config.get("MAX_CHUNK_COUNT", 48)
        except:
            threshold = getattr(Config, "TRANSCRIBE_CHUNK_THRESHOLD_SEC", 600)
            chunk_size_sec = getattr(Config, "TRANSCRIBE_CHUNK_SIZE_SEC", 300)
            max_chunk_count = getattr(Config, "MAX_CHUNK_COUNT", 48)

        # Gemini Client
        gemini_key = os.getenv("GEMINI_API_KEY")
        client = genai.Client(api_key=gemini_key)

        # ==========================================
        # 3️⃣ CHUNKING AUDIO SEGMENTS
        # ==========================================
        if duration_seconds > threshold:
            chunk_length_ms = chunk_size_sec * 1000
            chunks = []
            for i in range(0, len(audio), chunk_length_ms):
                chunks.append(audio[i : i + chunk_length_ms])
            print(f"Split audio into {len(chunks)} chunks (size: {chunk_size_sec}s).")
        else:
            chunks = [audio]
            print("Audio within threshold. Processing as a single chunk.")

        # Cost/Quota Safeguard: Verify chunk count does not exceed limit before starting transcription
        if len(chunks) > max_chunk_count:
            raise Exception(f"Audio chunk count ({len(chunks)}) exceeds the maximum allowed limit of {max_chunk_count} chunks.")

        completed_chunks = []

        # ==========================================
        # 4️⃣ UPLOAD AND TRANSCRIBE CHUNKS
        # ==========================================
        for idx, chunk in enumerate(chunks):
            chunk_num = idx + 1
            print(f"Processing chunk {chunk_num} of {len(chunks)}...")

            # Export chunk locally
            temp_chunk = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
            chunk_path = temp_chunk.name
            temp_chunk.close()

            try:
                chunk.export(chunk_path, format="mp3")

                # Retry Logic (3 attempts, backoffs: 2s, 4s, 8s)
                chunk_transcript = None
                backoffs = [2, 4, 8]
                
                for attempt in range(1, 4):
                    myfile = None
                    try:
                        print(f"Attempt {attempt}: Uploading chunk {chunk_num} to Gemini File API...")
                        myfile = client.files.upload(file=chunk_path)
                        
                        # Poll status until ACTIVE
                        while myfile.state.name == "PROCESSING":
                            print(f"Chunk {chunk_num} is processing in Gemini. Waiting...")
                            time.sleep(2)
                            myfile = client.files.get(name=myfile.name)

                        if myfile.state.name != "ACTIVE":
                            raise Exception(f"File processing failed in Gemini with state: {myfile.state.name}")

                        print(f"Chunk {chunk_num} is active in Gemini. Requesting transcription...")

                        # Generate transcription content
                        response = client.models.generate_content(
                            model="gemini-2.5-flash",
                            contents=[
                                myfile,
                                "Transcribe this audio verbatim.\n\n"
                                "Return only the spoken words.\n"
                                "Do not summarize.\n"
                                "Do not add speaker labels.\n"
                                "Do not add markdown.\n"
                                "Do not add explanations.\n"
                                "Do not add notes.\n\n"
                                "Return plain transcript text only."
                            ]
                        )
                        chunk_transcript = response.text or ""
                        break  # Successful transcription, break retry loop

                    except Exception as e:
                        print(f"Error during attempt {attempt} for chunk {chunk_num}: {e}")
                        if attempt == 3:
                            # Final attempt failed - raise PartialTranscriptionError
                            partial_accumulated = " ".join(completed_chunks)
                            raise PartialTranscriptionError(
                                message=f"Failed to transcribe chunk {chunk_num} after 3 attempts: {str(e)}",
                                partial_transcript=partial_accumulated
                            )
                        # Wait backoff and retry
                        sleep_time = backoffs[attempt - 1]
                        print(f"Sleeping for {sleep_time}s before retry...")
                        time.sleep(sleep_time)
                    finally:
                        # Clean up Gemini File API
                        if myfile:
                            try:
                                print(f"Deleting file {myfile.name} from Gemini storage...")
                                client.files.delete(name=myfile.name)
                            except Exception as del_err:
                                print(f"Warning: Failed to delete Gemini file {myfile.name}: {del_err}")

                completed_chunks.append(chunk_transcript.strip())
                if status_callback:
                    status_callback(chunk_num, len(chunks), chunk_transcript)
                if idx < len(chunks) - 1:
                    print("Sleeping 2 seconds to throttle Gemini token usage...")
                    time.sleep(2)

            finally:
                # Clean up local chunk file
                if os.path.exists(chunk_path):
                    try:
                        os.remove(chunk_path)
                    except Exception as err:
                        print("Warning: Failed to delete temporary chunk file:", err)

        # Join and clean up transcripts
        final_transcript = " ".join(completed_chunks).strip()
        print("Full transcription completed successfully.")
        return final_transcript, int(duration_seconds), file_size_bytes

    finally:
        # Clean up downloaded temp file
        if os.path.exists(input_path):
            try:
                os.remove(input_path)
            except Exception as err:
                print("Warning: Failed to delete temporary audio file:", err)
