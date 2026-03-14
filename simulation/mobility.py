"""
5G NR Mobility Models
Implements: Random Waypoint, Constant Velocity, Pedestrian, File-Based
"""
import math
import random


class MobilityModel:
    """Base mobility model"""

    def __init__(self, x, y, model_type='random_waypoint', **kwargs):
        self.x = x
        self.y = y
        self.model_type = model_type
        self.vx = 0
        self.vy = 0
        self.speed = kwargs.get('speed', 3.0)  # m/s
        self.bounds = kwargs.get('bounds', (0, 0, 800, 600))

        # Random waypoint
        self.waypoint_x = x
        self.waypoint_y = y
        self.pause_time = 0
        self.pause_remaining = 0
        self.min_speed = kwargs.get('min_speed', 1.0)
        self.max_speed = kwargs.get('max_speed', 15.0)

        # Path-based
        self.path = kwargs.get('path', [])
        self.path_index = 0

        # Constant velocity
        angle = kwargs.get('angle', random.uniform(0, 2 * math.pi))
        self.vx = self.speed * math.cos(angle)
        self.vy = self.speed * math.sin(angle)

        # ── Pedestrian ──────────────────────────────────────────────────────
        # Realistic pedestrian: slow random-waypoint walk (0.8–1.8 m/s)
        # with short pause bursts to mimic stop-and-go street behaviour.
        self._ped_waypoint_x = x
        self._ped_waypoint_y = y
        self._ped_pause_remaining = 0.0
        self._ped_speed = kwargs.get('ped_speed',
                                     random.uniform(0.8, 1.8))   # m/s

        # ── File-Based ───────────────────────────────────────────────────────
        # Sorted list of dicts: {time_stamp, ue_id, x, y}
        # Only rows whose ue_id matches self._file_ue_id are used.
        self._file_trace   = kwargs.get('file_trace', [])   # pre-parsed rows
        self._file_ue_id   = kwargs.get('file_ue_id', None) # e.g. "UE-1"
        self._file_idx     = 0
        self._file_time    = 0.0   # elapsed sim-time (seconds)

    # ─────────────────────────────────────────────────────────────────────────
    #  Public interface
    # ─────────────────────────────────────────────────────────────────────────

    def update(self, dt=0.1):
        """Update position based on mobility model"""
        if self.model_type == 'random_waypoint':
            self._update_random_waypoint(dt)
        elif self.model_type == 'constant_velocity':
            self._update_constant_velocity(dt)
        elif self.model_type == 'path_based':
            self._update_path_based(dt)
        elif self.model_type == 'pedestrian':
            self._update_pedestrian(dt)
        elif self.model_type == 'file_based':
            self._update_file_based(dt)

    # ─────────────────────────────────────────────────────────────────────────
    #  Existing models (unchanged)
    # ─────────────────────────────────────────────────────────────────────────

    def _update_random_waypoint(self, dt):
        """Random Waypoint Mobility Model"""
        if self.pause_remaining > 0:
            self.pause_remaining -= dt
            return

        dx = self.waypoint_x - self.x
        dy = self.waypoint_y - self.y
        dist = math.sqrt(dx**2 + dy**2)

        if dist < 5:
            self.waypoint_x = random.uniform(self.bounds[0] + 20, self.bounds[2] - 20)
            self.waypoint_y = random.uniform(self.bounds[1] + 20, self.bounds[3] - 20)
            self.speed = random.uniform(self.min_speed, self.max_speed)
            self.pause_remaining = random.uniform(0, 5)
        else:
            self.vx = (dx / dist) * self.speed
            self.vy = (dy / dist) * self.speed
            self.x += self.vx * dt
            self.y += self.vy * dt

    def _update_constant_velocity(self, dt):
        """Constant velocity with boundary reflection"""
        self.x += self.vx * dt
        self.y += self.vy * dt

        if self.x < self.bounds[0] or self.x > self.bounds[2]:
            self.vx = -self.vx
            self.x = max(self.bounds[0], min(self.bounds[2], self.x))
        if self.y < self.bounds[1] or self.y > self.bounds[3]:
            self.vy = -self.vy
            self.y = max(self.bounds[1], min(self.bounds[3], self.y))

    def _update_path_based(self, dt):
        """Path-based mobility following predefined waypoints"""
        if not self.path:
            return

        target = self.path[self.path_index % len(self.path)]
        dx = target[0] - self.x
        dy = target[1] - self.y
        dist = math.sqrt(dx**2 + dy**2)

        if dist < 5:
            self.path_index = (self.path_index + 1) % len(self.path)
        else:
            self.vx = (dx / dist) * self.speed
            self.vy = (dy / dist) * self.speed
            self.x += self.vx * dt
            self.y += self.vy * dt

    # ─────────────────────────────────────────────────────────────────────────
    #  NEW: Pedestrian model
    # ─────────────────────────────────────────────────────────────────────────

    def _update_pedestrian(self, dt):
        """
        Pedestrian Mobility Model
        ─────────────────────────
        Mimics human walking behaviour per 3GPP TR 38.901 §7.6:
          • Speed  : 0.8 – 1.8 m/s (randomly drawn each new waypoint)
          • Pauses : 2 – 8 s at each waypoint (simulate waiting at crossings,
                     looking at a phone, etc.)
          • Short-range waypoints (≤ 150 px) so the path looks natural
          • Heading changes are gentle (no teleporting across canvas)
        """
        if self._ped_pause_remaining > 0:
            self._ped_pause_remaining -= dt
            self.vx = 0.0
            self.vy = 0.0
            return

        dx = self._ped_waypoint_x - self.x
        dy = self._ped_waypoint_y - self.y
        dist = math.sqrt(dx**2 + dy**2)

        if dist < 3:   # arrived at waypoint
            # Pick next waypoint within ≤150 px (short pedestrian hop)
            max_hop = 150
            for _ in range(20):   # try up to 20 candidates
                angle = random.uniform(0, 2 * math.pi)
                hop   = random.uniform(30, max_hop)
                nx    = self.x + hop * math.cos(angle)
                ny    = self.y + hop * math.sin(angle)
                if (self.bounds[0] + 10 <= nx <= self.bounds[2] - 10 and
                        self.bounds[1] + 10 <= ny <= self.bounds[3] - 10):
                    self._ped_waypoint_x = nx
                    self._ped_waypoint_y = ny
                    break
            else:
                # Fallback: aim toward canvas centre
                self._ped_waypoint_x = (self.bounds[0] + self.bounds[2]) / 2
                self._ped_waypoint_y = (self.bounds[1] + self.bounds[3]) / 2

            self._ped_speed = random.uniform(0.8, 1.8)
            self._ped_pause_remaining = random.uniform(2.0, 8.0)
        else:
            self.vx = (dx / dist) * self._ped_speed
            self.vy = (dy / dist) * self._ped_speed
            self.x += self.vx * dt
            self.y += self.vy * dt

    # ─────────────────────────────────────────────────────────────────────────
    #  NEW: File-based model
    # ─────────────────────────────────────────────────────────────────────────

    def _update_file_based(self, dt):
        """
        File-Based Mobility Model
        ─────────────────────────
        Replays a CSV trace: timestamp_s, ue_id, x_coord, y_coord
        • Rows are sorted by timestamp ascending (done on upload).
        • Linear interpolation between consecutive rows for smooth motion.
        • When the trace ends the UE freezes at the last position.
        • If no trace is loaded the UE stays put.
        """
        if not self._file_trace:
            return

        self._file_time += dt

        # Find the two surrounding rows
        rows = self._file_trace
        n    = len(rows)

        # Fast-forward to the correct window
        while (self._file_idx + 1 < n and
               rows[self._file_idx + 1]['t'] <= self._file_time):
            self._file_idx += 1

        idx = self._file_idx

        if idx >= n - 1:
            # End of trace — freeze
            self.x  = rows[-1]['x']
            self.y  = rows[-1]['y']
            self.vx = 0.0
            self.vy = 0.0
            return

        r0 = rows[idx]
        r1 = rows[idx + 1]
        t0, t1 = r0['t'], r1['t']

        if t1 == t0:
            alpha = 1.0
        else:
            alpha = (self._file_time - t0) / (t1 - t0)
            alpha = max(0.0, min(1.0, alpha))

        new_x = r0['x'] + alpha * (r1['x'] - r0['x'])
        new_y = r0['y'] + alpha * (r1['y'] - r0['y'])

        if dt > 0:
            self.vx = (new_x - self.x) / dt
            self.vy = (new_y - self.y) / dt

        self.x = new_x
        self.y = new_y

    # ─────────────────────────────────────────────────────────────────────────
    #  Helpers
    # ─────────────────────────────────────────────────────────────────────────

    def get_velocity(self):
        """Return current velocity magnitude"""
        return math.sqrt(self.vx**2 + self.vy**2)

    def get_position(self):
        return {'x': round(self.x, 2), 'y': round(self.y, 2)}

    def set_mobility(self, model_type, **kwargs):
        """Change mobility model dynamically"""
        self.model_type = model_type
        if 'speed' in kwargs:
            self.speed = kwargs['speed']
        if 'path' in kwargs:
            self.path = kwargs['path']
            self.path_index = 0
        if 'file_trace' in kwargs:
            self._file_trace  = kwargs['file_trace']
            self._file_ue_id  = kwargs.get('file_ue_id', self._file_ue_id)
            self._file_idx    = 0
            self._file_time   = 0.0
