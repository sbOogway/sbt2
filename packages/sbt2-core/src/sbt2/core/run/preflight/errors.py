class PreflightError(RuntimeError):
    pass


class SnapshotBufferError(PreflightError):
    pass


class MissingDataError(PreflightError):
    pass


class InstrumentAssetClassError(PreflightError):
    pass


class LiquidationWithoutQuotesError(PreflightError):
    pass
