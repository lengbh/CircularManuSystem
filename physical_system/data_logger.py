"""
Data Logger
Logs events and calculates KPIs

Event format: {timestamp, part_id, station_id, activity}

"""

import logging
import csv
import os
from datetime import datetime
from threading import Lock
import time


class DataLogger:
    """
    Logs system events and calculates KPIs

    Event format matches requirements:
        Time | Station ID | Part ID | Activity
    """

    def __init__(self, log_file="data/events.csv"):
        """
        Initialize data logger

        log_file: Path to CSV log file
        """
        self.logger = logging.getLogger("DataLogger")
        self.log_file = log_file
        self.lock = Lock()

        # Create data directory if needed or do nothing if it exists
        os.makedirs(os.path.dirname(log_file), exist_ok=True)

        # Create CSV file with headers if it doesn't exist
        if not os.path.exists(log_file):
            self._create_csv()

        self.logger.info(f"Data logger initialized: {log_file}")

        # KPI tracking initialization as a dictionary
        self.kpis = {
            'total_parts': 0,
            'station1_count': 0,
            'station2_count': 0,
            'total_process_time': 0,
            'total_queue_time': 0
        }

        self.system_start_time = time.time()
        self.station_entry_times = {}
        self.current_wip = 0
        self.max_wip = 0

        self.cycle_times_s1 = []
        self.cycle_times_s2 = []

        self.station_states = {
            'S1': {'busy_since': None, 'total_busy_time': 0},
            'S2': {'busy_since': None, 'total_busy_time': 0}
        }

        self.corner_states = {
            'C1': {'busy_since': None, 'total_busy_time': 0},
            'C2': {'busy_since': None, 'total_busy_time': 0},
            'C3': {'busy_since': None, 'total_busy_time': 0},
            'C4': {'busy_since': None, 'total_busy_time': 0}
        }

        self.event_timestamps = []

        self.influx_writer = None

    def _create_csv(self):
        """Create CSV file with headers"""
        with open(self.log_file, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['Time', 'Station ID', 'Part ID', 'Activity', 'Tag'])
        self.logger.info("Created new event log file")

    def log_event(self, part_id, station_id, activity, tag=None):
        """
        Log an event with START/FINISH tag
            part_id: Part ID (e.g., "P001", "04a1b2c3d4e5f6")

            station_id: Station ID (e.g., "S1", "S2", "C1", "C2", "C3", "C4")

            activity: Activity type (e.g., "ENTER", "EXIT", "PROCESS_START", "PROCESS_END")

            tag: Event tag - "START" or "FINISH" (auto-inferred if None)

        """
        # Get current timestamp
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        current_time = time.time()

        # Auto-infer tag if not provided
        if tag is None:
            tag = self._infer_tag(activity)

        with self.lock:
            # Write to CSV with tag
            with open(self.log_file, 'a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([timestamp, station_id, part_id, activity, tag])

            # Log to console
            self.logger.info(f"Event: {timestamp} | {station_id} | {part_id} | {activity}")

            # Update KPIs
            self._update_kpis(station_id, activity)

            self._update_realtime_metrics(part_id, station_id, activity, current_time)

            if self.influx_writer:
                cycle_time = None
                if activity == 'EXIT' and station_id in ['S1', 'S2']:
                    key = f"{part_id}_{station_id}"
                    if key in self.station_entry_times:
                        cycle_time = current_time - self.station_entry_times[key]

                self.influx_writer.write_event(
                    part_id=part_id,
                    station_id=station_id,
                    activity=activity,
                    additional_fields={'cycle_time': cycle_time} if cycle_time else None
                )

    def _infer_tag(self, activity):
        """
        Automatically infer START/FINISH tag from activity name

        FINISH activities: EXIT, COMPLETE, END, FINISH
        START activities: Everything else (ENTER, PROCESS_START, PUSH_START, etc.)

        Returns: 'START' or 'FINISH'
        """
        finish_keywords = ['EXIT', 'COMPLETE', 'END', 'FINISH']

        activity_upper = activity.upper()
        for keyword in finish_keywords:
            if keyword in activity_upper:
                return 'FINISH'

        return 'START'

    def _update_kpis(self, station_id, activity):
        """Update KPI counters"""
        if activity == "EXIT":
            self.kpis['total_parts'] += 1
            if station_id == "S1":
                self.kpis['station1_count'] += 1
            elif station_id == "S2":
                self.kpis['station2_count'] += 1

    def _update_realtime_metrics(self, part_id, station_id, activity, current_time):
        """Update real-time metrics for Grafana"""
        self.event_timestamps.append((current_time, station_id, activity))

        cutoff = current_time - 3600
        self.event_timestamps = [e for e in self.event_timestamps if e[0] > cutoff]

        if station_id in ['S1', 'S2']:
            if activity == 'ENTER':
                key = f"{part_id}_{station_id}"
                self.station_entry_times[key] = current_time
                self.current_wip += 1
                self.max_wip = max(self.max_wip, self.current_wip)

                if self.station_states[station_id]['busy_since'] is None:
                    self.station_states[station_id]['busy_since'] = current_time

            elif activity == 'EXIT':
                key = f"{part_id}_{station_id}"
                if key in self.station_entry_times:
                    cycle_time = current_time - self.station_entry_times[key]

                    if station_id == 'S1':
                        self.cycle_times_s1.append(cycle_time)
                        if len(self.cycle_times_s1) > 100:
                            self.cycle_times_s1.pop(0)
                    elif station_id == 'S2':
                        self.cycle_times_s2.append(cycle_time)
                        if len(self.cycle_times_s2) > 100:
                            self.cycle_times_s2.pop(0)

                    del self.station_entry_times[key]

                if station_id == 'S2':
                    self.current_wip = max(0, self.current_wip - 1)

                if self.station_states[station_id]['busy_since'] is not None:
                    busy_duration = current_time - self.station_states[station_id]['busy_since']
                    self.station_states[station_id]['total_busy_time'] += busy_duration
                    self.station_states[station_id]['busy_since'] = None

        elif station_id in ['C1', 'C2', 'C3', 'C4']:
            if activity == 'PUSH_START':
                if self.corner_states[station_id]['busy_since'] is None:
                    self.corner_states[station_id]['busy_since'] = current_time

            elif activity == 'PUSH_COMPLETE':
                if self.corner_states[station_id]['busy_since'] is not None:
                    busy_duration = current_time - self.corner_states[station_id]['busy_since']
                    self.corner_states[station_id]['total_busy_time'] += busy_duration
                    self.corner_states[station_id]['busy_since'] = None

    def get_kpis(self):
        """
        Gets a current copy of the KPIs for other modules functions

        Returns:
            dict: KPI dictionary
        """
        with self.lock:
            current_time = time.time()
            runtime = current_time - self.system_start_time

            avg_cycle_s1 = (
                sum(self.cycle_times_s1) / len(self.cycle_times_s1)
                if self.cycle_times_s1 else 0
            )
            avg_cycle_s2 = (
                sum(self.cycle_times_s2) / len(self.cycle_times_s2)
                if self.cycle_times_s2 else 0
            )

            throughput = 0
            if runtime > 60:
                parts_completed = self.kpis['total_parts']
                throughput = (parts_completed / runtime) * 3600

            def get_utilization(station_id):
                state = self.station_states[station_id]
                total_busy = state['total_busy_time']

                if state['busy_since'] is not None:
                    total_busy += (current_time - state['busy_since'])

                return (total_busy / runtime * 100) if runtime > 0 else 0

            s1_util = get_utilization('S1')
            s2_util = get_utilization('S2')

            def get_corner_utilization(corner_id):
                state = self.corner_states[corner_id]
                total_busy = state['total_busy_time']

                if state['busy_since'] is not None:
                    total_busy += (current_time - state['busy_since'])

                return (total_busy / runtime * 100) if runtime > 0 else 0

            event_rate = len(self.event_timestamps) / (min(runtime, 3600) / 60) if runtime > 0 else 0

            return {
                'total_parts': self.kpis['total_parts'],
                'station1_count': self.kpis['station1_count'],
                'station2_count': self.kpis['station2_count'],
                'throughput_per_hour': throughput,
                'avg_cycle_time_s1': avg_cycle_s1,
                'avg_cycle_time_s2': avg_cycle_s2,
                'current_wip': self.current_wip,
                'max_wip': self.max_wip,
                'station1_utilization': s1_util,
                'station2_utilization': s2_util,
                'corner1_utilization': get_corner_utilization('C1'),
                'corner2_utilization': get_corner_utilization('C2'),
                'corner3_utilization': get_corner_utilization('C3'),
                'corner4_utilization': get_corner_utilization('C4'),
                'event_rate_per_minute': event_rate,
                'runtime_seconds': runtime,
                'runtime_minutes': runtime / 60
            }

    def print_kpis(self):
        """Print KPIs to console"""
        kpis = self.get_kpis()

        print("\n" + "=" * 70)
        print(" " * 20 + "SYSTEM PERFORMANCE REPORT")
        print("=" * 70)

        print(f"\nStation 1 processed: {kpis['station1_count']}")
        print(f"Station 2 processed: {kpis['station2_count']}")
        print(f"Total parts: {kpis['total_parts']}")

        if kpis['runtime_minutes'] > 1:
            print("\n--- REAL-TIME METRICS ---")
            print(f"Throughput: {kpis['throughput_per_hour']:.2f} parts/hour")
            print(f"Avg Cycle Time (S1): {kpis['avg_cycle_time_s1']:.2f}s")
            print(f"Avg Cycle Time (S2): {kpis['avg_cycle_time_s2']:.2f}s")
            print(f"Current WIP: {kpis['current_wip']}")
            print(f"Max WIP: {kpis['max_wip']}")
            print(f"Station 1 Utilization: {kpis['station1_utilization']:.1f}%")
            print(f"Station 2 Utilization: {kpis['station2_utilization']:.1f}%")
            print(f"Event Rate: {kpis['event_rate_per_minute']:.1f} events/min")
            print(f"Runtime: {kpis['runtime_minutes']:.2f} minutes")

        print("=" * 70 + "\n")