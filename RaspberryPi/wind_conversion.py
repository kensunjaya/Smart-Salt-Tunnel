V_REF = 5.0
RESISTOR = 220.0
WIND_MAX_MS = 70.0

def adc_ke_windspeed(adc):
    if adc is None or not isinstance(adc, (int, float)) or not 0 <= adc <= 1023:
        return None

    voltage = adc * V_REF / 1023.0
    current_ma = voltage / RESISTOR * 1000.0

    if current_ma < 3.5 or current_ma > 21.0:
        return None

    # value dibawah 4 mA dianggap 0 m/s, angka diatas 20 mA dianggap 70 m/s
    return round(max(0.0, min((current_ma - 4.0) / 16.0 * WIND_MAX_MS, WIND_MAX_MS)), 2)
