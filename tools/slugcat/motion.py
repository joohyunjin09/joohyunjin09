"""A small offline creature rig, not a sprite sheet or an in-browser game.

Design references are documented in docs/slugcat-animation.md. Physics is in
pixels and seconds. A 120 Hz integrator is independent of the SVG sample rate.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from math import cos, exp, hypot, pi, sin, sqrt
import random

from .contributions import Calendar, Day

TAU = 2 * pi
WIDTH, HEIGHT = 896, 238
GRID_X, GRID_Y, STRIDE, CELL = 52.5, 124.0, 15.0, 11.0
FLOOR = 112.0
DURATION = 36.0
PHYSICS_HZ = 120
TAIL_LENGTHS = (6.0, 6.5, 6.5, 6.0, 5.5, 4.5, 3.5)
TAIL_RADII = (7.2, 6.4, 5.3, 4.2, 3.1, 2.1, 1.15, 0.15)
Point = tuple[float, float]


def clamp(x: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, x))


def mix(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def ease(t: float) -> float:
    t = clamp(t)
    return t * t * t * (10 + t * (-15 + 6 * t))


def ease_speed(t: float) -> float:
    t = clamp(t)
    return 30 * t * t * (t - 1) ** 2


@dataclass
class Spring:
    value: float
    velocity: float = 0.0

    def step(self, target: float, dt: float, stiffness: float = 150,
             damping: float = 22, target_velocity: float = 0.0) -> float:
        self.velocity += (stiffness * (target - self.value)
                          - damping * (self.velocity - target_velocity)) * dt
        self.value += self.velocity * dt
        return self.value


@dataclass(frozen=True)
class Beat:
    state: str
    start: float
    duration: float
    x0: float
    x1: float
    facing0: int
    facing1: int


@dataclass(frozen=True)
class Plan:
    beats: tuple[Beat, ...]
    home: float
    interest: Day
    blinks: tuple[float, ...]
    phase: float

    def at(self, time: float) -> tuple[Beat, float]:
        time %= DURATION
        for beat in self.beats:
            if time < beat.start + beat.duration - 1e-9:
                return beat, clamp((time - beat.start) / beat.duration)
        return self.beats[-1], 1.0


def plan_for(calendar: Calendar) -> Plan:
    rng = random.Random(calendar.seed)
    # Choose a real cell in an approachable, high-activity column. Empty accounts
    # still have a quiet scene; no contribution count is invented for animation.
    eligible = [d for d in calendar.days if 22 <= calendar.position(d)[0] <= 38]
    interest = rng.choices(eligible, weights=[1 + sqrt(d.count) * 8 + d.level * 2 for d in eligible])[0]
    home = GRID_X + 8 * STRIDE + CELL / 2
    target = GRID_X + calendar.position(interest)[0] * STRIDE + CELL / 2
    midway = mix(home, target, 0.56)
    landing = target + 34
    beats: list[Beat] = []
    clock = 0.0

    def add(state: str, duration: float, start: float, end: float, f0: int = 1, f1: int = 1) -> None:
        nonlocal clock
        beats.append(Beat(state, clock, duration, start, end, f0, f1))
        clock += duration

    add("Idle", 2.3, home, home)
    add("Walk", (midway - home) / 42, home, midway)
    add("Idle", 0.9, midway, midway)
    add("Walk", (target - midway) / 42, midway, target)
    add("Inspect", 2.3, target, target)
    add("Crouch", 0.28, target, target)
    add("Hop", 0.72, target, landing)
    add("Land", 0.5, landing, landing)
    add("Idle", 0.7, landing, landing)
    add("Turn", 0.85, landing, landing, 1, -1)
    add("Walk", (landing - home) / 43, landing, home, -1, -1)
    add("Inspect", 1.5, home, home, -1, -1)
    add("Turn", 0.85, home, home, -1, 1)
    add("Idle", DURATION - clock, home, home)
    if beats[-1].duration < 2:
        raise ValueError("Route has insufficient settling time")
    blinks = []
    stamp = 1.15
    while stamp < DURATION - 0.8:
        blinks.append(stamp)
        if rng.random() < 0.22:
            blinks.append(stamp + 0.31)
        stamp += rng.uniform(2.6, 5.0)
    return Plan(tuple(beats), home, interest, tuple(blinks), rng.random() * TAU)


@dataclass
class Foot:
    x: float
    y: float = 0.0
    start_x: float = 0.0
    goal: float = 0.0
    elapsed: float = 1.0
    duration: float = 0.22

    @property
    def swinging(self) -> bool:
        return self.elapsed < self.duration

    def lift(self, goal: float, duration: float) -> None:
        self.start_x, self.goal, self.elapsed = self.x, goal, 0.0
        self.duration = duration

    def step(self, dt: float) -> None:
        if self.swinging:
            self.elapsed = min(self.duration, self.elapsed + dt)
            q = self.elapsed / self.duration
            self.x = mix(self.start_x, self.goal, ease(q))
            self.y = -5.0 * sin(pi * q) ** 2
        else:
            self.y = 0.0


def knee(hip: Point, foot: Point, facing: float) -> Point:
    dx, dy = foot[0] - hip[0], foot[1] - hip[1]
    distance = max(0.01, hypot(dx, dy))
    # Equal 15 px bones: choose the forward-bending solution. Feet remain actual
    # world-space contacts, rather than sliding backwards inside a walk sprite.
    reach = min(29.9, distance)
    bend = sqrt(max(0.0, 15 ** 2 - (reach / 2) ** 2)) * 0.66
    direction = 1 if facing >= 0 else -1
    return ((hip[0] + foot[0]) / 2 + dy / distance * bend * direction,
            (hip[1] + foot[1]) / 2 - dx / distance * bend * direction)


@dataclass(frozen=True)
class Pose:
    time: float
    state: str
    root: Point
    hips: Point
    chest: Point
    head: Point
    angle: float
    facing: float
    gaze: Point
    blink: float
    feet: tuple[Point, Point]
    knees: tuple[Point, Point]
    hands: tuple[Point, Point]
    elbows: tuple[Point, Point]
    tail: tuple[Point, ...]
    breath: float
    compression: float
    elevation: float
    attention: float
    planted: tuple[bool, bool]


class Creature:
    def __init__(self, plan: Plan):
        self.plan = plan
        self.root = Spring(plan.home)
        self.direction = Spring(1)
        self.face = Spring(0.65)
        self.look_y = Spring(0)
        self.hip_x, self.hip_y = Spring(-0.7), Spring(-13)
        self.chest_x, self.chest_y = Spring(3), Spring(-30)
        self.head_x, self.head_y = Spring(3), Spring(-42)
        self.head_angle = Spring(0)
        self.compression = Spring(0)
        self.walk_weight = Spring(0)
        self.hand_x = [Spring(-3), Spring(6)]
        self.hand_y = [Spring(-14), Spring(-13)]
        self.feet = [Foot(plan.home - 5), Foot(plan.home + 5)]
        self.next_foot = 0
        self.height = self.vertical_speed = 0.0
        self.previous_state = "Idle"
        self.tail = []
        length = 0.0
        for segment in TAIL_LENGTHS:
            length += segment
            self.tail.append([plan.home - length, -12 + length * 0.2])
        self.tail_velocity = [[0.0, 0.0] for _ in TAIL_LENGTHS]

    def step(self, time: float, dt: float) -> Pose:
        t = time % DURATION
        beat, q = self.plan.at(t)
        state = beat.state
        target_x = mix(beat.x0, beat.x1, ease(q))
        target_v = (beat.x1 - beat.x0) * ease_speed(q) / beat.duration
        previous_v = self.root.velocity
        x = self.root.step(target_x, dt, 130, 23, target_v)
        velocity = self.root.velocity
        acceleration = (velocity - previous_v) / dt
        weight = self.walk_weight.step(clamp(abs(velocity) / 36), dt, 100, 20)
        if state == "Turn":
            face_target = mix(beat.facing0, beat.facing1, ease(q / 0.55))
            body_target = mix(beat.facing0, beat.facing1, ease((q - 0.18) / 0.82))
        else:
            body_target = float(beat.facing1)
            face_target = body_target * (0.86 if state == "Walk" else 0.52)
        if state == "Idle":
            face_target += 0.30 * sin(TAU * 3 * t / DURATION + self.plan.phase)
        facing = self.direction.step(body_target, dt, 105, 20)
        face = self.face.step(face_target, dt, 160, 22)
        look_y = self.look_y.step(0.95 if state == "Inspect" else
                                 -0.18 + 0.15 * sin(TAU * 2 * t / DURATION), dt, 100, 19)

        if state == "Hop" and self.previous_state != "Hop":
            self.vertical_speed = -420 * beat.duration / 2
        landed = False
        if self.vertical_speed < 0 or self.height < 0:
            self.height += self.vertical_speed * dt + 0.5 * 420 * dt * dt
            self.vertical_speed += 420 * dt
            if self.height >= 0:
                self.height, self.vertical_speed = 0.0, 0.0
                self.compression.velocity += 48
                landed = True
        airborne = self.height < -0.01
        compress_target = 4.4 if state == "Crouch" else -1.0 if airborne else 0.0
        compression = self.compression.step(compress_target, dt, 175, 17)
        breath = sin(TAU * 11 * t / DURATION + 0.5)
        gait = TAU * (x - self.plan.home) / 27.0
        hip = (self.hip_x.step(-0.7 * facing - sin(gait) * 0.45 * weight, dt),
               self.hip_y.step(-13 + sin(gait * 2) * 1.65 * weight - breath * 0.28 + compression, dt))
        chest = (self.chest_x.step(2.8 * facing + velocity * 0.055 - acceleration * 0.009, dt, 140, 19),
                 self.chest_y.step(-30 + cos(gait * 2 + 0.7) * 1.10 * weight
                                   - breath * 0.65 + compression * 0.66, dt, 140, 19))
        head = (self.head_x.step(chest[0] + face * 1.8, dt, 155, 18),
                self.head_y.step(chest[1] - 12.2 + look_y * 1.1, dt, 155, 18))
        angle = self.head_angle.step(face * (look_y * 8 - 1.5)
                                    + velocity * 0.035 + sin(TAU * 7 * t / DURATION) * 0.6,
                                    dt, 125, 18)
        blink = 1.0
        for stamp in self.plan.blinks:
            elapsed = t - stamp
            if 0 <= elapsed <= 0.20:
                # Fast close, slower reopen; no one-frame visibility toggle.
                blink = min(blink, max(0.055, 1 - sin(pi * (elapsed / 0.20)) ** 2))

        if airborne:
            for side, foot in enumerate(self.feet):
                foot.elapsed = foot.duration
                blend = 1 - exp(-25 * dt)
                foot.x = mix(foot.x, x + (-6 if side == 0 else 6), blend)
                foot.y = mix(foot.y, self.height - 1.8, blend)
        else:
            if landed:
                for side, foot in enumerate(self.feet):
                    foot.x, foot.y = x + (-6 if side == 0 else 6), 0.0
                    foot.elapsed = foot.duration
            for foot in self.feet:
                foot.step(dt)
            if not any(foot.swinging for foot in self.feet):
                direction = 1 if velocity >= 0 else -1
                if abs(velocity) > 5:
                    behind = [(x - foot.x) * direction for foot in self.feet]
                    side = max(range(2), key=lambda i: behind[i])
                    if behind[side] > 9:
                        self.feet[side].lift(x + direction * (10 + abs(velocity) * 0.12), 0.22)
                        self.next_foot = 1 - side
                elif abs(velocity) < 0.7:
                    # Replant, rather than teleport, to the same relaxed stance.
                    for side in (self.next_foot, 1 - self.next_foot):
                        goal = x + (-5 if side == 0 else 5)
                        if abs(self.feet[side].x - goal) > 0.35:
                            self.feet[side].lift(goal, 0.30)
                            self.next_foot = 1 - side
                            break
        feet = tuple((foot.x - x, foot.y - self.height) for foot in self.feet)
        knees = tuple(knee((hip[0] + side * 3 - 1.5, hip[1] + 2), feet[side], facing) for side in range(2))
        hands, elbows = [], []
        for side in range(2):
            sign = -1 if side == 0 else 1
            swing = sin(gait + side * pi) * 3.9 * weight
            reach = sin(pi * q) ** 2 * (1 if side else 0) if state == "Inspect" else 0
            hand = (self.hand_x[side].step(chest[0] + sign * 3.6 + swing + face * reach * 5,
                                           dt, 100, 15),
                    self.hand_y[side].step(chest[1] + 14 - abs(swing) * 0.45 + reach * 3
                                           - (4 if airborne else 0), dt, 100, 15))
            shoulder = (chest[0] + sign * 5, chest[1] + 2)
            elbows.append((mix(shoulder[0], hand[0], 0.6) - facing * 2,
                           mix(shoulder[1], hand[1], 0.54)))
            hands.append(hand)
        root_tail = (x + hip[0] - facing * 2, self.height + hip[1] + 1.5)
        self.step_tail(root_tail, facing, t, dt, airborne)
        tail = (tuple((root_tail[0] - x, root_tail[1] - self.height)),) + tuple(
            (point[0] - x, point[1] - self.height) for point in self.tail)
        attention = sin(pi * q) ** 2 if state == "Inspect" and beat.x0 != self.plan.home else 0.0
        self.previous_state = state
        return Pose(t, state, (x, FLOOR + self.height), hip, chest, head, angle, facing,
                    (face, look_y), blink, feet, knees, tuple(hands), tuple(elbows), tail,
                    breath, compression, -self.height, attention,
                    tuple(not foot.swinging and not airborne for foot in self.feet))

    def step_tail(self, root: Point, facing: float, time: float, dt: float, airborne: bool) -> None:
        previous = [point[:] for point in self.tail]
        distance = 0.0
        for i, point in enumerate(self.tail):
            distance += TAIL_LENGTHS[i]
            curl = sin(TAU * 5 * time / DURATION - i * 0.43) * (i / 6) ** 2
            target_x = root[0] - facing * distance * 0.93
            target_y = root[1] + distance * 0.18 - curl * 1.3
            strength = 24 - i * 2.0
            velocity = self.tail_velocity[i]
            velocity[0] += (target_x - point[0]) * strength * dt
            velocity[1] += ((target_y - point[1]) * strength + (30 if airborne else 58)) * dt
            drag = exp(-(3.0 if airborne else 4.8) * dt)
            point[0] += velocity[0] * drag * dt
            point[1] += velocity[1] * drag * dt
        # Position-based distance constraints plus floor contact. The tail is
        # solved in WORLD space: changing facing never mirrors the chain.
        for _ in range(9):
            for i, point in enumerate(self.tail):
                anchor = root if i == 0 else self.tail[i - 1]
                dx, dy = point[0] - anchor[0], point[1] - anchor[1]
                length = max(0.001, hypot(dx, dy))
                error = (length - TAIL_LENGTHS[i]) / length
                weight = 1.0 if i == 0 else 0.5
                point[0] -= dx * error * weight
                point[1] -= dy * error * weight
                if i:
                    anchor[0] += dx * error * 0.5
                    anchor[1] += dy * error * 0.5
                point[1] = min(point[1], -TAIL_RADII[i + 1])
        for i, point in enumerate(self.tail):
            for axis in range(2):
                self.tail_velocity[i][axis] = clamp((point[axis] - previous[i][axis]) / dt, -260, 260)
            if point[1] >= -TAIL_RADII[i + 1] - 0.01:
                self.tail_velocity[i][0] *= exp(-5 * dt)
                self.tail_velocity[i][1] = min(0.0, self.tail_velocity[i][1])


def pose_vector(pose: Pose) -> tuple[float, ...]:
    points = (pose.root, pose.hips, pose.chest, pose.head, pose.gaze,
              *pose.feet, *pose.knees, *pose.hands, *pose.elbows, *pose.tail)
    return tuple(value for point in points for value in point) + (
        pose.angle, pose.facing, pose.blink, pose.breath, pose.compression, pose.attention)


@dataclass(frozen=True)
class Animation:
    plan: Plan
    frames: tuple[Pose, ...]
    fps: int
    seam_error: float
    warmup_cycles: int


def simulate(calendar: Calendar, fps: int = 24) -> Animation:
    if fps not in {12, 20, 24, 30, 40, 60}:
        raise ValueError("FPS must be one of 12, 20, 24, 30, 40 or 60 (divisors of 120)")
    plan = plan_for(calendar)
    creature = Creature(plan)
    dt = 1 / PHYSICS_HZ
    ticks = round(DURATION * PHYSICS_HZ)
    stride = PHYSICS_HZ // fps
    # Warm up complete closed cycles until physical state has actually settled.
    # We do not conceal a bad seam with a cross-fade or a teleport.
    for cycle in range(6):
        frames = []
        for tick in range(ticks):
            pose = creature.step(tick * dt, dt)
            if tick % stride == 0:
                frames.append(pose)
        # One more tick is the next cycle's first sample; save state, do not
        # integrate it twice on the next pass.
        end = copy.deepcopy(creature).step(0.0, dt)
        error = max(abs(a - b) for a, b in zip(pose_vector(frames[0]), pose_vector(end)))
        if cycle >= 2 and error < 0.08:
            # Exact repeated SVG endpoint, after testing the unsnapped solution.
            frames.append(frames[0])
            return Animation(plan, tuple(frames), fps, error, cycle)
    raise RuntimeError(f"Animation did not converge to a seamless cycle ({error:.3f} px)")
