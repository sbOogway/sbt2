import html as markup

_HEIGHT = 900


class Tearsheet:
    """A run's tearsheet as one HTML document, which a notebook shows inline."""

    def __init__(self, html: str) -> None:
        self.html = html

    def _repr_html_(self) -> str:
        # an iframe keeps the document's scripts and styles out of the notebook's
        return (
            f'<iframe srcdoc="{markup.escape(self.html)}" '
            f'style="width: 100%; height: {_HEIGHT}px; border: none"></iframe>'
        )
