import cv2
import numpy as np
from PyQt5.QtWidgets import QWidget
from PyQt5.QtCore import Qt, QRect, QPoint, pyqtSignal
from PyQt5.QtGui import QPainter, QPixmap, QImage, QColor, QPen, QBrush


class VideoCanvas(QWidget):
    region_drawn = pyqtSignal(tuple)  # (x, y, w, h) in frame coordinates

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap = None
        self._regions = []      # list of ((x, y, w, h), (r, g, b), label, is_selected)
        self._frame_size = (1, 1)
        self._render_rect = None  # (ox, oy, rw, rh) in widget coords

        self._selected_id = None
        self._drawing = False
        self._draw_start = None
        self._draw_current = None

        self.setMinimumSize(400, 300)
        self.setStyleSheet("background-color: #1a1a1a;")
        self.setCursor(Qt.CrossCursor)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_frame(self, frame_bgr, regions, selected_id=None):
        """
        Update the canvas with a new frame.
        regions: list of ((x, y, w, h), (r, g, b), region_id, label)
        selected_id: id of the currently selected region, or None
        """
        self._regions = regions
        self._selected_id = selected_id
        h, w = frame_bgr.shape[:2]
        self._frame_size = (w, h)

        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        # Must copy the data — QImage does not own the numpy buffer
        rgb = np.ascontiguousarray(rgb)
        qimg = QImage(rgb.data, w, h, w * 3, QImage.Format_RGB888).copy()
        self._pixmap = QPixmap.fromImage(qimg)
        self.update()

    def clear(self):
        self._pixmap = None
        self._regions = []
        self.update()

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        if self._pixmap is None:
            painter.fillRect(self.rect(), QColor("#1a1a1a"))
            painter.setPen(QColor("#555555"))
            painter.drawText(self.rect(), Qt.AlignCenter, "Open a video to get started")
            return

        # Draw frame scaled, centered, keeping aspect ratio
        scaled = self._pixmap.scaled(
            self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        ox = (self.width() - scaled.width()) // 2
        oy = (self.height() - scaled.height()) // 2
        painter.drawPixmap(ox, oy, scaled)
        self._render_rect = (ox, oy, scaled.width(), scaled.height())

        # Draw existing blur regions
        for rect, color, region_id, label in self._regions:
            r, g, b = color
            widget_rect = self._frame_to_widget_rect(rect)
            is_selected = (region_id == getattr(self, '_selected_id', None))

            if is_selected:
                # Outer glow: wide translucent ring
                painter.setPen(QPen(QColor(r, g, b, 80), 7))
                painter.setBrush(Qt.NoBrush)
                painter.drawRect(widget_rect)
                # Main border: thick solid
                painter.setPen(QPen(QColor(r, g, b), 3))
                painter.setBrush(QBrush(QColor(r, g, b, 60)))
            else:
                painter.setPen(QPen(QColor(r, g, b), 2))
                painter.setBrush(QBrush(QColor(r, g, b, 35)))

            painter.drawRect(widget_rect)

            # Region number label
            if widget_rect.width() > 20 and widget_rect.height() > 14:
                font = painter.font()
                font.setPointSize(8)
                font.setBold(is_selected)
                painter.setFont(font)
                painter.setPen(QColor(r, g, b) if not is_selected else QColor(255, 255, 255))
                painter.drawText(
                    widget_rect.adjusted(3, 2, -2, -2),
                    Qt.AlignTop | Qt.AlignLeft,
                    label
                )

        # Draw in-progress selection
        if self._drawing and self._draw_start and self._draw_current:
            sel = QRect(self._draw_start, self._draw_current).normalized()
            painter.setPen(QPen(QColor(0, 210, 255), 2, Qt.DashLine))
            painter.setBrush(QBrush(QColor(0, 210, 255, 30)))
            painter.drawRect(sel)

    # ------------------------------------------------------------------
    # Mouse events
    # ------------------------------------------------------------------

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self._pixmap is not None:
            self._drawing = True
            self._draw_start = event.pos()
            self._draw_current = event.pos()

    def mouseMoveEvent(self, event):
        if self._drawing:
            self._draw_current = event.pos()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._drawing:
            self._drawing = False
            if self._draw_start and self._draw_current:
                sel = QRect(self._draw_start, self._draw_current).normalized()
                if sel.width() > 8 and sel.height() > 8:
                    p1 = self._widget_to_frame_point(sel.topLeft())
                    p2 = self._widget_to_frame_point(sel.bottomRight())
                    if p1 and p2:
                        fw, fh = self._frame_size
                        fx = max(0, int(min(p1[0], p2[0])))
                        fy = max(0, int(min(p1[1], p2[1])))
                        frw = min(fw - fx, int(abs(p2[0] - p1[0])))
                        frh = min(fh - fy, int(abs(p2[1] - p1[1])))
                        if frw > 4 and frh > 4:
                            self.region_drawn.emit((fx, fy, frw, frh))
            self._draw_start = None
            self._draw_current = None
            self.update()

    # ------------------------------------------------------------------
    # Coordinate helpers
    # ------------------------------------------------------------------

    def _frame_to_widget_rect(self, rect):
        if not self._render_rect:
            return QRect()
        ox, oy, rw, rh = self._render_rect
        fw, fh = self._frame_size
        x, y, w, h = rect
        sx = rw / fw
        sy = rh / fh
        return QRect(int(ox + x * sx), int(oy + y * sy), int(w * sx), int(h * sy))

    def _widget_to_frame_point(self, pos):
        if not self._render_rect:
            return None
        ox, oy, rw, rh = self._render_rect
        fw, fh = self._frame_size
        if rw == 0 or rh == 0:
            return None
        x = (pos.x() - ox) * fw / rw
        y = (pos.y() - oy) * fh / rh
        return (x, y)
