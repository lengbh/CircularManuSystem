#!/usr/bin/env python3
"""
Manufacturing System - Main Entry Point
Producer-Consumer Architecture with Event Fusion
"""

import sys
import os
import logging
import platform
import signal
import time

# Add src directory to path
sys.path.insert(0, os.path.dirname(__file__))

from system_manager import SystemManager


def setup_logging():
    """Setup logging configuration"""
    # Create logs directory
    os.makedirs('logs', exist_ok=True)

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('logs/system.log'),
            logging.StreamHandler(sys.stdout)
        ],
        force=True
    )


def print_banner():
    """Print startup banner"""
    print("\n" + "=" * 60)
    print(" " * 10 + "CIRCULAR MANUFACTURING SYSTEM")
    print("=" * 60)
    print(f"Platform: {platform.system()} {platform.release()}")

    # Detect if on Mac or Pi
    if platform.system() == 'Darwin':
        print("Mode: SIMULATION (macOS)")
        print("Deploy to Raspberry Pi for hardware control")
    else:
        print("Mode: HARDWARE (Raspberry Pi)")
        print("Ready for physical system control")
        print("GPIO interrupts enabled (microsecond precision)")
        print("Event fusion active")

    print("=" * 60 + "\n")


def main():
    """Main entry point"""
    # Setup
    setup_logging()
    print_banner()

    logger = logging.getLogger("Main")

    # Detect platform
    is_mac = platform.system() == 'Darwin'
    simulation = is_mac

    # Create system manager
    logger.info("Initializing system...")
    system = SystemManager(
        config_file='config/config.yaml',
        simulation=simulation
    )

    # Shutdown handler
    def shutdown_handler(signum, frame):
        """Handle shutdown signals cleanly"""
        logger.warning(f"Shutdown signal {signum} received...")
        try:
            logger.info("Shutting down system...")
            system.stop()
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")
        finally:
            logger.info("System shutdown complete.")
            sys.exit(0)

    # Register signal handlers
    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    try:
        # Start system
        system.start()

        # Instructions
        print("\n" + "-" * 60)
        print("SYSTEM IS RUNNING")
        print("-" * 60)
        print("\nArchitecture:")
        print("  • GPIO Interrupts: Microsecond timestamp precision")
        print("  • NFC Threads: Background part identification")
        print("  • CEP Fusion: Time-window event matching")
        print("  • Passive FSMs: Event-driven state machines")

        print("\nMonitoring:")
        print("  • logs/system.log - Detailed system logs")
        print("  • data/events.csv - Event log (t,s,p,a)")

        if not is_mac:
            print("\nDashboards:")
            print("  • http://rbp8gb.local:1880 - Node-RED")
            print("  • http://rbp8gb.local:8086 - InfluxDB")
            print("  • http://rbp8gb.local:3000 - Grafana")

        print("\nPress Ctrl+C to stop system")
        print("-" * 60 + "\n")

        # Status monitoring loop
        logger.info("Entering monitoring loop...")
        while True:
            time.sleep(10)

            # Get system status
            status = system.get_status()

            # Log queue sizes periodically
            queue_sizes = status['queue_sizes']
            if any(queue_sizes.values()):
                logger.debug(
                    f"Queue sizes: GPIO={queue_sizes['gpio']}, "
                    f"MCP={queue_sizes['mcp']}, NFC={queue_sizes['nfc']}"
                )

    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
    finally:
        logger.info("Main finally block calling system.stop()")
        system.stop()
        logger.info("System shutdown complete.")


if __name__ == "__main__":
    main()