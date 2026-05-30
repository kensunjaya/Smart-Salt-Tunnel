#include <OneWire.h>
#include <DallasTemperature.h>
#include <Wire.h>
#include <Adafruit_HTU21DF.h>
#include <SPI.h>
#include <RF24.h>

#define TdsSensorPin A1
#define SalinitySensorPin A0
#define WATER_LEVEL_PIN A2
#define ONE_WIRE_BUS 2

#define VREF 5.0
#define SCOUNT 30

// suhu air
OneWire oneWire(ONE_WIRE_BUS);

DallasTemperature sensor_suhu_air(&oneWire);
Adafruit_HTU21DF htu = Adafruit_HTU21DF();
RF24 radio(7, 8);

const byte address[6] = "NODE1";

struct SensorData {
  float tds;
  float salinity;
  float waterTemp;
  float airTemp;
  float humidity;
  int waterLevel;
};

SensorData data;

// TDS buffers
int tdsBuffer[SCOUNT];
int tdsBufferTemp[SCOUNT];
int tdsBufferIndex = 0;

// Salinity buffers
int salinityBuffer[SCOUNT];
int salinityBufferTemp[SCOUNT];
int salinityBufferIndex = 0;

// Water Level Buffers
int waterLevelBuffer[SCOUNT];
int waterLevelBufferTemp[SCOUNT];
int waterLevelBufferIndex = 0;

float averageVoltage = 0;
float tdsValue = 0;
float temperature = 29.0;

// Median filter
int getMedianNum(int bArray[], int iFilterLen) {
    int bTab[iFilterLen];

    for (int i = 0; i < iFilterLen; i++) {
        bTab[i] = bArray[i];
    }

    int bTemp;

    for (int j=0; j < iFilterLen - 1; j++) {
        for (int i=0; i < iFilterLen-j-1; i++) {
            if (bTab[i] > bTab[i + 1]) {
                bTemp = bTab[i];
                bTab[i] = bTab[i + 1];
                bTab[i + 1] = bTemp;
            }
        }
    }

    if ((iFilterLen & 1) > 0) {
        bTemp = bTab[(iFilterLen - 1) / 2];
    }
    else {
        bTemp = (bTab[iFilterLen / 2] + bTab[iFilterLen / 2 - 1]) / 2;
    }
    return bTemp;
}

void setup()
{
  Serial.begin(115200);

  delay(500);
  
  pinMode(TdsSensorPin, INPUT);
  pinMode(SalinitySensorPin, INPUT);
  
  if (radio.begin()) {
    Serial.println("NRF FOUND");
    radio.printDetails();
    radio.openWritingPipe(address);

    radio.setPALevel(RF24_PA_LOW);
    radio.setDataRate(RF24_250KBPS);
    radio.setChannel(76);
    
    radio.stopListening();
  } else {
    Serial.println("NRF NOT FOUND");
  }
  sensor_suhu_air.begin();
  htu.begin();
}

void loop()
{
    static unsigned long analogSampleTimepoint = millis();

    // Sample sensors every 40 ms
    if (millis() - analogSampleTimepoint > 40U) {
        analogSampleTimepoint = millis();

        // Read TDS sensor
        tdsBuffer[tdsBufferIndex] = analogRead(TdsSensorPin);
        tdsBufferIndex++;

        if (tdsBufferIndex >= SCOUNT) {
            tdsBufferIndex = 0;
        }

        // Read Salinity sensor
        salinityBuffer[salinityBufferIndex] = analogRead(SalinitySensorPin);
        salinityBufferIndex++;

        if (salinityBufferIndex >= SCOUNT) {
            salinityBufferIndex = 0;
        }

        // Read Water Level Sensor
        waterLevelBuffer[waterLevelBufferIndex] = analogRead(WATER_LEVEL_PIN);
        waterLevelBufferIndex++;
        
        if (waterLevelBufferIndex >= SCOUNT) {
            waterLevelBufferIndex = 0;
        }
    }

    static unsigned long printTimepoint = millis();

    // Process and print every 1.2 seconds
    if (millis() - printTimepoint > 1200U) {
        printTimepoint = millis();

        // Copy buffers for filtering
        for (int i = 0; i < SCOUNT; i++) {
            tdsBufferTemp[i] = tdsBuffer[i];
            salinityBufferTemp[i] = salinityBuffer[i];
        }

        // ===== TDS Processing =====

        int tdsMedianADC = getMedianNum(tdsBufferTemp, SCOUNT);

        averageVoltage = tdsMedianADC * VREF / 1024.0;

        float compensationCoefficient = 1.0 + 0.02 * (temperature - 25.0);

        float compensationVoltage = averageVoltage / compensationCoefficient;

        tdsValue = (133.42 * compensationVoltage * compensationVoltage * compensationVoltage
            - 255.86 * compensationVoltage * compensationVoltage + 857.39 * compensationVoltage) * 0.5;

        // ===== Salinity Processing =====

        int salinityMedianADC = getMedianNum(salinityBufferTemp, SCOUNT);

        float salinityVoltage = salinityMedianADC * VREF / 1024.0;

        // ===== Water Level Processing =====

        for(int i = 0; i < SCOUNT; i++) {
            waterLevelBufferTemp[i] = waterLevelBuffer[i];
        }
        
        int waterLevelADC = getMedianNum(waterLevelBufferTemp, SCOUNT);

        // ===== Ambil bacaan sensor suhu air DS =====

        sensor_suhu_air.requestTemperatures();
        float sensorSuhuAirCelcius = sensor_suhu_air.getTempCByIndex(0);

        // ===== Ambil bacaan sensor HTU =====

        temperature = htu.readTemperature();
        float humidity = htu.readHumidity();  

        // ===== Output =====

        Serial.print("TDS: ");
        Serial.print(tdsValue, 0);
        Serial.println(" ppm");
        
        Serial.print("Salinity ADC: ");
        Serial.println(salinityMedianADC);

        Serial.print("Water Level ADC: ");
        Serial.println(waterLevelADC);

        Serial.print("Suhu Air: ");
        Serial.print(sensorSuhuAirCelcius);
        Serial.println(" °C");

        Serial.print("Suhu Udara: ");
        Serial.print(temperature);
        Serial.print(" °C");
      
        Serial.print(" | Humidity: ");
        Serial.print(humidity);
        Serial.println(" %");

        data.tds = tdsValue;
        data.salinity = salinityMedianADC;
        data.waterTemp = sensorSuhuAirCelcius;
        data.airTemp = temperature;
        data.humidity = humidity;
        data.waterLevel = waterLevelADC;

        bool ok = radio.write(&data, sizeof(data));

        if (ok) Serial.println("(v) Sent");
        else Serial.println("(x) Failed");
        Serial.println();
    }
}
