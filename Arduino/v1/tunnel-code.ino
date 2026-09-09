/*
SMART SALT TUNNEL v1
Author: Kenneth Sunjaya
Last Updated: 9 September 2026
*/

#include <Wire.h>
#include <SPI.h>
#include <RF24.h>
#include <Adafruit_HTU21DF.h>
#include <OneWire.h>
#include <DallasTemperature.h>

// RADIO CONFIGURATION
#define CE_PIN 9
#define CSN_PIN 10
#define RELAY_PIN 5
#define WATER_LEVEL_PIN A2
#define WATER_TEMP_PIN A3
#define DMS_S_PIN 6
#define DMS_ANALOG_PIN A0

Adafruit_HTU21DF htu = Adafruit_HTU21DF();
OneWire oneWire(WATER_TEMP_PIN);
DallasTemperature waterTempSensor(&oneWire);
RF24 radio(CE_PIN, CSN_PIN);

const byte RASPI_ADDRESS[6] = "RASPI"; // harus sama juga di sisi RPi
const byte DEVICE_ADDRESS[6] = "A0001"; // unique id setiap tunnel, nanti akan dipindahkan ke EEPROM

const uint8_t PAYLOAD_SIZE = 32;

// MESSAGE TYPES MAPPING
const uint8_t MSG_REGISTER_REQUEST = 1;
const uint8_t MSG_REGISTER_ACK = 2;
const uint8_t MSG_TELEMETRY = 3;
const uint8_t MSG_START_TRANSFER = 4;
const uint8_t MSG_TRANSFER_COMPLETE = 5;


// REGISTRATION STATUS
const uint8_t STATUS_UNREGISTERED = 0;
const uint8_t STATUS_DISABLED = 1;
const uint8_t STATUS_ENABLED = 2;


// DEVICE STATE
enum DeviceState {
  REGISTERING,
  UNREGISTERED,
  DISABLED,
  ENABLED
};

DeviceState device_state = REGISTERING;


// TIMING CONFIG

const unsigned long REGISTER_RETRY_INTERVAL = 20000; // interval retry kirim register request jika gagal.
const unsigned long TELEMETRY_INTERVAL = 10000; // interval tunnel kirim telemetry

unsigned long last_register_attempt = 0;
unsigned long last_telemetry_timestamp = 0;


// MESSAGE STATE

uint32_t telemetry_sequence = 0;
uint32_t prev_message_id = 0;
uint16_t active_min_level = 0;


// HELPER FUNCTIONS

void writeUInt16LE(byte* buffer, int offset, uint16_t value) {
  buffer[offset] = value & 0xFF;
  buffer[offset + 1] = (value >> 8) & 0xFF;
}

void writeInt16LE(byte* buffer, int offset, int16_t value) {
  writeUInt16LE(buffer, offset, (uint16_t)value);
}

void writeUInt32LE(byte* buffer, int offset, uint32_t value) {
  buffer[offset] = value & 0xFF;
  buffer[offset + 1] = (value >> 8) & 0xFF;
  buffer[offset + 2] = (value >> 16) & 0xFF;
  buffer[offset + 3] = (value >> 24) & 0xFF;
}

uint16_t readUInt16LE(byte* buffer, int offset) {
  return (
    ((uint16_t)buffer[offset]) |
    ((uint16_t)buffer[offset + 1] << 8)
  );
}

uint32_t readUInt32LE(byte* buffer, int offset) {
  return (
    ((uint32_t)buffer[offset]) |
    ((uint32_t)buffer[offset + 1] << 8) |
    ((uint32_t)buffer[offset + 2] << 16) |
    ((uint32_t)buffer[offset + 3] << 24)
  );
}


// RADIO INITIALIZATION

void initializeRadio() {
  if (!radio.begin()) {
    Serial.println(F("ERROR: nRF24 not detected"));
    while (true);
  }

  radio.setChannel(76);
  radio.setDataRate(RF24_250KBPS);
  radio.setPALevel(RF24_PA_LOW);
  radio.setPayloadSize(PAYLOAD_SIZE);
  radio.setAutoAck(true);
  radio.setRetries(5, 15);

  radio.openReadingPipe(1, DEVICE_ADDRESS);
  radio.openWritingPipe(RASPI_ADDRESS);

  radio.flush_rx();
  radio.startListening();
}


// REGISTER REQUEST

void sendRegisterRequest() {
  byte packet[PAYLOAD_SIZE] = {0};

  packet[0] = MSG_REGISTER_REQUEST;
  memcpy(&packet[1], DEVICE_ADDRESS, 5);

  radio.stopListening();

  bool success = radio.write(packet, PAYLOAD_SIZE);

  radio.startListening();

  Serial.print(F("REGISTER_REQUEST -> RPi"));

  if (success) {
    Serial.println(F(" [ACK]"));
  } else {
    Serial.println(F(" [FAILED]"));
  }
}


// REGISTER ACK

void handleRegisterAck(byte* packet) {
  uint8_t status = packet[6];

  Serial.print(F("REGISTER_ACK <- Pi"));

  if (status == STATUS_ENABLED) {
    device_state = ENABLED;
    last_telemetry_timestamp = millis();
    Serial.println(F("STATUS: ENABLED"));
  }

  else if (status == STATUS_DISABLED) {
    device_state = DISABLED;
    Serial.println(F("STATUS: DISABLED"));
  }

  else {
    device_state = UNREGISTERED;
    Serial.println(F("STATUS: UNREGISTERED"));
  }
}


// START TRANSFER

void handleStartTransfer(byte* packet) {
  if (device_state != ENABLED) {
    return;
  }

  Serial.print(F("RAW packet[10]="));
  Serial.print(packet[10], HEX);

  Serial.print(F(" packet[11]="));
  Serial.println(packet[11], HEX);

  uint32_t message_id = readUInt32LE(packet, 6);
  uint16_t min_level = readUInt16LE(packet, 10);

  Serial.print(F("Decoded min_level="));
  Serial.println(min_level);

  if (message_id == prev_message_id) {
    sendTransferComplete();
    return;
  }

  prev_message_id = message_id;
  active_min_level = min_level;

  digitalWrite(RELAY_PIN, LOW);

  Serial.println();
  Serial.println(F("*** START_TRANSFER RECEIVED ***"));

  Serial.print(F("message_id="));
  Serial.println(prev_message_id);

  Serial.print(F("min_level="));
  Serial.println(active_min_level);

  Serial.println(F("(+) PUMP: ON"));

  uint16_t temp_water_level = getWaterLevel();

  // TRANSFERRING
  // TODO: ubah menjadi non-blocking process
  while (temp_water_level > active_min_level) {
    Serial.print(F("Water level: "));
    Serial.println(temp_water_level);
    delay(500);
    temp_water_level = getWaterLevel();
  }

  // TRANSFER DONE
  digitalWrite(RELAY_PIN, HIGH);
  Serial.println(F("(-) PUMP: OFF"));
  
  sendTransferComplete();
}


// TRANSFER COMPLETE

void sendTransferComplete() {
  delay(500);
  Serial.println(F("++ Building Transfer Complete Payload..."));
  byte packet[PAYLOAD_SIZE] = {0};

  packet[0] = MSG_TRANSFER_COMPLETE;
  memcpy(&packet[1], DEVICE_ADDRESS, 5);
  writeUInt32LE(packet, 6, prev_message_id);

  Serial.println(F("++ Sending Transfer Complete via Radio..."));

  radio.stopListening();

  bool success = radio.write(packet, PAYLOAD_SIZE);

  radio.startListening();

  Serial.print(F("TRANSFER_COMPLETE -> RPi, message_id="));
  Serial.print(prev_message_id);

  if (success) {
    Serial.println(F(" [ACK]"));
  } else {
    Serial.println(F(" [FAILED]"));
  }
}

void checkIncomingRadio() {
  if (!radio.available()) {
    return;
  }

  byte packet[PAYLOAD_SIZE] = {0};

  radio.read(packet, PAYLOAD_SIZE);

  // DEBUG NOISE YANG MUNCUL
  Serial.print(F("RX RAW: "));

  for (uint8_t i = 0; i < 12; i++) {
    if (packet[i] < 0x10) {
      Serial.print('0');
    }
    Serial.print(packet[i], HEX);
    Serial.print(' ');
  }
  
  Serial.println();

  uint8_t message_type = packet[0];

  if (message_type == MSG_REGISTER_ACK) {
    handleRegisterAck(packet);
  }

  else if (message_type == MSG_START_TRANSFER) {
    handleStartTransfer(packet);
  }
}


// REGISTRATION

void handleRegistration() {
  if (device_state == ENABLED) {
    return;
  }

  unsigned long now = millis();

  if (last_register_attempt == 0 || now - last_register_attempt >= REGISTER_RETRY_INTERVAL) {
    last_register_attempt = now;
    sendRegisterRequest();
  }
}

int16_t getWaterTemp() {
  waterTempSensor.requestTemperatures();
  float temperature = waterTempSensor.getTempCByIndex(0);
  return (int16_t)(temperature * 100);
}

int16_t getAirTemp() {
  return (int16_t)(htu.readTemperature() * 100);
}

uint16_t getHumidity() {
  return (uint16_t)(htu.readHumidity() * 100);
}

int16_t getPH() {
  // TODO
  return -100;
}

uint16_t getSalinityADC(uint8_t pin, uint8_t sample_count) {
  uint32_t total = 0;
  uint16_t min_value = 1023;
  uint16_t max_value = 0;
  // trimmed mean ADC
  for (uint8_t i = 0; i < sample_count; i++) {
    uint16_t value = analogRead(pin);
    total += value;

    if (value < min_value) {
      min_value = value;
    }
    if (value > max_value) {
      max_value = value;
    }

    delay(2);
  }

  total -= min_value;
  total -= max_value;

  return total / (sample_count - 2);
}

uint16_t getSalinity() {
  digitalWrite(DMS_S_PIN, LOW); // DMS ON (active LOW)

  delay(100);

  // Buang ADC reading pertama
  analogRead(DMS_ANALOG_PIN);

  uint16_t adc_value = getSalinityADC(DMS_ANALOG_PIN, 20);

  digitalWrite(DMS_S_PIN, HIGH); // DMS OFF

  // ADC -> konduktivitas (uS/cm)
  // ini masih pakai kalibrasi bawaan dari penjual
  float conductivity = (0.2142f * adc_value) + 494.93f;

  // konduktivitas -> salinitas (ppt)
  float salinity = conductivity * 0.00064f;

  Serial.print(F("Salinity ADC="));
  Serial.print(adc_value);

  Serial.print(F(" conductivity="));
  Serial.print(conductivity, 2);

  Serial.print(F(" uS/cm salinity="));
  Serial.print(salinity, 2);
  Serial.println(F(" ppt"));

  return (uint16_t)(salinity * 100.0f + 0.5f);
}

uint16_t getWaterLevel() {
  // trimmed mean
  const uint8_t sample_count = 10;

  uint32_t total = 0;
  uint16_t min_value = 1023;
  uint16_t max_value = 0;

  for (uint8_t i = 0; i < sample_count; i++) {
    uint16_t value = analogRead(WATER_LEVEL_PIN);

    total += value;
    
    if (value < min_value) {
      min_value = value;
    }
    if (value > max_value) {
      max_value = value;
    }

    delay(2);
  }
  
  // buang outlier nilai tertinggi dan terendah
  total -= min_value;
  total -= max_value;

  return total / (sample_count - 2);
}


// SEND TELEMETRY

void sendTelemetry() {
  byte packet[PAYLOAD_SIZE] = {0};
  
  int16_t water_temp = getWaterTemp();
  int16_t air_temp = getAirTemp();
  uint16_t humidity = getHumidity();
  int16_t ph = getPH();
  uint16_t salinity = getSalinity();
  uint16_t water_level = getWaterLevel();

  packet[0] = MSG_TELEMETRY;

  memcpy(&packet[1], DEVICE_ADDRESS, 5);

  writeUInt32LE(packet, 6, telemetry_sequence);
  writeInt16LE(packet, 10, water_temp);
  writeInt16LE(packet, 12, air_temp);
  writeUInt16LE(packet, 14, humidity);
  writeUInt16LE(packet, 16, water_level);
  writeUInt16LE(packet, 18, salinity);
  writeInt16LE(packet, 20, ph);

  radio.stopListening();
  bool success = radio.write(packet, PAYLOAD_SIZE);
  radio.startListening();
  
  Serial.print(F("TEL "));
  Serial.print(telemetry_sequence);

  Serial.print(F(" water_level="));
  Serial.print(water_level);

  Serial.print(F(" salinity="));
  Serial.print(salinity / 100.0);

  Serial.print(F(" water_temp="));
  Serial.print(water_temp / 100.0);

  Serial.print(F(" air_temp/humid="));
  Serial.print(air_temp / 100.0);
  Serial.print(F("/"));
  Serial.print(humidity / 100.0);
  Serial.print(F("%"));

  if (success) {
    Serial.println(F(" [ACK]"));
  } else {
    Serial.println(F(" [FAILED]"));
  }
  telemetry_sequence++;
}


// TELEMETRY

void handleTelemetry() {
  if (device_state != ENABLED) {
    return;
  }

  unsigned long now = millis();

  if (now - last_telemetry_timestamp >= TELEMETRY_INTERVAL) {
    last_telemetry_timestamp = now;
    sendTelemetry();
  }
}

void setup() {
  Serial.begin(115200);

  pinMode(RELAY_PIN, OUTPUT);
  digitalWrite(RELAY_PIN, HIGH); // Relay OFF

  pinMode(DMS_S_PIN, OUTPUT);
  digitalWrite(DMS_S_PIN, HIGH); // DMS OFF

  delay(2000);

  if (!htu.begin()) {
    Serial.println(F("Air Temp & Humidity Sensor not detected"));
  }

  waterTempSensor.begin();

  if (waterTempSensor.getDeviceCount() == 0) {
    Serial.println(F("Water Temperature Sensor not detected"));
  }

  Serial.println();
  Serial.println(F("===================="));
  Serial.println(F("SMART SALT TUNNEL v1"));
  Serial.println(F("===================="));

  initializeRadio();

  Serial.println();
}

void loop() {
  checkIncomingRadio();
  handleRegistration();
  handleTelemetry();
}
