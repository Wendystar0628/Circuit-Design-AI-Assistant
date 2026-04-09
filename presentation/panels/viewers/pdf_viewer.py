import os

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

try:
    from PyQt6.QtPdf import QPdfDocument
    from PyQt6.QtPdfWidgets import QPdfView
    QT_PDF_AVAILABLE = True
except ImportError:
    QPdfDocument = None
    QPdfView = None
    QT_PDF_AVAILABLE = False


class PdfViewer(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._document = None
        self._view = None
        self._summary_label = QLabel(self)
        self._summary_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._message_label = QLabel(self)
        self._message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._message_label.setWordWrap(True)
        self._message_label.hide()
        self._fit_width_button = QPushButton("适应宽度", self)
        self._fit_page_button = QPushButton("适应页面", self)
        self._actual_size_button = QPushButton("100%", self)
        self._zoom_out_button = QPushButton("-", self)
        self._zoom_in_button = QPushButton("+", self)

        toolbar = QFrame(self)
        toolbar.setFrameShape(QFrame.Shape.NoFrame)
        toolbar.setStyleSheet("background: #f8fafc; border-bottom: 1px solid #dbe3ef;")
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(12, 8, 12, 8)
        toolbar_layout.setSpacing(8)
        toolbar_layout.addWidget(self._summary_label, 1)
        toolbar_layout.addWidget(self._zoom_out_button)
        toolbar_layout.addWidget(self._zoom_in_button)
        toolbar_layout.addWidget(self._actual_size_button)
        toolbar_layout.addWidget(self._fit_width_button)
        toolbar_layout.addWidget(self._fit_page_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(toolbar)
        layout.addWidget(self._message_label)

        if QT_PDF_AVAILABLE:
            self._document = QPdfDocument(self)
            self._view = QPdfView(self)
            self._view.setDocument(self._document)
            self._view.setPageMode(QPdfView.PageMode.MultiPage)
            self._view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
            layout.addWidget(self._view, 1)
            self._fit_width_button.clicked.connect(self._fit_width)
            self._fit_page_button.clicked.connect(self._fit_page)
            self._actual_size_button.clicked.connect(self._actual_size)
            self._zoom_out_button.clicked.connect(self._zoom_out)
            self._zoom_in_button.clicked.connect(self._zoom_in)
            self._document.statusChanged.connect(self._update_summary)
            self._document.pageCountChanged.connect(self._update_summary)
        else:
            self._message_label.setText("当前环境缺少 QtPdf，无法预览 PDF。")
            self._message_label.show()

    def load_pdf(self, path: str) -> bool:
        if not QT_PDF_AVAILABLE or self._document is None or self._view is None:
            self._set_error("当前环境缺少 QtPdf，无法预览 PDF。")
            return False

        abs_path = os.path.abspath(path)
        if not os.path.isfile(abs_path):
            self._set_error(f"PDF 文件不存在：{abs_path}")
            return False

        error = self._document.load(abs_path)
        if error != QPdfDocument.Error.None_:
            self._set_error(f"PDF 加载失败：{self._error_message(error)}")
            return False

        self._message_label.hide()
        self._view.show()
        self._fit_width()
        self._update_summary()
        return True

    def _fit_width(self):
        if self._view is None:
            return
        self._view.setZoomMode(QPdfView.ZoomMode.FitToWidth)

    def _fit_page(self):
        if self._view is None:
            return
        self._view.setZoomMode(QPdfView.ZoomMode.FitInView)

    def _actual_size(self):
        if self._view is None:
            return
        self._view.setZoomMode(QPdfView.ZoomMode.Custom)
        self._view.setZoomFactor(1.0)

    def _zoom_out(self):
        if self._view is None:
            return
        self._view.setZoomMode(QPdfView.ZoomMode.Custom)
        self._view.setZoomFactor(max(self._view.zoomFactor() * 0.85, 0.2))

    def _zoom_in(self):
        if self._view is None:
            return
        self._view.setZoomMode(QPdfView.ZoomMode.Custom)
        self._view.setZoomFactor(min(self._view.zoomFactor() * 1.15, 5.0))

    def _set_error(self, message: str) -> None:
        self._summary_label.setText("PDF 预览不可用")
        self._message_label.setText(message)
        self._message_label.show()
        if self._view is not None:
            self._view.hide()

    def _update_summary(self):
        if self._document is None:
            self._summary_label.setText("PDF")
            return
        page_count = self._document.pageCount()
        status_name = getattr(self._document.status(), "name", str(self._document.status()))
        self._summary_label.setText(f"PDF    {page_count} pages    status: {status_name}")

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
