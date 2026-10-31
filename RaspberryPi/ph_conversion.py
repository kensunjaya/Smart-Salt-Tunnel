def adc_ke_ph(adc):
    if adc is None or not 0 <= adc <= 1023:
        return None

    voltage = adc * 5.0 / 1024.0

    v_ph686 = 3.6354
    v_ph401 = 3.962875

    ph_step = (v_ph401 - v_ph686) / (6.86 - 4.01)

    return float(6.86 - (voltage - v_ph686) / ph_step)