from pathlib import Path


class FileLayout:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir

    def lesson_dir(self, lesson_id: int) -> Path:
        return self.data_dir / "lessons" / str(lesson_id)

    def source_wav(self, lesson_id: int) -> Path:
        return self.lesson_dir(lesson_id) / "source.wav"

    def clip_wav(self, lesson_id: int, idx: int) -> Path:
        return self.lesson_dir(lesson_id) / "clips" / f"{idx}.wav"

    def clip_opus(self, lesson_id: int, idx: int) -> Path:
        return self.lesson_dir(lesson_id) / "clips" / f"{idx}.opus"

    def clip_mp3(self, lesson_id: int, idx: int) -> Path:
        return self.lesson_dir(lesson_id) / "clips" / f"{idx}.mp3"

    def attempt_wav(self, attempt_id: int) -> Path:
        return self.data_dir / "attempts" / f"{attempt_id}.wav"

    def cache_dir(self, name: str) -> Path:
        p = self.data_dir / "cache" / name
        p.mkdir(parents=True, exist_ok=True)
        return p
