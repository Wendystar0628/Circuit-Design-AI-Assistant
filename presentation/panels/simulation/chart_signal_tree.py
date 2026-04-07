from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QStyle, QStyleOptionViewItem, QTreeWidget


class SignalTreeWidget(QTreeWidget):
    signal_label_clicked = pyqtSignal(object)

    def mousePressEvent(self, event):
        position = event.position().toPoint()
        item = self.itemAt(position)
        index = self.indexAt(position)
        if item is None or not index.isValid() or event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        if self._is_checkbox_hit(index, position):
            super().mousePressEvent(event)
            return
        self.signal_label_clicked.emit(item)
        event.accept()

    def _is_checkbox_hit(self, index, position) -> bool:
        if not self.model().flags(index) & Qt.ItemFlag.ItemIsUserCheckable:
            return False
        option = QStyleOptionViewItem()
        option.rect = self.visualRect(index)
        option.features = QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator
        option.state = QStyle.StateFlag.State_Enabled
        check_state = index.data(Qt.ItemDataRole.CheckStateRole)
        if check_state == Qt.CheckState.Checked or check_state == Qt.CheckState.Checked.value:
            option.state |= QStyle.StateFlag.State_On
        else:
            option.state |= QStyle.StateFlag.State_Off
        check_rect = self.style().subElementRect(QStyle.SubElement.SE_ItemViewItemCheckIndicator, option, self)
        return check_rect.contains(position)


__all__ = ["SignalTreeWidget"]
