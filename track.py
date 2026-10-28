"""Suivi de la bille par couleur : vidéo -> CSV t,x,y pour realityloop.py.

Solution de secours en attendant SAM 3.1 : même sortie, à remplacer sans toucher au reste.
Nécessite ffmpeg et ffprobe dans le PATH. Coordonnées en pixels lues sur une image de la vidéo :
  --origin : point du sol d'atterrissage à la verticale du bas de la rampe ;
  --ref + --ref-length : deux points du repère d'échelle et la distance réelle qui les sépare (m).

Usage :
    py track.py lancer.mp4 --color "#ff8000" --origin 350,440 --ref 100,460,600,460 --ref-length 1.0 -o lancer.csv
"""
import argparse
import json
import subprocess

import numpy as np
from scipy import ndimage


def probe(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,r_frame_rate",
         "-of", "json", path], capture_output=True, text=True, check=True).stdout
    s = json.loads(out)["streams"][0]
    num, den = s["r_frame_rate"].split("/")
    return s["width"], s["height"], float(num) / float(den)


def frames(path, w, h):
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-i", path, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         stdout=subprocess.PIPE)
    n = w * h * 3
    while len(buf := p.stdout.read(n)) == n:
        yield np.frombuffer(buf, np.uint8).reshape(h, w, 3)
    if p.wait():
        raise SystemExit(f"ffmpeg a échoué sur {path}")


def find_ball(frame, color, tol=60, min_px=20):
    """Centre (x, y) et rayon en pixels de la plus grande tache de la couleur donnée, ou None."""
    # shortcut: distance RVB brute, sensible aux ombres et aux reflets ; passer en teinte (HSV) si l'éclairage varie
    mask = np.linalg.norm(frame.astype(np.float32) - color, axis=2) < tol
    lab, n = ndimage.label(mask)
    if n == 0:
        return None
    sizes = np.bincount(lab.ravel())[1:]
    k = sizes.argmax()
    blob = lab == k + 1
    # une bille coupée par le bord a un centre faussé
    if sizes[k] < min_px or blob[[0, -1]].any() or blob[:, [0, -1]].any():
        return None
    cy, cx = ndimage.center_of_mass(blob)
    return cx, cy, np.sqrt(sizes[k] / np.pi)


def track(path, color, origin, ref, ref_length, tol=60):
    """Trajectoire (t, x, y) en mètres. y = 0 quand la bille roule au sol, x orienté vers le point d'arrivée."""
    w, h, fps = probe(path)
    hits = [(i / fps, *b) for i, f in enumerate(frames(path, w, h)) if (b := find_ball(f, color, tol))]
    if len(hits) < 10:
        raise SystemExit(f"bille trouvée sur {len(hits)} image(s) seulement : vérifier --color et --tol")
    t, cx, cy, r = np.array(hits).T
    # shortcut: suppose la caméra de face et horizontale (pas de correction de perspective) ; calibrer la caméra si le plan du mouvement est vu de biais
    scale = np.hypot(ref[2] - ref[0], ref[3] - ref[1]) / ref_length
    x = (cx - origin[0]) / scale
    y = (origin[1] - cy) / scale - np.median(r) / scale
    if x[-1] < x[0]:  # la bille va vers la gauche de l'image
        x = -x
    return t, x, y


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video")
    ap.add_argument("--color", required=True, help="couleur de la bille, ex. #ff8000")
    ap.add_argument("--tol", type=float, default=60, help="distance RVB acceptée (0-441)")
    ap.add_argument("--origin", required=True, help="px,py")
    ap.add_argument("--ref", required=True, help="x1,y1,x2,y2 en pixels")
    ap.add_argument("--ref-length", type=float, required=True, help="distance réelle entre les deux points (m)")
    ap.add_argument("-o", "--out", required=True, help="CSV de sortie")
    a = ap.parse_args()
    c = a.color.lstrip("#")
    if len(c) != 6:
        raise SystemExit("--color attend #rrggbb")
    color = np.array([int(c[i:i + 2], 16) for i in (0, 2, 4)], np.float32)
    origin = [float(v) for v in a.origin.split(",")]
    ref = [float(v) for v in a.ref.split(",")]
    if len(origin) != 2 or len(ref) != 4 or a.ref_length <= 0 or ref[:2] == ref[2:]:
        raise SystemExit("--origin px,py ; --ref x1,y1,x2,y2 (deux points distincts) ; --ref-length > 0")
    t, x, y = track(a.video, color, origin, ref, a.ref_length, a.tol)
    np.savetxt(a.out, np.c_[t, x, y], delimiter=",", header="t,x,y", comments="", fmt="%.5f")
    print(f"{len(t)} positions écrites dans {a.out} (de {t[0]:.2f} à {t[-1]:.2f} s)")


if __name__ == "__main__":
    main()
