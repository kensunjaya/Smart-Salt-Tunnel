#include <SPI.h>
#include <RF24.h>

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

void setup() {
  Serial.begin(115200);
  delay(500);
  if (!radio.begin()) {
    Serial.println("NRF NOT FOUND");
    while (1);
  }

  Serial.println("NRF FOUND");

  radio.openReadingPipe(0, address);

  radio.setPALevel(RF24_PA_LOW);
  radio.setDataRate(RF24_250KBPS);
  radio.setChannel(76);

  radio.startListening();
}

void loop() {

  if (radio.available()) {

    radio.read(&data, sizeof(data));
    if (data.airTemp > 0) {    
      Serial.println("===== DATA =====");
  
      Serial.print("TDS: ");
      Serial.println(data.tds);
  
      Serial.print("Salinity: ");
      Serial.println(data.salinity);
  
      Serial.print("Water Temp: ");
      Serial.println(data.waterTemp);
  
      Serial.print("Air Temp: ");
      Serial.println(data.airTemp);
  
      Serial.print("Humidity: ");
      Serial.println(data.humidity);
  
      Serial.print("Water Level: ");
      Serial.println(data.waterLevel);
  
      Serial.println();     
    }

  }
}
