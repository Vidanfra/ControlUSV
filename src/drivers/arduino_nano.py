import serial
import json
import time
import math

class ESP32Driver:
    def __init__(self, port, baudrate=115200):
        # Aumentamos un poco el timeout por si el Arduino está ocupado
        self.ser = serial.Serial(port, baudrate, timeout=0.1)
        time.sleep(2) # Esperar al reset del Arduino
        
        # Limpiar cualquier basura inicial
        self.ser.reset_input_buffer()

    def send_command(self, m1, m2, r1, r2, r3):
        """
        Send command to Arduino Nano.
        """
        # 1. Calcular Checksum (Suma de enteros, igual que en Arduino)
        checksum = int(m1) + int(m2) + int(r1) + int(r2) + int(r3)
        
        # 2. Crear Payload optimizado
        # Redondeamos a 2 decimales para no enviar "15.123456789" que satura el buffer
        payload = {
            "M1": round(m1, 2), 
            "M2": round(m2, 2), 
            "R1": int(r1), 
            "R2": int(r2), 
            "R3": int(r3),
            "C": checksum
        }
        
        # 3. Serializar SIN ESPACIOS
        # separators=(',', ':') convierte {"A": 1} en {"A":1} ahorrando bytes vitales
        msg = json.dumps(payload, separators=(',', ':')) + "\n"
        
        # Verificar longitud para depuración (El Nano tiene buffer de 64 bytes)
        if len(msg) > 63:
            print(f"Warning: Message too long ({len(msg)} bytes): {msg.strip()}")

        # 4. Enviar
        self.ser.reset_input_buffer() # Borrar ACKs viejos que no leímos
        self.ser.write(msg.encode('utf-8'))
        
        # 5. Esperar ACK
        start = time.time()
        while (time.time() - start) < 0.15: # 150ms timeout
            if self.ser.in_waiting:
                try:
                    line = self.ser.readline().decode('utf-8').strip()
                    if not line: continue # Linea vacia
                    
                    resp = json.loads(line)
                    
                    if "ACK" in resp:
                        if resp["ACK"] == checksum:
                            return True # Éxito rotundo
                        else:
                            print(f"Checksum mismatch: {resp}")
                    
                    elif "ERR" in resp:
                        # Si es error de Buffer o JSON, lo veremos aquí
                        print(f"Arduino Error: {resp}")
                        
                except ValueError:
                    pass # JSON incompleto o basura
                except Exception as e:
                    print(f"Comms Error: {e}")
            
            # Pequeña pausa para no quemar CPU de la Raspberry
            time.sleep(0.001) 
            
        raise TimeoutError("Arduino ACK Timeout")

    def close(self):
        self.ser.close()

if __name__ == "__main__":
    try:
        # Ajusta el puerto a tu Arduino Nano
        port = "/dev/arduino_nano" # Cambia según tu sistema (ej: /dev/ttyUSB0 o /dev/serial/by-id/...)

        driver = ESP32Driver(port) 
        print(f"Driver Started on {port}. Sending Sine Wave...")
        
        t = 0
        while True:
            # Generar onda
            val = 50 * math.sin(t*0.2)
            
            try:
                # Enviar comando
                success = driver.send_command(val, -val, 1, 1, 1)
                
                # Feedback visual simple
                print(f"Sent: {val:.1f} | ACK Received")
                
            except TimeoutError:
                print(f"Sent: {val:.1f} | TIMEOUT (Packet Lost)")
            except Exception as e:
                print(f"Error: {e}")
            
            t += 0.5
            # 15Hz es seguro. Si subes a 50Hz podrías saturar al Nano de nuevo.
            time.sleep(1) 
            
    except KeyboardInterrupt:
        print("\nStopping...")
        # Parar motores al salir
        try:
            driver.send_command(0, 0, 0, 1, 0)
        except:
            pass
        driver.close()