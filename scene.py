"""Lecture de scène par Muse : première image de la vidéo -> arguments de track.py et realityloop.py.

Muse (CLI `muse exec --image`) repère la bille, le bas de la rampe, le sol, le repère d'échelle et le gobelet.
La couleur de la bille est mesurée sur l'image, pas devinée par le modèle.
Les coordonnées d'un modèle de vision peuvent être approximatives : vérifiez l'image annotée avant de lancer.

Usage :
    py scene.py lancer.mp4 --ref-length 1.0 --ref-desc "the yellow ruler on the table" -o scene.png
"""
import argparse
import json
import math
import os
import re
import shutil
import subprocess
import tempfile

import numpy as np

from track import find_ball, probe

PROMPT = """The attached image is the first frame of a video, {w}x{h} pixels, origin at the top-left corner, \
x to the right, y down. It shows a ball resting at the top of a ramp, a cup, and {ref_desc} used as a scale reference.
Reply with only a JSON object, no other text, every value in pixels:
{{"ball": [x, y], "ramp_end": [x, y], "floor": [x, y], "ref": [x1, y1, x2, y2], "cup": [x, y]}}
ball: centre of the ball. ramp_end: lower end of the ramp's rolling surface. floor: point of the surface the ball \
lands on, directly below ramp_end. ref: the two ends of the scale reference. cup: centre of the cup's opening."""

KEYS = {"ball": 2, "ramp_end": 2, "floor": 2, "ref": 4, "cup": 2}
MARKS = {"ball": (255, 255, 255), "ramp_end": (0, 0, 255), "floor": (255, 0, 255), "ref": (255, 255, 0),
         "cup": (0, 255, 255)}


def first_frame(path):
    w, h, _ = probe(path)
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24",
                          "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(h, w, 3)


def ask_muse(png, prompt, timeout=600):
    """Points de la scène renvoyés par Muse, dict de listes de pixels."""
    muse = shutil.which("muse")
    if not muse:
        raise SystemExit("CLI muse introuvable dans le PATH")
    with tempfile.TemporaryDirectory() as d:  # dossier vide : l'agent Muse n'a accès à rien d'autre
        pf = os.path.join(d, "prompt.txt")
        with open(pf, "w", encoding="utf-8") as f:
            f.write(prompt)  # par fichier : muse.cmd retire les guillemets des arguments
        r = subprocess.run([muse, "exec", "--image", os.path.abspath(png), "--prompt-file", pf], cwd=d,
                           capture_output=True, text=True, encoding="utf-8", timeout=timeout)
    m = re.search(r"\{.*\}", r.stdout, re.S)
    if r.returncode or not m:
        raise SystemExit(f"réponse de Muse inexploitable :\n{r.stdout}\n{r.stderr[-500:]}")
    return json.loads(m.group())


def scene_args(s, frame, ref_length):
    """Arguments de track.py et realityloop.py tirés des points de la scène (clics ou réponse du modèle, vérifiés)."""
    h, w, _ = frame.shape
    for k, n in KEYS.items():
        v = s.get(k)
        if not (isinstance(v, list) and len(v) == n and all(isinstance(c, (int, float)) for c in v)):
            raise SystemExit(f"repères : '{k}' attendu comme {n} nombres, reçu {v!r}")
        if not all(0 <= c < (w if i % 2 == 0 else h) for i, c in enumerate(v)):
            raise SystemExit(f"repères : '{k}' hors de l'image {w}x{h} : {v}")
    (bx, by), (ex, ey), (ox, oy), (cx, cy), ref = s["ball"], s["ramp_end"], s["floor"], s["cup"], s["ref"]
    scale = math.hypot(ref[2] - ref[0], ref[3] - ref[1]) / ref_length
    if scale == 0:
        raise SystemExit("repères : les deux extrémités du repère sont confondues")
    patch = frame[max(int(by) - 2, 0):int(by) + 3, max(int(bx) - 2, 0):int(bx) + 3].reshape(-1, 3)
    color = np.median(patch, axis=0)
    ball = find_ball(frame, color.astype(np.float32))
    r = ball[2] if ball else 0.0
    # le centre de la bille est à un rayon au-dessus de la surface : on retire ce décalage perpendiculaire
    D = math.hypot(bx - ex, by - ey)
    d = math.sqrt(max(D**2 - r**2, 0))
    a = {
        "color": "#%02x%02x%02x" % tuple(int(c) for c in color),
        "origin": (ox, oy), "ref": ref,
        "length": d / scale,
        "angle": math.degrees(math.atan2(ey - by, abs(ex - bx)) - math.atan2(r, d)),
        "height": (oy - ey) / scale,
        "cup": abs(cx - ox) / scale,
        "cup_height": (oy - cy) / scale,
    }
    if not (0 < a["angle"] < 90 and 0 <= a["cup_height"] < a["height"]):
        raise SystemExit(f"repères : géométrie incohérente (angle {a['angle']:.1f}°, hauteur {a['height']:.3f} m, "
                         f"gobelet {a['cup_height']:.3f} m) ; relancer ou relever les points à la main")
    return a


def annotate(frame, s, out):
    """Image PNG avec un carré de couleur sur chaque point renvoyé par Muse."""
    f = frame.copy()
    for k, col in MARKS.items():
        v = s[k]
        for u, w in zip(v[0::2], v[1::2]):
            u, w = int(u), int(w)
            f[max(w - 4, 0):w + 5, max(u - 4, 0):u + 5] = col
    h, w, _ = f.shape
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-i", "-",
                    out], input=f.tobytes(), check=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video")
    ap.add_argument("--ref-length", type=float, required=True, help="longueur réelle du repère d'échelle (m)")
    ap.add_argument("--ref-desc", default="a ruler lying on the table", help="description du repère, en anglais")
    ap.add_argument("-o", "--out", required=True, help="image annotée à vérifier (.png)")
    a = ap.parse_args()
    if a.ref_length <= 0:
        raise SystemExit("--ref-length doit être > 0")
    frame = first_frame(a.video)
    h, w, _ = frame.shape
    with tempfile.TemporaryDirectory() as d:
        png = os.path.join(d, "frame.png")
        annotate(frame, {k: [] for k in MARKS}, png)  # image brute, sans marque
        s = ask_muse(png, PROMPT.format(w=w, h=h, ref_desc=a.ref_desc))
    r = scene_args(s, frame, a.ref_length)
    annotate(frame, s, a.out)
    print(f"Points de Muse dessinés dans {a.out} : blanc bille, bleu bas de rampe, magenta sol, jaune repère, "
          f"cyan gobelet. Vérifiez-les, puis :")
    print(f'py track.py {a.video} --color "{r["color"]}" --origin {r["origin"][0]:.0f},{r["origin"][1]:.0f} '
          f'--ref {",".join(f"{c:.0f}" for c in r["ref"])} --ref-length {a.ref_length} -o lancer.csv')
    print(f'py realityloop.py --length {r["length"]:.3f} --height {r["height"]:.3f} --cup {r["cup"]:.3f} '
          f'--cup-height {r["cup_height"]:.3f} lancer.csv@{r["angle"]:.1f}')


if __name__ == "__main__":
    main()
