"""
Collision Manager
Prevents collisions by tracking part locations
"""

import logging
from threading import Lock  # To ensure that only one thread can access critical sections at a time
import time


class CollisionManager:
    """
    Manages collision prevention at corners

    Tracks which corners are occupied and prevents
    simultaneous transfers that could collide
    """

    def __init__(self):
        """Initialize collision manager"""
        self.logger = logging.getLogger("CollisionMgr")
        self.lock = Lock()

        # Track corner states dictionary
        self.corners_occupied = {
            1: False,
            2: False,
            3: False,
            4: False
        }

        # Track when corner was last used
        self.corner_last_used = {
            1: 0,
            2: 0,
            3: 0,
            4: 0
        }

        # Track which corners are waiting for a handshake
        self.corners_waiting_handshake = {
            1: False,
            2: False,
            3: False,
            4: False
        }

        # Minimum time between uses (seconds)
        self.min_interval = 2.0

        self.logger.info("Collision Manager initialized")

    def request_corner(self, corner_num):
        """
        Atomically check if a corner is safe and reserve it, to prevent race conditions.

        corner_num: Corner number (1-4)

        """
        with self.lock:
            # Check if this corner is already occupied
            if self.corners_occupied[corner_num]:
                return False

            # Check if enough time has passed since last use
            time_since = time.time() - self.corner_last_used[corner_num]
            if time_since < self.min_interval:
                return False

            # Check adjacent corners for occupation
            adjacent = self._get_adjacent_corners(corner_num)
            for adj in adjacent:
                if self.corners_occupied[adj]:
                    return False

            # If all checks passed, reserve the corner
            self.corners_occupied[corner_num] = True
            self.logger.debug(f"Corner {corner_num} reserved")
            return True

    def release_corner(self, corner_num):
        """
        Release a corner after use

        """
        with self.lock:
            self.corners_occupied[corner_num] = False
            self.corner_last_used[corner_num] = time.time()
            self.logger.debug(f"Corner {corner_num} released")

    def _get_adjacent_corners(self, corner_num):
        """
        Get adjacent corners

        Returns:
            list: Adjacent corner numbers
        """
        adjacency = {
            1: [2, 4],
            2: [1, 3],
            3: [2, 4],
            4: [1, 3]
        }
        return adjacency[corner_num]

    def get_status(self):
        """
        Get collision manager status

        Returns:
            dict: Status information
        """
        with self.lock:
            return {
                'corners_occupied': self.corners_occupied.copy(),
                'corner_last_used': self.corner_last_used.copy()
            }

    def set_handshake_wait(self, corner_num):
        """Flag that a corner is waiting for a part"""
        with self.lock:
            self.corners_waiting_handshake[corner_num] = True
            self.logger.debug(f"Corner {corner_num} is now WAITING for handshake.")

    def clear_handshake_wait(self, corner_num):
        """Flag that a corner has received its handshake"""
        with self.lock:
            self.corners_waiting_handshake[corner_num] = False
            self.logger.debug(f"Corner {corner_num} is NO LONGER waiting.")

    def is_conveyor_safe_to_stop(self, feed_motor_num):
        """
        Check if a main conveyor is safe to stop.
        Can't consider safe if another corner is waiting for a part from it.
        """
        with self.lock:
            if feed_motor_num == 1:  # Top Conveyor (M1)
                # Check if C2 is waiting for a part
                if self.corners_waiting_handshake[2]:
                    return False
            elif feed_motor_num == 2:  # Bottom Conveyor (M2)
                # Check if C4 is waiting for a part
                if self.corners_waiting_handshake[4]:
                    return False
            # If no one is waiting, it's safe
            return True