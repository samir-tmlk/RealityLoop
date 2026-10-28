"""RealityLoop : jumeau numérique d'une bille sur rampe, calibré sur des lancers filmés.

Repère : origine au bas de la rampe, x vers le gobelet, y vers le haut, en mètres.
La rampe pivote autour de son extrémité basse, posée à la hauteur `height` au-dessus du sol d'atterrissage.
Chaque lancer est un CSV `t,x,y` (en-tête obligatoire) : temps en s, position du centre de la bille,
y = 0 quand la bille roule au sol. C'est la sortie attendue du module perception (SAM 3.1 + repère d'échelle).

Usage :
    py realityloop.py --length 0.6 --height 0.3 --cup 0.2 --cup-height 0.1 ref.csv@25 essai2.csv@31

Avec plusieurs lancers, le dernier sert de vérification : il est prédit à partir des précédents,
puis l'ajustement est refait sur tous (recalage) avant de recommander l'angle suivant.
Si le système a changé (autre surface, autre bille), ne passez que les lancers faits après le changement.
"""
import argparse

import numpy as np
from scipy.optimize import least_squares

G = 9.81


def _exit(theta, mu, L):
    """Temps et vitesse de sortie de rampe (sphère pleine qui roule, résistance au roulement mu)."""
    a = 5 / 7 * G * (np.sin(theta) - mu * np.cos(theta))
    if a <= 0:
        return np.inf, 0.0
    T = np.sqrt(2 * L / a)
    return T, a * T


def simulate(t, theta, mu, e, L, h):
    """Positions (x, y) aux instants t (s, 0 = lâcher en haut de rampe)."""
    t = np.asarray(t, float)
    c, s = np.cos(theta), np.sin(theta)
    T, v = _exit(theta, mu, L)
    d = L - 0.5 * (v / T if np.isfinite(T) else 0) * np.clip(t, 0, T) ** 2  # distance restante sur la rampe
    x, y = -d * c, h + d * s
    t_start, x0, y0, vx, vy = T, 0.0, h, v * c, -v * s
    while t_start <= t.max():
        tau = (vy + np.sqrt(vy**2 + 2 * G * y0)) / G  # temps jusqu'au sol
        m = t >= t_start
        dt = t[m] - t_start
        x[m], y[m] = x0 + vx * dt, np.maximum(y0 + vy * dt - 0.5 * G * dt**2, 0)
        vy = e * (G * tau - vy)  # rebond : vitesse d'impact multipliée par e
        t_start, x0, y0 = t_start + tau, x0 + vx * tau, 0.0
        if vy < 0.05:  # shortcut: pas de frottement au sol, la bille roule à vx constante ; à ajouter si les vidéos montrent un arrêt
            vy = 0.0
            m = t >= t_start
            x[m], y[m] = x0 + vx * (t[m] - t_start), 0.0
            break
    return x, y


def landing(theta, mu, L, h, yc=0.0):
    """Abscisse où la bille redescend à la hauteur yc (bord du gobelet) lors du premier vol."""
    _, v = _exit(theta, mu, L)
    vx, vy = v * np.cos(theta), -v * np.sin(theta)
    return vx * (vy + np.sqrt(vy**2 + 2 * G * (h - yc))) / G


def observed_landing(x, y, yc=0.0):
    """Première descente sous yc après la sortie de rampe, interpolée ; None si absente."""
    for i in range(len(x) - 1):
        if x[i] > 0 and y[i] >= yc > y[i + 1]:
            return x[i] + (x[i + 1] - x[i]) * (y[i] - yc) / (y[i] - y[i + 1])
    return None


def fit(throws, L, h):
    """Ajuste mu, e et un instant de lâcher par lancer. throws : liste de (theta, t, x, y).

    Renvoie (p, cov, rms) avec p = [mu, e, t0_1, ...].
    """
    def residuals(p):
        return np.concatenate([
            np.concatenate(simulate(t - p[2 + i], th, p[0], p[1], L, h)) - np.concatenate([x, y])
            for i, (th, t, x, y) in enumerate(throws)
        ])

    p0 = [0.02, 0.5] + [t[0] for _, t, _, _ in throws]
    lo = [0.0, 0.0] + [-np.inf] * len(throws)
    hi = [1.0, 1.0] + [np.inf] * len(throws)
    r = least_squares(residuals, p0, bounds=(lo, hi))
    n, k = r.fun.size, r.x.size
    # shortcut: covariance gaussienne à bruit indépendant, sous-estime si le suivi a des erreurs corrélées ; passer au bootstrap par lancer pour le banc d'essai
    cov = 2 * r.cost / max(n - k, 1) * np.linalg.pinv(r.jac.T @ r.jac)
    return r.x, cov, np.sqrt(np.mean(r.fun**2))


def predict(theta, p, cov, L, h, yc, n=500, seed=0):
    """Atterrissage prédit (moyenne, écart-type) en propageant l'incertitude sur mu."""
    mus = np.clip(np.random.default_rng(seed).normal(p[0], np.sqrt(cov[0, 0]), n), 0, 1)
    xs = np.array([landing(theta, m, L, h, yc) for m in mus])
    xs = xs[np.isfinite(xs) & (xs > 0)]
    return xs.mean(), xs.std()


def plan(cup, p, L, h, yc, lo=5.0, hi=60.0):
    """Angle (rad) dont l'atterrissage prédit est le plus proche du gobelet."""
    angles = np.radians(np.arange(lo, hi, 0.05))
    err = [abs(landing(a, p[0], L, h, yc) - cup) for a in angles]
    return angles[int(np.nanargmin(err))]


def load(arg):
    path, deg = arg.rsplit("@", 1)  # @ plutôt que : pour les chemins Windows
    deg = float(deg)
    if not 0 < deg < 90:
        raise SystemExit(f"{arg} : angle hors de ]0, 90[ degrés")
    data = np.loadtxt(path, delimiter=",", skiprows=1, ndmin=2)
    if data.shape[1] != 3 or len(data) < 10 or not np.all(np.diff(data[:, 0]) > 0):
        raise SystemExit(f"{path} : il faut au moins 10 lignes t,x,y avec t croissant")
    return np.radians(deg), data[:, 0], data[:, 1], data[:, 2]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("throws", nargs="+", help="lancer.csv@angle_en_degrés, le plus récent en dernier")
    ap.add_argument("--length", type=float, required=True, help="longueur parcourue sur la rampe (m)")
    ap.add_argument("--height", type=float, required=True, help="hauteur du bas de rampe (m)")
    ap.add_argument("--cup", type=float, required=True, help="abscisse du centre du gobelet (m)")
    ap.add_argument("--cup-height", type=float, default=0.0, help="hauteur du bord du gobelet (m)")
    ap.add_argument("--tol", type=float, default=0.03, help="écart accepté, rayon du gobelet par défaut (m)")
    ap.add_argument("--sim-out", help="CSV de la trajectoire simulée du dernier lancer, pour track.py --overlay")
    a = ap.parse_args()
    if a.length <= 0 or a.cup_height >= a.height:
        raise SystemExit("il faut --length > 0 et --cup-height < --height")
    throws = [load(s) for s in a.throws]
    L, h, yc = a.length, a.height, a.cup_height

    if len(throws) > 1:
        th, _, x, y = throws[-1]
        p, cov, _ = fit(throws[:-1], L, h)
        m, sd = predict(th, p, cov, L, h, yc)
        obs = observed_landing(x, y, yc)
        print(f"Vérification du dernier lancer ({np.degrees(th):.1f}°) : prédit {m:.3f} ± {sd:.3f} m", end="")
        if obs is None:
            print(", atterrissage non observé dans la vidéo")
        else:
            ok = abs(obs - m) <= a.tol
            print(f", observé {obs:.3f} m, écart {obs - m:+.3f} m -> {'OK' if ok else 'recalage'}")

    p, cov, rms = fit(throws, L, h)
    if a.sim_out:
        th, t, _, _ = throws[-1]
        np.savetxt(a.sim_out, np.c_[t, *simulate(t - p[-1], th, p[0], p[1], L, h)],
                   delimiter=",", header="t,x,y", comments="", fmt="%.5f")
    sd = np.sqrt(np.diag(cov))
    print(f"Calibration sur {len(throws)} lancer(s) : mu = {p[0]:.4f} ± {sd[0]:.4f}, "
          f"e = {p[1]:.3f} ± {sd[1]:.3f}, erreur de superposition RMS = {1000 * rms:.1f} mm")
    th = plan(a.cup, p, L, h, yc)
    m, s = predict(th, p, cov, L, h, yc)
    print(f"Réglez la rampe à {np.degrees(th):.1f}° : atterrissage prédit {m:.3f} ± {s:.3f} m "
          f"(gobelet à {a.cup:.3f} m)")
    if abs(m - a.cup) > a.tol:
        print("Attention : aucun angle entre 5° et 60° n'atteint le gobelet à la tolérance près.")


if __name__ == "__main__":
    main()
