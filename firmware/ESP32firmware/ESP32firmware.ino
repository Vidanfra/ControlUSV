#include <Arduino.h>
#include <ESP32Servo.h>
#include <ArduinoJson.h>

// --- CONFIGURACIÓN (ESP32 WROOM - Freenove) ---
// NOTA: GPIO34..39 son SOLO ENTRADA en el ESP32 WROOM original, por lo que
// los pines del firmware original (S3: 20,21,38,39,40) se han reasignado a
// pines válidos de salida. Cámbialos si tu cableado es distinto.
const int PIN_M1 = 15;  // Babor (Port)
const int PIN_M2 = 0;  // Estribor (Starboard)
const int PIN_R1 = 18;  // Motor Relay
const int PIN_R2 = 19;  // Comms Relay (Default ON)
const int PIN_R3 = 21;  // Payload Relay

// LED integrado de un solo color del Freenove ESP32 WROOM (GPIO 2)
const int PIN_LED = 2;

const unsigned long TIMEOUT_MS = 250; // 0.25 segundos failsafe
const long BAUDRATE = 115200;

// Objetos Servo para controlar los motores (ESCs)
Servo m1;
Servo m2;

// Variables de estado
unsigned long last_packet_time = 0;

// Prototipos de funciones
void setMotors(float p1, float p2);
void setRelays(int v1, int v2, int v3);
void activateFailsafe();
void updateLed(bool isFailsafe);

void setup() {
  // Inicializar Serial
  Serial.begin(BAUDRATE);

  // LED integrado apagado al inicio
  pinMode(PIN_LED, OUTPUT);
  digitalWrite(PIN_LED, LOW);

  // Configurar Pines de Relés
  pinMode(PIN_R1, OUTPUT);
  pinMode(PIN_R2, OUTPUT);
  pinMode(PIN_R3, OUTPUT);

  // Configurar Pines de Motores (ESP32Servo se encarga del PWM a 50Hz)
  // Rango estándar de ESC: 1000us a 2000us
  m1.setPeriodHertz(50); 
  m1.attach(PIN_M1, 1000, 2000);
  
  m2.setPeriodHertz(50);
  m2.attach(PIN_M2, 1000, 2000);

  // Estado Inicial
  activateFailsafe();
  last_packet_time = millis();
}

void loop() {
  unsigned long current_time = millis();
  bool isFailsafe = false;

  // --- 1. CHECK FAILSAFE ---
  if (current_time - last_packet_time > TIMEOUT_MS) {
    activateFailsafe();
    isFailsafe = true;
  }

  // --- 2. UPDATE LED ---
  updateLed(isFailsafe);

  // --- 3. CHECK INCOMING DATA ---
  if (Serial.available() > 0) {
    String line = Serial.readStringUntil('\n');
    line.trim(); // Quitar espacios en blanco / \r

    if (line.length() > 0) {
      // Buffer para JSON (ajusta el tamaño si envías paquetes muy grandes)
      StaticJsonDocument<256> doc;
      
      // Intentar deserializar
      DeserializationError error = deserializeJson(doc, line);

      if (!error) {
        // Extraer campos (con valores por defecto si faltan)
        float m1_val = doc["M1"] | 0.0;
        float m2_val = doc["M2"] | 0.0;
        int r1_val = doc["R1"] | 0;
        int r2_val = doc["R2"] | 1; // Default 1
        int r3_val = doc["R3"] | 0;
        int rx_checksum = doc["C"] | -1;

        // Calcular Checksum (Igual que en Python: suma de enteros)
        int calc_checksum = (int)m1_val + (int)m2_val + r1_val + r2_val + r3_val;

        if (rx_checksum == calc_checksum) {
          // --- PAQUETE VALIDO ---
          setMotors(m1_val, m2_val);
          setRelays(r1_val, r2_val, r3_val);
          
          last_packet_time = millis();

          // Enviar ACK
          StaticJsonDocument<64> resp;
          resp["ACK"] = calc_checksum;
          serializeJson(resp, Serial);
          Serial.println();
        } else {
          // --- ERROR CHECKSUM ---
          StaticJsonDocument<128> resp;
          resp["ERR"] = "CHECKSUM";
          resp["EXPECTED"] = calc_checksum;
          resp["GOT"] = rx_checksum;
          serializeJson(resp, Serial);
          Serial.println();
        }

      } else {
        // --- ERROR PARSEO JSON ---
        StaticJsonDocument<128> resp;
        resp["ERR"] = "JSON_PARSE";
        resp["MSG"] = error.c_str();
        serializeJson(resp, Serial);
        Serial.println();
      }
    }
  }
}

// --- FUNCIONES AUXILIARES ---

void setMotors(float p1, float p2) {
  // Clamp values (-100 a 100)
  if (p1 > 100) p1 = 100;
  if (p1 < -100) p1 = -100;
  
  if (p2 > 100) p2 = 100;
  if (p2 < -100) p2 = -100;

  // Mapear -100..100 a 1000us..2000us
  // Formula: us = (percent * 5) + 1500
  int us1 = (int)(p1 * 5.0 + 1500.0);
  int us2 = (int)(p2 * 5.0 + 1500.0);

  m1.writeMicroseconds(us1);
  m2.writeMicroseconds(us2);
}

void setRelays(int v1, int v2, int v3) {
  digitalWrite(PIN_R1, v1 ? HIGH : LOW);
  digitalWrite(PIN_R2, v2 ? HIGH : LOW);
  digitalWrite(PIN_R3, v3 ? HIGH : LOW);
}


void updateLed(bool isFailsafe) {
  static unsigned long lastBlink = 0;
  static bool ledState = false;

  if (isFailsafe) {
    // Error / sin conexión con la Raspberry -> parpadeo rápido (100 ms)
    if (millis() - lastBlink > 100) {
      lastBlink = millis();
      ledState = !ledState;
      digitalWrite(PIN_LED, ledState ? HIGH : LOW);
    }
  } else {
    // Conexión correcta con la Raspberry -> LED fijo encendido
    ledState = true;
    digitalWrite(PIN_LED, HIGH);
  }
}
void activateFailsafe() {
  // Def: M1:0, M2:0, R1:0, R2:1, R3:0
  setMotors(0, 0);
  //setRelays(0, 1, 0);
}