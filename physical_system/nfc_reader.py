"""
NFC Reader
Each reader runs in its own thread, continuously polling for tags
"""

import logging
import time
from threading import Thread, Lock, Event

# Try to import NFC libraries
try:
    import board
    import busio
    from adafruit_pn532.spi import PN532_SPI
    HARDWARE_AVAILABLE = True
except (ImportError, NotImplementedError):
    HARDWARE_AVAILABLE = False
    logging.warning("NFC libraries not available - using simulation mode")


class NFCReaderThread(Thread):
    """
    NFC Reader Producer Thread

    Continuously polls for NFC tags and puts results in queue
    """

    def __init__(self, reader_num, station_id, nfc_queue, simulation=False):
        """
        Initialize NFC reader thread

        reader_num: Reader number (1 or 2)
        station_id: Station ID (1 or 2)
        nfc_queue: Queue to put NFC events into
        simulation: Run without hardware
        """
        # Thread setup
        super().__init__(daemon=True, name=f"NFC{reader_num}")

        self.logger = logging.getLogger(f"NFC{reader_num}")
        self.reader_num = reader_num
        self.station_id = station_id
        self.nfc_queue = nfc_queue
        self.simulation = simulation or not HARDWARE_AVAILABLE

        # Thread control
        self.running = False
        self.stop_event = Event()

        # Hardware control
        self.lock = Lock()
        self.pn532 = None

        # Initialize hardware
        if not self.simulation:
            self._init_hardware()
        else:
            self.logger.info(f"NFC Reader {reader_num} running in SIMULATION mode")

    def _init_hardware(self):
        """Initialize PN532 NFC reader hardware"""
        try:
            # Initialize SPI
            spi = busio.SPI(board.SCK, board.MOSI, board.MISO)

            # Select chip enable based on reader number
            if self.reader_num == 1:
                cs_pin = board.CE0 # Chip Enable 0
            elif self.reader_num == 2:
                cs_pin = board.CE1 # Chip Enable 1
            else:
                raise ValueError("reader_num must be 1 or 2")

            # Initialize PN532
            self.pn532 = PN532_SPI(spi, cs_pin, debug=False)
            self.pn532.SAM_configuration()

            self.logger.info(f"NFC Reader {self.reader_num} initialized on CE{self.reader_num-1}")

        except Exception as e:
            self.logger.error(f"Failed to initialize: {e}")
            self.logger.error("Falling back to simulation mode")
            self.simulation = True

    def run(self):
        """Main thread loop - continuously scans for NFC tags"""
        self.running = True
        self.logger.info(f"NFC Reader {self.reader_num} thread started")

        while self.running and not self.stop_event.is_set():
            try:
                # Blocking NFC read to detect tag and not holding up the other threads
                part_id = self._blocking_read_tag()

                if part_id:
                    # Capture timestamp after successful read
                    t_nfc = time.time()

                    # Create NFC event
                    event = {
                        'timestamp': t_nfc,
                        'station_id': self.station_id,
                        'part_id': part_id,
                        'reader_num': self.reader_num
                    }

                    # Put in queue
                    try:
                        self.nfc_queue.put_nowait(event) # Non-blocking put to avoid blocking producer thread
                        self.logger.info(f"NFC read: Station {self.station_id}, Part {part_id[:8]}...")
                    except:
                        self.logger.warning(f"NFC queue full, dropping read: {part_id[:8]}")

                # Small delay between reads
                time.sleep(0.1)

            except Exception as e:
                self.logger.error(f"Error in NFC scan loop: {e}")
                time.sleep(1)

        self.logger.info(f"NFC Reader {self.reader_num} thread stopped")

    def _blocking_read_tag(self, timeout=1.0):
        """
        Blocking NFC tag read

        timeout: Read timeout in seconds

        Returns: Tag UID as hex string, or None if no tag
        """
        if self.simulation:
            # In simulation, return None (no tag)
            time.sleep(0.5)  # Simulate blocking read
            return None

        with self.lock:
            try:
                # Read passive target (NFC tag)
                uid = self.pn532.read_passive_target(timeout=timeout)

                if uid:
                    # Convert UID bytes to hex string
                    uid_hex = ''.join([f'{b:02x}' for b in uid])
                    return uid_hex

                return None

            except Exception as e:
                self.logger.error(f"Read error: {e}")
                return None

    def stop(self):
        """Stop the NFC reader thread"""
        self.logger.info(f"Stopping NFC Reader {self.reader_num}...")
        self.running = False
        self.stop_event.set()


class Part:
    """
    Represents a part being tracked through the system

    Stores part ID and events
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

    def add_event(self, station_id, activity, timestamp):
        """
        Record an event

        station_id: Station ID (e.g., "S1", "S2")
        activity: Activity type (e.g., "ENTER", "EXIT")
        timestamp: Event timestamp
        """
        event = {
            'timestamp': timestamp,
            'part_id': self.part_id,
            'station_id': station_id,
            'activity': activity
        }
        self.events.append(event)
        self.current_location = station_id

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