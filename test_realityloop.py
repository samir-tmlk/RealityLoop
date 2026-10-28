"""Auto-vérification sur lancers synthétiques : py test_realityloop.py (ou pytest)."""
import numpy as np

from realityloop import fit, landing, observed_landing, plan, predict, simulate

L, H, YC = 0.6, 0.3, 0.1
MU, E = 0.05, 0.6


def throw(deg, t0=0.1, noise=0.002, seed=1):
    t = np.arange(0, 1.4, 1 / 120)
    x, y = simulate(t - t0, np.radians(deg), MU, E, L, H)
    rng = np.random.default_rng(seed)
    return np.radians(deg), t, x + rng.normal(0, noise, t.size), y + rng.normal(0, noise, t.size)


def test_calibration_recovers_parameters():
    p, cov, rms = fit([throw(25)], L, H)
    sd = np.sqrt(np.diag(cov))
    assert abs(p[0] - MU) < max(4 * sd[0], 0.005), (p, sd)
    assert abs(p[1] - E) < 0.05, (p, sd)
    assert abs(p[2] - 0.1) < 0.01, p
    assert rms < 0.004, rms


def test_plan_hits_cup_with_true_physics():
    p, cov, _ = fit([throw(25)], L, H)
    th = plan(0.20, p, L, H, YC)
    assert abs(landing(th, MU, L, H, YC) - 0.20) < 0.01


def test_verification_of_a_new_throw():
    p, cov, _ = fit([throw(25)], L, H)
    th, _, x, y = throw(33, t0=0.3, seed=2)
    m, sd = predict(th, p, cov, L, H, YC)
    obs = observed_landing(x, y, YC)
    assert sd < 0.01 and abs(obs - m) < 0.01, (m, sd, obs)
    p2, _, _ = fit([throw(25), (th, _, x, y)], L, H)
    assert abs(p2[0] - MU) < 0.005, p2


if __name__ == "__main__":
    for f in [test_calibration_recovers_parameters, test_plan_hits_cup_with_true_physics, test_verification_of_a_new_throw]:
        f()
        print("ok", f.__name__)
