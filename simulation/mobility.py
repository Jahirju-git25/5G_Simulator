"""5G NR Mobility Models"""
import math
import random


class MobilityModel:

    def __init__(self, x, y, model_type='none', **kwargs):
        self.x          = x
        self.y          = y
        self.model_type = model_type
        self.vx         = 0.0
        self.vy         = 0.0
        self.speed      = kwargs.get('speed', 3.0)
        self.bounds     = kwargs.get('bounds', (0, 0, 800, 600))

        # random waypoint
        self.waypoint_x       = x
        self.waypoint_y       = y
        self.pause_time       = 0
        self.pause_remaining  = 0
        self.min_speed        = kwargs.get('min_speed', 1.0)
        self.max_speed        = kwargs.get('max_speed', 15.0)

        # constant velocity
        angle = kwargs.get('angle', random.uniform(0, 2 * math.pi))
        if model_type == 'constant_velocity':
            self.vx = self.speed * math.cos(angle)
            self.vy = self.speed * math.sin(angle)

        # random walk
        self._rw_dir_timer    = 0.0
        self._rw_dir_interval = kwargs.get('rw_dir_interval', 1.0)
        self._rw_angle        = random.uniform(0, 2 * math.pi)

        # path based
        self.path       = kwargs.get('path', [])
        self.path_index = 0

        # pedestrian
        self._ped_waypoint_x       = x
        self._ped_waypoint_y       = y
        self._ped_pause_remaining  = 0.0
        self._ped_speed            = kwargs.get('ped_speed', random.uniform(0.8, 1.8))

        # ── file-based ──────────────────────────────────────────────────
        # Traces advance at 1-second intervals (not 0.1 s) so UEs dwell
        # at each waypoint for a full second before snapping to the next.
        self._file_trace   = kwargs.get('file_trace', [])
        self._file_ue_id   = kwargs.get('file_ue_id', None)
        self._file_idx     = 0
        self._file_time    = 0.0      # simulation time accumulator (seconds)
        self._file_dt_accum = 0.0    # sub-second accumulator for 1-s stepping

    # ── public API ────────────────────────────────────────────────────────

    def update(self, dt=0.1):
        if   self.model_type == 'none':
            self.vx = 0.0; self.vy = 0.0
        elif self.model_type == 'random_walk':
            self._update_random_walk(dt)
        elif self.model_type == 'random_waypoint':
            self._update_random_waypoint(dt)
        elif self.model_type == 'constant_velocity':
            self._update_constant_velocity(dt)
        elif self.model_type == 'path_based':
            self._update_path_based(dt)
        elif self.model_type == 'pedestrian':
            self._update_pedestrian(dt)
        elif self.model_type == 'file_based':
            self._update_file_based(dt)

    def get_velocity(self):
        return math.sqrt(self.vx**2 + self.vy**2)

    def get_position(self):
        return {'x': round(self.x, 2), 'y': round(self.y, 2)}

    def set_mobility(self, model_type, **kwargs):
        self.model_type = model_type
        if 'speed' in kwargs:
            self.speed = kwargs['speed']
        if 'path' in kwargs:
            self.path = kwargs['path']
            self.path_index = 0
        if 'file_trace' in kwargs:
            self._file_trace    = kwargs['file_trace']
            self._file_ue_id    = kwargs.get('file_ue_id', self._file_ue_id)
            self._file_idx      = 0
            self._file_time     = 0.0
            self._file_dt_accum = 0.0

    # ── mobility implementations ──────────────────────────────────────────

    def _update_random_walk(self, dt):
        self._rw_dir_timer += dt
        if self._rw_dir_timer >= self._rw_dir_interval:
            self._rw_dir_timer = 0.0
            self._rw_angle = random.uniform(0, 2 * math.pi)
        self.vx = self.speed * math.cos(self._rw_angle)
        self.vy = self.speed * math.sin(self._rw_angle)
        nx = self.x + self.vx * dt
        ny = self.y + self.vy * dt
        if nx < self.bounds[0] + 5 or nx > self.bounds[2] - 5:
            self._rw_angle = math.pi - self._rw_angle
            nx = max(self.bounds[0]+5, min(self.bounds[2]-5, nx))
        if ny < self.bounds[1] + 5 or ny > self.bounds[3] - 5:
            self._rw_angle = -self._rw_angle
            ny = max(self.bounds[1]+5, min(self.bounds[3]-5, ny))
        self.x = nx; self.y = ny

    def _update_random_waypoint(self, dt):
        if self.pause_remaining > 0:
            self.pause_remaining -= dt
            self.vx = 0.0; self.vy = 0.0
            return
        dx = self.waypoint_x - self.x
        dy = self.waypoint_y - self.y
        dist = math.sqrt(dx**2 + dy**2)
        if dist < 5:
            self.waypoint_x = random.uniform(self.bounds[0]+20, self.bounds[2]-20)
            self.waypoint_y = random.uniform(self.bounds[1]+20, self.bounds[3]-20)
            self.speed      = random.uniform(self.min_speed, self.max_speed)
            self.pause_remaining = random.uniform(0, self.pause_time)
        else:
            self.vx = (dx / dist) * self.speed
            self.vy = (dy / dist) * self.speed
            self.x += self.vx * dt
            self.y += self.vy * dt

    def _update_constant_velocity(self, dt):
        nx = self.x + self.vx * dt
        ny = self.y + self.vy * dt
        if nx < self.bounds[0]+5 or nx > self.bounds[2]-5:
            self.vx = -self.vx
            nx = max(self.bounds[0]+5, min(self.bounds[2]-5, nx))
        if ny < self.bounds[1]+5 or ny > self.bounds[3]-5:
            self.vy = -self.vy
            ny = max(self.bounds[1]+5, min(self.bounds[3]-5, ny))
        self.x = nx; self.y = ny

    def _update_path_based(self, dt):
        if not self.path:
            return
        if self.path_index >= len(self.path):
            self.path_index = 0
        target = self.path[self.path_index]
        dx = target['x'] - self.x
        dy = target['y'] - self.y
        dist = math.sqrt(dx**2 + dy**2)
        if dist < 5:
            self.path_index = (self.path_index + 1) % len(self.path)
        else:
            self.vx = (dx / dist) * self.speed
            self.vy = (dy / dist) * self.speed
            self.x += self.vx * dt
            self.y += self.vy * dt

    def _update_pedestrian(self, dt):
        if self._ped_pause_remaining > 0:
            self._ped_pause_remaining -= dt
            self.vx = 0.0; self.vy = 0.0
            return
        dx = self._ped_waypoint_x - self.x
        dy = self._ped_waypoint_y - self.y
        dist = math.sqrt(dx**2 + dy**2)
        if dist < 3:
            for _ in range(20):
                angle = random.uniform(0, 2 * math.pi)
                hop   = random.uniform(30, 150)
                nx    = self.x + hop * math.cos(angle)
                ny    = self.y + hop * math.sin(angle)
                if (self.bounds[0]+10 <= nx <= self.bounds[2]-10 and
                        self.bounds[1]+10 <= ny <= self.bounds[3]-10):
                    self._ped_waypoint_x = nx
                    self._ped_waypoint_y = ny
                    break
            else:
                self._ped_waypoint_x = (self.bounds[0]+self.bounds[2]) / 2
                self._ped_waypoint_y = (self.bounds[1]+self.bounds[3]) / 2
            self._ped_speed           = random.uniform(0.8, 1.8)
            self._ped_pause_remaining = random.uniform(2.0, 8.0)
        else:
            self.vx = (dx / dist) * self._ped_speed
            self.vy = (dy / dist) * self._ped_speed
            self.x += self.vx * dt
            self.y += self.vy * dt

    def _update_file_based(self, dt):
        """
        Advances through the CSV trace at 1-second intervals.
        The UE holds each waypoint position for exactly 1 real second,
        then snaps to the next row — no interpolation.
        Previously used 0.1 s steps which caused jitter on sparse traces.
        """
        if not self._file_trace:
            return

        self._file_dt_accum += dt

        # Advance index once per 1-second interval.
        # Use 0.9999 threshold to handle float accumulation imprecision
        # (10 × 0.1 s can land at 0.9999… in IEEE 754).
        if self._file_dt_accum >= 0.9999:
            self._file_dt_accum = max(0.0, self._file_dt_accum - 1.0)
            self._file_idx = min(self._file_idx + 1,
                                 len(self._file_trace) - 1)

        row   = self._file_trace[self._file_idx]
        new_x = row['x']
        new_y = row['y']

        if dt > 0:
            self.vx = (new_x - self.x) / dt
            self.vy = (new_y - self.y) / dt
        else:
            self.vx = 0.0; self.vy = 0.0

        self.x = new_x
        self.y = new_y
