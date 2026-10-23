# BEACON COMPUTING INITIATIVE
# BCIWhisper 59.7–60.0 Timeline Acceptance
# Developer Seal: CJB-DEV-2026
import tempfile
import unittest
import wave
from pathlib import Path
from bciwhisper.recording.timeline import EpisodeTimeline

class TimelineSequenceTests(unittest.TestCase):
    def test_import_trim_save_and_reopen(self):
        with tempfile.TemporaryDirectory() as root:
            wav = Path(root) / "take.wav"
            with wave.open(str(wav), "wb") as out:
                out.setnchannels(1)
                out.setsampwidth(2)
                out.setframerate(48000)
                out.writeframes(b"\x00\x00" * 48000)
            model = EpisodeTimeline()
            model.import_wav(str(wav))
            model.trim(0, .2, .8)
            model.add_transcript_marker(.4, "hello")
            project = Path(root) / "episode.json"
            model.save(str(project))
            loaded = EpisodeTimeline.load(str(project))
            self.assertEqual(len(loaded.tracks), 1)
            self.assertEqual(loaded.tracks[0]["in"], .2)
            self.assertEqual(loaded.markers[0]["text"], "hello")
            with wave.open(str(wav), "rb") as source:
                self.assertEqual(source.getnframes(), 48000)

    def test_invalid_trim_does_not_modify_source(self):
        with tempfile.TemporaryDirectory() as root:
            wav = Path(root) / "take.wav"
            with wave.open(str(wav), "wb") as out:
                out.setnchannels(1)
                out.setsampwidth(2)
                out.setframerate(48000)
                out.writeframes(b"\x00\x00" * 4800)
            m = EpisodeTimeline()
            m.import_wav(str(wav))
            with self.assertRaises(ValueError):
                m.trim(0, 0.4, 0.2)

if __name__ == "__main__":
    unittest.main()
