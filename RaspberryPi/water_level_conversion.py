WATER_LEVEL_MAX_MM = 40.0  # Panjang area pengukuran sensor

def adc_ke_mm(adc):
    adc = max(0, min(adc, 1023))
    return float(adc / 1023 * WATER_LEVEL_MAX_MM)


def mm_ke_adc(mm):
    mm = max(0, min(mm, WATER_LEVEL_MAX_MM))
    return int(round(mm / WATER_LEVEL_MAX_MM * 1023))