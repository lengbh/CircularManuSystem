## CircularManuSystem
The repository of a lab-scale 2-station closed-loop manufacturing system. 

*developed by Nikolaos, Bohan*

## Project Overview

This project implements a lab-scale manufacturing system with two processing stations connected in a closed loop using Fischertechnik components and Raspberry Pi control. The system is designed to demonstrate key concepts in automated manufacturing including:

- Part tracking through RFID/NFC technology
- Queue management and buffer behavior
- Real-time process monitoring
- Key performance indicator (KPI) calculation
- Data collection and visualization

## System Architecture

```mermaid

classDiagram
    direction TB
    class SystemManager {
        +config
        +motors
        +sensors
        +nfc1, nfc2
        +data_logger
        +mqtt
        +collision_mgr
        +station1, station2
        +corners[]
        +start()
        +stop()
        -load_config()
    }
    class MotorController {
        -hat1, hat2
        -simulation
        +set_speed(motor_num, speed)
        +stop(motor_num)
        +stop_all()
        +start_conveyors()
    }
    class SensorReader {
        -simulation
        -lock
        +read(pin)
        +station1_entry()
        +corner_pre(corner_num)
        +wait_for(pin)
    }
    class NFCReader {
        -pn532
        -simulation
        +read_tag(timeout)
        +wait_for_tag(timeout)
    }
    class StationController {
        -state
        -current_part
        +start()
        +stop()
        -run()
        -state_idle()
        -state_processing()
    }
    class CornerController {
        -state
        +start()
        +stop()
        -run()
        -state_idle()
        -state_extending()
        -state_retracting()
    }
    class CollisionManager {
        -corners_occupied
        -lock
        +is_corner_safe(corner_num)
        +reserve_corner(corner_num)
        +release_corner(corner_num)
    }
    class DataLogger {
        -log_file
        -lock
        +log_event(part_id, station_id, activity)
        +get_kpis()
    }
    class MQTTHandler {
        -client
        -connected
        +publish_event(part_id, station_id, activity)
        +publish_kpi(kpi_name, value)
    }
    class Part {
        +part_id
        +events
        +current_location
        +add_event()
    }
    SystemManager "1" *-- "1" MotorController : manages
    SystemManager "1" *-- "1" SensorReader : manages
    SystemManager "1" *-- "2" NFCReader : manages
    SystemManager "1" *-- "1" DataLogger : manages
    SystemManager "1" *-- "1" MQTTHandler : manages
    SystemManager "1" *-- "1" CollisionManager : manages
    SystemManager "1" *-- "2" StationController : manages
    SystemManager "1" *-- "4" CornerController : manages
    StationController ..> MotorController : uses
    StationController ..> SensorReader : uses
    StationController ..> NFCReader : uses
    StationController ..> DataLogger : uses
    StationController ..> Part : uses
    CornerController ..> MotorController : uses
    CornerController ..> SensorReader : uses
    CornerController ..> CollisionManager : uses
    NFCReader ..> Part : creates

```


## Production Concept

The system simulates a small manufacturing cell that could represent various real-world processes:

### Manufacturing Scenario 1: Electronics Assembly

- **Station 1**: Component Placement
  Parts are positioned precisely and components are placed onto a circuit board.
  
- **Station 2**: Quality Inspection
  Completed assemblies are inspected for defects using vision systems.

### Manufacturing Scenario 2: Machining Operations

- **Station 1**: Milling Operation
  Raw parts are milled to create specific features or shapes.
  
- **Station 2**: Finishing and Deburring
  Machined parts have sharp edges removed and surfaces smoothed.

### Manufacturing Scenario 3: Packaging Line

- **Station 1**: Product Filling
  Containers are filled with a specified amount of product.
  
- **Station 2**: Labeling and Sealing
  Filled containers are labeled and sealed for shipment.

## System Features

- **Closed-Loop Material Flow**: Parts continuously circulate through the system
- **Software Queuing**: Parts wait at station entrance if the processing position is occupied
- **NFC Tag Identification**: Each part is uniquely