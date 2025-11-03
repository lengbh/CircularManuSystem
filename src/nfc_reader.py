"""
NFC Reader
Reads NFC tags for part identification
"""

import logging
import time
from threading import Lock # For preventing function calls at the same time

# Try to import NFC libraries, simulation/hardware mode
try:
    import board
    import busio
    from adafruit_pn532.spi import PN532_SPI
    HARDWARE_AVAILABLE = True
except (ImportError, NotImplementedError):
    HARDWARE_AVAILABLE = False
    logging.warning("NFC libraries not available or not supported - using simulation mode")


class NFCReader:
    """
    Reads NFC tags via PN532 SPI reader

    Two readers:
    Reader 1 (Station 1): CE0
    Reader 2 (Station 2): CE1
    """

    def __init__(self, reader_num, simulation=False):
        """
        Initialize NFC reader

        reader_num: Reader number (1 for Station 1 or 2 for Station 2)

        simulation: Run without hardware
        """
        self.logger = logging.getLogger(f"NFC{reader_num}")
        self.reader_num = reader_num
        self.simulation = simulation or not HARDWARE_AVAILABLE
        self.lock = Lock()
        self.pn532 = None

        if not self.simulation:
            try:
                # Initialize SPI
                spi = busio.SPI(board.SCK, board.MOSI, board.MISO)

                # Select chip enable based on reader number
                if reader_num == 1:
                    cs_pin = board.CE0
                elif reader_num == 2:
                    cs_pin = board.CE1
                else:
                    raise ValueError("reader_num must be 1 or 2")

                # Initialize PN532 NFC reader object
                self.pn532 = PN532_SPI(spi, cs_pin, debug=False)

                # Configure PN532
                self.pn532.SAM_configuration()

                self.logger.info(f"NFC Reader {reader_num} initialized")
            # Error handling for hardware failures so the program can fallback to simulation mode
            except Exception as e:
                self.logger.error(f"Failed to initialize: {e}")
                self.logger.error("Falling back to simulation mode")
                self.simulation = True
        else:
            self.logger.info("Running in SIMULATION mode")

    def read_tag(self, timeout=1.0):
        """
        Read NFC tag

        timeout: Read timeout in seconds
        Returns:
            str: Tag UID as hex string (e.g., "04a1b2c3d4e5f6"),
        or None if no tag

        """
        if self.simulation:
            # In simulation, return None (no tag)
            return None

        with self.lock:
            try:
                # Read tag with 1 second timeout
                uid = self.pn532.read_passive_target(timeout=timeout)

                if uid:
                    # Convert UID bytes to hex string for formatting
                    uid_hex = ''.join([f'{b:02x}' for b in uid])
                    self.logger.debug(f"Tag read: {uid_hex}")
                    return uid_hex

                return None

            except Exception as e:
                self.logger.error(f"Read error: {e}")
                return None

    def wait_for_tag(self, timeout=10):
        """
        Wait for tag to be present

        timeout: Maximum wait time in seconds
        Returns:
            str: Tag UID, or None on timeout
        """
        start = time.time()

        while time.time() - start < timeout:
            uid = self.read_tag(timeout=0.5)
            if uid:
                return uid
            time.sleep(0.1)

        return None


class Part:
    """
    Represents a part being tracked through the system

    Stores part ID and events in format:
    {timestamp, part_id, station_id, activity}
    """

    def __init__(self, part_id):
        """
        Create a tracked part

        part_id: Part ID (from NFC tag or generated)
        """
        self.part_id = part_id
        self.entry_time = time.time()
        self.events = []
        self.current_location = "Entry"

    def add_event(self, station_id, activity):
        """
        Record an event

        station_id: Station ID (e.g., "S1" for Station 1, "S2" for Station 2, "C1" for Corner 1, etc.)

        activity: Activity type (e.g., "ENTER", "EXIT", "PROCESS")
        """
        event = {
            'timestamp': time.time(),
            'part_id': self.part_id,
            'station_id': station_id,
            'activity': activity
        }
        self.events.append(event)
        self.current_location = station_id
    # Some helping functions for tracking and displaying part information
    def time_in_system(self):
        """Get time part has been in system (seconds)"""
        return time.time() - self.entry_time

    def get_short_id(self):
        """Get shortened part ID for display"""
        if len(self.part_id) > 8:
            return self.part_id[:8] + "..."
        return self.part_id

    def __str__(self):
        return f"Part({self.get_short_id()} at {self.current_location})"

    def __repr__(self):
        return self.__str__()