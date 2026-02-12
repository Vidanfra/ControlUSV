import serial
import json
import time

'''
ESP32 pinout:

const int PIN_M1 = 20;  // Babor (Port)
const int PIN_M2 = 21;  // Estribor (Starboard)
const int PIN_R1 = 38;  // Motor Relay [WHITE]
const int PIN_R2 = 39;  // Comms Relay (Default ON) [GREEN]
const int PIN_R3 = 40;  // Payload Relay [YELLOW]
'''

class ESP32Driver:
    def __init__(self, port, baudrate=115200):
        self.ser = serial.Serial(port, baudrate, timeout=0.1)
        self.last_ack_time = time.time()
        time.sleep(2) # Wait for ESP32 reset if dtr implies reset

    def send_command(self, m1, m2, r1, r2, r3):
        """
        Send command to ESP32.
        m1, m2: Motor percentages (-100 to 100)
        r1, r2, r3: Relay states (0 or 1)
        """
        # Calculate Checksum (Int sum)
        checksum = int(m1) + int(m2) + int(r1) + int(r2) + int(r3)
        
        payload = {
            "M1": m1, 
            "M2": m2, 
            "R1": int(r1), 
            "R2": int(r2), 
            "R3": int(r3),
            "C": checksum
        }
        
        # Send JSON
        msg = json.dumps(payload) + "\n"
        self.ser.write(msg.encode('utf-8'))
        
        # Wait for ACK
        start = time.time()
        while (time.time() - start) < 0.2: # 200ms timeout for ACK
            if self.ser.in_waiting:
                try:
                    line = self.ser.readline().decode('utf-8').strip()
                    resp = json.loads(line)
                    if "ACK" in resp:
                         if resp["ACK"] == checksum:
                             return True # Success
                    if "ERR" in resp:
                        print(f"ESP32 Error: {resp}")
                except Exception as e:
                    print(f"ESP32 Comms Error: {e}")
            time.sleep(0.005)
            
        raise TimeoutError("ESP32 ACK Timeout")

    def close(self):
        self.ser.close()

if __name__ == "__main__":
    # Test Script
    try:
        driver = ESP32Driver("COM5") # Change COM port as needed
        print("Driver Started. Sending Sine Wave...")
        import math
        t = 0
        while True:
            val = 100 * math.sin(t)
            try:
                if int(val) % 2 == 0:
                    driver.send_command(val, -val, 1, 1, 1)
                else:
                    driver.send_command(val, -val, 0, 1, 0)
                print(f"Sent: {val:.1f}")
            except Exception as e:
                print(f"Error: {e}")
            
            t += 0.1
            time.sleep(1/15) # 15 Hz
            
    except KeyboardInterrupt:
        driver.close()
