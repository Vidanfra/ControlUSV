'''
## Installation

1. Install Python 3 from the [official website](https://www.python.org/downloads/).

2. Install the required Python libraries by running the following command in your terminal or command prompt:

   ```
   pip install minimalmodbus pyserial
   ```

3. Clone this repository or download the Python scripts `pzem_reading.py` and `change_settings.py`.

```
git clone https://github.com/croutonso/PZEM017modbus.git
```

4. Connect the PZEM device to your Raspberry Pi or Linux system using a USB to RS485 converter.

## Usage

### pzem_reading.py

This script reads data from the PZEM-017 device and displays the voltage, current, power, and energy values.

1. Open `pzem_reading.py` in a text editor and set the `DEVICE_ADDRESS`, `PORT`, and other parameters according to your device and connection.

2. Save the changes and close the text editor.

3. Open a terminal, navigate to the directory containing `pzem_reading.py`, and run the following command:

   ```
   python pzem_reading.py
   ```

4. The script will display the voltage, current, power, and energy values.

### change_settings.py

This script allows you to change the parameters of the PZEM-017 device, such as high and low voltage alarm thresholds, slave address, and current range (PZEM-017 only).

1. Open `change_settings.py` in a text editor and set the `SLAVE_ADDRESS`, `DEVICE_PORT`, and other parameters according to your device and connection.

2. Save the changes and close the text editor.

3. Open a terminal, navigate to the directory containing `change_settings.py`, and run the following command:

   ```
   python change_settings.py
   ```

4. The script will display a menu with options to change various device parameters.
'''
'''
## Installation

1. Install Python 3 from the [official website](https://www.python.org/downloads/).

2. Install the required Python libraries by running the following command in your terminal or command prompt:

   ```
   pip install minimalmodbus pyserial
   ```

3. Clone this repository or download the Python scripts `pzem_reading.py` and `change_settings.py`.

```
git clone https://github.com/croutonso/PZEM017modbus.git
```

4. Connect the PZEM device to your Raspberry Pi or Linux system using a USB to RS485 converter.

## Usage

### pzem_reading.py

This script reads data from the PZEM-017 device and displays the voltage, current, power, and energy values.

1. Open `pzem_reading.py` in a text editor and set the `DEVICE_ADDRESS`, `PORT`, and other parameters according to your device and connection.

2. Save the changes and close the text editor.

3. Open a terminal, navigate to the directory containing `pzem_reading.py`, and run the following command:

   ```
   python pzem_reading.py
   ```

4. The script will display the voltage, current, power, and energy values.

### change_settings.py

This script allows you to change the parameters of the PZEM-017 device, such as high and low voltage alarm thresholds, slave address, and current range (PZEM-017 only).

1. Open `change_settings.py` in a text editor and set the `SLAVE_ADDRESS`, `DEVICE_PORT`, and other parameters according to your device and connection.

2. Save the changes and close the text editor.

3. Open a terminal, navigate to the directory containing `change_settings.py`, and run the following command:

   ```
   python change_settings.py
   ```

4. The script will display a menu with options to change various device parameters.
'''

import threading
import time
import minimalmodbus
import serial

class PZEMParser:
    def __init__(self, port='/dev/ttyUSB0', device_address=0x01, baud_rate=9600, timeout=1, update_hz=1):
        """
        PZEM Parser with background thread.
        :param port: serial port
        :param device_address: Modbus device address
        :param baud_rate: serial baudrate
        :param timeout: serial timeout in seconds
        :param update_hz: update frequency in Hz
        """
        try:
            self.port = port
            self.device_address = device_address
            self.baud_rate = baud_rate
            self.timeout = timeout
            self.update_interval = 1.0 / update_hz

            # Threading
            self.lock = threading.Lock()
            self._stop_event = threading.Event()
            self.thread = None
        except Exception as e:
            print(f"Failed to start PZEM parser thread: {e}")
        try:
            # Data storage
            self.data = {
                "voltage": 0.0,
                "current": 0.0,
                "power": 0,
                "energy": 0,
                "high_voltage_alarm": 0,
                "low_voltage_alarm": 0
            }

            # Initialize instrument
            self.instrument = minimalmodbus.Instrument(self.port, self.device_address)
            self.instrument.serial.baudrate = self.baud_rate
            self.instrument.serial.bytesize = 8
            self.instrument.serial.parity = serial.PARITY_NONE
            self.instrument.serial.stopbits = 2
            self.instrument.serial.timeout = self.timeout
        except Exception as e:
            print(f"Failed to open Serial Port to read PZEM: {e}")
        finally:
            self.stop()

    def start(self):
        """Start the background thread."""
        try:
            if self.instrument is None:
                raise Exception("Instrument not initialized.")
            
            self._stop_event.clear()
            self.thread = threading.Thread(target=self._worker, daemon=True)
            self.thread.start()
        except Exception as e:
            print(f"Failed to start PZEM parser thread: {e}")
            self.stop()

    def stop(self):
        """Stop the background thread."""
        self._stop_event.set()
        if self.thread:
            self.thread.join()

    def _worker(self):
        """Background thread to continuously read PZEM data."""
        while not self._stop_event.is_set():
            try:
                voltage = self.instrument.read_register(0x0000, number_of_decimals=2, functioncode=4)
                current = self.instrument.read_register(0x0001, number_of_decimals=2, functioncode=4)
                power_low = self.instrument.read_register(0x0002, functioncode=4)
                power_high = self.instrument.read_register(0x0003, functioncode=4)
                power = (power_high << 16) + power_low
                energy_low = self.instrument.read_register(0x0004, functioncode=4)
                energy_high = self.instrument.read_register(0x0005, functioncode=4)
                energy = (energy_high << 16) + energy_low
                high_voltage_alarm = self.instrument.read_register(0x0006, functioncode=4)
                low_voltage_alarm = self.instrument.read_register(0x0007, functioncode=4)

                with self.lock:
                    self.data.update({
                        "voltage": voltage,
                        "current": current,
                        "power": power,
                        "energy": energy,
                        "high_voltage_alarm": high_voltage_alarm,
                        "low_voltage_alarm": low_voltage_alarm
                    })

            except minimalmodbus.IllegalRequestError as e:
                print(f"PZEM read error: {e}")          
            except Exception as e:
                print(f"PZEM unexpected error: {e}")

            time.sleep(self.update_interval)

    # --- Getters ---
    def get_voltage(self):
        with self.lock:
            return self.data["voltage"]

    def get_current(self):
        with self.lock:
            return self.data["current"]

    def get_power(self):
        with self.lock:
            return self.data["power"]

    def get_energy(self):
        with self.lock:
            return self.data["energy"]

    def get_high_voltage_alarm(self):
        with self.lock:
            return self.data["high_voltage_alarm"]

    def get_low_voltage_alarm(self):
        with self.lock:
            return self.data["low_voltage_alarm"]

    def get_all(self):
        with self.lock:
            return self.data.copy()


# --- Example usage ---
if __name__ == "__main__":
    pzem = PZEMParser(port='/dev/ttyUSB0', device_address=1, baud_rate=9600, timeout=1, update_hz=1)
    pzem.start()
    try:
        while True:
            data = pzem.get_all()
            print(f"Voltage: {data['voltage']} V, Current: {data['current']} A, Power: {data['power']} W, Energy: {data['energy']} Wh")
            time.sleep(1)
    except KeyboardInterrupt:
        print("Stopping...")
    finally:
        pzem.stop()

    
