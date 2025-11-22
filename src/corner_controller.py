"""
Corner Controller Passive Finite State Machine (FSM) Architecture
Event driven state machine for corner transfers
"""

import logging
import time
from enum import Enum
from threading import Timer


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
    Passive Corner Controller FSM

    Responds to events from CEP Consumer
    Handles pusher mechanism and collision avoidance
    """

    def __init__(self, corner_num, motors, collision_mgr, config):
        """
        Initialize corner controller

        corner_num: Corner number (1-4)
        motors: MotorController instance
        collision_mgr: CollisionManager instance
        config: Configuration dictionary
        """
        self.logger = logging.getLogger(f"Corner{corner_num}")
        self.corner_num = corner_num
        self.corner_id = f"C{corner_num}"

        # References to subsystems
        self.motors = motors
        self.collision_mgr = collision_mgr

        # Configuration
        self.config = config
        self.push_speed = config['motors']['corner_speed']
        self.extend_time = config['corners']['extend_time']
        self.retract_time = config['corners']['retract_time']
        self.final_delay = config['corners']['final_approach_delay']
        self.handshake_timeout = config['corners']['handshake_timeout']

        # Motor assignment
        self.motor_num = 4 + corner_num

        # Conveyor management
        self.is_fed_by_main_conveyor = corner_num in [1, 3]
        self.feed_motor_num = 1 if corner_num == 1 else (2 if corner_num == 3 else None)
        self.conveyor_speed = config['motors']['conveyor_speed']

        # Confirmation sensor mapping
        self.confirmation_sensor = {
            1: 'S1_ENTRY',
            2: 'M1_START',
            3: 'S2_ENTRY',
            4: 'M2_START'
        }.get(corner_num)

        # State machine
        self.state = CornerState.IDLE

        # Timers
        self.approach_timer = None
        self.handshake_timer = None

        # Conveyor control
        if self.is_fed_by_main_conveyor:
            self._start_feed_conveyor()

        self.logger.info(f"Corner {corner_num} initialized (passive FSM)")
        self.influx_writer = None

    def _transition_to(self, new_state):
        """
        Handle state transitions with InfluxDB logging
        """
        old_state = self.state
        self.state = new_state

        self.logger.debug(f"State transition: {old_state.value} -> {new_state.value}")

        # Log to InfluxDB
        if self.influx_writer:
            self.influx_writer.write_corner_state(
                corner_id=self.corner_id,
                state=new_state.value
            )

    def process_event(self, event):
        """
        Process an event from CEP Consumer
        Looks at the current state and routes to the correct handler

        Event format:
        {
            'timestamp' ,
            'barrier_id' ,
            'part_id' ,
            'location_type' ,
            'location_id'
        }
        """
        barrier_id = event['barrier_id']
        timestamp = event['timestamp']

        self.logger.debug(f"Event: {barrier_id}, State: {self.state.value}")

        # State machine
        if self.state == CornerState.IDLE:
            self._handle_idle(event)

        elif self.state == CornerState.FINAL_APPROACH:
            self._handle_final_approach(event)

        elif self.state == CornerState.READY_TO_PUSH:
            self._handle_ready_to_push(event)

        elif self.state == CornerState.EXTENDING:
            self._handle_extending(event)

        elif self.state == CornerState.PUSHING:
            self._handle_pushing(event)

        elif self.state == CornerState.WAITING_FOR_CONFIRMATION:
            self._handle_waiting_for_confirmation(event)

        elif self.state == CornerState.RETRACTING:
            self._handle_retracting(event)

    def _handle_idle(self, event):
        """Handle events in IDLE state"""
        barrier_id = event['barrier_id']

        # Only accept corner position sensor
        if barrier_id != f'C{self.corner_num}_POS':
            return

        self.logger.info("Part detected at corner sensor")

        # Check if conveyor is safe to stop
        if self.is_fed_by_main_conveyor:
            if not self.collision_mgr.is_conveyor_safe_to_stop(self.feed_motor_num):
                self.logger.debug("Conveyor busy, waiting...")
                return

            # Stop conveyor
            self._stop_feed_conveyor()

        # Start final approach timer
        self.approach_timer = Timer(self.final_delay, self._final_approach_complete)
        self.approach_timer.start()

        self._transition_to(CornerState.FINAL_APPROACH)

    def _handle_final_approach(self, event):
        """Handle events in FINAL_APPROACH state"""
        # Ignore jitter
        pass

    def _final_approach_complete(self):
        """Called when final approach timer expires"""
        self.logger.info("Final approach complete, part in position")
        self._transition_to(CornerState.READY_TO_PUSH)

        # Try to reserve corner
        self._try_push()

    def _try_push(self):
        """Try to reserve corner and start push"""
        if self.collision_mgr.request_corner(self.corner_num):
            self.logger.info("Corner reserved, starting push")
            self._transition_to(CornerState.EXTENDING)
            self._extend_pusher()
        else:
            # Not safe yet, try again later
            Timer(0.2, self._try_push).start()

    def _handle_ready_to_push(self, event):
        """Handle events in READY_TO_PUSH state"""
        # Waiting for collision clearance
        pass

    def _extend_pusher(self):
        """Extend the pusher"""
        self.logger.info("Extending pusher...")
        self.motors.set_speed(self.motor_num, self.push_speed)
        # we'll get CORNER_EXT event when limit switch is hit

    def _handle_extending(self, event):
        """Handle events in EXTENDING state"""
        barrier_id = event['barrier_id']

        # Wait for extended limit switch
        if barrier_id == f'CORNER{self.corner_num}_EXT': # Extended limit switch hit
            self.motors.stop(self.motor_num)
            self.logger.info("Pusher extended")
            self._transition_to(CornerState.PUSHING)

            # Set handshake wait flag
            self.collision_mgr.set_handshake_wait(self.corner_num)

            # Start handshake timer
            self.handshake_timer = Timer(
                self.handshake_timeout,
                self._handshake_timeout
            )
            self.handshake_timer.start()

            self._transition_to(CornerState.WAITING_FOR_CONFIRMATION)

    def _handle_pushing(self, event):
        """Handle events in PUSHING state"""
        # Transition happens via timer
        pass

    def _handle_waiting_for_confirmation(self, event):
        """Handle events in WAITING_FOR_CONFIRMATION state"""
        barrier_id = event['barrier_id']

        # Check for confirmation sensor
        if barrier_id == self.confirmation_sensor:
            # Handshake received
            if self.handshake_timer:
                self.handshake_timer.cancel()

            self.logger.info("Push confirmed by next sensor")
            self.collision_mgr.clear_handshake_wait(self.corner_num)

            # Start retraction
            self._transition_to(CornerState.RETRACTING)
            self._retract_pusher()

    def _handshake_timeout(self):
        """Called when handshake timer expires (jam scenario)"""
        self.logger.critical(f"JAM DETECTED! Part never arrived at next sensor")
        self.collision_mgr.clear_handshake_wait(self.corner_num)

        # Keep corner locked, don't release
        # Manual intervention required
        self.logger.critical("Corner locked, manual intervention required")

    def _retract_pusher(self):
        """Retract the pusher"""
        self.logger.info("Retracting pusher...")
        self.motors.set_speed(self.motor_num, -self.push_speed)

        # Will get CORNER_RET event when limit switch is hit

    def _handle_retracting(self, event):
        """Handle events in RETRACTING state"""
        barrier_id = event['barrier_id']

        # Wait for retracted limit switch
        if barrier_id == f'CORNER{self.corner_num}_RET':
            self.motors.stop(self.motor_num)
            self.logger.info("Pusher retracted")

            # Release corner
            self.collision_mgr.release_corner(self.corner_num)

            # Restart conveyor
            self._start_feed_conveyor()

            # Return to IDLE
            self._transition_to(CornerState.IDLE)
            self.logger.info("Corner ready for next part")

    def _start_feed_conveyor(self):
        """Start the main conveyor that feeds this corner"""
        if self.is_fed_by_main_conveyor:
            self.logger.debug(f"Starting conveyor M{self.feed_motor_num}")
            self.motors.set_speed(self.feed_motor_num, self.conveyor_speed)

    def _stop_feed_conveyor(self):
        """Stop the main conveyor that feeds this corner"""
        if self.is_fed_by_main_conveyor:
            self.logger.debug(f"Stopping conveyor M{self.feed_motor_num}")
            self.motors.stop(self.feed_motor_num)

    def stop(self):
        """Stop the corner controller"""
        # Cancel any active timers
        if self.approach_timer and self.approach_timer.is_alive():
            self.approach_timer.cancel()
        if self.handshake_timer and self.handshake_timer.is_alive():
            self.handshake_timer.cancel()

        # Stop motor
        self.motors.stop(self.motor_num)

        self.logger.info(f"Corner {self.corner_num} stopped")

    def get_status(self):
        """Get current corner status"""
        return {
            'corner_id': self.corner_id,
            'state': self.state.value
        }