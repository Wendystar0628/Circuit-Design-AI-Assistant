from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPainter, QPixmap
from PyQt6.QtWidgets import QWidget


def export_widget_image(
    owner_widget: QWidget,
    target_widget: QWidget,
    path: str,
    *,
    minimum_surface_width: int = 1280,
    minimum_surface_height: int = 840,
    minimum_render_width: int = 960,
    minimum_render_height: int = 640,
) -> bool:
    if owner_widget is None or target_widget is None:
        return False

    owner_widget.resize(
        max(owner_widget.width(), minimum_surface_width),
        max(owner_widget.height(), minimum_surface_height),
    )
    owner_widget.ensurePolished()
    layout = owner_widget.layout()
    if layout is not None:
        layout.activate()

    render_width = max(int(target_widget.width()), minimum_render_width)
    render_height = max(int(target_widget.height()), minimum_render_height)
    if render_width <= 0 or render_height <= 0:
        return False

    pixmap = QPixmap(render_width, render_height)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    try:
        target_widget.render(painter)
    finally:
        painter.end()

    if pixmap.isNull():
        return False
    return pixmap.save(path)


__all__ = ["export_widget_image"]
