#include <EEPROM.h>

void setup() {
  Serial.begin(115200);

  const char DEVICE_ID[] = "A0002"; // unique identifier untuk setiap tunnel

  for (uint8_t i = 0; i < 5; i++) {
    EEPROM.update(i, DEVICE_ID[i]);
  }

  Serial.println("Device ID saved to EEPROM");
}

void loop() {
}
