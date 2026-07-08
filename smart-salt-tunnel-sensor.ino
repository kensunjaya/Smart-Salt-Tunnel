// Library yang harus diinstal: RF24, OneWire, DallasTemperature, DHT sensor library
#include <SPI.h>
#include <RF24.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include <DHT.h>

// DS18B20
#define ONE_WIRE_BUS A3

// DHT11
#define DHT_PIN 7
#define DHT_TYPE DHT11

// NRF24L01
#define NRF_CE_PIN 9
#define NRF_CSN_PIN 10

// Analog sensors
#define WATER_LEVEL_PIN A2
#define DMS_ANALOG_PIN A1
#define DMS_S_PIN 4

OneWire oneWire(ONE_WIRE_BUS);
DallasTemperature waterTemperature(&oneWire);

DHT dht(DHT_PIN, DHT_TYPE);

RF24 radio(NRF_CE_PIN, NRF_CSN_PIN);
const byte radioAddress[6] = "TUNL1";

// nrf24 payload
struct SensorData {
  float waterTemperature;
  float airTemperature;
  float humidity;
  int waterLevel;
  float salinitas;
};

SensorData data;

int readAverageADC(int pin, int samples) {
  long total = 0;
  for (int i = 0; i < samples; i++) {
    total += analogRead(pin);
    delay(10);
  }
  return total / samples;
}

float readSalinitas() {
  digitalWrite(DMS_S_PIN, LOW); // Mengaktifkan DMS

  Serial.println(F("DMS ACTIVE. Waiting 10 seconds until DMS stabilizes"));
  
  delay(10000);

  // Read ADC
  int adcVal = readAverageADC(DMS_ANALOG_PIN, 20);

  Serial.print(F("ADC sensor salinitas: "));
  Serial.println(adcVal);

  // ADC -> konduktivitas (uS/cm)
  float konduktivitas = (0.2142 * adcVal) + 494.93;

  Serial.print(F("Konduktivitas: "));
  Serial.print(konduktivitas);
  Serial.println(F(" uS/cm"));

  // konduktivitas -> salinitas (ppt)
  float salinitas = konduktivitas * 0.00064;

  digitalWrite(DMS_S_PIN, HIGH); // Disable DMS

  Serial.println(F("DMS OFF"));
  Serial.println();

  return salinitas;
}


void setup() {

  Serial.begin(9600);
  
  // DS18B20
  waterTemperature.begin();

  // DHT11
  dht.begin();

  // setup pin
  pinMode(WATER_LEVEL_PIN, INPUT);
  pinMode(DMS_ANALOG_PIN, INPUT);
  pinMode(DMS_S_PIN, OUTPUT);

  digitalWrite(DMS_S_PIN, HIGH); // non-aktifkan DMS

  // NRF24 setup
  if (!radio.begin()) {
    Serial.println(F("NRF24 NOT DETECTED"));
    while (1) {
      delay(1000);
    }
  }

  radio.openWritingPipe(radioAddress);
  radio.setPALevel(RF24_PA_LOW);
  radio.setDataRate(RF24_1MBPS);
  radio.stopListening();

  Serial.println(F("Done setup"));
  Serial.println();
}


void loop() {
  getSensorData();
  printSensorData();
  sendSensorData();
  delay(2000);
}

void getSensorData() {
  // baca DS18B20
  waterTemperature.requestTemperatures();
  data.waterTemperature = waterTemperature.getTempCByIndex(0);

  // baca DHT11
  data.airTemperature = dht.readTemperature();
  data.humidity = dht.readHumidity();

  // baca water level sensor
  data.waterLevel = analogRead(WATER_LEVEL_PIN);

  // baca sensor salinitas
  data.salinitas = readSalinitas();
}

void printSensorData() {
  Serial.println(F("----- NRF PAYLOAD -----"));
  Serial.print(F("Water Temperature : "));
  Serial.print(data.waterTemperature);
  Serial.println(F(" C"));

  Serial.print(F("Air Temperature   : "));
  Serial.print(data.airTemperature);
  Serial.println(F(" C"));

  Serial.print(F("Humidity          : "));
  Serial.print(data.humidity);
  Serial.println(F(" %"));

  Serial.print(F("Water Level ADC   : "));
  Serial.println(data.waterLevel);

  Serial.print(F("Salinitas         : "));
  Serial.print(data.salinitas);
  Serial.println(F(" ppt"));
  
  Serial.println();
}

void sendSensorData() {
  bool success = radio.write(&data, sizeof(data));

  if (success) {
    Serial.println(F("NRF24: Data transmitted successfully"));
  } 
  else {
    Serial.println(F("NRF24: Transmission failed"));
  }
}
