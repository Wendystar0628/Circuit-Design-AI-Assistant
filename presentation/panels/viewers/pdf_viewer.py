import os

from PyQt6.QtCore import QUrl

try:
    from PyQt6.QtPdf import QPdfDocument
    QT_PDF_AVAILABLE = True
except ImportError:
    QPdfDocument = None
    QT_PDF_AVAILABLE = False

try:
    from PyQt6.QtWebEngineCore import QWebEngineSettings
except ImportError:
    QWebEngineSettings = None

from .web_document_viewer import WebDocumentViewer


class PdfViewer(WebDocumentViewer):
    def __init__(self, parent=None):
        super().__init__(parent, enable_host_zoom=False)
        self._document = QPdfDocument(self) if QT_PDF_AVAILABLE else None
        if self.web_view is not None and QWebEngineSettings is not None:
            settings = self.web_view.settings()
            pdf_attr = getattr(QWebEngineSettings.WebAttribute, "PdfViewerEnabled", None)
            if pdf_attr is not None:
                settings.setAttribute(pdf_attr, True)
            plugins_attr = getattr(QWebEngineSettings.WebAttribute, "PluginsEnabled", None)
            if plugins_attr is not None:
                settings.setAttribute(plugins_attr, True)

    def load_pdf(self, path: str) -> bool:
        if self.web_view is None:
            self.show_error("当前环境缺少 QtWebEngine，无法预览 PDF。", title="PDF 预览不可用")
            return False

        abs_path = os.path.abspath(path)
        if not os.path.isfile(abs_path):
            self.show_error(f"PDF 文件不存在：{abs_path}", title="PDF 预览不可用")
            return False

        if self._document is not None:
            error = self._document.load(abs_path)
            if error != QPdfDocument.Error.None_:
                self.show_error(f"PDF 加载失败：{self._error_message(error)}", title="PDF 预览不可用")
                return False

        if self.web_view is not None:
            self.web_view.setZoomFactor(1.0)
        self.web_view.setUrl(QUrl.fromLocalFile(abs_path))
        return True

    @staticmethod
    def _error_message(error) -> str:
        mapping = {
            QPdfDocument.Error.None_: "无错误",
            QPdfDocument.Error.Unknown: "未知错误",
            QPdfDocument.Error.DataNotYetAvailable: "数据尚未可用",
            QPdfDocument.Error.FileNotFound: "文件不存在",
            QPdfDocument.Error.InvalidFileFormat: "无效的 PDF 格式",
            QPdfDocument.Error.IncorrectPassword: "PDF 密码错误",
            QPdfDocument.Error.UnsupportedSecurityScheme: "不支持的 PDF 安全方案",
        }
        return mapping.get(error, getattr(error, "name", str(error)))


__all__ = ["PdfViewer"]
