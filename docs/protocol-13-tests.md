# البروتوكول المعتمد — SHIMADZU-LC2050C-UV-CAL v1.0.0

الجهاز: Shimadzu i-Series LC-2050C (UV Detector + Sample Cooler)
رقم القطعة: `S228-65821-58` · الرقم التسلسلي المسجل: `L22976302572`
الدورية: كل 180 يوماً أو بعد أي صيانة كبرى.

لكل اختبار: المعادلة المُنفَّذة حرفياً في المحرك، والحدود المعتمدة، ومصدرها.

---

## T01 — التحقق التلقائي الشامل (Auto Validation, GRAD)
**المرجع:** Integrity Guide Ch.2
**الحدود المعتمدة (AUTHORITY_LIMIT):** انحراف الطول الموجي ≤ 1.0 nm · طاقة D2 ≥ 400 mV ·
النبض ≤ 0.20 MPa · ثبات الفرن ≤ 0.20°C · انحراف الامتصاصية ≤ 3.0% · الضجيج ≤ 0.0200 mAU ·
الانحراف ≤ 0.60 mAU/h · انحراف التدرج ≤ 2.00%.
**الإجراء:** Menu → Maintenance → Validation → Auto Validation → الوضع [GRAD.] → A/B, A/C, A/D،
أنبوب مقاومة 228-38994 في الفرن، كافيين 10 mg/L في A وماء في B/C/D.

## T02 — دقة معدل التدفق
```
actual_flow = (collected_vol × 60) / actual_time
%error      = ((actual_flow − set_flow) / set_flow) × 100      → المقياس: max(|%error|)
```
| المصدر | الحد |
|---|---|
| Ch.2 | ±2.00% |
| iOQ (وزني) | ±2.5% |
| المصنع | ±1.0% |
| SOP | ±2.0% |
| **AUTHORITY** | **±2.00%** (و±1.0% كحد تنبيهي) |

## T03 — نبض الضغط ومحدداته
`pulsation ≤ 0.20 MPa` عند 1 mL/min و40°C + نجاح المحدد العلوي والسفلي (Passed).

## T04 — دقة صمام التدرج GPV
```
%Actual(x) = [(Height_x − Height_0) / (Height_100 − Height_0)] × 100
Deviation  = %Actual(x) − x                                  → المقياس: max|Deviation|
```
الحد: **±2.00%** لكل مستوى (10, 50, 90, 100%) ولكل زوج قنوات (A/B, A/C, A/D).
*(GAP-03 مغلقة: المعادلة من iOQ ص192 بعد أن كانت غائبة من SOP.)*

## T05 — دقة حجم الحقن الوزنية
```
measured_vol = ((W1 − W2) × 1000) / water_density
%accuracy    = ((measured_vol / (set_vol × N)) − 1) × 100     → المقياس: |%accuracy|
```
| المصدر | الحد |
|---|---|
| Ch.2 | ±1.3% (10×50 µL) |
| iOQ | ±2.0% (50 µL) · ±5.0% (20×5 µL) |
| المصنع | ±1.0% |
| **AUTHORITY** | **±1.3%** |

*(GAP-06 مغلقة: هذا اختبار دقة، منفصل تماماً عن تكرارية المساحة.)*

## T06 — خطية الحاقن وتكرارية الحلقة
```
R², slope, intercept = OLS(volumes, areas)        → الحد R² ≥ 0.9990
%RSD = (SD(n−1) / Mean) × 100                     → الحد ≤ 2.0%
```

## T07 — دقة حرارة مبرد العينات
```
T_Ref_Corrected = T_ref_raw + offset(certificate)
Error           = T_Ref_Corrected − T_Set          → المقياس: |Error|
```
**الحد المعتمد:** 4°C ± 3.0°C · انتظار ≥ 90 دقيقة · حرارة غرفة ≤ 30°C · قارورة 1.5 mL بماء 1 mL
في **الموقع 27** على الصفيحة المعدنية 228-61615-42.
*(GAP-08 مغلقة: SOP كان يضع الميزان داخل فرن العمود — خطأ جسيم مرفوض.)*

## T08 — حرارة فرن العمود وحساس الغاز
```
|T_Set − T_Ref_Corrected|      ≤ 2.0°C   (AUTHORITY)
|T_Display − T_Ref_Corrected|  ≤ 2.0°C
Fluctuation                    ≤ 0.20°C
Gas Sensor                     = Passed
```
*(GAP-07 مغلقة: تُسجَّل القيم الثلاث Set/Display/Reference بدل الغموض السابق.)*

## T09 — طاقة لمبة D2 ودقة الطول الموجي
| المقياس | الحد المعتمد |
|---|---|
| طاقة D2 عند 220 nm | ≥ 400 mV |
| انحراف الطول الموجي | ≤ 1.0 nm |
| قمة الكافيين 1 (205 nm) | ≤ 2.0 nm انحراف |
| القاع (245 nm) | ≤ 2.0 nm انحراف |
| قمة الكافيين 2 (273 nm) | ≤ 2.0 nm انحراف |
حد استبدال اللمبة 2000 ساعة · تنبيه استباقي عند 1800.
*(GAP-09 مغلقة: مسح كامل 200–280 nm بخطوة 1 nm بدل فقدان نقطة 246 nm.)*

## T10 — دقة الامتصاصية وخطية الكاشف
```
|absorbance_dev| ≤ 3.0%                            (فلتر داخلي أو JCRM230A)
R² = OLS(concs, heights) ≥ 0.9990                   (iOQ)
RS_i = Height_i / Conc_i ; Std_RS = (RS1+RS2+RS3)/3
%Dev_i = ((RS_i − Std_RS) / Std_RS) × 100           → max|%Dev| ≤ 5.0%   (Ch.2)
```

## T11 — ضجيج وانحراف خط الأساس (ASTM E1657-98)
| المقياس | AUTHORITY | Ch.2 | iOQ |
|---|---|---|---|
| Noise | ≤ 0.0200 mAU | ≤ 0.0200 mAU | ≤ 0.04 mAU |
| Drift | ≤ 0.60 mAU/h | ≤ 0.60 mAU/h | ≤ ±0.50 mAU/h |

قياس 15 دقيقة = 30 فترة × 30 ثانية، والانحراف الساعي = 4 × ميل الـ 15 دقيقة.
*(GAP-02 مغلقة: حدود SOP بوحدة `AU/h` وقيم أكبر 1000 مرة مُصنَّفة `CONFLICT_REQUIRES_QA` ولا تُنتج PASS.)*

## T12 — تكرارية النظام والترحيل المتبقي
```
%RSD(RT)   ≤ 0.5%     (6 حقنات)
%RSD(Area) ≤ 1.0%
Carryover_Ch.2 = (Area_Blank / Area_Sample_250) × 100          ≤ 0.010%   ← AUTHORITY
Carryover_iOQ  = (Area_Blank / (5 × Area_Sample_50)) × 100     ≤ 0.100%   ← CONFLICT (أوسع 10×)
Carryover_SOP  = ((Blank2 − Blank1) / Mean_Sample_Areas) × 100 ≤ 0.010%
```
الإشارة السالبة تُحفظ ولا تُصفَّر صامتاً.

## T13 — حساسات التسرب والضبط الميكانيكي
`Detector`, `Pump`, `Autosampler HPV`, `Autosampler LPV` → **Passed** جميعاً.
`Rack Setting` و`Injection Port Teaching` عند تغيير الإبرة أو الرفوف فقط.

---

## ملاحظات التقريب
كل القيم تُخزَّن بدقتها الكاملة. عدد المنازل العشرية للعرض مُعرَّف لكل معادلة في
`FormulaSpec.decimals`، والتقريب بـ `ROUND_HALF_UP` عند العرض فقط.
