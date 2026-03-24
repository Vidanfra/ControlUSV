import serial
import time

# Configuracion del puerto serie (Asegurate de que coincide con tus pines)
SERIAL_PORT = '/dev/serial0'
BAUD_RATE = 9600

def send_wittmotion_command(ser, command_bytes, description=""):
    """Envia una trama de bytes al sensor y espera un momento."""
    print(f"Enviando comando: {description}")
    ser.write(command_bytes)
    time.sleep(0.1)  # Pequeña pausa requerida por el microcontrolador del sensor

def main():
    try:
        # Abrir el puerto serie
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
        print(f"Conectado a la IMU en {SERIAL_PORT} a {BAUD_RATE} baudios.")

        # 1. Comando de Desbloqueo (Unlock)
        # Segun el datasheet de WittMotion: 0xFF 0xAA 0x69 0x88 0xB5
        cmd_unlock = b'\xFF\xAA\x69\x88\xB5'
        send_wittmotion_command(ser, cmd_unlock, "Desbloquear configuracion")

        # 2. Cambiar Frecuencia (Return Rate) a 20 Hz
        # Registro: 0x03
        # Valor para 20Hz: 0x07 
        # Trama: 0xFF 0xAA 0x03 0x07 0x00
        cmd_set_20hz = b'\xFF\xAA\x03\x07\x00'
        send_wittmotion_command(ser, cmd_set_20hz, "Establecer frecuencia a 20 Hz")

        # 3. Guardar Configuracion (Save)
        # Registro: 0x00
        # Valor: 0x00
        # Trama: 0xFF 0xAA 0x00\x00\x00
        cmd_save = b'\xFF\xAA\x00\x00\x00'
        send_wittmotion_command(ser, cmd_save, "Guardar configuracion en memoria no volatil")

        print("\nConfiguracion completada exitosamente. La IMU ahora envia datos a 20 Hz.")

    except serial.SerialException as e:
        print(f"Error al abrir el puerto serie: {e}")
    except Exception as e:
        print(f"Ocurrio un error inesperado: {e}")
    finally:
        if 'ser' in locals() and ser.is_open:
            ser.close()
            print("Puerto serie cerrado.")

if __name__ == '__main__':
    main()