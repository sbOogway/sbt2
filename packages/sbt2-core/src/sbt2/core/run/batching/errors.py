from pathlib import Path


class RunFailedError(RuntimeError):
    def __init__(self, run_id: str, folder: Path, reason: str) -> None:
        super().__init__(f"run {run_id} failed: {reason}; its folder is {folder}")
        self.run_id = run_id
        self.folder = folder


class OutOfMemoryError(RunFailedError):
    pass


class StudyError(RuntimeError):
    """A run that does not fit the study it names."""


class StudyContextError(StudyError):
    pass


class StudyCodeError(StudyError):
    pass
