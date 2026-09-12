/*
SMART SALT TUNNEL v1
Author: Kenneth Sunjaya
Last Updated: 12 September 2026
*/

#include <EEPROM.h>
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
byte DEVICE_ADDRESS[6]; // unique identifier untuk setiap tunnel

const uint8_t PAYLOAD_SIZE = 32;

// MESSAGE TYPES MAPPING
const uint8_t MSG_REGISTER_REQUEST = 1;
const uint8_t MSG_REGISTER_ACK = 2;
const uint8_t MSG_TELEMETRY = 3;
const uint8_t MSG_START_TRANSFER = 4;
const uint8_t MSG_TRANSFER_COMPLETE = 5;
const uint8_t MSG_SET_STATUS = 6;


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
const unsigned long TELEMETRY_JITTER = 1000; // range untuk jitter interval yang diperbolehkan, untuk menghindari beberapa tunnel kirim telemetry secara bersamaan

unsigned long current_telemetry_interval = TELEMETRY_INTERVAL;
unsigned long last_register_attempt = 0;
unsigned long last_telemetry_timestamp = 0;


// MESSAGE STATE
uint32_t telemetry_sequence = 0;
uint32_t active_message_id = 0;
uint32_t last_completed_message_id = 0;
uint16_t active_min_level = 0;
bool transfer_active = false;
unsigned long last_transfer_check = 0;
const unsigned long TRANSFER_CHECK_INTERVAL = 500;

bool is_htu_available = true;
bool is_water_temp_available = true;

// baca tunnel id dari EEPROM
bool loadDeviceAddress() {
  for (uint8_t i = 0; i < 5; i++) {
    DEVICE_ADDRESS[i] = EEPROM.read(i);

    if (DEVICE_ADDRESS[i] == 0xFF) {
      return false;
    }
  }

  DEVICE_ADDRESS[5] = '\0';

  return true;
}

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
  radio.setAutoAck(true); // enhanced shockburst autoack (ESB)
  radio.setRetries(5, 15); // retry delay, banyaknya retry yg diperbolehkan

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

  Serial.print(F("(TX) REGISTER_REQUEST -> RPi"));

  if (success) {
    Serial.println(F(" [ACK]"));
  } else {
    Serial.println(F(" [FAILED]"));
  }
}


// REGISTER ACK

void handleRegisterAck(byte* packet) {
  uint8_t status = packet[6];

  Serial.print(F("(RX) REGISTER_ACK <- Pi"));

  if (status == STATUS_ENABLED) {
    device_state = ENABLED;
    last_telemetry_timestamp = millis();
  
    generateNextTelemetryInterval();
  
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

void handleSetStatus(byte* packet) {
  uint8_t status = packet[6];

  if (status == STATUS_DISABLED) {
    device_state = DISABLED;

    digitalWrite(RELAY_PIN, HIGH); // jika status disabled dikirimkan, maka langsung paksa matikan pompa

    if (transfer_active) {
      transfer_active = false;
      active_message_id = 0;

      Serial.println(F("Active transfer cancelled"));
    }

    Serial.println(F("(RX) DEVICE DISABLED"));
    Serial.println(F("(-) PUMP: OFF"));
    return;
  }

  if (status == STATUS_ENABLED) {
    device_state = ENABLED;
  
    last_telemetry_timestamp = millis(); // reset last telemetry timetamp agar menghindari telemetry langsung terkirim jika memang sudah jatuh tempo
    generateNextTelemetryInterval();
  
    Serial.println(F("(RX) DEVICE ENABLED"));
  }
}


// START TRANSFER

void handleStartTransfer(byte* packet) {
  if (device_state != ENABLED) {
    return;
  }

  uint32_t message_id = readUInt32LE(packet, 6);
  uint16_t min_level = readUInt16LE(packet, 10);

  Serial.println();
  Serial.println(F("(RX) START_TRASNFER"));

  Serial.print(F("message_id="));
  Serial.println(message_id);

  Serial.print(F("min_level="));
  Serial.println(min_level);

  // jika masih ada transfer yang sedang berjalan
  if (transfer_active) {
    if (message_id == active_message_id) {
      Serial.println(F("Transfer already active"));
    } else {
      Serial.println(F("Another transfer is already active, ignoring"));
    }

    return;
  }

  // transfer ini udah selesai sebelumnya
  if (message_id == last_completed_message_id) {
    Serial.println(F("Transfer already completed, resending TRANSFER_COMPLETE"));
    sendTransferComplete(last_completed_message_id);
    return;
  }

  // mulai transfer air
  active_message_id = message_id;
  active_min_level = min_level;
  transfer_active = true;

  last_transfer_check = 0;

  digitalWrite(RELAY_PIN, LOW);

  Serial.println(F("(+) PUMP: ON"));
}

void handleTransfer() {
  if (!transfer_active) {
    return;
  }

  unsigned long now = millis();

  if (last_transfer_check != 0 &&
      now - last_transfer_check < TRANSFER_CHECK_INTERVAL) {
    return;
  }

  last_transfer_check = now;

  uint16_t water_level = getWaterLevel();

  Serial.print(F("Transfer water_level="));
  Serial.print(water_level);

  Serial.print(F(" min_level="));
  Serial.println(active_min_level);

  if (water_level <= active_min_level) {
    digitalWrite(RELAY_PIN, HIGH);

    Serial.println(F("(-) PUMP: OFF"));
    Serial.println(F("*** MINIMUM WATER LEVEL REACHED ***"));

    uint32_t completed_message_id = active_message_id;

    transfer_active = false;
    active_message_id = 0;

    last_completed_message_id = completed_message_id;

    sendTransferComplete(completed_message_id);
  }
}

// TRANSFER COMPLETE
void sendTransferComplete(uint32_t message_id) {
  byte packet[PAYLOAD_SIZE] = {0};

  packet[0] = MSG_TRANSFER_COMPLETE;
  memcpy(&packet[1], DEVICE_ADDRESS, 5);
  writeUInt32LE(packet, 6, message_id);

  Serial.println(F("++ Sending Transfer Complete via Radio..."));

  radio.stopListening();

  bool success = radio.write(packet, PAYLOAD_SIZE);

  radio.startListening();

  Serial.print(F("TRANSFER_COMPLETE -> RPi, message_id="));
  Serial.print(message_id);

  if (success) {
    Serial.println(F(" [ACK]"));
  } else {
    Serial.println(F(" [FAILED]"));
  }
}

// CEK BUFFER FIFO RX
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

  else if (message_type == MSG_SET_STATUS) {
    handleSetStatus(packet);
  }
}


// REGISTRATION
void handleRegistration() {
  if (device_state != REGISTERING && device_state != UNREGISTERED) {
    return;
  }

  unsigned long now = millis();

  if (last_register_attempt == 0 || now - last_register_attempt >= REGISTER_RETRY_INTERVAL) {
    last_register_attempt = now;
    sendRegisterRequest();
  }
}

// SENSOR READINGS
int16_t getWaterTemp() {
  if (!is_water_temp_available) {
    return -1;
  }
  waterTempSensor.requestTemperatures();
  float temperature = waterTempSensor.getTempCByIndex(0);
  return (int16_t)(temperature * 100);
}

int16_t getAirTemp() {
  if (!is_htu_available) {
    return -1;
  }
  return (int16_t)(htu.readTemperature() * 100);
}

int16_t getHumidity() {
  if (!is_htu_available) {
    return -1;
  }
  return (int16_t)(htu.readHumidity() * 100);
}

int16_t getPH() {
  // TODO
  return -1;
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

  delay(100); // tunggu sebentar sampai sensor stabil

  // buang ADC reading pertama
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
  int16_t humidity = getHumidity();
  int16_t ph = getPH();
  uint16_t salinity = getSalinity();
  uint16_t water_level = getWaterLevel();

  packet[0] = MSG_TELEMETRY;

  memcpy(&packet[1], DEVICE_ADDRESS, 5);

  writeUInt32LE(packet, 6, telemetry_sequence);
  writeInt16LE(packet, 10, water_temp);
  writeInt16LE(packet, 12, air_temp);
  writeInt16LE(packet, 14, humidity);
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



// menambahkan offset jitter pada telemetry interval secara acak
void generateNextTelemetryInterval() {
  long jitter = random(-(long)TELEMETRY_JITTER, (long)TELEMETRY_JITTER + 1);
  current_telemetry_interval = TELEMETRY_INTERVAL + jitter;
}

// TELEMETRY (menentukan akan kirim telemetry atau tidak)
void handleTelemetry() {
  if (device_state != ENABLED || transfer_active) {
    return;
  }

  unsigned long now = millis();

  if (now - last_telemetry_timestamp >= current_telemetry_interval) {
    last_telemetry_timestamp = now;
    sendTelemetry();
    generateNextTelemetryInterval();
  }
}

void setup() {
  Serial.begin(115200);

  if (!loadDeviceAddress()) {
    Serial.println(F("ERROR: Device ID not configured"));
    while (true);
  }

  Serial.print(F("[LOADED] Device ID: "));
  Serial.println((char*)DEVICE_ADDRESS);

  randomSeed(analogRead(A1)); // random seed noise untuk jitter interval

  pinMode(RELAY_PIN, OUTPUT);
  digitalWrite(RELAY_PIN, HIGH); // Relay OFF

  pinMode(DMS_S_PIN, OUTPUT);
  digitalWrite(DMS_S_PIN, HIGH); // DMS OFF

  delay(2000);

  is_htu_available = htu.begin();

  if (!is_htu_available) {
    Serial.println(F("Air Temp & Humidity Sensor not detected"));
  }

  waterTempSensor.begin();
  // waktu pembacaan waterTempSensor adalah ~750ms karena 12bit. bisa dikurangi menjadi ~188ms jika diset ke 10bit tapi presisinya berkurang
  // waterTempSensor.setResolution(10);
  is_water_temp_available = waterTempSensor.getDeviceCount() > 0;

  if (!is_water_temp_available) {
    Serial.println(F("Water Temperature Sensor not detected"));
  }

  initializeRadio();

  Serial.println();
}

void loop() {
  checkIncomingRadio();
  handleRegistration();
  handleTelemetry();
  handleTransfer();
}
