"""Interface graphique locale : py app.py, puis le navigateur s'ouvre sur http://127.0.0.1:8765.

Les vidéos téléversées et les superpositions sont rangées dans runs/ (ignoré par git).
"""
import json
import os
import re
import subprocess
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

from realityloop import loop
from scene import PROMPT, annotate, ask_muse, first_frame, scene_args
from track import overlay, probe, track

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, "runs")
ID = re.compile(r"[0-9a-f]{32}")
TYPES = {"png": "image/png", "mp4": "video/mp4"}


def video_path(i):
    if not isinstance(i, str) or not ID.fullmatch(i):
        raise SystemExit("identifiant de vidéo invalide")
    p = os.path.join(WORK, i + ".video")
    if not os.path.exists(p):
        raise SystemExit("vidéo inconnue : téléversez-la à nouveau")
    return p


def upload(body):
    """Enregistre la vidéo, renvoie son identifiant et l'URL de sa première image."""
    os.makedirs(WORK, exist_ok=True)
    i = uuid.uuid4().hex
    p = os.path.join(WORK, i + ".video")
    with open(p, "wb") as f:
        f.write(body)
    try:
        w, h, fps = probe(p)
        annotate(first_frame(p), {k: [] for k in ("ball", "ramp_end", "floor", "ref", "cup")},
                 os.path.join(WORK, i + ".png"))
    except (subprocess.CalledProcessError, KeyError, IndexError, ValueError):
        os.remove(p)
        raise SystemExit("fichier illisible : est-ce bien une vidéo ?")
    return {"id": i, "w": w, "h": h, "fps": fps, "frame": f"/media/{i}.png"}


def muse(q):
    p = video_path(q.get("id"))
    frame = first_frame(p)
    h, w, _ = frame.shape
    s = ask_muse(os.path.join(WORK, q["id"] + ".png"), PROMPT.format(w=w, h=h, ref_desc=q.get("ref_desc") or
                                                                       "a ruler lying on the table"))
    scene_args(s, frame, 1.0)  # rejette une réponse incomplète ou hors de l'image
    return {"points": s}


def run(q):
    """Suivi de chaque lancer, calibration, vérification et angle recommandé."""
    throws = q.get("throws") or []
    if not throws:
        raise SystemExit("ajoutez au moins un lancer")
    ref_length, tol = float(q.get("ref_length", 0)), float(q.get("tol", 0.03))
    if ref_length <= 0 or tol <= 0:
        raise SystemExit("la longueur du repère et la tolérance doivent être positives")
    g = scene_args(q.get("points") or {}, first_frame(video_path(throws[0].get("id"))), ref_length)
    color = np.array([int(g["color"][k:k + 2], 16) for k in (1, 3, 5)], np.float32)
    data, angles = [], []
    for n, t in enumerate(throws):
        a = g["angle"] if n == 0 and t.get("angle") is None else t.get("angle")
        if not isinstance(a, (int, float)) or not 0 < a < 90:
            raise SystemExit(f"lancer {n + 1} : indiquez l'angle de la rampe, entre 0 et 90°")
        angles.append(float(a))
        data.append((np.radians(a), *track(video_path(t["id"]), color, g["origin"], g["ref"], ref_length)))
    r = loop(data, g["length"], g["height"], g["cup"], g["cup_height"], tol)
    last = throws[-1]["id"]
    overlay(video_path(last), os.path.join(WORK, last + ".mp4"), color, g["origin"], g["ref"], ref_length, r.pop("sim"))
    g = {k: v for k, v in g.items() if k not in ("origin", "ref")}
    return {"geometry": g, "angles": angles, "result": r, "overlay": f"/media/{last}.mp4"}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj).encode(), "application/json")

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/":
            with open(os.path.join(HERE, "ui.html"), "rb") as f:
                return self._send(200, f.read(), "text/html; charset=utf-8")
        m = re.fullmatch(r"/media/([0-9a-f]{32})\.(png|mp4)", path)
        if m and os.path.exists(f := os.path.join(WORK, f"{m[1]}.{m[2]}")):
            with open(f, "rb") as fh:
                return self._send(200, fh.read(), TYPES[m[2]])
        self._json(404, {"error": "introuvable"})

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        routes = {"/api/upload": lambda: upload(body), "/api/muse": lambda: muse(json.loads(body)),
                  "/api/run": lambda: run(json.loads(body))}
        if self.path not in routes:
            return self._json(404, {"error": "introuvable"})
        try:
            self._json(200, routes[self.path]())
        except SystemExit as e:
            self._json(400, {"error": str(e)})
        except Exception as e:  # erreur imprévue : on l'affiche dans l'interface plutôt que de couper la connexion
            self._json(500, {"error": f"{type(e).__name__} : {e}"})

    def log_message(self, *args):
        pass


def main():
    url = "http://127.0.0.1:8765"
    server = ThreadingHTTPServer(("127.0.0.1", 8765), Handler)  # local uniquement
    print(f"RealityLoop sur {url} (Ctrl+C pour arrêter)")
    webbrowser.open(url)
    server.serve_forever()


if __name__ == "__main__":
    main()
