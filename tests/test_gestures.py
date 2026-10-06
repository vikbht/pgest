from pageturner.gestures import ArmToggle, SwipeDetector


def feed(det, xs, dt=0.05, y=0.5, size=0.1):
    out = None
    for i, x in enumerate(xs):
        out = det.update(i * dt, x, y, size) or out
    return out


def test_swipe_left_and_right():
    assert feed(SwipeDetector(), [0.8, 0.7, 0.6, 0.5, 0.4, 0.3]) == "left"
    assert feed(SwipeDetector(), [0.2, 0.3, 0.4, 0.5, 0.6, 0.7]) == "right"


def test_slow_drift_ignored():
    assert feed(SwipeDetector(), [0.5 + 0.005 * i for i in range(40)]) is None


def test_vertical_ignored():
    d, hits = SwipeDetector(), []
    for i in range(6):
        hits.append(d.update(i * 0.05, 0.5 + 0.02 * i, 0.2 + 0.1 * i, 0.1))
    assert not any(hits)


def test_cooldown_swallows_return_stroke():
    d = SwipeDetector()
    assert feed(d, [0.8, 0.7, 0.6, 0.5, 0.4, 0.3]) == "left"
    assert [d.update(0.3 + i * 0.05, 0.3 + 0.1 * i, 0.5, 0.1) for i in range(1, 6)] == [None] * 5


def test_arm_toggle_requires_hold_and_stillness():
    a, flipped = ArmToggle(), False
    for i in range(30):
        flipped |= a.update(i * 0.05, True, 0.5, 0.5, 0.1)
    assert flipped and a.armed
    b = ArmToggle()
    assert not any(b.update(i * 0.05, True, 0.1 + 0.03 * i, 0.5, 0.1) for i in range(30))
