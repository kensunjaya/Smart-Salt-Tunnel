# Smart-Salt-Tunnel
Smart Salt Tunnel Schema, Integration Code + NRF24L01 communication

<img width="3248" height="2299" alt="Schematic_Smart-Salt-Tunnel-std-v1_2026-09-18-2-1" src="https://github.com/user-attachments/assets/f900956e-dba4-4007-935e-134dbdd30bd3" />


```text
TDS Sensor      Arduino
-----------------------
VCC         -> 5V
GND         -> GND
AO          -> A1
```

```text
Salinity Sensor    Arduino
---------------------------
VCC            -> 5V
GND            -> GND
OUT            -> A0
```

```text
Water Level Sensor    Arduino
--------------------------------
+                 -> 5V
-                 -> GND
S                 -> A2
```

```text
DS18B20         Arduino
------------------------
VCC         -> 5V
GND         -> GND
DATA        -> D2
```

```text
HTU21D      Arduino
--------------------
+       -> 3.3V
-       -> GND
DA      -> A4
CL      -> A5
```

```text
NRF24L01      Arduino
----------------------
VCC       -> 3.3V
GND       -> GND
CE        -> D7
CSN       -> D8
MOSI      -> D11
MISO      -> D12
SCK       -> D13
IRQ       -> NC
```
