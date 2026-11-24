"""SHIMADZU-LC2050C-UV-CAL v1.0.0 — authoritative protocol blueprint.

Single source of truth for seeding. Every limit below is transcribed from the
comparative report (matrix 2.1) and the gap-closure matrix (2.4). Limits that the
report classifies as defective or conflicting are seeded as CONFLICT_REQUIRES_QA
so the engine can never silently issue a PASS on them.

The frontend twin lives in src/core/protocol.ts; the two are kept aligned by a
conformance test (backend/tests/test_protocol_parity.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal

PROTOCOL_CODE = "SHIMADZU-LC2050C-UV-CAL"
PROTOCOL_VERSION = "1.0.0"
PROTOCOL_TITLE_AR = "البروتوكول الشامل لمعايرة وتحقق الأداء — Shimadzu LC-2050C UV"
PROTOCOL_TITLE_EN = "Calibration & OQ Protocol — Shimadzu i-Series LC-2050C (UV)"

LimitSource = Literal[
    "INTEGRITY_GUIDE_CH2",
    "IOQ_PROTOCOL_CH4",
    "MANUFACTURER_SPEC",
    "SOP_LIMIT",
    "AUTHORITY_LIMIT",
]
Operator = Literal["lte", "gte", "abs_lte", "between", "equals"]
Approval = Literal["UNAPPROVED", "APPROVED", "CONFLICT_REQUIRES_QA", "REJECTED"]


@dataclass(frozen=True, slots=True)
class FieldSpec:
    key: str
    label_ar: str
    label_en: str
    type: Literal["number", "integer", "series", "text", "select", "boolean", "spectrum"]
    unit: str | None = None
    length: int | None = None
    options: tuple[str, ...] | None = None
    required: bool = True
    hint_ar: str | None = None


@dataclass(frozen=True, slots=True)
class FormulaSpec:
    key: str
    expression: str
    description_ar: str
    description_en: str
    decimals: int = 3


@dataclass(frozen=True, slots=True)
class TestSpec:
    code: str
    sequence: int
    name_ar: str
    name_en: str
    module: str
    standard: str
    procedure_ar: tuple[str, ...]
    fields: tuple[FieldSpec, ...]
    formulas: tuple[FormulaSpec, ...]
    metrics: tuple[str, ...]
    chart: str
    mandatory: bool = True


@dataclass(frozen=True, slots=True)
class LimitSpec:
    test_code: str
    metric_key: str
    source_type: LimitSource
    operator: Operator
    min_value: Decimal | None
    max_value: Decimal | None
    unit: str
    approval_status: Approval
    note_ar: str | None = None
    flagged: bool = False


def _d(x: str | int | float | None) -> Decimal | None:
    return None if x is None else Decimal(str(x))


# ════════════════════════════════════════════════════════════════════════════
# 13 tests
# ════════════════════════════════════════════════════════════════════════════

TESTS: tuple[TestSpec, ...] = (
    TestSpec(
        code="T01",
        sequence=1,
        name_ar="التحقق التلقائي الشامل (Auto Validation)",
        name_en="Automatic Validation (GRAD mode)",
        module="AUTO",
        standard="Integrity Guide Ch.2 — Auto Validation",
        procedure_ar=(
            "من قائمة الجهاز: Menu → Maintenance → Validation → Auto Validation، واختر الوضع [GRAD.] والمنافذ A/B وA/C وA/D.",
            "ركّب أنبوب المقاومة (228-38994) داخل فرن العمود بدلاً من العمود التحليلي.",
            "ضع محلول كافيين 10 mg/L في المنفذ A وماء HPLC نقي في B/C/D ومنفذ الغسيل.",
            "تأكد أن تقلب حرارة الغرفة أقل من ±1°C، ثم اضغط Start وانتظر انتهاء الدورة.",
            "اضغط [Logged] لحفظ النتائج في Validation Log، ثم أدخل القيم الظاهرة في هذه الشاشة.",
        ),
        fields=(
            FieldSpec("wavelength_dev", "انحراف الطول الموجي (هولميوم/D2)", "Wavelength deviation", "number", "nm"),
            FieldSpec("d2_energy", "طاقة لمبة D2 عند 220 nm", "D2 lamp energy @220 nm", "number", "mV"),
            FieldSpec("pulsation", "نبض الضغط", "Pressure pulsation", "number", "MPa"),
            FieldSpec("oven_stability", "ثبات حرارة الفرن", "Oven stability", "number", "°C"),
            FieldSpec("absorbance_dev", "انحراف الامتصاصية (فلتر داخلي)", "Absorbance deviation", "number", "%"),
            FieldSpec("noise", "الضجيج", "Noise", "number", "mAU"),
            FieldSpec("drift", "الانحراف", "Drift", "number", "mAU/h"),
            FieldSpec("gradient_dev", "أقصى انحراف تدرج", "Max gradient deviation", "number", "%"),
            FieldSpec("pressure_limiter", "محدد الضغط (علوي/سفلي)", "Pressure limiter", "select", None, None, ("Passed", "Failed")),
        ),
        formulas=(
            FormulaSpec("wavelength_dev_abs", "abs(wavelength_dev)", "القيمة المطلقة لانحراف الطول الموجي", "Absolute wavelength deviation", 2),
            FormulaSpec("d2_energy", "d2_energy", "طاقة لمبة D2 المقاسة", "Measured D2 energy", 0),
            FormulaSpec("pulsation", "pulsation", "نبض الضغط المقاس", "Measured pulsation", 3),
            FormulaSpec("oven_stability", "oven_stability", "ثبات حرارة الفرن", "Oven stability", 2),
            FormulaSpec("absorbance_dev_abs", "abs(absorbance_dev)", "القيمة المطلقة لانحراف الامتصاصية", "Absolute absorbance deviation", 2),
            FormulaSpec("noise", "noise", "ضجيج خط الأساس", "Baseline noise", 4),
            FormulaSpec("drift_abs", "abs(drift)", "القيمة المطلقة للانحراف", "Absolute drift", 3),
            FormulaSpec("gradient_dev_abs", "abs(gradient_dev)", "أقصى انحراف تدرج مطلق", "Absolute max gradient deviation", 2),
        ),
        metrics=("wavelength_dev_abs", "d2_energy", "pulsation", "oven_stability", "absorbance_dev_abs", "noise", "drift_abs", "gradient_dev_abs"),
        chart="bar",
    ),
    TestSpec(
        code="T02",
        sequence=2,
        name_ar="دقة معدل التدفق للمضخة",
        name_en="Pump Flow Rate Accuracy",
        module="PUMP",
        standard="Integrity Guide Ch.2 · iOQ Ch.4 §Flow",
        procedure_ar=(
            "ركّب أنبوب المقاومة واضبط الماء النقي كطور متحرك.",
            "Performance Check → Pump → Flow rate accuracy واختر القناة ومعدلات التدفق 0.5 و1.0 و2.0 mL/min.",
            "نفّذ Purge لمدة 3 دقائق ثم انتظر استقرار الضغط (~10 دقائق).",
            "اجمع الحجم المعاير في دورق 5 mL (Class A) وقس الزمن بساعة إيقاف معايرة دون ملامسة الأنبوب لسطح الماء.",
            "للطريقة الوزنية (iOQ) زن الماء المجمع وميزه على كثافة الماء عند حرارة القياس.",
        ),
        fields=(
            FieldSpec("set_flow", "معدلات التدفق المضبوطة", "Set flow rates", "series", "mL/min", 3, None, True, "0.5 ، 1.0 ، 2.0"),
            FieldSpec("collected_vol", "الأحجام المجموعة", "Collected volumes", "series", "mL", 3),
            FieldSpec("actual_time", "الأزمنة المقاسة", "Measured times", "series", "s", 3),
        ),
        formulas=(
            FormulaSpec("actual_flow", "(collected_vol * 60) / actual_time", "التدفق الفعلي = (الحجم × 60) ÷ الزمن", "Actual flow = (volume × 60) / time", 4),
            FormulaSpec("pct_error", "((actual_flow - set_flow) / set_flow) * 100", "نسبة الخطأ", "%Error", 3),
            FormulaSpec("max_abs_error", "max(abs(pct_error))", "أقصى خطأ مطلق", "Max absolute error", 3),
        ),
        metrics=("max_abs_error",),
        chart="flow",
    ),
    TestSpec(
        code="T03",
        sequence=3,
        name_ar="نبض الضغط ومحددات الضغط",
        name_en="Pressure Pulsation & Pressure Limiter",
        module="PUMP",
        standard="Integrity Guide Ch.2",
        procedure_ar=(
            "ضخ ماء نقي بمعدل 1 mL/min عند 40°C عبر أنبوب المقاومة؛ يراقب الجهاز تذبذب الضغط لمدة دقيقة.",
            "سجّل قيمة النبض العظمى الظاهرة (الحد ≤ 0.20 MPa).",
            "نفّذ Pressure Limiter: يقيس الجهاز الضغط المستقر X، يضبط الحد الأعلى X+1 MPa والأدنى X−1 MPa.",
            "تحقق من استجابة الإيقاف عند 1.5 و0.5 mL/min وسجّل النتيجة.",
        ),
        fields=(
            FieldSpec("pulsation", "نبض الضغط المقاس", "Measured pulsation", "number", "MPa"),
            FieldSpec("upper_limiter", "استجابة الحد الأعلى", "Upper limiter response", "select", None, None, ("Passed", "Failed")),
            FieldSpec("lower_limiter", "استجابة الحد الأدنى", "Lower limiter response", "select", None, None, ("Passed", "Failed")),
        ),
        formulas=(FormulaSpec("pulsation", "pulsation", "نبض الضغط", "Pulsation", 3),),
        metrics=("pulsation",),
        chart="bar",
    ),
    TestSpec(
        code="T04",
        sequence=4,
        name_ar="دقة صمام التدرج اللوني (GPV)",
        name_en="Gradient Proportioning Valve Accuracy",
        module="GPV",
        standard="Integrity Guide Ch.2 · iOQ Ch.4 p.190-192",
        procedure_ar=(
            "نفّذ آلياً عبر Performance Check → Pump → GE composition (كافيين 10 mg/L في A، ماء في B/C/D، 1 mL/min، 272 nm، 40°C).",
            "أو يدوياً عبر LabSolutions: ماء في A/C، كافيين 10 mg/L عند 273 nm في B/D.",
            "سجّل ارتفاعات القمم عند المستويات 0 و10 و50 و90 و100% لكل زوج قنوات (A/B، A/C، A/D).",
            "يُحسب التركيز الفعلي بمعادلة iOQ الرسمية ثم الانحراف عن القيمة المضبوطة.",
        ),
        fields=(
            FieldSpec("height_0", "ارتفاع القمة عند 0%", "Peak height @0%", "series", "mAU", 3, None, True, "لكل زوج قنوات"),
            FieldSpec("height_10", "ارتفاع القمة عند 10%", "Peak height @10%", "series", "mAU", 3),
            FieldSpec("height_50", "ارتفاع القمة عند 50%", "Peak height @50%", "series", "mAU", 3),
            FieldSpec("height_90", "ارتفاع القمة عند 90%", "Peak height @90%", "series", "mAU", 3),
            FieldSpec("height_100", "ارتفاع القمة عند 100%", "Peak height @100%", "series", "mAU", 3),
        ),
        formulas=(
            FormulaSpec("actual_10", "((height_10 - height_0) / (height_100 - height_0)) * 100", "التركيز الفعلي عند 10%", "Actual @10%", 3),
            FormulaSpec("actual_50", "((height_50 - height_0) / (height_100 - height_0)) * 100", "التركيز الفعلي عند 50%", "Actual @50%", 3),
            FormulaSpec("actual_90", "((height_90 - height_0) / (height_100 - height_0)) * 100", "التركيز الفعلي عند 90%", "Actual @90%", 3),
            FormulaSpec("dev_10", "actual_10 - 10", "انحراف مستوى 10%", "Deviation @10%", 3),
            FormulaSpec("dev_50", "actual_50 - 50", "انحراف مستوى 50%", "Deviation @50%", 3),
            FormulaSpec("dev_90", "actual_90 - 90", "انحراف مستوى 90%", "Deviation @90%", 3),
            FormulaSpec("dev_100", "((height_100 - height_0) / (height_100 - height_0)) * 100 - 100", "انحراف مستوى 100%", "Deviation @100%", 3),
            FormulaSpec("max_abs_dev", "max(abs(dev_10), abs(dev_50), abs(dev_90), abs(dev_100))", "أقصى انحراف مطلق للتدرج", "Max absolute gradient deviation", 3),
        ),
        metrics=("max_abs_dev",),
        chart="gradient",
    ),
    TestSpec(
        code="T05",
        sequence=5,
        name_ar="دقة حجم الحقن الوزنية",
        name_en="Injection Volume Accuracy (Gravimetric)",
        module="INJECTOR",
        standard="Integrity Guide Ch.2 · iOQ Ch.4 · GAP-06",
        procedure_ar=(
            "أطفئ مبرد العينات (Cooler OFF) لمنع التكثف، واغسل الخطوط بالماء النقي.",
            "ضع 1 mL ماء HPLC في قارورة 1.5 mL محكمة الغلق وزنها بميزان تحليلي (0.0001 g) وسجّل W1.",
            "ضع القارورة في الموقع 1 بالرف الأيسر ونفّذ N حقنة بحجم 50 µL (أو 20 حقنة × 5 µL وفق iOQ).",
            "أعد وزن القارورة وسجّل W2 ثم احسب الحجم المقاس والدقة النسبية.",
        ),
        fields=(
            FieldSpec("w1", "الوزن قبل الحقن W1", "Weight before W1", "number", "g"),
            FieldSpec("w2", "الوزن بعد الحقن W2", "Weight after W2", "number", "g"),
            FieldSpec("water_density", "كثافة الماء عند حرارة القياس", "Water density", "number", "g/mL"),
            FieldSpec("set_vol", "حجم الحقنة المضبوط", "Set injection volume", "number", "µL"),
            FieldSpec("n_injections", "عدد الحقنات N", "Number of injections", "integer"),
        ),
        formulas=(
            FormulaSpec("measured_vol", "((w1 - w2) * 1000) / water_density", "الحجم المقاس", "Measured volume", 3),
            FormulaSpec("pct_accuracy", "((measured_vol / (set_vol * n_injections)) - 1) * 100", "الدقة النسبية للحجم", "Volumetric %accuracy", 3),
            FormulaSpec("pct_accuracy_abs", "abs(pct_accuracy)", "القيمة المطلقة للدقة", "Absolute %accuracy", 3),
        ),
        metrics=("pct_accuracy_abs",),
        chart="bar",
    ),
    TestSpec(
        code="T06",
        sequence=6,
        name_ar="خطية الحاقن وتكرارية الحلقة",
        name_en="Injection Linearity & Loop Precision",
        module="INJECTOR",
        standard="iOQ Ch.4 · SOP Test 08",
        procedure_ar=(
            "استخدم محلول كافيين 20 mg/L وطوراً متحركاً ماء/ميثانول أو ماء عبر أنبوب المقاومة.",
            "خطية الحاقن: احقن الأحجام 2 و5 و10 و20 و50 µL وسجّل مساحات القمم.",
            "تكرارية الحلقة: احقن 5 تكرارات لكل من 10 و20 و50 µL وسجّل المساحات.",
        ),
        fields=(
            FieldSpec("volumes", "أحجام الحقن للخطية", "Linearity volumes", "series", "µL", 5, None, True, "2 ، 5 ، 10 ، 20 ، 50"),
            FieldSpec("linearity_areas", "مساحات القمم للخطية", "Linearity peak areas", "series", "mAU·s", 5),
            FieldSpec("loop_areas", "مساحات تكرارية 50 µL", "Loop precision areas", "series", "mAU·s", 5),
        ),
        formulas=(
            FormulaSpec("r2", "ols_r2(volumes, linearity_areas)", "معامل التحديد R²", "OLS R²", 5),
            FormulaSpec("slope", "ols_slope(volumes, linearity_areas)", "ميل الانحدار", "OLS slope", 5),
            FormulaSpec("intercept", "ols_intercept(volumes, linearity_areas)", "تقاطع الانحدار", "OLS intercept", 5),
            FormulaSpec("loop_rsd", "rsd(loop_areas)", "الانحراف النسبي", "Loop %RSD", 3),
            FormulaSpec("loop_mean", "mean(loop_areas)", "متوسط المساحات", "Mean area", 3),
            FormulaSpec("loop_sd", "sd(loop_areas)", "الانحراف المعياري (n−1)", "Sample SD", 4),
        ),
        metrics=("r2", "loop_rsd"),
        chart="linearity",
    ),
    TestSpec(
        code="T07",
        sequence=7,
        name_ar="دقة حرارة مبرد العينات",
        name_en="Sample Cooler Temperature Accuracy",
        module="TEMPERATURE",
        standard="Integrity Guide Ch.2 p.48/175 · iOQ · GAP-08",
        procedure_ar=(
            "ضع 1 mL ماء في قارورة 1.5 mL وأدخل الحساس المعاير عبر الغطاء حتى يلامس قاع القارورة.",
            "ضع القارورة في الموقع 27 على الصفيحة المعدنية (228-61615-42) — وليس في فرن العمود (تصحيح GAP-08).",
            "Performance Check → Autosampler → Cooler Temperature accuracy اضبط 4°C وانتظر ≥ 90 دقيقة مع حرارة غرفة ≤ 30°C.",
            "أدخل قراءة الحساس المرجعي بعد تطبيق معامل التصحيح من شهادة المعايرة.",
        ),
        fields=(
            FieldSpec("t_set", "الحرارة المضبوطة", "Set temperature", "number", "°C"),
            FieldSpec("t_ref_raw", "قراءة الحساس الخام", "Reference raw reading", "number", "°C"),
            FieldSpec("ref_offset", "معامل تصحيح الشهادة", "Certificate correction offset", "number", "°C", required=False),
            FieldSpec("wait_minutes", "زمن الانتظار", "Equilibration time", "number", "min"),
            FieldSpec("ambient_temp", "حرارة الغرفة", "Ambient temperature", "number", "°C"),
        ),
        formulas=(
            FormulaSpec("t_ref_corrected", "t_ref_raw + ref_offset", "الحرارة المرجعية المصححة", "Corrected reference", 3),
            FormulaSpec("error", "t_ref_corrected - t_set", "الخطأ", "Error", 3),
            FormulaSpec("error_abs", "abs(t_ref_corrected - t_set)", "الخطأ المطلق", "Absolute error", 3),
        ),
        metrics=("error_abs",),
        chart="temperature",
    ),
    TestSpec(
        code="T08",
        sequence=8,
        name_ar="دقة وثبات حرارة فرن العمود وحساس الغاز",
        name_en="Column Oven Temperature & Gas Sensor",
        module="TEMPERATURE",
        standard="Integrity Guide Ch.2 · iOQ · GAP-07",
        procedure_ar=(
            "ثبت طرف الحساس على حامل العمود بشريط ألمنيوم بعرض 1 cm وأغلق الباب.",
            "اختبر النقاط 40 و50 وRT−5°C (أو 20/30/40/50/70 وفق SOP).",
            "سجّل T_Set وT_Display وT_Ref ثم أدخل قيمة التذبذب التلقائي.",
            "اختبار حساس الغاز: عند 50°C احقن 100 µL إيثانول وتأكد من الاستجابة.",
        ),
        fields=(
            FieldSpec("t_set", "الحرارة المضبوطة T_Set", "Set temperature", "number", "°C"),
            FieldSpec("t_display", "الحرارة المعروضة T_Display", "Display temperature", "number", "°C"),
            FieldSpec("t_ref_raw", "قراءة الحساس الخام", "Reference raw reading", "number", "°C"),
            FieldSpec("ref_offset", "معامل تصحيح الشهادة", "Correction offset", "number", "°C", required=False),
            FieldSpec("fluctuation", "التذبذب التلقائي", "Auto fluctuation", "number", "°C"),
            FieldSpec("gas_sensor", "استجابة حساس الغاز", "Gas sensor response", "select", None, None, ("Passed", "Failed")),
        ),
        formulas=(
            FormulaSpec("t_ref_corrected", "t_ref_raw + ref_offset", "الحرارة المرجعية المصححة", "Corrected reference", 3),
            FormulaSpec("error_set", "abs(t_set - (t_ref_raw + ref_offset))", "|T_Set − T_Ref|", "|T_Set − T_Ref|", 3),
            FormulaSpec("error_display", "abs(t_display - (t_ref_raw + ref_offset))", "|T_Display − T_Ref|", "|T_Display − T_Ref|", 3),
            FormulaSpec("fluctuation", "fluctuation", "التذبذب المقاس", "Measured fluctuation", 3),
        ),
        metrics=("error_set", "error_display", "fluctuation"),
        chart="temperature",
    ),
    TestSpec(
        code="T09",
        sequence=9,
        name_ar="طاقة لمبة D2 ودقة الطول الموجي",
        name_en="D2 Lamp Energy & Wavelength Accuracy",
        module="DETECTOR",
        standard="Integrity Guide Ch.2 p.16/57 · iOQ p.182-184",
        procedure_ar=(
            "Performance Check → Detector → Wavelength accuracy/Lamp energy بالماء في الخلية.",
            "طريقة الكافيين (iOQ): مسح 200–280 nm بخطوة 1 nm.",
            "أدخل طاقة لمبة D2 عند 220 nm والقيم المكتشفة للقمم والقيعان.",
            "راجع عدّاد ساعات اللمبة مقابل حد الاستبدال 2000 ساعة.",
        ),
        fields=(
            FieldSpec("d2_energy", "طاقة لمبة D2 عند 220 nm", "D2 energy @220 nm", "number", "mV"),
            FieldSpec("lamp_hours", "ساعات تشغيل اللمبة", "Lamp hours", "number", "h"),
            FieldSpec("wavelength_dev", "انحراف الطول الموجي", "Wavelength deviation", "number", "nm"),
            FieldSpec("peak_205", "قمة الكافيين الأولى", "Caffeine peak 1", "number", "nm", required=False),
            FieldSpec("valley_245", "قاع الكافيين", "Caffeine valley", "number", "nm", required=False),
            FieldSpec("peak_273", "قمة الكافيين الثانية", "Caffeine peak 2", "number", "nm", required=False),
        ),
        formulas=(
            FormulaSpec("d2_energy", "d2_energy", "طاقة اللمبة", "Lamp energy", 0),
            FormulaSpec("wavelength_dev_abs", "abs(wavelength_dev)", "انحراف الطول الموجي المطلق", "Absolute deviation", 2),
            FormulaSpec("peak1_dev", "abs(peak_205 - 205)", "انحراف القمة الأولى", "Peak-1 deviation", 2),
            FormulaSpec("valley_dev", "abs(valley_245 - 245)", "انحراف القاع", "Valley deviation", 2),
            FormulaSpec("peak2_dev", "abs(peak_273 - 273)", "انحراف القمة الثانية", "Peak-2 deviation", 2),
            FormulaSpec("lamp_headroom", "2000 - lamp_hours", "الساعات المتبقية", "Hours remaining", 0),
        ),
        metrics=("d2_energy", "wavelength_dev_abs", "peak1_dev", "valley_dev", "peak2_dev"),
        chart="spectrum",
    ),
    TestSpec(
        code="T10",
        sequence=10,
        name_ar="دقة الامتصاصية وخطية الكاشف",
        name_en="Absorbance Accuracy & Detector Linearity",
        module="DETECTOR",
        standard="Integrity Guide Ch.2 · iOQ Ch.4 · GAP-05",
        procedure_ar=(
            "دقة الامتصاصية: الفحص بالفلتر الداخلي أو JCRM230A (الحد ±3.0%).",
            "خطية الامتصاصية: احقن 20 و30 و40 و50 و60 mg/L عبر أنبوب المقاومة.",
            "اضبط ارتفاع قمة المحلول الخامس بين 1.4 و1.5 AU وسجّل القيم.",
        ),
        fields=(
            FieldSpec("absorbance_dev", "انحراف الامتصاصية", "Absorbance deviation", "number", "%"),
            FieldSpec("concs", "التركيزات", "Concentrations", "series", "mg/L", 5, None, True, "20 ، 30 ، 40 ، 50 ، 60"),
            FieldSpec("heights", "ارتفاعات القمم", "Peak heights", "series", "AU", 5),
        ),
        formulas=(
            FormulaSpec("absorbance_dev_abs", "abs(absorbance_dev)", "انحراف الامتصاصية المطلق", "Absolute absorbance deviation", 2),
            FormulaSpec("r2", "ols_r2(concs, heights)", "معامل التحديد R²", "OLS R²", 5),
            FormulaSpec("rs_dev_max", "max(abs(rs_deviation(heights, concs)))", "أقصى انحراف حساسية نسبية", "Max relative-sensitivity deviation", 3),
            FormulaSpec("rs_std", "mean(rs_deviation(heights, concs))", "متوسط انحراف الحساسية", "Mean sensitivity deviation", 3),
        ),
        metrics=("absorbance_dev_abs", "r2", "rs_dev_max"),
        chart="linearity",
    ),
    TestSpec(
        code="T11",
        sequence=11,
        name_ar="ضجيج وانحراف خط الأساس (ASTM E1657-98)",
        name_en="UV Baseline Noise & Drift",
        module="DETECTOR",
        standard="ASTM E1657-98 · Integrity Guide Ch.2 · iOQ · GAP-02",
        procedure_ar=(
            "اضبط ماء HPLC منزوع الغاز عند 1.0 mL/min، فرن وخلية 40°C، 250 nm، استجابة 2 ثانية.",
            "انتظر 60 دقيقة للاستقرار ثم سجّل خط الأساس 15 دقيقة.",
            "قسّم الـ15 دقيقة إلى 30 فترة × 30 ثانية لحساب متوسط الضجيج.",
            "احسب الانحراف الساعي = 4 × ميل الـ15 دقيقة مع حفظ الإشارة.",
        ),
        fields=(
            FieldSpec("noise", "الضجيج المحسوب", "Computed noise", "number", "mAU"),
            FieldSpec("drift", "الانحراف المحسوب", "Computed drift", "number", "mAU/h"),
        ),
        formulas=(
            FormulaSpec("noise", "noise", "الضجيج", "Noise", 4),
            FormulaSpec("drift_abs", "abs(drift)", "القيمة المطلقة للانحراف", "Absolute drift", 3),
        ),
        metrics=("noise", "drift_abs"),
        chart="repeatability",
    ),
    TestSpec(
        code="T12",
        sequence=12,
        name_ar="تكرارية النظام والترحيل المتبقي",
        name_en="System Repeatability & Carryover",
        module="SYSTEM",
        standard="Integrity Guide Ch.2 p.92 · iOQ p.199 · SOP",
        procedure_ar=(
            "التكرارية: كافيين 20 mg/L، 272–273 nm، 40°C، Blank ثم 6 حقنات.",
            "سجّل أزمنة الاستبقاء ومساحات القمم للحقنات الست.",
            "الترحيل: 250 mg/L ثم Blank مباشرة (أو Blank1 → 3×200 µg/mL → Blank2).",
            "احسب الترحيل بالصيغة المعتمدة من ضمان الجودة.",
        ),
        fields=(
            FieldSpec("rt_values", "أزمنة الاستبقاء (6 حقنات)", "Retention times", "series", "min", 6),
            FieldSpec("areas", "مساحات القمم (6 حقنات)", "Peak areas", "series", "mAU·s", 6),
            FieldSpec("area_blank", "مساحة قمة الـ Blank", "Blank peak area", "number", "mAU·s"),
            FieldSpec("area_sample_250", "مساحة العينة 250 mg/L", "Sample area 250 mg/L", "number", "mAU·s"),
            FieldSpec("area_sample_50", "مساحة العينة 50 mg/L", "Sample area 50 mg/L", "number", "mAU·s"),
        ),
        formulas=(
            FormulaSpec("rt_rsd", "rsd(rt_values)", "انحراف أزمنة الاستبقاء", "RT %RSD", 3),
            FormulaSpec("area_rsd", "rsd(areas)", "انحراف المساحات", "Area %RSD", 3),
            FormulaSpec("carryover_ch2", "(area_blank / area_sample_250) * 100", "الترحيل وفق الفصل 2", "Carryover (Ch.2)", 5),
            FormulaSpec("carryover_ioq", "(area_blank / (5 * area_sample_50)) * 100", "الترحيل وفق iOQ", "Carryover (iOQ)", 5),
            FormulaSpec("rt_mean", "mean(rt_values)", "متوسط زمن الاستبقاء", "Mean retention time", 4),
            FormulaSpec("area_mean", "mean(areas)", "متوسط المساحات", "Mean area", 3),
        ),
        metrics=("rt_rsd", "area_rsd", "carryover_ch2"),
        chart="repeatability",
    ),
    TestSpec(
        code="T13",
        sequence=13,
        name_ar="حساسات التسرب وضبط النظام الميكانيكي",
        name_en="Leak Sensors & System Adjustment",
        module="SYSTEM",
        standard="Integrity Guide Ch.2 · Performance Check → Other",
        procedure_ar=(
            "Performance Check → Other → Leak Sensor: بلّل حساس كل وحدة ونفّذ الفحص.",
            "الحساسات: Detector وPump وAutosampler HPV وLPV — يجب أن تكون Passed.",
            "جفّف الماء فوراً بعد نجاح الفحص.",
            "عند تغيير الإبرة أو الرفوف: Rack Setting ثم Injection Port Teaching.",
        ),
        fields=(
            FieldSpec("detector_sensor", "حساس الكاشف", "Detector sensor", "select", None, None, ("Passed", "Failed")),
            FieldSpec("pump_sensor", "حساس المضخة", "Pump sensor", "select", None, None, ("Passed", "Failed")),
            FieldSpec("hpv_sensor", "حساس HPV", "Autosampler HPV", "select", None, None, ("Passed", "Failed")),
            FieldSpec("lpv_sensor", "حساس LPV", "Autosampler LPV", "select", None, None, ("Passed", "Failed")),
            FieldSpec("rack_setting", "ضبط الرف Rack Setting", "Rack setting", "select", None, None, ("Passed", "Failed", "Not Required")),
            FieldSpec("port_teaching", "ضبط منفذ الحقن", "Injection port teaching", "select", None, None, ("Passed", "Failed", "Not Required")),
        ),
        formulas=(),
        metrics=(),
        chart="none",
    ),
)


def _L(
    test_code: str,
    metric_key: str,
    source: LimitSource,
    operator: Operator,
    min_value: str | int | float | None,
    max_value: str | int | float | None,
    unit: str,
    approval: Approval,
    note: str | None = None,
    flagged: bool = False,
) -> LimitSpec:
    return LimitSpec(
        test_code=test_code,
        metric_key=metric_key,
        source_type=source,
        operator=operator,
        min_value=_d(min_value),
        max_value=_d(max_value),
        unit=unit,
        approval_status=approval,
        note_ar=note,
        flagged=flagged,
    )


A = "APPROVED"
C = "CONFLICT_REQUIRES_QA"

LIMITS: tuple[LimitSpec, ...] = (
    # T01 — consolidated auto validation
    _L("T01", "wavelength_dev_abs", "INTEGRITY_GUIDE_CH2", "lte", None, 1.0, "nm", A),
    _L("T01", "wavelength_dev_abs", "IOQ_PROTOCOL_CH4", "lte", None, 2.0, "nm", A),
    _L("T01", "wavelength_dev_abs", "MANUFACTURER_SPEC", "lte", None, 1.0, "nm", A),
    _L("T01", "wavelength_dev_abs", "SOP_LIMIT", "lte", None, 2.0, "nm", A),
    _L("T01", "wavelength_dev_abs", "AUTHORITY_LIMIT", "lte", None, 1.0, "nm", A, "اعتماد الفحص المدمج ±1.0 nm مع فحص كافيين iOQ كتحقق مكمل"),
    _L("T01", "d2_energy", "INTEGRITY_GUIDE_CH2", "gte", 400, None, "mV", A),
    _L("T01", "d2_energy", "IOQ_PROTOCOL_CH4", "gte", 400, None, "mV", A),
    _L("T01", "d2_energy", "SOP_LIMIT", "gte", 400, None, "mV", A),
    _L("T01", "d2_energy", "AUTHORITY_LIMIT", "gte", 400, None, "mV", A, "GAP-10 مغلقة: الحد مؤكد في الدليل ص16 و57"),
    _L("T01", "pulsation", "INTEGRITY_GUIDE_CH2", "lte", None, 0.2, "MPa", A),
    _L("T01", "pulsation", "AUTHORITY_LIMIT", "lte", None, 0.2, "MPa", A, "1 mL/min عند 40°C مع أنبوب مقاومة ~10 MPa"),
    _L("T01", "oven_stability", "INTEGRITY_GUIDE_CH2", "lte", None, 0.2, "°C", A),
    _L("T01", "oven_stability", "AUTHORITY_LIMIT", "lte", None, 0.2, "°C", A),
    _L("T01", "absorbance_dev_abs", "INTEGRITY_GUIDE_CH2", "lte", None, 3.0, "%", A),
    _L("T01", "absorbance_dev_abs", "AUTHORITY_LIMIT", "lte", None, 3.0, "%", A),
    _L("T01", "noise", "INTEGRITY_GUIDE_CH2", "lte", None, 0.02, "mAU", A),
    _L("T01", "noise", "IOQ_PROTOCOL_CH4", "lte", None, 0.04, "mAU", A),
    _L("T01", "noise", "MANUFACTURER_SPEC", "lte", None, 0.0025, "mAU", A),
    _L("T01", "noise", "SOP_LIMIT", "lte", None, 20, "AU/h", C, "SOP يخلط وحدة الضجيج مع AU/h والقيمة أكبر 1000 مرة — GAP-02", True),
    _L("T01", "noise", "AUTHORITY_LIMIT", "lte", None, 0.02, "mAU", A, "رفض أرقام SOP واعتماد حد Integrity Guide"),
    _L("T01", "drift_abs", "INTEGRITY_GUIDE_CH2", "lte", None, 0.6, "mAU/h", A),
    _L("T01", "drift_abs", "IOQ_PROTOCOL_CH4", "lte", None, 0.5, "mAU/h", A),
    _L("T01", "drift_abs", "MANUFACTURER_SPEC", "lte", None, 0.1, "mAU/h", A),
    _L("T01", "drift_abs", "SOP_LIMIT", "lte", None, 500, "AU/h", C, "خطأ وحدة ومقدار ×1000 — GAP-02", True),
    _L("T01", "drift_abs", "AUTHORITY_LIMIT", "lte", None, 0.6, "mAU/h", A),
    _L("T01", "gradient_dev_abs", "INTEGRITY_GUIDE_CH2", "lte", None, 2.0, "%", A),
    _L("T01", "gradient_dev_abs", "IOQ_PROTOCOL_CH4", "lte", None, 2.0, "%", A),
    _L("T01", "gradient_dev_abs", "MANUFACTURER_SPEC", "lte", None, 0.5, "%", A, "دقة التدرج المصنعية ±0.5% — حد تنبيهي"),
    _L("T01", "gradient_dev_abs", "SOP_LIMIT", "lte", None, 2.0, "%", A),
    _L("T01", "gradient_dev_abs", "AUTHORITY_LIMIT", "lte", None, 2.0, "%", A),

    # T02 — flow rate
    _L("T02", "max_abs_error", "INTEGRITY_GUIDE_CH2", "lte", None, 2.0, "%", A, "5 mL / ساعة إيقاف عند 0.5 و1 و2 mL/min"),
    _L("T02", "max_abs_error", "IOQ_PROTOCOL_CH4", "lte", None, 2.5, "%", A, "طريقة وزنية"),
    _L("T02", "max_abs_error", "MANUFACTURER_SPEC", "lte", None, 1.0, "%", A),
    _L("T02", "max_abs_error", "SOP_LIMIT", "lte", None, 2.0, "%", A, "10 mL أسطوانة Class A"),
    _L("T02", "max_abs_error", "AUTHORITY_LIMIT", "lte", None, 2.0, "%", A, "اعتماد ±2.00% مع ±1.0% كحد تنبيهي"),

    # T03 — pulsation
    _L("T03", "pulsation", "INTEGRITY_GUIDE_CH2", "lte", None, 0.2, "MPa", A),
    _L("T03", "pulsation", "MANUFACTURER_SPEC", "lte", None, 0.06, "%", A, "RSD للتدفق < 0.06%"),
    _L("T03", "pulsation", "AUTHORITY_LIMIT", "lte", None, 0.2, "MPa", A),

    # T04 — gradient
    _L("T04", "max_abs_dev", "INTEGRITY_GUIDE_CH2", "lte", None, 2.0, "%", A),
    _L("T04", "max_abs_dev", "IOQ_PROTOCOL_CH4", "lte", None, 2.0, "%", A, "المعادلة الرسمية iOQ ص192"),
    _L("T04", "max_abs_dev", "MANUFACTURER_SPEC", "lte", None, 0.5, "%", A),
    _L("T04", "max_abs_dev", "SOP_LIMIT", "lte", None, 2.0, "%", A, "المعادلة غائبة في SOP — GAP-03"),
    _L("T04", "max_abs_dev", "AUTHORITY_LIMIT", "lte", None, 2.0, "%", A, "لكل مستوى ولكل زوج قنوات"),

    # T05 — injection volume accuracy
    _L("T05", "pct_accuracy_abs", "INTEGRITY_GUIDE_CH2", "lte", None, 1.3, "%", A, "10 حقنات × 50 µL وزني"),
    _L("T05", "pct_accuracy_abs", "IOQ_PROTOCOL_CH4", "lte", None, 2.0, "%", A, "50 µL؛ و±5.0% عند 5 µL"),
    _L("T05", "pct_accuracy_abs", "MANUFACTURER_SPEC", "lte", None, 1.0, "%", A),
    _L("T05", "pct_accuracy_abs", "SOP_LIMIT", "lte", None, 2.0, "%", A, "SOP يقيس التكرارية لا الدقة — GAP-06"),
    _L("T05", "pct_accuracy_abs", "AUTHORITY_LIMIT", "lte", None, 1.3, "%", A),

    # T06 — injector linearity + loop precision
    _L("T06", "r2", "IOQ_PROTOCOL_CH4", "gte", 0.999, None, "—", A),
    _L("T06", "r2", "MANUFACTURER_SPEC", "gte", 0.9999, None, "—", A),
    _L("T06", "r2", "SOP_LIMIT", "gte", 0.99, None, "—", C, "تعارض داخلي بين المتن 0.99 والملحق 0.997 — GAP-05", True),
    _L("T06", "r2", "AUTHORITY_LIMIT", "gte", 0.999, None, "—", A),
    _L("T06", "loop_rsd", "SOP_LIMIT", "lte", None, 2.0, "%", A),
    _L("T06", "loop_rsd", "AUTHORITY_LIMIT", "lte", None, 2.0, "%", A),

    # T07 — sample cooler
    _L("T07", "error_abs", "INTEGRITY_GUIDE_CH2", "lte", None, 3.0, "°C", A, "عند 4°C، حساس في الموقع 27"),
    _L("T07", "error_abs", "IOQ_PROTOCOL_CH4", "lte", None, 3.0, "°C", A),
    _L("T07", "error_abs", "SOP_LIMIT", "lte", None, 1.0, "°C", C, "SOP يضع الميزان داخل فرن العمود — GAP-08", True),
    _L("T07", "error_abs", "AUTHORITY_LIMIT", "lte", None, 3.0, "°C", A, "اعتماد 4°C ± 3.0°C"),

    # T08 — oven
    _L("T08", "error_set", "INTEGRITY_GUIDE_CH2", "lte", None, 2.0, "°C", A),
    _L("T08", "error_set", "IOQ_PROTOCOL_CH4", "lte", None, 2.0, "°C", A),
    _L("T08", "error_set", "MANUFACTURER_SPEC", "lte", None, 0.8, "°C", A),
    _L("T08", "error_set", "SOP_LIMIT", "lte", None, 1.0, "°C", A, "GAP-07 محلول بتسجيل الثلاثة"),
    _L("T08", "error_set", "AUTHORITY_LIMIT", "lte", None, 2.0, "°C", A),
    _L("T08", "error_display", "AUTHORITY_LIMIT", "lte", None, 2.0, "°C", A),
    _L("T08", "fluctuation", "INTEGRITY_GUIDE_CH2", "lte", None, 0.2, "°C", A),
    _L("T08", "fluctuation", "MANUFACTURER_SPEC", "lte", None, 0.1, "°C", A),
    _L("T08", "fluctuation", "AUTHORITY_LIMIT", "lte", None, 0.2, "°C", A),

    # T09 — lamp + wavelength
    _L("T09", "d2_energy", "INTEGRITY_GUIDE_CH2", "gte", 400, None, "mV", A),
    _L("T09", "d2_energy", "SOP_LIMIT", "gte", 400, None, "mV", A),
    _L("T09", "d2_energy", "AUTHORITY_LIMIT", "gte", 400, None, "mV", A),
    _L("T09", "wavelength_dev_abs", "INTEGRITY_GUIDE_CH2", "lte", None, 1.0, "nm", A),
    _L("T09", "wavelength_dev_abs", "MANUFACTURER_SPEC", "lte", None, 1.0, "nm", A),
    _L("T09", "wavelength_dev_abs", "IOQ_PROTOCOL_CH4", "lte", None, 2.0, "nm", A),
    _L("T09", "wavelength_dev_abs", "AUTHORITY_LIMIT", "lte", None, 1.0, "nm", A),
    _L("T09", "peak1_dev", "IOQ_PROTOCOL_CH4", "lte", None, 2.0, "nm", A, "قمة 205 ± 2 nm"),
    _L("T09", "peak1_dev", "AUTHORITY_LIMIT", "lte", None, 2.0, "nm", A),
    _L("T09", "valley_dev", "IOQ_PROTOCOL_CH4", "lte", None, 2.0, "nm", A, "قاع 245 ± 2 nm"),
    _L("T09", "valley_dev", "AUTHORITY_LIMIT", "lte", None, 2.0, "nm", A),
    _L("T09", "peak2_dev", "IOQ_PROTOCOL_CH4", "lte", None, 2.0, "nm", A, "قمة 273 ± 2 nm — GAP-09"),
    _L("T09", "peak2_dev", "AUTHORITY_LIMIT", "lte", None, 2.0, "nm", A),

    # T10 — absorbance & detector linearity
    _L("T10", "absorbance_dev_abs", "INTEGRITY_GUIDE_CH2", "lte", None, 3.0, "%", A),
    _L("T10", "absorbance_dev_abs", "AUTHORITY_LIMIT", "lte", None, 3.0, "%", A),
    _L("T10", "r2", "IOQ_PROTOCOL_CH4", "gte", 0.999, None, "—", A),
    _L("T10", "r2", "MANUFACTURER_SPEC", "gte", 0.9995, None, "—", A),
    _L("T10", "r2", "AUTHORITY_LIMIT", "gte", 0.999, None, "—", A),
    _L("T10", "rs_dev_max", "INTEGRITY_GUIDE_CH2", "lte", None, 5.0, "%", A),
    _L("T10", "rs_dev_max", "AUTHORITY_LIMIT", "lte", None, 5.0, "%", A),

    # T11 — noise & drift
    _L("T11", "noise", "INTEGRITY_GUIDE_CH2", "lte", None, 0.02, "mAU", A),
    _L("T11", "noise", "IOQ_PROTOCOL_CH4", "lte", None, 0.04, "mAU", A),
    _L("T11", "noise", "MANUFACTURER_SPEC", "lte", None, 0.0025, "mAU", A),
    _L("T11", "noise", "SOP_LIMIT", "lte", None, 20, "AU/h", C, "خطأ وحدة الضجيج — GAP-02", True),
    _L("T11", "noise", "AUTHORITY_LIMIT", "lte", None, 0.02, "mAU", A),
    _L("T11", "drift_abs", "INTEGRITY_GUIDE_CH2", "lte", None, 0.6, "mAU/h", A),
    _L("T11", "drift_abs", "IOQ_PROTOCOL_CH4", "lte", None, 0.5, "mAU/h", A),
    _L("T11", "drift_abs", "SOP_LIMIT", "lte", None, 500, "AU/h", C, "خطأ مقدار ×1000 — GAP-02", True),
    _L("T11", "drift_abs", "AUTHORITY_LIMIT", "lte", None, 0.6, "mAU/h", A),

    # T12 — repeatability & carryover
    _L("T12", "rt_rsd", "INTEGRITY_GUIDE_CH2", "lte", None, 0.5, "%", A),
    _L("T12", "rt_rsd", "IOQ_PROTOCOL_CH4", "lte", None, 0.5, "%", A),
    _L("T12", "rt_rsd", "SOP_LIMIT", "lte", None, 1.0, "%", A),
    _L("T12", "rt_rsd", "AUTHORITY_LIMIT", "lte", None, 0.5, "%", A),
    _L("T12", "area_rsd", "INTEGRITY_GUIDE_CH2", "lte", None, 1.0, "%", A),
    _L("T12", "area_rsd", "IOQ_PROTOCOL_CH4", "lte", None, 1.0, "%", A),
    _L("T12", "area_rsd", "AUTHORITY_LIMIT", "lte", None, 1.0, "%", A),
    _L("T12", "carryover_ch2", "INTEGRITY_GUIDE_CH2", "lte", None, 0.01, "%", A),
    _L("T12", "carryover_ch2", "SOP_LIMIT", "lte", None, 0.01, "%", A),
    _L("T12", "carryover_ch2", "AUTHORITY_LIMIT", "lte", None, 0.01, "%", A, "اعتماد ≤ 0.010%"),
    _L("T12", "carryover_ioq", "IOQ_PROTOCOL_CH4", "lte", None, 0.1, "%", C, "أوسع 10 أضعاف — يتطلب تحذير QA صريح", True),
    _L("T12", "carryover_ioq", "MANUFACTURER_SPEC", "lte", None, 0.0025, "%", A),
)


# ════════════════════════════════════════════════════════════════════════════
# Post-breakdown calibration matrix (report §3.3)
# ════════════════════════════════════════════════════════════════════════════

BREAKDOWN_MATRIX: tuple[dict[str, Any], ...] = (
    {"key": "PUMP", "ar": "المضخة / أختام المكبس", "en": "Pump / Plunger seals", "tests": ("T02", "T03", "T04")},
    {"key": "D2_LAMP", "ar": "لمبة الديوتيريوم", "en": "D2 lamp replacement", "tests": ("T09", "T11")},
    {"key": "GPV", "ar": "صمام التدرج اللوني", "en": "Gradient proportioning valve", "tests": ("T04", "T02")},
    {"key": "DETECTOR", "ar": "الكاشف أو خلية التدفق", "en": "UV detector / flow cell", "tests": ("T09", "T10", "T11", "T12")},
    {"key": "INJECTOR", "ar": "الحاقن / الإبرة / حلقة العينة", "en": "Injector / needle / sample loop", "tests": ("T05", "T06", "T12", "T13")},
    {"key": "OVEN_COOLER", "ar": "فرن العمود أو مبرد العينات", "en": "Column oven / sample cooler", "tests": ("T07", "T08")},
)


def tests_for_component(component: str) -> tuple[str, ...]:
    for row in BREAKDOWN_MATRIX:
        if row["key"] == component:
            return row["tests"]
    return ()


def test_by_code(code: str) -> TestSpec | None:
    return next((t for t in TESTS if t.code == code), None)
