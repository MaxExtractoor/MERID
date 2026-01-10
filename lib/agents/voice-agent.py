import sounddevice as sd
import numpy as np
from faster_whisper import WhisperModel
from piper.voice import PiperVoice
import requests
import json
import sys

stt = WhisperModel("base", device="cpu", compute_type="int8")
tts = PiperVoice.load("en_US-lessac-medium.onnx")

def record(duration=5, fs=16000):
  recording = sd.rec(int(duration * fs), samplerate=fs, channels=1, dtype='float32')
  sd.wait()
  return np.squeeze(recording)

def stt_audio(audio):
  segments, _ = stt.transcribe(audio, language="en")
  return " ".join([s.text for s in segments]).strip()

def tts_speak(text):
  audio = tts.synthesize(text)
  sd.play(audio, samplerate=22050)
  sd.wait()

if len(sys.argv) > 1:
  command = sys.argv[1]
  tts_speak(command)
  print(json.dumps({"response": "Spoke: " + command}))
else:
  while True:
    audio = record(5)
    text = stt_audio(audio)
    if "hey merid" in text.lower():
      tts_speak("Yes?")
      query_audio = record(6)
      query = stt_audio(query_audio)
      # Pipe query to router (call node router.js via subprocess)
      proc = spawn('node', ['../router.js', query])
      output = ''
      proc.stdout.on('data', (d) => output += d.toString())
      proc.on('close', () => tts_speak(output))
