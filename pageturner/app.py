"""Camera loop: hand tracking -> gestures -> arrow-key presses."""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import cv2
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision

from .gestures import ArmToggle, SwipeDetector, hand_size, is_open_palm, palm_center

MODEL = Path(__file__).resolve().parent.parent / "models" / "hand_landmarker.task"


def main() -> None:
    ap = argparse.ArgumentParser(description="Turn pages with hand swipes.")
    ap.add_argument("--camera", type=int, default=0)
    ap.add_argument("--fps", type=int, default=20, help="processing rate cap (lower = less battery)")
    ap.add_argument("--next", choices=["left", "right"], default="left",
                    help="hand-motion direction (as you see it) that means NEXT page; default: swipe left")
    ap.add_argument("--dry-run", action="store_true", help="don't send keys, just print")
    ap.add_argument("--debug", action="store_true", help="print why near-miss swipes were rejected")
    ap.add_argument("--no-preview", action="store_true")
    ap.add_argument("--always-armed", action="store_true", help="skip the open-palm arm step")
    args = ap.parse_args()

    keyboard = None
    if not args.dry_run:
        from pynput.keyboard import Controller
        keyboard = Controller()

    from pynput.keyboard import Key
    next_key, prev_key = (Key.right, Key.left)

    landmarker = vision.HandLandmarker.create_from_options(vision.HandLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=str(MODEL)),
        running_mode=vision.RunningMode.VIDEO, num_hands=1))

    cap = cv2.VideoCapture(args.camera)
    if not cap.isOpened():
        raise SystemExit("Could not open camera (check System Settings > Privacy > Camera).")

    swipe, arm = SwipeDetector(), ArmToggle(armed=args.always_armed)
    flash, flash_until, min_dt = "", 0.0, 1.0 / args.fps
    last = 0.0
    print("Running. Hold an open palm still for 1s to arm/disarm. 'q' in preview window quits.")

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        now = time.monotonic()
        if now - last < min_dt:
            continue
        last = now
        frame = cv2.flip(frame, 1)  # mirror so on-screen motion matches your hand
        rgb = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        res = landmarker.detect_for_video(rgb, int(now * 1000))

        if res.hand_landmarks:
            lm = res.hand_landmarks[0]
            x, y = palm_center(lm)
            size = hand_size(lm)
            if not args.always_armed and arm.update(now, is_open_palm(lm), x, y, size):
                swipe.reset()
                flash, flash_until = ("ARMED" if arm.armed else "DISARMED"), now + 1.0
                print(flash)
            if arm.armed:
                d = swipe.update(now, x, y, size)
                if args.debug and swipe.reject:
                    print(f"  miss dx={swipe.travel:+.2f} {swipe.reject}")
                if d:
                    key, label = (next_key, "NEXT") if d == args.next else (prev_key, "PREV")
                    flash, flash_until = label, now + 0.7
                    print(f"{label}  travel={swipe.travel:+.2f} speed={swipe.speed:.1f}")
                    if keyboard:
                        keyboard.press(key); keyboard.release(key)
            if not args.no_preview:
                h, w = frame.shape[:2]
                for p in lm:
                    cv2.circle(frame, (int(p.x * w), int(p.y * h)), 3, (0, 255, 0), -1)
                cv2.putText(frame, f"travel {swipe.travel:+.2f} (need {swipe.min_travel})", (10, 100),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
                bar = int(arm.progress(now) * 200)
                cv2.rectangle(frame, (10, h - 20), (10 + bar, h - 10), (0, 200, 255), -1)
        else:
            arm.lost()  # keep swipe history: fast motion can blur the hand for a frame or two

        if not args.no_preview:
            status = ("ARMED" if arm.armed else "disarmed (hold open palm)")
            cv2.putText(frame, status, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8,
                        (0, 255, 0) if arm.armed else (0, 0, 255), 2)
            if now < flash_until:
                cv2.putText(frame, flash, (10, 70), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 0), 3)
            cv2.imshow("pageturner", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

    cap.release()
    cv2.destroyAllWindows()
