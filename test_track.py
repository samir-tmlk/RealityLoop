"""Bout en bout sur une vidéo synthétique encodée en H.264 : py test_track.py (ou pytest)."""
import os
import subprocess
import tempfile

import numpy as np

from realityloop import fit, simulate
from track import overlay, probe, track

W, H, FPS, SCALE, R = 640, 480, 60, 500, 8  # SCALE en px/m, R rayon de la bille en px
ORIGIN = (350, 440)
L, HEIGHT, MU, E = 0.6, 0.3, 0.05, 0.6


def make_video(path, deg=25, t0=0.2):
    t = np.arange(0, 1.4, 1 / FPS)
    x, y = simulate(t - t0, np.radians(deg), MU, E, L, HEIGHT)
    yy, xx = np.mgrid[:H, :W]
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                          "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", path],
                         stdin=subprocess.PIPE)
    for xi, yi in zip(x, y):
        f = np.full((H, W, 3), 128, np.uint8)
        cx, cy = ORIGIN[0] + xi * SCALE, ORIGIN[1] - (yi * SCALE + R)
        f[(xx - cx) ** 2 + (yy - cy) ** 2 <= R**2] = (255, 128, 0)
        p.stdin.write(f.tobytes())
    p.stdin.close()
    assert p.wait() == 0
    return t, x, y


def test_track_then_fit():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "lancer.mp4")
        t_true, x_true, y_true = make_video(path)
        orange = np.array([255, 128, 0], np.float32)
        t, x, y = track(path, orange, ORIGIN, (0, 0, SCALE, 0), 1.0)
        inside = np.isin(np.round(t_true * FPS), np.round(t * FPS))
        err = np.hypot(x - x_true[inside], y - y_true[inside])
        assert np.max(err) < 0.003, np.max(err)  # moins de 1,5 px
        p, _, _ = fit([(np.radians(25), t, x, y)], L, HEIGHT)
        assert abs(p[0] - MU) < 0.005 and abs(p[1] - E) < 0.05, p

        out = os.path.join(d, "superposition.mp4")
        sim = (t, *simulate(t - p[-1], np.radians(25), p[0], p[1], L, HEIGHT))
        overlay(path, out, orange, ORIGIN, (0, 0, SCALE, 0), 1.0, sim)
        assert probe(out)[:2] == (W, H)


if __name__ == "__main__":
    test_track_then_fit()
    print("ok test_track_then_fit")
