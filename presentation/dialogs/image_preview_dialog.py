from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from presentation.panels.viewers.image_viewer import ImageViewer


class ImagePreviewDialog(QDialog):
    def __init__(self, image_path: str, parent=None):
        super().__init__(parent)
        self._image_path = image_path
        self._image_viewer = ImageViewer(self)
        self._close_button = QPushButton("×", self)
        self._setup_ui()
        self._image_viewer.load_image(image_path)
        self._image_viewer.fit_to_window()

    def _setup_ui(self) -> None:
        self.setWindowTitle("Image Preview")
        self.resize(960, 720)
        self.setModal(True)
        self.setStyleSheet("QDialog { background: #111827; }")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        top_bar = QWidget(self)
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.addStretch()

        self._close_button.setFixedSize(32, 32)
        self._close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close_button.setStyleSheet(
            "QPushButton { background: rgba(255,255,255,0.12); color: white; border: none; border-radius: 16px; font-size: 20px; }"
            "QPushButton:hover { background: rgba(255,255,255,0.24); }"
        )
        self._close_button.clicked.connect(self.close)
        top_layout.addWidget(self._close_button)

        layout.addWidget(top_bar)
        layout.addWidget(self._image_viewer, 1)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
        else:
            super().mousePressEvent(event)


__all__ = ["ImagePreviewDialog"]
