from sbt2.protocol.v1.types_pb2 import Error, ErrorCode


class LabError(Exception):
    pass


class ConnectError(LabError):
    pass


class MissingCapabilityError(LabError):
    pass


class ServerError(LabError):
    """An ``Error`` the server answered a request with."""

    def __init__(self, error: Error) -> None:
        self.code = ErrorCode.Name(error.code)
        self.message = error.message
        super().__init__(f"{self.code}: {self.message}")


class StrategyModuleError(LabError):
    pass


class JobFailedError(LabError):
    """A job that did not finish: it failed or was cancelled."""
