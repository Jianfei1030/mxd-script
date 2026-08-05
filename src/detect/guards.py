"""兜底异常检测:画面签名与静止判定。"""
import cv2
import numpy as np


def signature(frame, size=(64, 36)):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return cv2.resize(gray, size, interpolation=cv2.INTER_AREA).astype(np.int16)


def frame_frozen(sig_a, sig_b, threshold=0.5):
    return float(np.abs(sig_a - sig_b).mean()) < threshold
