from sbt2.protocol.v1.envelope_pb2 import ClientMessage, ServerMessage
from sbt2.protocol.v1.types_pb2 import Error, ErrorCode
from sbt2.server import Handler, Outbox
from sbt2.server.modules import module_name_problem
from sbt2.server.strategies.encoding import InvalidArgumentError
from sbt2.server.strategies.process import describe_in_process

IMPORT_SECONDS = 30.0


def routes(timeout: float = IMPORT_SECONDS) -> dict[str, Handler]:
    """A handler that describes the strategy of an uploaded module, which a
    process of its own imports for at most ``timeout`` seconds."""

    async def describe_strategy(
        request: ClientMessage, _outbox: Outbox
    ) -> ServerMessage:
        module = request.describe_strategy.strategy
        try:
            if problem := module_name_problem(module.name):
                raise InvalidArgumentError(problem)
            return await describe_in_process(module, timeout)
        except InvalidArgumentError as error:
            code = ErrorCode.ERROR_CODE_INVALID_ARGUMENT
            return ServerMessage(error=Error(code=code, message=str(error)))

    return {"describe_strategy": describe_strategy}


__all__ = ["routes"]
