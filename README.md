# RealityLoop

An agent that films a simple physical system, builds a calibrated digital twin of it, predicts an outcome,
checks the prediction against the real world and recalibrates when it is wrong.

First system: a ball rolls down a ramp and must land in a cup. The agent picks the ramp angle.

```
video ──► tracking ──► calibration ──► control ──► real throw ──► verification
                           ▲                                          │
                           └──────── error above threshold ◄──────────┘
```

## Status

| Step | State |
| --- | --- |
| Tracking (video → trajectory in metres) | ✅ colour tracking (`track.py`), fallback until SAM 3.1 is wired in |
| Digital twin (ramp, flight, bounces) | ✅ `realityloop.py` |
| Calibration with uncertainties | ✅ |
| Control (ramp angle that hits the cup) | ✅ |
| Verification and recalibration | ✅ |
| Simulation / video overlay | ✅ |
| SAM 3.1, Muse Spark, Muse Voice Transcribe | ❌ not wired in yet |
| Web interface | ❌ command line only |
| Benchmark on real videos | ❌ tests use synthetic videos only |

## Install

Python 3.10+, `pip install -r requirements.txt`, and `ffmpeg` / `ffprobe` on the `PATH`.

## Usage

**1. Film.** Fixed camera on a tripod, facing the plane of motion, level. Bright ball whose colour
appears nowhere else in the frame. A scale reference of known length on the table.

**2. Read three things off one frame** (any image viewer), in pixels:
- `--origin`: the point on the landing surface directly below the bottom end of the ramp;
- `--ref x1,y1,x2,y2`: the two ends of the scale reference, and `--ref-length` its real length in metres;
- `--color`: the ball colour, `#rrggbb`.

**3. Run the loop.**

```sh
# video -> trajectory (t, x, y in metres)
py track.py ref.mp4 --color "#ff8000" --origin 350,440 --ref 100,460,600,460 --ref-length 1.0 -o ref.csv

# calibrate, recommend an angle; the ramp angle of each throw follows the @
py realityloop.py --length 0.6 --height 0.3 --cup 0.2 --cup-height 0.1 ref.csv@25 --sim-out sim.csv

# overlay the fitted simulation on the video (green: observed, red: simulated)
py track.py ref.mp4 --color "#ff8000" --origin 350,440 --ref 100,460,600,460 --ref-length 1.0 --overlay sim.csv -o overlay.mp4
```

Set the ramp to the recommended angle, throw, film, track, then pass every throw, latest last:

```sh
py realityloop.py --length 0.6 --height 0.3 --cup 0.2 --cup-height 0.1 ref.csv@25 throw2.csv@33.9
```

The last throw is predicted from the earlier ones and compared with where it actually landed (`OK` or
`recalage`), then the twin is refitted on all throws and a new angle is recommended.
If the system changed (other surface, other ball), pass only the throws made after the change.

Geometry: `--length` is the distance the ball rolls on the ramp, `--height` the height of the ramp's
bottom end above the landing surface, `--cup` the horizontal distance from the ramp's bottom end to the
cup centre, `--cup-height` the height of the cup rim. The ramp is assumed to pivot about its bottom end.

## Method

**Twin.** Frame: origin on the landing surface below the ramp's bottom end, x towards the cup, y up.
y is the height of the ball centre minus its radius, so y = 0 when the ball rolls on the floor.

- Ramp: a solid sphere rolling without slipping with rolling resistance μ,
  a = 5/7 · g · (sin θ − μ cos θ), from rest.
- Flight: ballistic from the ramp end, no air drag.
- Bounces: the vertical velocity is multiplied by the restitution e; the horizontal velocity is kept.

**Calibration.** Non-linear least squares (`scipy.optimize.least_squares`) on the x and y residuals of every
frame of every throw. Parameters: μ and e (shared), plus one release time per throw, since nobody knows
the exact release frame. Covariance: σ² (JᵀJ)⁺ at the optimum. The overlay error reported is the RMS of the
residuals.

Mass is not fitted: without drag it does not affect the trajectory and cannot be identified from video.

**Control.** Grid search of the ramp angle over 5–60° in 0.05° steps for the landing point at rim height
closest to the cup. Uncertainty on the landing point: 500 samples of μ from its fitted distribution.
Restitution does not affect the first landing, so it only matters for fitting the post-bounce frames.
The tool warns when no angle reaches the cup within `--tol`.

**Verification.** The landing point observed at rim height (linear interpolation between frames) is compared
with the landing point predicted from the earlier throws. Above `--tol` (3 cm by default, roughly a cup
radius) the agent recalibrates.

## Known limits

- The uncertainties assume independent tracking errors from frame to frame, so they are too small on real
  video. A per-throw bootstrap is still to be done.
- No perspective correction: the camera must face the plane of motion.
- RGB colour thresholding is sensitive to shadows, reflections and same-coloured objects. Frames where the
  ball touches the image border are dropped.
- No floor friction after the bounces, no air drag, no slipping on the ramp.
- All tests run on synthetic trajectories and synthetic H.264 videos. Real-world error is not measured yet.

## Tests

```sh
py test_realityloop.py
py test_track.py
```

They check that calibration recovers the true parameters, that the chosen
angle hits the cup within 1 cm, that a new throw is predicted within 1 cm, and that tracking a rendered
H.264 video stays within 3 mm of the truth.
