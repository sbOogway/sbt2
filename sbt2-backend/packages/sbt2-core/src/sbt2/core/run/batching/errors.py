from pathlib import Path


class RunFailedError(RuntimeError):
    def __init__(self, run_id: str, folder: Path, reason: str) -> None:
        super().__init__(f"run {run_id} failed: {reason}; its folder is {folder}")
        self.run_id = run_id
        self.folder = folder
        self.reason = reason


class OutOfMemoryError(RunFailedError):
    pass


class StudyError(RuntimeError):
    """A run that does not fit the study it names."""


class StudyContextError(StudyError):
    def __init__(self, message: str, keys: tuple[str, ...]) -> None:
        super().__init__(message)
        self.keys = keys


class StudyCodeError(StudyError):
    pass


class DuplicateStudyRunError(StudyError):
    def __init__(self, message: str, run_id: str) -> None:
        super().__init__(message)
        self.run_id = run_id
