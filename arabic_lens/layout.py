"""Find bounded UI panels from screenshot pixels, independent of game processes."""
import cv2
from .models import Rect


class TextContainerDetector:
    def detect(self, image):
        gray = cv2.cvtColor(image, cv2.COLOR_BGRA2GRAY if image.shape[2] == 4 else cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 30, 90)
        contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        panels = []
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            if w < 35 or h < 18 or h > 400 or w * h > image.shape[0] * image.shape[1] * .75:
                continue
            area = abs(cv2.contourArea(contour))
            if area / (w * h) < .72:
                continue
            corners = cv2.approxPolyDP(contour, cv2.arcLength(contour, True) * .025, True)
            if not 4 <= len(corners) <= 10:
                continue
            rect = Rect(x, y, w, h)
            if not any(rect.overlap(p) > .95 and abs(rect.w * rect.h - p.w * p.h) < rect.w * rect.h * .15 for p in panels):
                panels.append(rect)
        return sorted(panels, key=lambda r: r.w * r.h)

    @staticmethod
    def containing(panels, word):
        cx, cy = word.x + word.w / 2, word.y + word.h / 2
        return next((p for p in panels if p.x <= cx < p.right and p.y <= cy < p.bottom
            and word.overlap(p) > .85), None)
