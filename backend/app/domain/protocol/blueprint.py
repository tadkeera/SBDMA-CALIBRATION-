"""HPLC SHIMADZU LC 2050 C PROTOCOL v2.1.0 — authoritative unified protocol blueprint.

Single source of truth for seeding and execution. Combines:
  - Shimadzu i-Series LC-2050C (UV) Integrity Guide 228-93518D (Ch.2 & Ch.4 iOQ)
  - USA USP <621>, <857>, and <1058> chromatographic & photometric qualification tests
  - Flow Rate Accuracy configuration: 1.0, 1.5, 2.0 mL/min, ten measured replicates per
    set point, ±2.0 % accuracy (98.0–102.0 %) and %RSD ≤ 1.0 % (v2.1.0, on request)

Conflict resolution policy:
  - Flow Rate Accuracy (T02): 1.0, 1.5, 2.0 mL/min × 10 replicates; the adopted
    AUTHORITY_LIMIT is ±2.0 % accuracy and %RSD ≤ 1.0 %. The stricter manufacturer
    ±1.0 % and the iOQ ±2.5 % rows stay in the table and remain selectable as the
    run's limit-source policy — they were not deleted, only out-ranked.
  - All other parameters: where references conflict, the stricter USA USP or
    Shimadzu Integrity Guide (Ch.2 / iOQ) operational limit is adopted as AUTHORITY_LIMIT.
  - All limit source_type values strictly conform to the database Enum:
    INTEGRITY_GUIDE_CH2, IOQ_PROTOCOL_CH4, MANUFACTURER_SPEC, SOP_LIMIT, AUTHORITY_LIMIT.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

PROTOCOL_CODE = "HPLC-SHIMADZU-LC2050C-PROTOCOL"
PROTOCOL_VERSION = "2.1.0"
PROTOCOL_TITLE_AR = "بروتوكول معايرة وتحقق أداء جهاز HPLC SHIMADZU LC 2050 C الموحد"
PROTOCOL_TITLE_EN = "HPLC SHIMADZU LC 2050 C PROTOCOL"

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
# 20 Unified Tests — HPLC SHIMADZU LC 2050 C PROTOCOL
# ════════════════════════════════════════════════════════════════════════════

TESTS: tuple[TestSpec, ...] = (
    # ── T01: Auto Validation ────────────────────────────────────────────────
    TestSpec(
        code="T01",
        sequence=1,
        name_ar="التحقق التلقائي الشامل (Auto Validation)",
        name_en="Automatic Validation (GRAD mode)",
        module="AUTO",
        standard="Shimadzu Integrity Guide Ch.2 — Auto Validation",
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
            FieldSpec("drift", "انحراف خط الأساس", "Drift", "number", "mAU/h"),
            FieldSpec("gradient_dev", "أقصى انحراف تدرج لوني", "Max gradient deviation", "number", "%"),
            FieldSpec("pressure_limiter_pass", "نجاح محددات الضغط", "Pressure limiter pass", "select", options=("PASS", "FAIL")),
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
        metrics=(
            "wavelength_dev_abs",
            "d2_energy",
            "pulsation",
            "oven_stability",
            "absorbance_dev_abs",
            "noise",
            "drift_abs",
            "gradient_dev_abs",
        ),
        chart="bar",
    ),
    # ── T02: Pump Flow Rate Accuracy (Custom: 1.0, 1.5, 2.0 mL/min, 10 mL, ±1.0%) ──
    TestSpec(
        code="T02",
        sequence=2,
        name_ar="دقة معدل التدفق للمضخة (Flow Rate Accuracy)",
        name_en="Pump Flow Rate Accuracy",
        module="PUMP",
        standard="Custom Protocol (1.0/1.5/2.0 mL/min, 10 mL, ±1.0%) & USP <1058> OQ",
        procedure_ar=(
            "ركّب أنبوب المقاومة واضبط الماء النقي كطور متحرك، وقم بعمل Purge لمدة 3 دقائق ثم انتظر استقرار الضغط (~10 دقائق).",
            "اختبر السرعات الثلاث المعتمدة: 1.0 و1.5 و2.0 mL/min لكل قناة مفعلة.",
            "اجمع حجماً قياسياً قدره 10.0 mL في دورق حجمي معاير Class A وقس الزمن بالثواني بساعة إيقاف معايرة دون ملامسة الأنبوب لسطح الماء.",
            "أدخل السرعات المضبوطة (1.0, 1.5, 2.0) والحجم المجمع (10.0, 10.0, 10.0) والأزمنة المقاسة بالثواني.",
            "حد القبول المعتمد: يجب ألا يتجاوز الخطأ ±1.0% عند أي سرعة.",
        ),
        fields=(
            FieldSpec(
                "flow_p1000",
                "قراءات معدل التدفق عند 1.000 mL/min",
                "Flow readings @ 1.000 mL/min",
                "series",
                "mL/min",
                length=10,
                hint_ar="عشر قراءات مستقلة (Runs 1–10) — القيمة المضبوطة 1.000 mL/min، المدى المقبول 0.980–1.020",
            ),
            FieldSpec(
                "flow_p1500",
                "قراءات معدل التدفق عند 1.500 mL/min",
                "Flow readings @ 1.500 mL/min",
                "series",
                "mL/min",
                length=10,
                hint_ar="عشر قراءات مستقلة (Runs 1–10) — القيمة المضبوطة 1.500 mL/min، المدى المقبول 1.470–1.530",
            ),
            FieldSpec(
                "flow_p2000",
                "قراءات معدل التدفق عند 2.000 mL/min",
                "Flow readings @ 2.000 mL/min",
                "series",
                "mL/min",
                length=10,
                hint_ar="عشر قراءات مستقلة (Runs 1–10) — القيمة المضبوطة 2.000 mL/min، المدى المقبول 1.960–2.040",
            ),
        ),
        formulas=(
            FormulaSpec("mean_p1000", "mean(flow_p1000)", "متوسط قراءات 1.000 mL/min", "Mean @ 1.000 mL/min", 4),
            FormulaSpec("sd_p1000", "sd(flow_p1000)", "الانحراف المعياري عند 1.000 mL/min", "SD @ 1.000 mL/min", 5),
            FormulaSpec("rsd_p1000", "rsd(flow_p1000)", "معامل الاختلاف عند 1.000 mL/min", "%RSD @ 1.000 mL/min", 3),
            FormulaSpec("acc_p1000", "pct_error(mean_p1000, 1.0)", "دقة 1.000 mL/min", "%Accuracy @ 1.000 mL/min", 3),
            FormulaSpec("mean_p1500", "mean(flow_p1500)", "متوسط قراءات 1.500 mL/min", "Mean @ 1.500 mL/min", 4),
            FormulaSpec("sd_p1500", "sd(flow_p1500)", "الانحراف المعياري عند 1.500 mL/min", "SD @ 1.500 mL/min", 5),
            FormulaSpec("rsd_p1500", "rsd(flow_p1500)", "معامل الاختلاف عند 1.500 mL/min", "%RSD @ 1.500 mL/min", 3),
            FormulaSpec("acc_p1500", "pct_error(mean_p1500, 1.5)", "دقة 1.500 mL/min", "%Accuracy @ 1.500 mL/min", 3),
            FormulaSpec("mean_p2000", "mean(flow_p2000)", "متوسط قراءات 2.000 mL/min", "Mean @ 2.000 mL/min", 4),
            FormulaSpec("sd_p2000", "sd(flow_p2000)", "الانحراف المعياري عند 2.000 mL/min", "SD @ 2.000 mL/min", 5),
            FormulaSpec("rsd_p2000", "rsd(flow_p2000)", "معامل الاختلاف عند 2.000 mL/min", "%RSD @ 2.000 mL/min", 3),
            FormulaSpec("acc_p2000", "pct_error(mean_p2000, 2.0)", "دقة 2.000 mL/min", "%Accuracy @ 2.000 mL/min", 3),
            FormulaSpec("max_abs_error", "max(abs(acc_p1000), abs(acc_p1500), abs(acc_p2000))", "أقصى خطأ دقة مطلق", "Worst absolute %accuracy", 3),
            FormulaSpec("max_rsd", "max(rsd_p1000, rsd_p1500, rsd_p2000)", "أقصى معامل اختلاف", "Worst %RSD", 3),
        ),
        metrics=("max_abs_error", "max_rsd"),
        chart="flow",
    ),
    # ── T03: Pressure Pulsation & Limiter ───────────────────────────────────
    TestSpec(
        code="T03",
        sequence=3,
        name_ar="ثبات الضغط ومحددات الضغط (Pressure Pulsation & Limiter)",
        name_en="Pressure Pulsation & Pressure Limiter",
        module="PUMP",
        standard="Shimadzu Integrity Guide Ch.2 — Pump",
        procedure_ar=(
            "ضخ ماء HPLC بمعدل 1.0 mL/min عند 40°C عبر أنبوب المقاومة (~10 MPa) وراقب تذبذب الضغط لمدة دقيقة واحدة.",
            "نفّذ اختبار محددات الضغط (Pressure Limiter) للحد الأعلى (X+1 MPa) والأدنى (X-1 MPa) وتأكد من إيقاف الضخ تلقائياً.",
        ),
        fields=(
            FieldSpec("pulsation", "تذبذب الضغط (النبض)", "Pressure pulsation", "number", "MPa"),
            FieldSpec("upper_limiter_pass", "نجاح محدد الضغط العلوي", "Upper pressure limiter", "select", options=("PASS", "FAIL")),
            FieldSpec("lower_limiter_pass", "نجاح محدد الضغط السفلي", "Lower pressure limiter", "select", options=("PASS", "FAIL")),
        ),
        formulas=(
            FormulaSpec("pulsation", "pulsation", "نبض الضغط المقاس", "Measured pulsation", 3),
        ),
        metrics=("pulsation",),
        chart="bar",
    ),
    # ── T04: Gradient Proportioning Valve (GPV) ─────────────────────────────
    TestSpec(
        code="T04",
        sequence=4,
        name_ar="دقة صمام التدرج اللوني (Gradient Proportioning Valve — GPV)",
        name_en="Gradient Proportioning Valve Accuracy",
        module="PUMP",
        standard="Shimadzu Integrity Guide Ch.2/iOQ & USP <1058> OQ",
        procedure_ar=(
            "ضع ماء HPLC في القنوات المرجعية ومحلول كافيين 10 mg/L (عند 272–273 nm) أو أسيتون 0.1–0.3% (عند 254–265 nm) في قنوات التدرج.",
            "شغّل خطوات التدرج عند 0%، 10%، 50%، 90%، 100% لكل زوج قنوات (A/B وA/C وA/D).",
            "أدخل ارتفاعات الدرجات المقاسة لكل مستوى لحساب النسب الفعلية والانحرافات تلقائياً.",
        ),
        fields=(
            FieldSpec("channel_pair", "زوج القنوات المختبر", "Channel pair", "select", options=("A/B", "A/C", "A/D")),
            FieldSpec("height_0", "ارتفاع خط الأساس عند 0%", "Height at 0%", "number", "mAU"),
            FieldSpec("height_10", "ارتفاع الدرجة عند 10%", "Height at 10%", "number", "mAU"),
            FieldSpec("height_50", "ارتفاع الدرجة عند 50%", "Height at 50%", "number", "mAU"),
            FieldSpec("height_90", "ارتفاع الدرجة عند 90%", "Height at 90%", "number", "mAU"),
            FieldSpec("height_100", "ارتفاع الدرجة عند 100%", "Height at 100%", "number", "mAU"),
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
    # ── T05: Gravimetric Injection Volume Accuracy ──────────────────────────
    TestSpec(
        code="T05",
        sequence=5,
        name_ar="دقة حجم الحقن الوزنية (Injection Volume Accuracy — Gravimetric)",
        name_en="Injection Volume Accuracy (Gravimetric)",
        module="AUTOSAMPLER",
        standard="Shimadzu Integrity Guide Ch.2 (50 µL × 10, ±1.3%)",
        procedure_ar=(
            "أطفئ مبرد العينات (Cooler OFF) لمنع التكثف، واغسل الخطوط بماء HPLC نقي.",
            "ضع 1 mL ماء في قارورة 1.5 mL محكمة الغلق بغطاء Septum وزنها بميزان تحليلي (0.0001 g) وسجل W1.",
            "ضع القارورة في الموقع 1 بالرف الأيسر ونفّذ 10 حقنات متتالية بحجم 50 µL.",
            "أعد وزن القارورة بدقة وسجل W2، ثم أدخل كثافة الماء عند حرارة الغرفة.",
        ),
        fields=(
            FieldSpec("w1", "وزن القارورة قبل الحقن (W1)", "Pre-injection weight (W1)", "number", "g"),
            FieldSpec("w2", "وزن القارورة بعد الحقن (W2)", "Post-injection weight (W2)", "number", "g"),
            FieldSpec("water_density", "كثافة الماء عند حرارة الغرفة", "Water density", "number", "g/mL", hint_ar="مثلاً 0.9970 عند 25°C"),
            FieldSpec("set_vol", "حجم الحقنة الواحدة", "Set injection volume", "number", "µL", hint_ar="القياسي: 50 µL"),
            FieldSpec("n_injections", "عدد الحقنات", "Number of injections", "integer", "—", hint_ar="القياسي: 10 حقنات"),
        ),
        formulas=(
            FormulaSpec("measured_vol", "((w1 - w2) * 1000) / water_density", "الحجم المقاس (µL)", "Measured volume (µL)", 3),
            FormulaSpec("pct_accuracy", "((measured_vol / (set_vol * n_injections)) - 1) * 100", "الدقة النسبية للحجم", "Volumetric %accuracy", 3),
            FormulaSpec("pct_accuracy_abs", "abs(pct_accuracy)", "القيمة المطلقة للدقة", "Absolute %accuracy", 3),
        ),
        metrics=("pct_accuracy_abs",),
        chart="bar",
    ),
    # ── T06: Injection Linearity & Loop Precision ───────────────────────────
    TestSpec(
        code="T06",
        sequence=6,
        name_ar="خطية الحاقن التلقائي وتكرارية الحلقة (Injection Linearity & Precision)",
        name_en="Injection Linearity & Loop Precision",
        module="AUTOSAMPLER",
        standard="Shimadzu iOQ Ch.4 (R² ≥ 0.9990) & USP <1058> OQ",
        procedure_ar=(
            "استخدم محلول كافيين 20 mg/L عند 273 nm (أو 10 ppm وفق الطريقة).",
            "لخطية الحاقن: احقن 5 أحجام متصاعدة (مثل 2, 5, 10, 20, 50 µL) واحسب معامل التحديد R² لمساحة القمم مقابل الحجم.",
            "لتكرارية الحلقة: احقن 5 تكرارات لحجم ثابت واحسب %RSD لمساحات القمم.",
        ),
        fields=(
            FieldSpec("volumes", "أحجام الحقن المختبرة", "Injection volumes", "series", "µL", length=5, hint_ar="مثلاً: 2, 5, 10, 20, 50"),
            FieldSpec("linearity_areas", "مساحات القمم المقابلة", "Peak areas for linearity", "series", "mAU·s", length=5),
            FieldSpec("loop_areas", "مساحات تكرارية الحلقة (5 حقنات)", "Loop repeatability areas", "series", "mAU·s", length=5),
        ),
        formulas=(
            FormulaSpec("r2", "ols_r2(volumes, linearity_areas)", "معامل التحديد R²", "OLS R²", 5),
            FormulaSpec("slope", "ols_slope(volumes, linearity_areas)", "ميل الانحدار", "OLS slope", 5),
            FormulaSpec("intercept", "ols_intercept(volumes, linearity_areas)", "تقاطع الانحدار", "OLS intercept", 5),
            FormulaSpec("loop_rsd", "rsd(loop_areas)", "الانحراف النسبي %RSD", "Loop %RSD", 3),
            FormulaSpec("loop_mean", "mean(loop_areas)", "متوسط المساحات", "Mean area", 3),
            FormulaSpec("loop_sd", "sd(loop_areas)", "الانحراف المعياري (n−1)", "Sample SD", 4),
        ),
        metrics=("r2", "loop_rsd"),
        chart="linearity",
    ),
    # ── T07: Sample Cooler Temperature Accuracy ─────────────────────────────
    TestSpec(
        code="T07",
        sequence=7,
        name_ar="دقة حرارة مبرد العينات (Sample Cooler Temperature Accuracy)",
        name_en="Sample Cooler Temperature Accuracy",
        module="AUTOSAMPLER",
        standard="Shimadzu Integrity Guide Ch.2 & iOQ Ch.4 (4°C ± 3.0°C)",
        procedure_ar=(
            "ضع 1 mL ماء في قارورة 1.5 mL وأدخل حساس الحرارة المعاير عبر الغطاء حتى يلامس قاع القارورة.",
            "ضع القارورة في الموقع 27 على الصفيحة المعدنية (228-61615-42) داخل الرف المخصص.",
            "اضبط المبرد على 4°C وانتظر الاستقرار لمدة ≥ 90 دقيقة (حرارة الغرفة ≤ 30°C).",
            "سجّل قراءة الحساس المرجعي الخام ومعامل تصحيح شهادة المعايرة.",
        ),
        fields=(
            FieldSpec("t_set", "الحرارة المضبوطة", "Set temperature", "number", "°C", hint_ar="القياسي: 4.0°C"),
            FieldSpec("t_ref_raw", "قراءة الحساس المرجعي الخام", "Raw reference reading", "number", "°C"),
            FieldSpec("ref_offset", "معامل تصحيح شهادة المعايرة", "Calibration offset", "number", "°C", hint_ar="0 إن لم يوجد تصحيح"),
        ),
        formulas=(
            FormulaSpec("t_ref_corrected", "t_ref_raw + ref_offset", "الحرارة المرجعية المصححة", "Corrected reference", 3),
            FormulaSpec("error", "t_ref_corrected - t_set", "الخطأ", "Error", 3),
            FormulaSpec("error_abs", "abs(t_ref_corrected - t_set)", "الخطأ المطلق", "Absolute error", 3),
        ),
        metrics=("error_abs",),
        chart="temperature",
    ),
    # ── T08: Column Oven Temperature & Gas Sensor ───────────────────────────
    TestSpec(
        code="T08",
        sequence=8,
        name_ar="دقة وثبات حرارة فرن العمود وحساس الغاز (Column Oven & Gas Sensor)",
        name_en="Column Oven Temperature & Gas Sensor",
        module="OVEN",
        standard="Shimadzu Integrity Guide Ch.2 & USP <1058> OQ (±2.0°C, Stab ≤ 0.20°C)",
        procedure_ar=(
            "ثبّت طرف الحساس الحراري المعاير على حامل العمود بشريط ألمنيوم بعرض 1 cm وأغلق الباب.",
            "اختبر نقاط الحرارة المعتمدة (مثل 25, 40, 50, 60°C أو 40, 50°C) وسجّل Set وDisplay وReference.",
            "سجّل التذبذب الحراري (Fluctuation) من الجهاز، ثم نفّذ اختبار حساس الغاز بحقن 100 µL إيثانول عند 50°C.",
        ),
        fields=(
            FieldSpec("t_set", "درجات الحرارة المضبوطة", "Set temperatures", "series", "°C", length=4, hint_ar="مثلاً: 25, 40, 50, 60"),
            FieldSpec("t_display", "قراءات شاشة الجهاز", "Instrument display", "series", "°C", length=4),
            FieldSpec("t_ref_raw", "قراءات الترمومتر المرجعي الخام", "Raw reference thermometer", "series", "°C", length=4),
            FieldSpec("ref_offset", "معامل تصحيح الترمومتر", "Thermometer offset", "number", "°C"),
            FieldSpec("fluctuation", "تذبذب حرارة الفرن (Fluctuation)", "Oven fluctuation", "number", "°C"),
            FieldSpec("gas_sensor_pass", "استجابة حساس الغاز", "Gas sensor response", "select", options=("PASS", "FAIL")),
        ),
        formulas=(
            FormulaSpec("t_ref_corrected", "t_ref_raw + ref_offset", "الحرارة المرجعية المصححة", "Corrected reference", 3),
            FormulaSpec("error_set", "max(abs(t_set - (t_ref_raw + ref_offset)))", "أقصى |T_Set − T_Ref|", "Max |T_Set − T_Ref|", 3),
            FormulaSpec("error_display", "max(abs(t_display - (t_ref_raw + ref_offset)))", "أقصى |T_Display − T_Ref|", "Max |T_Display − T_Ref|", 3),
            FormulaSpec("fluctuation", "fluctuation", "التذبذب المقاس", "Measured fluctuation", 3),
        ),
        metrics=("error_set", "error_display", "fluctuation"),
        chart="temperature",
    ),
    # ── T09: D2 Lamp Energy, Lamp Hours & Wavelength Accuracy (Shimadzu) ────
    TestSpec(
        code="T09",
        sequence=9,
        name_ar="طاقة وساعات لمبة D2 ودقة الطول الموجي (المدمج + كافيين)",
        name_en="D2 Lamp Energy, Hours & Wavelength Accuracy (Shimadzu)",
        module="DETECTOR",
        standard="Shimadzu Integrity Guide Ch.2 & iOQ Ch.4",
        procedure_ar=(
            "من Performance Check → Detector → Wavelength accuracy/Lamp energy: تحقق من طاقة اللمبة عند 220 nm (≥ 400 mV) وساعات التشغيل (≤ 2000 ساعة).",
            "تحقق من دقة الطول الموجي المدمجة عبر فلتر الهولميوم (~241 nm) وخط D2 عند 656.1 nm (±1.0 nm).",
            "نفّذ المسح الطيفي لمحلول كافيين 10 mg/L (200–280 nm بخطوة 1 nm) وسجّل القمتين (205 و273 nm) والقاع (245 nm).",
        ),
        fields=(
            FieldSpec("d2_energy", "طاقة لمبة D2 عند 220 nm", "D2 lamp energy @220 nm", "number", "mV"),
            FieldSpec("lamp_hours", "ساعات تشغيل اللمبة", "UV lamp hours", "number", "hrs"),
            FieldSpec("wavelength_dev", "انحراف الطول الموجي المدمج (هولميوم/D2)", "Built-in wavelength deviation", "number", "nm"),
            FieldSpec("peak_205", "القمة الأولى للكافيين (~205 nm)", "Caffeine peak 1 (~205 nm)", "number", "nm"),
            FieldSpec("valley_245", "القاع الطيفي للكافيين (~245 nm)", "Caffeine valley (~245 nm)", "number", "nm"),
            FieldSpec("peak_273", "القمة الثانية للكافيين (~273 nm)", "Caffeine peak 2 (~273 nm)", "number", "nm"),
        ),
        formulas=(
            FormulaSpec("d2_energy", "d2_energy", "طاقة اللمبة", "Lamp energy", 0),
            FormulaSpec("lamp_hours", "lamp_hours", "ساعات تشغيل اللمبة", "Lamp hours", 0),
            FormulaSpec("lamp_headroom", "2000 - lamp_hours", "الساعات المتبقية للاستبدال", "Hours remaining", 0),
            FormulaSpec("wavelength_dev_abs", "abs(wavelength_dev)", "الانحراف المطلق المدمج", "Built-in abs deviation", 2),
            FormulaSpec("peak1_dev", "abs(peak_205 - 205)", "انحراف القمة 205 nm", "Peak-1 deviation", 2),
            FormulaSpec("valley_dev", "abs(valley_245 - 245)", "انحراف القاع 245 nm", "Valley deviation", 2),
            FormulaSpec("peak2_dev", "abs(peak_273 - 273)", "انحراف القمة 273 nm", "Peak-2 deviation", 2),
        ),
        metrics=("d2_energy", "lamp_hours", "wavelength_dev_abs", "peak1_dev", "valley_dev", "peak2_dev"),
        chart="spectrum",
    ),
    # ── T10: Absorbance Accuracy (Filter) & Detector Linearity ──────────────
    TestSpec(
        code="T10",
        sequence=10,
        name_ar="دقة الامتصاصية بالفلتر وخطية الكاشف (Detector Linearity)",
        name_en="Absorbance Accuracy (Filter) & Detector Linearity",
        module="DETECTOR",
        standard="Shimadzu Ch.2/iOQ (R² ≥ 0.9990) & USP <857>",
        procedure_ar=(
            "نفّذ فحص دقة الامتصاصية بالفلتر المدمج أو الخارجي JCRM230A (±3.0%).",
            "احقن 5 تراكيز كافيين (20, 30, 40, 50, 60 mg/L) عند 272–273 nm بحيث يكون أعلى ارتفاع قمة ≤ 1.5 AU.",
            "يُحسب تلقائياً معامل التحديد R² (حد iOQ الصارم ≥ 0.9990) وأقصى انحراف للحساسية النسبية (±5.0%).",
        ),
        fields=(
            FieldSpec("absorbance_dev", "انحراف الامتصاصية بالفلتر", "Filter absorbance deviation", "number", "%"),
            FieldSpec("concs", "تراكيز محاليل الكافيين", "Caffeine concentrations", "series", "mg/L", length=5, hint_ar="20, 30, 40, 50, 60"),
            FieldSpec("heights", "ارتفاعات القمم المقاسة", "Peak heights", "series", "mAU", length=5),
        ),
        formulas=(
            FormulaSpec("absorbance_dev_abs", "abs(absorbance_dev)", "القيمة المطلقة لانحراف الامتصاصية", "Abs absorbance deviation", 2),
            FormulaSpec("r2", "ols_r2(concs, heights)", "معامل التحديد R²", "OLS R²", 5),
            FormulaSpec("slope", "ols_slope(concs, heights)", "ميل منحنى المعايرة", "Calibration slope", 5),
            FormulaSpec("intercept", "ols_intercept(concs, heights)", "تقاطع المنحنى", "Calibration intercept", 5),
            FormulaSpec("rs_dev_max", "max(abs(rs_deviation(heights, concs)))", "أقصى انحراف حساسية نسبية", "Max relative sensitivity deviation", 3),
        ),
        metrics=("absorbance_dev_abs", "r2", "rs_dev_max"),
        chart="linearity",
    ),
    # ── T11: UV Baseline Noise & Drift ──────────────────────────────────────
    TestSpec(
        code="T11",
        sequence=11,
        name_ar="ضجيج وانحراف خط الأساس (UV Baseline Noise & Drift)",
        name_en="UV Baseline Noise & Drift",
        module="DETECTOR",
        standard="Shimadzu Integrity Guide Ch.2 (ASTM E1657-98)",
        procedure_ar=(
            "ركّب أنبوب المقاومة واضبط ماء HPLC منزوع الغاز عند 1.0 mL/min، حرارة الفرن والخلية 40°C، الطول الموجي 250 nm، زمن الاستجابة 2 ثانية.",
            "انتظر 60 دقيقة للاستقرار ثم سجّل خط الأساس لمدة 15 دقيقة لحساب متوسط الضجيج والانحراف الساعي.",
        ),
        fields=(
            FieldSpec("noise", "ضجيج خط الأساس (Noise)", "Baseline noise", "number", "mAU"),
            FieldSpec("drift", "انحراف خط الأساس الساعي (Drift)", "Baseline drift", "number", "mAU/h"),
        ),
        formulas=(
            FormulaSpec("noise", "noise", "الضجيج المقاس", "Measured noise", 4),
            FormulaSpec("drift_abs", "abs(drift)", "القيمة المطلقة للانحراف", "Absolute drift", 3),
        ),
        metrics=("noise", "drift_abs"),
        chart="repeatability",
    ),
    # ── T12: System Repeatability & Carryover ───────────────────────────────
    TestSpec(
        code="T12",
        sequence=12,
        name_ar="تكرارية النظام والترحيل المتبقي (System Repeatability & Carryover)",
        name_en="System Repeatability & Carryover",
        module="SYSTEM",
        standard="Shimadzu Ch.2 (RT ≤ 0.5%, CO ≤ 0.01%) & USP <621> Table 2 (Area ≤ 0.85%)",
        procedure_ar=(
            "للتكرارية: احقن 6 حقنات متتالية من محلول الكافيين القياسي (20 mg/L) وسجّل أزمنة الاستبقاء RT ومساحات القمم.",
            "للترحيل المتبقي (Carryover): احقن محلول كافيين عالي التركيز (250 mg/L) متبوعاً مباشرة بحقنة Blank (ماء) وسجّل المساحتين.",
            "ملاحظة حسم التعارض: اعتُمد حد %RSD للمساحة ≤ 0.85% وفق USP <621> Table 2 (لـ n=6, B=2.0%) وحد RT ≤ 0.5% وفق شيمادزو.",
        ),
        fields=(
            FieldSpec("rt_values", "أزمنة الاستبقاء (6 حقنات)", "Retention times (6 injections)", "series", "min", length=6),
            FieldSpec("areas", "مساحات القمم (6 حقنات)", "Peak areas (6 injections)", "series", "mAU·s", length=6),
            FieldSpec("area_blank", "مساحة القمة في حقنة الـ Blank", "Blank peak area", "number", "mAU·s"),
            FieldSpec("area_sample_250", "مساحة القمة للعينة المركزة (250 mg/L)", "High-std peak area", "number", "mAU·s"),
        ),
        formulas=(
            FormulaSpec("rt_mean", "mean(rt_values)", "متوسط زمن الاستبقاء", "Mean RT", 4),
            FormulaSpec("rt_rsd", "rsd(rt_values)", "الانحراف النسبي لزمن الاستبقاء", "RT %RSD", 3),
            FormulaSpec("area_mean", "mean(areas)", "متوسط المساحات", "Mean area", 3),
            FormulaSpec("area_rsd", "rsd(areas)", "الانحراف النسبي للمساحات", "Area %RSD", 3),
            FormulaSpec("carryover_pct", "(area_blank / area_sample_250) * 100", "نسبة الترحيل المتبقي %", "Carryover %", 5),
        ),
        metrics=("rt_rsd", "area_rsd", "carryover_pct"),
        chart="repeatability",
    ),
    # ── T13: Leak Sensors & System Adjustment ───────────────────────────────
    TestSpec(
        code="T13",
        sequence=13,
        name_ar="حساسات التسرب والضبط الميكانيكي (Leak Sensors & Adjustment)",
        name_en="Leak Sensors & System Adjustment",
        module="SYSTEM",
        standard="Shimadzu Integrity Guide Ch.2 — Other",
        procedure_ar=(
            "من Performance Check → Other → Leak Sensor: بلّل حساس كل وحدة (Detector, Pump, Autosampler HPV & LPV) بماء HPLC ونفّذ الفحص ثم جفّف الماء فوراً.",
            "عند تغيير الإبرة أو الرفوف: نفّذ Rack Setting وInjection Port Teaching.",
        ),
        fields=(
            FieldSpec("leak_detector", "حساس تسرب الكاشف", "Detector leak sensor", "select", options=("PASS", "FAIL")),
            FieldSpec("leak_pump", "حساس تسرب المضخة", "Pump leak sensor", "select", options=("PASS", "FAIL")),
            FieldSpec("leak_hpv", "حساس تسرب الحاقن HPV", "Autosampler HPV leak sensor", "select", options=("PASS", "FAIL")),
            FieldSpec("leak_lpv", "حساس تسرب الحاقن LPV", "Autosampler LPV leak sensor", "select", options=("PASS", "FAIL")),
        ),
        formulas=(),
        metrics=(),
        chart="none",
    ),
    # ── T14: USP <857> Wavelength Accuracy & Repeatability — UV ─────────────
    TestSpec(
        code="T14",
        sequence=14,
        name_ar="دقة وتكرارية الطول الموجي — نطاق UV (USP <857>)",
        name_en="Wavelength Accuracy & Repeatability — UV (USP <857>)",
        module="DETECTOR",
        standard="USA USP <857> Table 1 (200–400 nm)",
        procedure_ar=(
            "استخدم مادة مرجعية معتمدة CRM (مثل أكسيد الهولميوم أو خطوط D2) ضمن نطاق 200–400 nm.",
            "نفّذ 6 قياسات مكررة للطول الموجي وأدخل القيمة المرجعية للـ CRM والقياسات الستة.",
            "حدود USP <857> Table 1: الدقة ≤ 1.0 nm، والتكرارية (SD) ≤ 0.5 nm.",
        ),
        fields=(
            FieldSpec("crm_wavelength", "الطول الموجي المرجعي (CRM)", "CRM certified wavelength", "number", "nm"),
            FieldSpec("measured_wavelengths", "الأطوال الموجية المقاسة (6 تكرارات)", "Measured wavelengths (6 replicates)", "series", "nm", length=6),
        ),
        formulas=(
            FormulaSpec("uv_wl_mean", "mean(measured_wavelengths)", "متوسط الطول الموجي المقاس", "Mean measured wavelength", 3),
            FormulaSpec("uv_wl_acc", "abs(mean(measured_wavelengths) - crm_wavelength)", "خطأ دقة الطول الموجي UV", "UV wavelength accuracy error", 3),
            FormulaSpec("uv_wl_sd", "sd(measured_wavelengths)", "الانحراف المعياري للتكرارية (SD)", "UV wavelength repeatability SD", 3),
        ),
        metrics=("uv_wl_acc", "uv_wl_sd"),
        chart="spectrum",
    ),
    # ── T15: USP <857> Wavelength Accuracy & Repeatability — Vis ────────────
    TestSpec(
        code="T15",
        sequence=15,
        name_ar="دقة وتكرارية الطول الموجي — نطاق Vis (USP <857>)",
        name_en="Wavelength Accuracy & Repeatability — Vis (USP <857>)",
        module="DETECTOR",
        standard="USA USP <857> Table 1 (400–780 nm)",
        procedure_ar=(
            "استخدم مادة مرجعية معتمدة CRM (أو خط انبعاث الديوتيريوم 486.0 nm / 656.1 nm) ضمن نطاق 400–780 nm.",
            "نفّذ 6 قياسات مكررة وأدخل القيمة المرجعية والقياسات الستة.",
            "حدود USP <857> Table 1: الدقة ≤ 2.0 nm، والتكرارية (SD) ≤ 0.5 nm.",
        ),
        fields=(
            FieldSpec("crm_wavelength", "الطول الموجي المرجعي Vis (CRM)", "CRM certified wavelength (Vis)", "number", "nm"),
            FieldSpec("measured_wavelengths", "الأطوال الموجية المقاسة (6 تكرارات)", "Measured wavelengths (6 replicates)", "series", "nm", length=6),
        ),
        formulas=(
            FormulaSpec("vis_wl_mean", "mean(measured_wavelengths)", "متوسط الطول الموجي المقاس", "Mean measured wavelength", 3),
            FormulaSpec("vis_wl_acc", "abs(mean(measured_wavelengths) - crm_wavelength)", "خطأ دقة الطول الموجي Vis", "Vis wavelength accuracy error", 3),
            FormulaSpec("vis_wl_sd", "sd(measured_wavelengths)", "الانحراف المعياري للتكرارية (SD)", "Vis wavelength repeatability SD", 3),
        ),
        metrics=("vis_wl_acc", "vis_wl_sd"),
        chart="spectrum",
    ),
    # ── T16: USP <857> Absorbance Accuracy & Repeatability (< 1.0 AU) ───────
    TestSpec(
        code="T16",
        sequence=16,
        name_ar="دقة وتكرارية الامتصاصية (< 1.0 AU) — USP <857>",
        name_en="Absorbance Accuracy & Repeatability (< 1.0 AU) — USP <857>",
        module="DETECTOR",
        standard="USA USP <857> Table 4 (< 1.0 AU)",
        procedure_ar=(
            "استخدم محلولاً مرجعياً معتمداً (مثل K2Cr2O7 أو Nicotinic Acid) بامتصاصية معتمدة أقل من 1.0 AU.",
            "سجّل 6 قراءات امتصاصية متكررة وأدخل القيمة المرجعية للـ CRM.",
            "حدود USP <857> Table 4: الدقة ≤ 0.010 AU، والتكرارية (SD) ≤ 0.005 AU.",
        ),
        fields=(
            FieldSpec("crm_abs", "الامتصاصية المرجعية المعتمدة (CRM)", "CRM certified absorbance", "number", "AU"),
            FieldSpec("measured_abs", "قراءات الامتصاصية المقاسة (6 تكرارات)", "Measured absorbances (6 replicates)", "series", "AU", length=6),
        ),
        formulas=(
            FormulaSpec("abs_low_mean", "mean(measured_abs)", "متوسط الامتصاصية", "Mean absorbance", 4),
            FormulaSpec("abs_low_acc", "abs(mean(measured_abs) - crm_abs)", "خطأ دقة الامتصاصية (< 1.0 AU)", "Absorbance accuracy error", 4),
            FormulaSpec("abs_low_sd", "sd(measured_abs)", "الانحراف المعياري للتكرارية (SD)", "Absorbance repeatability SD", 4),
        ),
        metrics=("abs_low_acc", "abs_low_sd"),
        chart="bar",
    ),
    # ── T17: USP <857> Absorbance Accuracy & Repeatability (> 1.0 AU) ───────
    TestSpec(
        code="T17",
        sequence=17,
        name_ar="دقة وتكرارية الامتصاصية (> 1.0 AU) — USP <857>",
        name_en="Absorbance Accuracy & Repeatability (> 1.0 AU) — USP <857>",
        module="DETECTOR",
        standard="USA USP <857> Table 4 (> 1.0 AU)",
        procedure_ar=(
            "استخدم محلولاً مرجعياً معتمداً بامتصاصية معتمدة أعلى من 1.0 AU.",
            "سجّل 6 قراءات امتصاصية متكررة وأدخل القيمة المرجعية للـ CRM.",
            "حدود USP <857> Table 4: الدقة ≤ 1.0%، والتكرارية ≤ 0.50%.",
        ),
        fields=(
            FieldSpec("crm_abs", "الامتصاصية المرجعية المعتمدة (CRM)", "CRM certified absorbance", "number", "AU"),
            FieldSpec("measured_abs", "قراءات الامتصاصية المقاسة (6 تكرارات)", "Measured absorbances (6 replicates)", "series", "AU", length=6),
        ),
        formulas=(
            FormulaSpec("abs_high_mean", "mean(measured_abs)", "متوسط الامتصاصية", "Mean absorbance", 4),
            FormulaSpec("abs_high_acc_pct", "(abs(mean(measured_abs) - crm_abs) / crm_abs) * 100", "نسبة خطأ الدقة %", "Absorbance accuracy %error", 3),
            FormulaSpec("abs_high_sd_pct", "(sd(measured_abs) / crm_abs) * 100", "نسبة التكرارية %", "Absorbance repeatability %", 3),
        ),
        metrics=("abs_high_acc_pct", "abs_high_sd_pct"),
        chart="bar",
    ),
    # ── T18: USP <857> Stray Light Limit ────────────────────────────────────
    TestSpec(
        code="T18",
        sequence=18,
        name_ar="حد الضوء الشارد (Stray Light Limit — USP <857>)",
        name_en="Stray Light Limit (USP <857>)",
        module="DETECTOR",
        standard="USA USP <857> Table 5",
        procedure_ar=(
            "الإجراء A (مرشح القطع المزدوج): قس فرق الامتصاص ΔA بين خليتين بمسارين ضوئيين (10 mm و5 mm)؛ الحد ΔA ≥ 0.7 AU (ويكافئ S_λ ≤ 0.01).",
            "الإجراء B (مرشح القطع الفردي): قس أقصى امتصاص A_max لمحلول القطع القياسي (مثل KCl أو NaI)؛ الحد A_max ≥ 2.0 AU.",
        ),
        fields=(
            FieldSpec("delta_a", "فرق الامتصاص ΔA (إجراء A)", "Absorbance difference ΔA (Proc. A)", "number", "AU"),
            FieldSpec("a_max", "أقصى امتصاص A_max (إجراء B)", "Max absorbance A_max (Proc. B)", "number", "AU"),
        ),
        formulas=(
            FormulaSpec("delta_a", "delta_a", "فرق الامتصاص ΔA", "ΔA (Proc. A)", 3),
            FormulaSpec("stray_light_s", "0.25 * (10 ** (-2 * delta_a))", "معامل الضوء الشارد S_λ", "Stray light ratio S_λ", 5),
            FormulaSpec("a_max", "a_max", "أقصى امتصاص A_max", "A_max (Proc. B)", 3),
        ),
        metrics=("delta_a", "stray_light_s", "a_max"),
        chart="bar",
    ),
    # ── T19: USP <857> Spectral Resolution ──────────────────────────────────
    TestSpec(
        code="T19",
        sequence=19,
        name_ar="دقة الفصل الطيفي (Spectral Resolution — USP <857>)",
        name_en="Spectral Resolution (USP <857>)",
        module="DETECTOR",
        standard="USA USP <857> — Control of Resolution",
        procedure_ar=(
            "حضّر محلول تولوين 0.020% (v/v) في الهكسان النقي.",
            "قس الامتصاص عند القمة (~269 nm) وعند القاع (~266 nm) مقابل الهكسان كـ Blank.",
            "حد USP <857>: نسبة الامتصاص (A_269 / A_266) ≥ 1.3 لعرض نطاق طيفي SBW ≤ 2 nm.",
        ),
        fields=(
            FieldSpec("abs_269", "الامتصاص عند القمة (~269 nm)", "Peak absorbance (~269 nm)", "number", "AU"),
            FieldSpec("abs_266", "الامتصاص عند القاع (~266 nm)", "Minimum absorbance (~266 nm)", "number", "AU"),
        ),
        formulas=(
            FormulaSpec("res_ratio", "abs_269 / abs_266", "نسبة الفصل الطيفي (A269 / A266)", "Spectral resolution ratio", 3),
        ),
        metrics=("res_ratio",),
        chart="bar",
    ),
    # ── T20: USP <621> Chromatographic System Suitability ───────────────────
    TestSpec(
        code="T20",
        sequence=20,
        name_ar="ملاءمة النظام الكروماتوغرافي (USP <621> System Suitability)",
        name_en="Chromatographic System Suitability (USP <621>)",
        module="SYSTEM",
        standard="USA USP <621> — S/N, Symmetry, Plates & Resolution",
        procedure_ar=(
            "قس ارتفاع القمة H عند حد التقدير الكمي (LOQ) وارتفاع ضجيج خط الأساس h في الـ Blank لحساب S/N = 2H/h (≥ 10.0).",
            "قس عرض القمة عند 5% من ارتفاعها (W_0.05) والمسافة الأمامية (d) لحساب معامل التماثل A_s = W_0.05 / (2d) (بين 0.8 و1.8).",
            "سجّل أزمنة الاستبقاء (t_R1, t_R2) وعرض القمتين عند منتصف الارتفاع (W_h1, W_h2) لحساب عدد الصفائح النظرية N (≥ 2000) والدقة R_s (≥ 2.0).",
        ),
        fields=(
            FieldSpec("peak_height_h", "ارتفاع القمة (H)", "Peak height (H)", "number", "mAU"),
            FieldSpec("blank_noise_h", "ارتفاع ضجيج الـ Blank (h)", "Blank noise height (h)", "number", "mAU"),
            FieldSpec("w_005", "عرض القمة عند 5% (W_0.05)", "Peak width at 5% height", "number", "min"),
            FieldSpec("d_leading", "المسافة الأمامية عند 5% (d)", "Leading half-width at 5%", "number", "min"),
            FieldSpec("tr1", "زمن استبقاء القمة الأولى (t_R1)", "Retention time peak 1", "number", "min"),
            FieldSpec("tr2", "زمن استبقاء القمة الثانية (t_R2)", "Retention time peak 2", "number", "min"),
            FieldSpec("wh1", "عرض القمة 1 عند 50% (W_h1)", "Width at half-height peak 1", "number", "min"),
            FieldSpec("wh2", "عرض القمة 2 عند 50% (W_h2)", "Width at half-height peak 2", "number", "min"),
        ),
        formulas=(
            FormulaSpec("sn_ratio", "(2 * peak_height_h) / blank_noise_h", "نسبة الإشارة إلى الضجيج (S/N)", "Signal-to-Noise ratio (S/N)", 2),
            FormulaSpec("as_factor", "w_005 / (2 * d_leading)", "معامل تماثل القمة (A_s)", "Symmetry / Tailing factor (A_s)", 3),
            FormulaSpec("plate_n", "5.54 * ((tr2 / wh2) ** 2)", "عدد الصفائح النظرية (N)", "Theoretical plates (N)", 0),
            FormulaSpec("rs", "(1.18 * (tr2 - tr1)) / (wh1 + wh2)", "دقة الفصل الكروماتوغرافي (R_s)", "Chromatographic resolution (R_s)", 3),
        ),
        metrics=("sn_ratio", "as_factor", "plate_n", "rs"),
        chart="bar",
    ),
)


# ════════════════════════════════════════════════════════════════════════════
# Acceptance Limits (Unified Authority + Reference Comparison)
# ════════════════════════════════════════════════════════════════════════════

A: Approval = "APPROVED"
C: Approval = "CONFLICT_REQUIRES_QA"


def _L(
    test_code: str,
    metric_key: str,
    source_type: LimitSource,
    operator: Operator,
    min_value: str | int | float | None,
    max_value: str | int | float | None,
    unit: str,
    approval_status: Approval,
    note_ar: str | None = None,
    flagged: bool = False,
) -> LimitSpec:
    return LimitSpec(
        test_code=test_code,
        metric_key=metric_key,
        source_type=source_type,
        operator=operator,
        min_value=_d(min_value),
        max_value=_d(max_value),
        unit=unit,
        approval_status=approval_status,
        note_ar=note_ar,
        flagged=flagged,
    )


LIMITS: tuple[LimitSpec, ...] = (
    # T01 — Auto Validation (Shimadzu Ch.2)
    _L("T01", "wavelength_dev_abs", "INTEGRITY_GUIDE_CH2", "lte", None, 1.0, "nm", A),
    _L("T01", "wavelength_dev_abs", "AUTHORITY_LIMIT", "lte", None, 1.0, "nm", A, "Shimadzu Ch.2 / USP <857> UV"),
    _L("T01", "d2_energy", "INTEGRITY_GUIDE_CH2", "gte", 400, None, "mV", A),
    _L("T01", "d2_energy", "AUTHORITY_LIMIT", "gte", 400, None, "mV", A),
    _L("T01", "pulsation", "INTEGRITY_GUIDE_CH2", "lte", None, 0.2, "MPa", A),
    _L("T01", "pulsation", "AUTHORITY_LIMIT", "lte", None, 0.2, "MPa", A),
    _L("T01", "oven_stability", "INTEGRITY_GUIDE_CH2", "lte", None, 0.2, "°C", A),
    _L("T01", "oven_stability", "AUTHORITY_LIMIT", "lte", None, 0.2, "°C", A),
    _L("T01", "absorbance_dev_abs", "INTEGRITY_GUIDE_CH2", "lte", None, 3.0, "%", A),
    _L("T01", "absorbance_dev_abs", "AUTHORITY_LIMIT", "lte", None, 3.0, "%", A),
    _L("T01", "noise", "INTEGRITY_GUIDE_CH2", "lte", None, 0.02, "mAU", A),
    _L("T01", "noise", "AUTHORITY_LIMIT", "lte", None, 0.02, "mAU", A),
    _L("T01", "drift_abs", "INTEGRITY_GUIDE_CH2", "lte", None, 0.6, "mAU/h", A),
    _L("T01", "drift_abs", "AUTHORITY_LIMIT", "lte", None, 0.6, "mAU/h", A),
    _L("T01", "gradient_dev_abs", "INTEGRITY_GUIDE_CH2", "lte", None, 2.0, "%", A),
    _L("T01", "gradient_dev_abs", "AUTHORITY_LIMIT", "lte", None, 2.0, "%", A),

    # T02 — Pump Flow Rate Accuracy (Custom Override: 1.0, 1.5, 2.0 mL/min, 10 mL, ±1.0%)
    _L("T02", "max_abs_error", "INTEGRITY_GUIDE_CH2", "lte", None, 2.0, "%", A, "حد شيمادزو Ch.2 المرجعي (±2.0%)"),
    _L("T02", "max_abs_error", "IOQ_PROTOCOL_CH4", "lte", None, 2.5, "%", A, "حد iOQ الوزني (±2.5%)"),
    _L("T02", "max_abs_error", "MANUFACTURER_SPEC", "lte", None, 1.0, "%", A, "مواصفة المصنع (±1.0%)"),
    _L(
        "T02", "max_abs_error", "AUTHORITY_LIMIT", "lte", None, 2.0, "%", A,
        "الحد المعتمد (v2.1.0): الدقة ±2.0% أي 98.0–102.0% عند 1.000 و1.500 و2.000 mL/min — "
        "طلب الهيئة؛ صف المصنع ±1.0% باقٍ وقابل للاختيار كسياسة تشغيل",
    ),
    _L(
        "T02", "max_rsd", "AUTHORITY_LIMIT", "lte", None, 1.0, "%", A,
        "الحد المعتمد (v2.1.0): %RSD ≤ 1.0% عبر عشر قراءات لكل نقطة ضبط",
    ),
    _L("T02", "max_rsd", "SOP_LIMIT", "lte", None, 1.0, "%", A, "إجراء التشغيل القياسي: %RSD ≤ 1.0%"),

    # T03 — Pressure Pulsation
    _L("T03", "pulsation", "INTEGRITY_GUIDE_CH2", "lte", None, 0.2, "MPa", A),
    _L("T03", "pulsation", "AUTHORITY_LIMIT", "lte", None, 0.2, "MPa", A),

    # T04 — Gradient Proportioning Valve (GPV)
    _L("T04", "max_abs_dev", "INTEGRITY_GUIDE_CH2", "lte", None, 2.0, "%", A),
    _L("T04", "max_abs_dev", "IOQ_PROTOCOL_CH4", "lte", None, 2.0, "%", A),
    _L("T04", "max_abs_dev", "MANUFACTURER_SPEC", "lte", None, 0.5, "%", A),
    _L("T04", "max_abs_dev", "AUTHORITY_LIMIT", "lte", None, 2.0, "%", A, "تطابق شيمادزو وUSP <1058> OQ: ±2.0%"),

    # T05 — Gravimetric Injection Volume Accuracy
    _L("T05", "pct_accuracy_abs", "INTEGRITY_GUIDE_CH2", "lte", None, 1.3, "%", A, "10 حقنات × 50 µL وزني"),
    _L("T05", "pct_accuracy_abs", "IOQ_PROTOCOL_CH4", "lte", None, 2.0, "%", A),
    _L("T05", "pct_accuracy_abs", "MANUFACTURER_SPEC", "lte", None, 1.0, "%", A),
    _L("T05", "pct_accuracy_abs", "AUTHORITY_LIMIT", "lte", None, 1.3, "%", A, "اعتماد حد شيمادزو Ch.2 الأشد (±1.3%)"),

    # T06 — Injection Linearity & Loop Precision
    _L("T06", "r2", "IOQ_PROTOCOL_CH4", "gte", 0.999, None, "—", A),
    _L("T06", "r2", "MANUFACTURER_SPEC", "gte", 0.9999, None, "—", A),
    _L("T06", "r2", "AUTHORITY_LIMIT", "gte", 0.999, None, "—", A, "اعتماد Shimadzu iOQ (R² ≥ 0.9990؛ أشد من USP 0.995)"),
    _L("T06", "loop_rsd", "SOP_LIMIT", "lte", None, 2.0, "%", A),
    _L("T06", "loop_rsd", "AUTHORITY_LIMIT", "lte", None, 2.0, "%", A),

    # T07 — Sample Cooler Temperature Accuracy
    _L("T07", "error_abs", "INTEGRITY_GUIDE_CH2", "lte", None, 3.0, "°C", A, "4°C ± 3.0°C في الموقع 27"),
    _L("T07", "error_abs", "IOQ_PROTOCOL_CH4", "lte", None, 3.0, "°C", A),
    _L("T07", "error_abs", "AUTHORITY_LIMIT", "lte", None, 3.0, "°C", A, "اعتماد Shimadzu Ch.2/iOQ"),

    # T08 — Column Oven Temperature & Fluctuation
    _L("T08", "error_set", "INTEGRITY_GUIDE_CH2", "lte", None, 2.0, "°C", A),
    _L("T08", "error_set", "IOQ_PROTOCOL_CH4", "lte", None, 2.0, "°C", A),
    _L("T08", "error_set", "MANUFACTURER_SPEC", "lte", None, 0.8, "°C", A),
    _L("T08", "error_set", "AUTHORITY_LIMIT", "lte", None, 2.0, "°C", A, "Shimadzu Ch.2/iOQ وUSP <1058>"),
    _L("T08", "error_display", "AUTHORITY_LIMIT", "lte", None, 2.0, "°C", A),
    _L("T08", "fluctuation", "INTEGRITY_GUIDE_CH2", "lte", None, 0.2, "°C", A),
    _L("T08", "fluctuation", "AUTHORITY_LIMIT", "lte", None, 0.2, "°C", A),

    # T09 — D2 Lamp Energy, Hours & Wavelength Accuracy (Shimadzu)
    _L("T09", "d2_energy", "INTEGRITY_GUIDE_CH2", "gte", 400, None, "mV", A),
    _L("T09", "d2_energy", "AUTHORITY_LIMIT", "gte", 400, None, "mV", A),
    _L("T09", "lamp_hours", "INTEGRITY_GUIDE_CH2", "lte", None, 2000, "hrs", A),
    _L("T09", "lamp_hours", "AUTHORITY_LIMIT", "lte", None, 2000, "hrs", A, "الحد الاستبدالي الموصى به 2000 ساعة"),
    _L("T09", "wavelength_dev_abs", "INTEGRITY_GUIDE_CH2", "lte", None, 1.0, "nm", A),
    _L("T09", "wavelength_dev_abs", "AUTHORITY_LIMIT", "lte", None, 1.0, "nm", A),
    _L("T09", "peak1_dev", "IOQ_PROTOCOL_CH4", "lte", None, 2.0, "nm", A, "قمة 205 ± 2 nm"),
    _L("T09", "peak1_dev", "AUTHORITY_LIMIT", "lte", None, 2.0, "nm", A),
    _L("T09", "valley_dev", "IOQ_PROTOCOL_CH4", "lte", None, 2.0, "nm", A, "قاع 245 ± 2 nm"),
    _L("T09", "valley_dev", "AUTHORITY_LIMIT", "lte", None, 2.0, "nm", A),
    _L("T09", "peak2_dev", "IOQ_PROTOCOL_CH4", "lte", None, 2.0, "nm", A, "قمة 273 ± 2 nm"),
    _L("T09", "peak2_dev", "AUTHORITY_LIMIT", "lte", None, 2.0, "nm", A),

    # T10 — Absorbance Accuracy & Detector Linearity
    _L("T10", "absorbance_dev_abs", "INTEGRITY_GUIDE_CH2", "lte", None, 3.0, "%", A),
    _L("T10", "absorbance_dev_abs", "AUTHORITY_LIMIT", "lte", None, 3.0, "%", A),
    _L("T10", "r2", "IOQ_PROTOCOL_CH4", "gte", 0.999, None, "—", A),
    _L("T10", "r2", "AUTHORITY_LIMIT", "gte", 0.999, None, "—", A, "اعتماد Shimadzu iOQ (R² ≥ 0.9990؛ أشد من USP 0.995)"),
    _L("T10", "rs_dev_max", "INTEGRITY_GUIDE_CH2", "lte", None, 5.0, "%", A),
    _L("T10", "rs_dev_max", "AUTHORITY_LIMIT", "lte", None, 5.0, "%", A),

    # T11 — UV Baseline Noise & Drift
    _L("T11", "noise", "INTEGRITY_GUIDE_CH2", "lte", None, 0.02, "mAU", A),
    _L("T11", "noise", "IOQ_PROTOCOL_CH4", "lte", None, 0.04, "mAU", A),
    _L("T11", "noise", "MANUFACTURER_SPEC", "lte", None, 0.0025, "mAU", A),
    _L("T11", "noise", "AUTHORITY_LIMIT", "lte", None, 0.02, "mAU", A, "اعتماد Shimadzu Ch.2 (≤ 0.0200 mAU)"),
    _L("T11", "drift_abs", "INTEGRITY_GUIDE_CH2", "lte", None, 0.6, "mAU/h", A),
    _L("T11", "drift_abs", "IOQ_PROTOCOL_CH4", "lte", None, 0.5, "mAU/h", A),
    _L("T11", "drift_abs", "AUTHORITY_LIMIT", "lte", None, 0.6, "mAU/h", A, "اعتماد Shimadzu Ch.2 (≤ 0.60 mAU/h)"),

    # T12 — System Repeatability & Carryover
    _L("T12", "rt_rsd", "INTEGRITY_GUIDE_CH2", "lte", None, 0.5, "%", A),
    _L("T12", "rt_rsd", "AUTHORITY_LIMIT", "lte", None, 0.5, "%", A, "اعتماد Shimadzu Ch.2/iOQ (RT %RSD ≤ 0.5%)"),
    _L("T12", "area_rsd", "INTEGRITY_GUIDE_CH2", "lte", None, 1.0, "%", A, "حد شيمادزو Ch.2 (≤ 1.0%)"),
    _L("T12", "area_rsd", "AUTHORITY_LIMIT", "lte", None, 0.85, "%", A, "اعتماد USA USP <621> Table 2 (B=2.0%, n=6 → ≤ 0.85%)"),
    _L("T12", "carryover_pct", "INTEGRITY_GUIDE_CH2", "lte", None, 0.01, "%", A),
    _L("T12", "carryover_pct", "IOQ_PROTOCOL_CH4", "lte", None, 0.1, "%", C, "حد iOQ أوسع 10 أضعاف — مرفوض لصالح ≤ 0.010%", True),
    _L("T12", "carryover_pct", "AUTHORITY_LIMIT", "lte", None, 0.01, "%", A, "اعتماد ≤ 0.010% (Shimadzu Ch.2 & USP OQ)"),

    # T14 — USP <857> Wavelength UV
    _L("T14", "uv_wl_acc", "AUTHORITY_LIMIT", "lte", None, 1.0, "nm", A, "USA USP <857> Table 1 (200–400 nm: ±1.0 nm)"),
    _L("T14", "uv_wl_sd", "AUTHORITY_LIMIT", "lte", None, 0.5, "nm", A, "USA USP <857> Table 1 (SD ≤ 0.5 nm)"),

    # T15 — USP <857> Wavelength Vis
    _L("T15", "vis_wl_acc", "AUTHORITY_LIMIT", "lte", None, 2.0, "nm", A, "USA USP <857> Table 1 (400–780 nm: ±2.0 nm)"),
    _L("T15", "vis_wl_sd", "AUTHORITY_LIMIT", "lte", None, 0.5, "nm", A, "USA USP <857> Table 1 (SD ≤ 0.5 nm)"),

    # T16 — USP <857> Absorbance (< 1.0 AU)
    _L("T16", "abs_low_acc", "AUTHORITY_LIMIT", "lte", None, 0.01, "AU", A, "USA USP <857> Table 4 (< 1.0 AU: ±0.010 AU)"),
    _L("T16", "abs_low_sd", "AUTHORITY_LIMIT", "lte", None, 0.005, "AU", A, "USA USP <857> Table 4 (SD ≤ 0.005 AU)"),

    # T17 — USP <857> Absorbance (> 1.0 AU)
    _L("T17", "abs_high_acc_pct", "AUTHORITY_LIMIT", "lte", None, 1.0, "%", A, "USA USP <857> Table 4 (> 1.0 AU: ±1.0%)"),
    _L("T17", "abs_high_sd_pct", "AUTHORITY_LIMIT", "lte", None, 0.5, "%", A, "USA USP <857> Table 4 (≤ 0.50%)"),

    # T18 — USP <857> Stray Light
    _L("T18", "delta_a", "AUTHORITY_LIMIT", "gte", 0.7, None, "AU", A, "USA USP <857> Table 5 Proc. A (ΔA ≥ 0.7 AU)"),
    _L("T18", "stray_light_s", "AUTHORITY_LIMIT", "lte", None, 0.01, "—", A, "USA USP <857> Table 5 Proc. A (S_λ ≤ 0.01)"),
    _L("T18", "a_max", "AUTHORITY_LIMIT", "gte", 2.0, None, "AU", A, "USA USP <857> Table 5 Proc. B (A_max ≥ 2.0 AU)"),

    # T19 — USP <857> Spectral Resolution
    _L("T19", "res_ratio", "AUTHORITY_LIMIT", "gte", 1.3, None, "—", A, "USA USP <857> Toluene/Hexane (≥ 1.3 for SBW ≤ 2 nm)"),

    # T20 — USP <621> Chromatographic System Suitability
    _L("T20", "sn_ratio", "AUTHORITY_LIMIT", "gte", 10.0, None, "—", A, "USA USP <621> LOQ Sensitivity (S/N ≥ 10.0)"),
    _L("T20", "as_factor", "AUTHORITY_LIMIT", "between", 0.8, 1.8, "—", A, "USA USP <621> Peak Symmetry (0.8 ≤ A_s ≤ 1.8)"),
    _L("T20", "plate_n", "AUTHORITY_LIMIT", "gte", 2000, None, "—", A, "USA USP <621> Column Efficiency (N ≥ 2000)"),
    _L("T20", "rs", "AUTHORITY_LIMIT", "gte", 2.0, None, "—", A, "USA USP <621> Resolution (R_s ≥ 2.0)"),
)


# ════════════════════════════════════════════════════════════════════════════
# Post-breakdown calibration matrix
# ════════════════════════════════════════════════════════════════════════════

BREAKDOWN_MATRIX: tuple[dict[str, Any], ...] = (
    {"key": "PUMP", "ar": "المضخة / أختام المكبس", "en": "Pump / Plunger seals", "tests": ("T02", "T03", "T04")},
    {"key": "D2_LAMP", "ar": "لمبة الديوتيريوم", "en": "D2 lamp replacement", "tests": ("T09", "T11", "T14", "T18")},
    {"key": "GPV", "ar": "صمام التدرج اللوني", "en": "Gradient proportioning valve", "tests": ("T04", "T02")},
    {"key": "DETECTOR", "ar": "الكاشف أو خلية التدفق", "en": "UV detector / flow cell", "tests": ("T09", "T10", "T11", "T12", "T14", "T16", "T17", "T18", "T19")},
    {"key": "INJECTOR", "ar": "الحاقن / الإبرة / حلقة العينة", "en": "Injector / needle / sample loop", "tests": ("T05", "T06", "T12", "T13")},
    {"key": "OVEN_COOLER", "ar": "فرن العمود أو مبرد العينات", "en": "Column oven / sample cooler", "tests": ("T07", "T08")},
    {"key": "COLUMN_SUITABILITY", "ar": "تغيير العمود / ملاءمة النظام", "en": "Column / System Suitability", "tests": ("T12", "T20")},
)


def tests_for_component(component: str) -> tuple[str, ...]:
    for row in BREAKDOWN_MATRIX:
        if row["key"] == component:
            return row["tests"]
    return ()


def test_by_code(code: str) -> TestSpec | None:
    return next((t for t in TESTS if t.code == code), None)
