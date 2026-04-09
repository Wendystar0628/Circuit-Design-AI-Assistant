from .web_document_viewer import WebDocumentViewer


class PdfViewer(WebDocumentViewer):
    def load_pdf(self, path: str) -> bool:
        return self.load_local_file(path)


__all__ = ["PdfViewer"]
