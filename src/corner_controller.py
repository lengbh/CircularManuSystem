"""
Corner Controller
Manages corner transfers with pusher mechanism
"""

import logging
import time
from enum import Enum  # For defining corner states as a list of named constants
from threading import Thread, Event


class CornerState(Enum):
    """Corner states"""
    IDLE = "idle"
    FINAL_APPROACH = "final_approach"
    READY_TO_PUSH = "ready_to_push"
    EXTENDING = "extending"
    PUSHING = "pushing"
    WAITING_FOR_CONFIRMATION = "waiting_for_confirmation"
    RETRACTING = "retracting"


class CornerController:
    """
    Controls a single corner transfer

    State machine:
    IDLE to FINAL_APPROACH to READY_TO_PUSH to EXTENDING to PUSHING
    to WAITING_FOR_CONFIRMATION to RETRACTING back to IDLE
    """

    def __init__(self, corner_num, motors, sensors, collision_mgr, config):
        """
        Initialize corner controller
        """
        self.logger = logging.getLogger(f"Corner{corner_num}")
        self.corner_num = corner_num
        self.corner_id = f"C{corner_num}"

        # References to subsystems
        self.motors = motors
        self.sensors = sensors
        self.collision_mgr = collision_mgr

        # Load settings from config
        self.config = config
        self.push_speed = config['motors']['corner_speed']
        self.extend_time = config['corners']['extend_time']
        self.retract_time = config['corners']['retract_time']
        self.final_delay = config['corners']['final_approach_delay']
        self.handshake_timeout = config['corners']['handshake_timeout']

        # Circular Flow: C1 is fed by M1, C3 is fed by M2 , C2 and C4 are fed by the stations
        self.is_fed_by_main_conveyor = self.corner_num in [1, 3]
        self.feed_motor_num = 1 if self.corner_num == 1 else (2 if self.corner_num == 3 else None)
        self.conveyor_speed = config['motors']['conveyor_speed']

        # Defines the "confirmation" sensor for each corner's push
        # (e.g. C1 pushes to S1, so it waits for the S1_ENTRY sensor)
        self.confirmation_sensor = {
            1: ('station', 1),  # 1 = Station 1
            2: ('main_conveyor', 1),  # 1 = M1
            3: ('station', 2),  # 2 = Station 2
            4: ('main_conveyor', 2)  # 2 = M2
        }.get(self.corner_num)

        # Assign motor number (Motors 5-8 for Corners 1-4)
        self.motor_num = 4 + corner_num

        # State machine
        self.state = CornerState.IDLE

        # Thread control
        self.running = False
        self.stop_event = Event()
        self.thread = None

        self.logger.info(f"Corner {corner_num} initialized")

    def _stop_feed_conveyor(self):
        """Stops the main conveyor (M1/M2) that feeds this corner, if applicable."""
        if self.is_fed_by_main_conveyor:
            self.logger.info(f"Stopping main conveyor (Motor {self.feed_motor_num})")
            self.motors.stop(self.feed_motor_num)

    def _start_feed_conveyor(self):
        """Starts the main conveyor (M1/M2) that feeds this corner, if applicable."""
        if self.is_fed_by_main_conveyor:
            self.logger.info(f"Restarting main conveyor (Motor {self.feed_motor_num})")
            self.motors.set_speed(self.feed_motor_num, self.conveyor_speed)

    def start(self):
        """Start corner control thread"""
        # Check if already running
        if self.running:
            self.logger.warning(f"Corner {self.corner_num} already running")
            return

        if self.state != CornerState.IDLE:
            self.logger.error(f"Cannot start corner {self.corner_num} - not in IDLE state (current: {self.state})")
            return

        # Start the feed conveyor for corners C1 and C3
        if self.is_fed_by_main_conveyor:
            self._start_feed_conveyor()

        self.running = True
        self.stop_event.clear()
        self.thread = Thread(target=self._run, daemon=True)
        self.thread.start()
        self.logger.info(f"Corner {self.corner_num} started")

    def stop(self):
        """Stop corner control thread"""
        if not self.running:
            return

        self.running = False
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=2)
        self.motors.stop(self.motor_num)
        self.logger.info(f"Corner {self.corner_num} stopped")

    def _run(self):
        """Main corner control loop"""
        while self.running and not self.stop_event.is_set():
            try:
                # State machine
                if self.state == CornerState.IDLE:
                    self._state_idle()

                elif self.state == CornerState.FINAL_APPROACH:
                    self._state_final_approach()

                elif self.state == CornerState.READY_TO_PUSH:
                    self._state_ready_to_push()

                elif self.state == CornerState.EXTENDING:
                    self._state_extending()

                elif self.state == CornerState.PUSHING:
                    self._state_pushing()

                elif self.state == CornerState.WAITING_FOR_CONFIRMATION:
                    self._state_waiting_for_confirmation()

                elif self.state == CornerState.RETRACTING:
                    self._state_retracting()

                time.sleep(0.05)  # Small delay

            except Exception as e:
                self.logger.error(f"Error in control loop: {e}", exc_info=True)
                self.motors.stop(self.motor_num)
                time.sleep(1)

    def _state_idle(self):
        """Idle state - waiting for part at the 'corner_pos' sensor"""
        # Check the 'corner_pos' sensor
        if self.sensors.corner_pos(self.corner_num):
            self.logger.info("Part detected at corner sensor.")

            if self.is_fed_by_main_conveyor:
                # Check if the conveyor is busy
                if self.collision_mgr.is_conveyor_safe_to_stop(self.feed_motor_num):
                    # If it's safe, stop the conveyor and proceed.
                    self._stop_feed_conveyor()
                    self.state = CornerState.FINAL_APPROACH
                else:
                    # Conveyor is busy, wait and check again.
                    self.logger.debug("Part detected, but conveyor is busy. Waiting...")
                    time.sleep(0.1)
            else:
                # Not fed by main conveyor (C2, C4), always safe to proceed.
                self.state = CornerState.FINAL_APPROACH

    def _state_final_approach(self):
        """Part is at 'corner_pos' sensor. Wait for a short delay."""

        # Wait for the part to travel the last distance
        self.logger.debug(f"Waiting {self.final_delay}s for final approach...")
        time.sleep(self.final_delay)
        self.logger.info("Final approach complete. Part is in position.")
        self.state = CornerState.READY_TO_PUSH

    def _state_ready_to_push(self):
        """Ready to push - check for collisions"""
        # Atomically check and "reserve" the corner
        if self.collision_mgr.request_corner(self.corner_num):
            self.logger.info("Safe to push, corner reserved.")
            self.state = CornerState.EXTENDING
        else:
            self.logger.debug("Waiting for safe conditions...")
            time.sleep(0.2)  # If not safe wait and try again on the next loop

    def _state_extending(self):
        """Extending pusher"""
        self.logger.info("Extending pusher...")

        # Ensure fully retracted first
        if not self.sensors.corner_retracted(self.corner_num):
            self.logger.warning("Pusher not retracted - forcing retraction")
            if not self._force_retract():
                # Retract failed, stop the thread
                self.logger.critical(f"Corner {self.corner_num} failed to retract. Assuming it is stuck!")
                self._stop_feed_conveyor()  # Stop conveyor to prevent more parts
                self.running = False
                return

        # Extend pusher
        self.motors.set_speed(self.motor_num, self.push_speed)

        # Wait for extended limit switch
        if not self.sensors.wait_for_mcp(f'CORNER{self.corner_num}_EXT', timeout=self.extend_time * 2):
            self.logger.error("Timeout extending pusher")
            self.motors.stop(self.motor_num)
            self.collision_mgr.release_corner(self.corner_num)
            # Stop conveyor on error and go to IDLE
            self._stop_feed_conveyor()
            self.running = False  # Stop the thread
            return

        self.motors.stop(self.motor_num)
        self.logger.info("Pusher extended")
        self.state = CornerState.PUSHING

    def _state_pushing(self):
        """Pusher is extended, part is pushed. Move to wait for confirmation."""
        # Simple check if the part is still on the sensor. If so, print a warning.
        if self.sensors.corner_pos(self.corner_num):
            self.logger.critical(f"JAM DETECTED! Part stuck on sensor at corner {self.corner_num}.")
            self.collision_mgr.clear_handshake_wait(self.corner_num)  # Clear handshake wait
            self.running = False  # Stop the thread
        else:
            # Part has moved off the sensor, now wait for it to arrive at the next one
            self.state = CornerState.WAITING_FOR_CONFIRMATION

    def _state_waiting_for_confirmation(self):
        """Wait for the part to be confirmed at the next sensor after push"""
        self.logger.debug(f"Waiting for push confirmation (timeout={self.handshake_timeout}s)...")
        self.collision_mgr.set_handshake_wait(self.corner_num)  # Set handshake wait

        # Add a safety check
        if not self.confirmation_sensor:
            self.logger.error(f"No confirmation sensor defined for corner {self.corner_num}")
            self.collision_mgr.clear_handshake_wait(self.corner_num)
            self.running = False
            return

        # Determine which sensor to wait for
        sensor_type, sensor_ref_id = self.confirmation_sensor
        push_success = False
        # Wait for confirmation from the appropriate sensor
        if sensor_type == 'station':
            push_success = self.sensors.wait_for_station_entry(sensor_ref_id, timeout=self.handshake_timeout)
        elif sensor_type == 'main_conveyor':
            push_success = self.sensors.wait_for_main_conveyor_start(sensor_ref_id, timeout=self.handshake_timeout)

        if push_success:
            # Confirmation received, proceed to retract
            self.logger.info("Push confirmed by next sensor.")
            self.state = CornerState.RETRACTING
        else:
            # Timeout waiting for confirmation - JAM detected
            self.logger.critical(f"JAM DETECTED! Part never arrived at next sensor for corner {self.corner_num}.")
            self.collision_mgr.clear_handshake_wait(self.corner_num)
            self.running = False  # Stop the thread

    def _state_retracting(self):
        """Retracting pusher"""
        self.logger.info("Retracting pusher...")

        # No longer waiting for the handshake in any case
        self.collision_mgr.clear_handshake_wait(self.corner_num)

        # Check if the retract was successful
        success = self._force_retract()

        if success:
            # Release the lock only on successful retraction
            self.collision_mgr.release_corner(self.corner_num)
            self.state = CornerState.IDLE
            # Restart conveyor to resume operations
            self._start_feed_conveyor()
        else:
            # The corner and adjacent corners are now locked until manual intervention
            self.logger.critical(f"Corner {self.corner_num} failed to retract. Assuming it is stuck!")
            self.logger.critical(f"Corner {self.corner_num} and adjacent corners are locked.")
            self.logger.critical(f"Manual intervention required , use the recovery file to reset the corner states.")

            # Stop the feed conveyor to prevent more parts from arriving
            self._stop_feed_conveyor()

            # Stop this thread - no automatic recovery
            self.running = False

    def _force_retract(self):
        """Helper function to retract motor until switch is hit"""
        self.motors.set_speed(self.motor_num, -self.push_speed)

        # Wait for retracted limit switch
        success = self.sensors.wait_for_mcp(f'CORNER{self.corner_num}_RET', timeout=self.retract_time * 2)

        if not success:
            self.logger.error("Timeout retracting pusher")
            self.motors.stop(self.motor_num)  # Stop motor on failure
            return False

        self.motors.stop(self.motor_num)
        self.logger.info("Pusher retracted")
        return True
