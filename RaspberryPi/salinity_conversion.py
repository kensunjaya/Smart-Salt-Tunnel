import numpy as np

SUHU_REF = np.array([25., 35., 40., 50.])

PPT = np.array([1, 2.5, 4, 6, 7.5, 10, 11, 13, 14.5, 16, 18, 20, 22, 23.5, 25.5])

ADC_REF = np.array([
    [625, 629, 632, 638], # 1 gram
    [662, 666, 668, 674], # 2 gram
    [685, 687, 691, 696], # 3 gram
    [695, 697, 700, 704], # 4 gram
    [700, 703, 705, 709], # 5 gram
    [709, 710, 711, 713], # 6 gram
    [713, 714, 715, 716], # 7 gram
    [719, 720, 721, 722], # 8 gram
    [722, 723, 724, 726], # 9 gram
    [725, 726, 727, 728], # 10 gram
    [726, 727, 728, 730], # 11 gram
    [728, 729, 730, 731], # 12 gram
    [730, 731, 732, 733], # 13 gram
    [732, 733, 734, 735], # 14 gram
    [734, 735, 735, 736], # 15 gram
], dtype=float)


# Data densitas NaCl berdasarkan konsentrasi dan temperatur
PPT_SG = np.array([0, 10, 20, 40, 80, 120, 160, 200, 240, 260])
SUHU_SG = np.array([0, 10, 25, 40, 60, 80, 100])

DENSITAS = np.array([
    [0.9998395, 0.9997026, 0.9970479, 0.9922, 0.9832, 0.9718, 0.9584],
    [1.00747, 1.00707, 1.00409, 0.99908, 0.9900, 0.9785, 0.9651],
    [1.01509, 1.01442, 1.01112, 1.00593, 0.9967, 0.9852, 0.9719],
    [1.03038, 1.02920, 1.02530, 1.01977, 1.0103, 0.9988, 0.9855],
    [1.06121, 1.05907, 1.05412, 1.04798, 1.0381, 1.0264, 1.0134],
    [1.09244, 1.08946, 1.08365, 1.07699, 1.0667, 1.0549, 1.0420],
    [1.12419, 1.12056, 1.11401, 1.10688, 1.0962, 1.0842, 1.0713],
    [1.15663, 1.15254, 1.14533, 1.13774, 1.1268, 1.1146, 1.1017],
    [1.18999, 1.18557, 1.17776, 1.16971, 1.1584, 1.1463, 1.1331],
    [1.20709, 1.20254, 1.19443, 1.18614, 1.1747, 1.1626, 1.1492],
])

# Menghitung SG dari data densitas
SG_REF = DENSITAS / DENSITAS[0]

# Regresi kuadratik untuk masing-masing temperatur
MODEL_SG = [
    np.polyfit(PPT_SG, SG_REF[:, i], 2)
    for i in range(len(SUHU_SG))
]


# Membentuk kurva ADC berdasarkan temperatur
def kurva_adc(suhu):
    suhu = np.clip(float(suhu), 25., 50.)

    return np.array([
        np.interp(suhu, SUHU_REF, baris)
        for baris in ADC_REF
    ])


# Konversi ADC -> ppt
def adc_ke_ppt(adc, suhu):
    if adc is None or suhu is None:
        return None

    if not np.isfinite(adc) or not np.isfinite(suhu) or not 0 <= adc <= 1023:
        return None

    kurva = kurva_adc(suhu)

    if adc < kurva[0]:
        return 0.0

    # Linear interpolation (untuk ADC dalam range kurva)
    if adc <= kurva[-1]:
        return float(np.interp(adc, kurva, PPT))

    # cubic regression extrapolation
    batas = kurva[-1]
    a, b, c, _ = np.polyfit(kurva - batas, PPT, 3)

    x = adc - batas

    return float(PPT[-1] + c*x + b*x*x + a*x*x*x)


# Konversi ppt -> SG
def ppt_ke_sg(ppt, suhu):
    if ppt is None or suhu is None:
        return None

    if not np.isfinite(ppt) or not np.isfinite(suhu) or ppt < 0:
        return None

    if ppt == 0:
        return 1.0

    suhu = np.clip(float(suhu), 0., 100.)

    # Prediksi SG pada setiap temperatur referensi
    sg_per_suhu = [
        np.polyval(model, ppt)
        for model in MODEL_SG
    ]

    # Interpolasi SG berdasarkan temperatur aktual
    return float(np.interp(suhu, SUHU_SG, sg_per_suhu))


# Konversi SG -> derajat Be
def sg_ke_baume(sg):
    if sg is None or not np.isfinite(sg) or sg <= 0:
        return None

    return float(145 - 145 / sg)


# Konversi ADC -> ppt -> SG -> Be
def konversi_salinitas(adc, suhu):
    ppt = adc_ke_ppt(adc, suhu)
    sg = ppt_ke_sg(ppt, suhu)

    return {
        "ppt": ppt,
        "sg": sg,
        "baume": sg_ke_baume(sg)
    }