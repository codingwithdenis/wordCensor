from PyQt5.QtWidgets import QWidget
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPainter, QColor, QPen, QFont


ROW_H = 14          # height of each region row in pixels
MIN_HEIGHT = ROW_H  # at least one row tall


class TimelineMarkers(QWidget):
    """
    Timeline bar showing each region's active span on its own row,
    with a colored strip, start/end ticks, and the playhead.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(MIN_HEIGHT)
        self.total_frames = 1
        self.regions = []
        self.current_frame = 0

    def update_state(self, total_frames, regions, current_frame):
        self.total_frames = max(1, total_frames)
        self.regions = regions
        self.current_frame = current_frame
        new_h = max(MIN_HEIGHT, len(regions) * ROW_H)
        if self.height() != new_h:
            self.setFixedHeight(new_h)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        w = self.width()
        h = self.height()

        painter.fillRect(self.rect(), QColor("#1e1e1e"))

        font = QFont()
        font.setPointSize(7)
        painter.setFont(font)

        for row, region in enumerate(self.regions):
            r, g, b = region.color
            color = QColor(r, g, b)

            row_top = row * ROW_H
            row_mid = row_top + ROW_H // 2

            x_start = self._frame_to_x(region.start_frame, w)
            x_end = self._frame_to_x(
                region.end_frame if region.end_frame is not None
                else self.total_frames - 1,
                w
            )

            # Subtle row background alternating
            if row % 2 == 1:
                painter.fillRect(0, row_top, w, ROW_H, QColor(255, 255, 255, 8))

            # Filled span bar (thin, vertically centered in the row)
            bar_h = 4
            bar_y = row_top + (ROW_H - bar_h) // 2
            painter.fillRect(x_start, bar_y, max(1, x_end - x_start), bar_h,
                             QColor(r, g, b, 150))

            # Start tick
            painter.setPen(QPen(color, 2))
            painter.drawLine(x_start, row_top + 1, x_start, row_top + ROW_H - 2)

            # End tick (only if explicitly set)
            if region.end_frame is not None:
                painter.drawLine(x_end, row_top + 1, x_end, row_top + ROW_H - 2)

            # Region label — to the left of the start tick if space allows
            label = f"R{region.id + 1}"
            painter.setPen(QColor(r, g, b))
            label_x = x_start + 3
            painter.drawText(label_x, row_top, 20, ROW_H, Qt.AlignVCenter | Qt.AlignLeft, label)

        # Playhead — drawn over all rows
        px = self._frame_to_x(self.current_frame, w)
        painter.setPen(QPen(QColor(255, 255, 255, 200), 1))
        painter.drawLine(px, 0, px, h)

    def _frame_to_x(self, frame, width):
        if self.total_frames <= 1:
            return 0
        return int(frame / (self.total_frames - 1) * width)
