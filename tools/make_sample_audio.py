"""Generate synthetic audio (macOS `say`) that matches sample_transcript.docx —
but speaks the planted ERRORS CORRECTLY ('catalyst', 'reinforcement learning')
and adds ONE extra sentence the docx omits. So the alignment should surface
2 disagreements + 1 omission. Fake data, for testing only.
"""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WAV = ROOT / "data" / "testsets" / "sample_audio.wav"
AIFF = Path("/tmp/sample_audio.aiff")

SCRIPT = (
    "So could you walk me through the reactor setup? "
    "Sure, it's a fixed-bed reactor. We rely on a catalyst to speed up the reaction without consuming it. "
    "Okay. And then we measure the conversion. "
    "I can explain that part. Oh, okay. "
    "We also trained a model. Which one? Or rather a few of them. "
    "Okay, then please continue. "
    "Yeah, we used reinforcement learning to optimize the policy. Interesting. And then we validated it on held-out runs. "
    "We also compared it against a strong baseline before deployment. "   # <-- omitted in the docx
    "Okay. Okay. Thanks for explaining all of that."
)


def main():
    WAV.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["say", "-o", str(AIFF), SCRIPT], check=True)
    subprocess.run(["ffmpeg", "-y", "-i", str(AIFF), "-ar", "16000", "-ac", "1", str(WAV)],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"wrote {WAV}")


if __name__ == "__main__":
    main()
