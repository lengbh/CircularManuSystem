"""
Motor Controller
Controls 8 motors via 2 Adafruit Motor HATs
"""

import logging
import time

# Try to import hardware libraries
try:
    from adafruit_motorkit import MotorKit
    HARDWARE_AVAILABLE = True
except (ImportError, NotImplementedError):
    HARDWARE_AVAILABLE = False
    logging.warning("Hardware libraries not found or not supported - using simulation mode")

class MotorController:
    """
    Controls all 8 motors in the system

    Motors:
        HAT #1 (0x60) - Conveyors & Stations:
            motor1 = Motor 1 (Top Conveyor)
            motor2 = Motor 2 (Bottom Conveyor)
            motor3 = Motor 3 (Station 1)
            motor4 = Motor 4 (Station 2)

        HAT #2 (0x61) - Corner Pushers:
            motor1 = Motor 5 (Corner 1)
            motor2 = Motor 6 (Corner 2)
            motor3 = Motor 7 (Corner 3)
            motor4 = Motor 8 (Corner 4)
    """

    def __init__(self, simulation=False):
        """
        Initialize motor controller


        simulation: If True, run without hardware
        """
        self.logger = logging.getLogger("MotorController")
        self.simulation = simulation or not HARDWARE_AVAILABLE

        # Motor names for logging
        self.motor_names = {
            1: "Top Conveyor",
            2: "Bottom Conveyor",
            3: "Station 1",
            4: "Station 2",
            5: "Corner 1 Pusher",
            6: "Corner 2 Pusher",
            7: "Corner 3 Pusher",
            8: "Corner 4 Pusher"
        }
        self.hat1 = None  # Define them as None first
        self.hat2 = None

        if not self.simulation:
            try:
                # Initialize Motor HATs
                self.logger.info("Initializing Motor HAT #1 (0x60)...")
                self.hat1 = MotorKit(address=0x60)

                self.logger.info("Initializing Motor HAT #2 (0x61)...")
                self.hat2 = MotorKit(address=0x61)

                self.logger.info("Motor HATs initialized")

                # Stop all motors on init
                self.stop_all()

            except Exception as e:
                self.logger.error(f"Failed to initialize Motor HATs: {e}")
                self.logger.error("Falling back to simulation mode")
                self.simulation = True
        else:
            self.logger.info("Running in SIMULATION mode")

    def set_speed(self, motor_num, speed):
        """
        Set motor speed

        motor_num: Motor number (1-8)

        speed: Speed from -1.0 to 1.0

        Positive = forward

        Negative = reverse

        0 = stop
        """
        # Clamp speed to valid range
        speed = max(-1.0, min(1.0, speed))

        if self.simulation:
            if speed != 0:
                self.logger.debug(f"[SIM] Motor {motor_num} ({self.motor_names[motor_num]}): {speed:+.2f}")
            return

        try:
            # Route to correct HAT and motor
            if motor_num == 1:
                self.hat1.motor1.throttle = speed
            elif motor_num == 2:
                self.hat1.motor2.throttle = speed
            elif motor_num == 3:
                self.hat1.motor3.throttle = speed
            elif motor_num == 4:
                self.hat1.motor4.throttle = speed
            elif motor_num == 5:
                self.hat2.motor1.throttle = speed
            elif motor_num == 6:
                self.hat2.motor2.throttle = speed
            elif motor_num == 7:
                self.hat2.motor3.throttle = speed
            elif motor_num == 8:
                self.hat2.motor4.throttle = speed
            else:
                self.logger.error(f"Invalid motor number: {motor_num}")
                return

            if speed != 0:
                self.logger.debug(f"Motor {motor_num} ({self.motor_names[motor_num]}): {speed:+.2f}")

        except Exception as e:
            self.logger.error(f"Error setting motor {motor_num}: {e}")

    def stop(self, motor_num):
        """Stop a specific motor"""
        self.set_speed(motor_num, 0)

    def stop_all(self):
        """Emergency stop - all motors to 0"""
        self.logger.info("STOPPING ALL MOTORS")

        for motor_num in range(1, 9):
            self.set_speed(motor_num, 0)

    def start_conveyors(self, speed=0.5):
        """Start main conveyors (motors 1 & 2)"""
        self.set_speed(1, speed)  # Top
        self.set_speed(2, speed)  # Bottom

    def stop_conveyors(self):
        """Stop main conveyors"""
        self.stop(1)
        self.stop(2)

    def cleanup(self):
        """Cleanup on exit"""
        self.logger.info("Cleaning up motors...")
        self.stop_all()