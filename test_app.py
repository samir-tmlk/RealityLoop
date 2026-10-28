"""API de l'interface sur une vidéo synthétique : py test_app.py (ou pytest)."""
import os
import tempfile

import numpy as np

import app
from realityloop import landing
from test_track import HEIGHT, MU, ORIGIN, R, SCALE, L, make_video, simulate

CUP = (ORIGIN[0] + 0.2 * SCALE, ORIGIN[1] - 0.1 * SCALE)  # gobelet à 0,20 m, bord à 0,10 m


def points():
    x, y = simulate(np.array([0.0]), np.radians(25), MU, 0.6, L, HEIGHT)
    return {"ball": [ORIGIN[0] + x[0] * SCALE, ORIGIN[1] - (y[0] * SCALE + R)],
            "ramp_end": [ORIGIN[0], ORIGIN[1] - HEIGHT * SCALE], "floor": list(ORIGIN),
            "ref": [10, 10, 10 + SCALE, 10], "cup": list(CUP)}


def test_upload_then_run():
    with tempfile.TemporaryDirectory() as d:
        app.WORK = d
        make_video(os.path.join(d, "src.mp4"))
        with open(os.path.join(d, "src.mp4"), "rb") as f:
            v = app.upload(f.read())
        assert (v["w"], v["h"]) == (640, 480) and os.path.exists(os.path.join(d, v["id"] + ".png"))
        out = app.run({"points": points(), "ref_length": 1.0, "tol": 0.03, "throws": [{"id": v["id"], "angle": None}]})
        g, r = out["geometry"], out["result"]
        assert abs(out["angles"][0] - 25) < 1, out["angles"]
        assert abs(g["length"] - L) < 0.02 and abs(g["height"] - HEIGHT) < 0.005 and abs(g["cup"] - 0.2) < 0.005, g
        assert abs(landing(np.radians(r["angle"]), MU, L, HEIGHT, 0.1) - 0.2) < 0.02, r
        assert os.path.exists(os.path.join(d, v["id"] + ".mp4"))
        try:
            app.run({"points": points(), "ref_length": 1.0, "throws": [{"id": "../etc"}]})
            raise AssertionError("identifiant non vérifié")
        except SystemExit:
            pass


if __name__ == "__main__":
    test_upload_then_run()
    print("ok test_upload_then_run")
