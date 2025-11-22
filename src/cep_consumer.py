"""
CEP Consumer (Complex Event Processing and Matching (Fusion))
Fuses sensor events with NFC events using time window matching
"""

import logging
import time
from threading import Thread, Event
import queue


class CEPConsumer(Thread):
    """
    Complex Event Processing Consumer

    Fuses sensor events with NFC events
    using time-window matching to create validated (timestamp,station,part,activity) tuples
    """

    def __init__(self, gpio_queue, mcp_queue, nfc_queue, fsm_map, data_logger,
                 config, simulation=False):
        """
        Initialize CEP Consumer

        gpio_queue: Queue for GPIO sensor events
        mcp_queue: Queue for MCP23017 sensor events
        nfc_queue: Queue for NFC reader events
        fsm_map: Dictionary mapping location to FSM instance
        data_logger: DataLogger instance for logging matched events
        config: System configuration
        simulation: Simulation mode flag
        """
        super().__init__(daemon=True, name="CEPConsumer")

        self.logger = logging.getLogger("CEPConsumer")

        # Input queues
        self.gpio_queue = gpio_queue
        self.mcp_queue = mcp_queue
        self.nfc_queue = nfc_queue

        # FSM mapping
        self.fsm_map = fsm_map

        # Data logging
        self.data_logger = data_logger

        # Configuration and parameters
        self.simulation = simulation
        self.DELTA_T_FUSE = config.get('cep', {}).get('fusion_window', 2.0)  # 2s fusion window
        self.DELTA_T_EXPIRY = config.get('cep', {}).get('expiry_timeout', 5.0)  # 5s expiry

        # Pending event lists (for fusion)
        self.pending_gpio_events = []  # List of GPIO/MCP sensor events
        self.pending_nfc_events = []   # List of NFC events

        # Thread control
        self.running = False
        self.stop_event = Event()

        # Statistics
        self.stats = {
            'fused_events': 0,
            'orphaned_gpio': 0,
            'ghost_nfc': 0,
            'total_gpio': 0,
            'total_nfc': 0
        }

        self.logger.info(f"CEP Consumer initialized (fusion={self.DELTA_T_FUSE}s, expiry={self.DELTA_T_EXPIRY}s)")
        self.influx_writer = None

    def run(self):
        """Main CEP loop for consuming, fusing, expiring, and delivering events"""
        self.running = True
        self.logger.info("CEP Consumer started")

        while self.running and not self.stop_event.is_set():
            try:
                # Step 1: Consume events from queues
                self._consume_events()

                # Step 2: Try to fuse events
                self._fuse_events()

                # Step 3: Expire old events
                self._expire_events()

                # Small sleep to prevent CPU spinning
                time.sleep(0.01)  # 10ms loop

            except Exception as e:
                self.logger.error(f"Error in CEP loop: {e}", exc_info=True)
                time.sleep(0.1)

        self.logger.info("CEP Consumer stopped")
        self._print_statistics()

    def _consume_events(self):
        """Consume events from all queues"""
        # Consume GPIO events
        try:
            while True:
                # Get event without blocking
                event = self.gpio_queue.get_nowait()
                # Add to pending GPIO events
                self.pending_gpio_events.append(event)
                # Update statistics
                self.stats['total_gpio'] += 1
                self.logger.debug(f"Consumed GPIO: {event['barrier_id']}")
        except queue.Empty:
            pass

        # Consume MCP events
        try:
            while True:
                event = self.mcp_queue.get_nowait()
                self.pending_gpio_events.append(event)  # Treat MCP same as GPIO
                self.stats['total_gpio'] += 1
                self.logger.debug(f"Consumed MCP: {event['barrier_id']}")
        except queue.Empty:
            pass

        # Consume NFC events
        try:
            while True:
                event = self.nfc_queue.get_nowait()
                self.pending_nfc_events.append(event)
                self.stats['total_nfc'] += 1
                self.logger.debug(f"Consumed NFC: Station {event['station_id']}, Part {event['part_id'][:8]}")
        except queue.Empty:
            pass

    def _fuse_events(self):
        """Try to fuse (match) GPIO/MCP events with NFC events"""
        current_time = time.time()

        # Try to match each GPIO event with an NFC event
        gpio_to_remove = []
        nfc_to_remove = []

        for gpio_idx, gpio_event in enumerate(self.pending_gpio_events):
            # Only try to fuse entry barriers with NFC
            if not self._is_entry_barrier(gpio_event['barrier_id']):
                # Non entry barriers don't need NFC fusion, deliver immediately
                self._deliver_event(gpio_event, part_id=None)
                gpio_to_remove.append(gpio_idx)
                continue

            # Try to find matching NFC event
            for nfc_idx, nfc_event in enumerate(self.pending_nfc_events):
                # Check if they match
                if self._events_match(gpio_event, nfc_event, current_time):
                    # Fusion successful
                    self.logger.info(
                        f"Fused: {gpio_event['barrier_id']} + Part {nfc_event['part_id'][:8]} "
                        f"(Δt={abs(gpio_event['timestamp'] - nfc_event['timestamp']):.3f}s)"
                    )

                    # Deliver fused event
                    self._deliver_event(gpio_event, part_id=nfc_event['part_id'])

                    # Mark for removal
                    gpio_to_remove.append(gpio_idx)
                    nfc_to_remove.append(nfc_idx)

                    # Update stats
                    self.stats['fused_events'] += 1

                    break  # Found match, move to next GPIO event

        # Remove matched events (reverse order to preserve indices)
        for idx in sorted(gpio_to_remove, reverse=True):
            del self.pending_gpio_events[idx]
        for idx in sorted(nfc_to_remove, reverse=True):
            del self.pending_nfc_events[idx]

    def _is_entry_barrier(self, barrier_id):
        """Check if barrier is an entry point that requires NFC fusion"""
        entry_barriers = ['S1_ENTRY', 'S2_ENTRY']
        return barrier_id in entry_barriers

    def _events_match(self, gpio_event, nfc_event, current_time):
        """
        Check if GPIO and NFC events match

        Matching criteria:
        1. Location must match (GPIO station == NFC station)
        2. Time difference must be within fusion window
        """
        # Extract location from GPIO event
        if gpio_event['location_type'] == 'station':
            gpio_station = gpio_event['location_id']
        else:
            return False  # Only fuse station events

        # Extract station from NFC event
        nfc_station = nfc_event['station_id']

        # Check location match
        if gpio_station != nfc_station:
            return False

        # Check time window
        time_diff = abs(gpio_event['timestamp'] - nfc_event['timestamp'])
        if time_diff > self.DELTA_T_FUSE:
            return False

        # Match successful
        return True

    def _expire_events(self):
        """Remove events that have been waiting too long"""
        current_time = time.time()

        # Expire GPIO events (orphans/missing NFC)
        gpio_to_remove = []
        for idx, event in enumerate(self.pending_gpio_events):
            age = current_time - event['timestamp']
            if age > self.DELTA_T_EXPIRY:
                # This is an orphaned event
                self.logger.warning(
                    f"Orphaned GPIO event (no NFC match): {event['barrier_id']} "
                    f"(age={age:.1f}s)"
                )
                self.stats['orphaned_gpio'] += 1

                # Log error event
                self.data_logger.log_event(
                    part_id='UNKNOWN',
                    station_id=f"{event['location_type']}{event['location_id']}",
                    activity=f"ERROR_ORPHAN_{event['barrier_id']}"
                )

                gpio_to_remove.append(idx)

        # Remove expired GPIO events
        for idx in sorted(gpio_to_remove, reverse=True):
            del self.pending_gpio_events[idx]

        # Expire NFC events (ghosts - missing GPIO)
        nfc_to_remove = []
        for idx, event in enumerate(self.pending_nfc_events):
            age = current_time - event['timestamp']
            if age > self.DELTA_T_EXPIRY:
                # This is a ghost read
                self.logger.warning(
                    f"Ghost NFC read (no GPIO match): Station {event['station_id']}, "
                    f"Part {event['part_id'][:8]} (age={age:.1f}s)"
                )
                self.stats['ghost_nfc'] += 1

                # Log error event
                self.data_logger.log_event(
                    part_id=event['part_id'],
                    station_id=f"S{event['station_id']}",
                    activity="ERROR_GHOST_NFC"
                )

                nfc_to_remove.append(idx)

        # Remove expired NFC events
        for idx in sorted(nfc_to_remove, reverse=True):
            del self.pending_nfc_events[idx]

    def _deliver_event(self, sensor_event, part_id):
        """
        Deliver fused event to appropriate FSM

        sensor_event: GPIO/MCP sensor event
        part_id: Fused part ID (or None for non entry events)
        """
        # Extract location info
        location_type = sensor_event['location_type']
        location_id = sensor_event['location_id']

        # Create FSM key
        fsm_key = f"{location_type}_{location_id}"

        # Get FSM
        fsm = self.fsm_map.get(fsm_key)

        if not fsm:
            self.logger.error(f"No FSM found for {fsm_key}")
            return

        # Create fused event tuple for FSM
        fused_event = {
            'timestamp': sensor_event['timestamp'],  # Precise GPIO timestamp!
            'barrier_id': sensor_event['barrier_id'],
            'part_id': part_id,  # None for non-entry barriers
            'location_type': location_type,
            'location_id': location_id
        }

        # Deliver to FSM
        try:
            fsm.process_event(fused_event)
            self.logger.debug(f"Delivered to {fsm_key}: {sensor_event['barrier_id']}")
        except Exception as e:
            self.logger.error(f"Error delivering event to {fsm_key}: {e}", exc_info=True)

        # Log sensor event to InfluxDB
        if self.influx_writer:
            self.influx_writer.write_sensor_event(
                barrier_id=sensor_event['barrier_id'],
                location_type=location_type,
                location_id=location_id
            )

    def _print_statistics(self):
        """Print CEP statistics"""
        self.logger.info("=" * 60)
        self.logger.info("CEP CONSUMER STATISTICS")
        self.logger.info("=" * 60)
        self.logger.info(f"Total GPIO events: {self.stats['total_gpio']}")
        self.logger.info(f"Total NFC events: {self.stats['total_nfc']}")
        self.logger.info(f"Fused events: {self.stats['fused_events']}")
        self.logger.info(f"Orphaned GPIO: {self.stats['orphaned_gpio']}")
        self.logger.info(f"Ghost NFC: {self.stats['ghost_nfc']}")

        if self.stats['total_gpio'] > 0:
            fusion_rate = (self.stats['fused_events'] / self.stats['total_gpio']) * 100
            self.logger.info(f"Fusion rate: {fusion_rate:.1f}%")

        self.logger.info("=" * 60)

    def stop(self):
        """Stop the CEP consumer"""
        self.logger.info("Stopping CEP Consumer...")
        self.running = False
        self.stop_event.set()

    def get_statistics(self):
        """Get current statistics"""
        return self.stats.copy()