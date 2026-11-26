"""The English reference manual and documented procedures — one authoritative source.

Two things live here, and they are both *documentation attached to a test*, not logic:

  * ``PROCEDURES_EN`` — the documented procedure printed in the laboratory screen for
    each of the 20 tests. The agency asked for laboratory-grade English (USP / Ph. Eur.
    / ISO 17025 wording) instead of the Arabic steps, so the wording is held in one
    reference file rather than inline in a component, and it is written to the database
    (``test_definitions.procedure_en``) so the document that is printed is the document
    a reviewer can audit against the protocol revision.

  * ``MANUAL`` — the Reference Manual entry for each test: what the test is for, the
    readings an analyst must enter with the ideal reference values used as a worked
    example, how each metric is evaluated, and the scientific sources the limits and
    equations come from.

Why a separate module and not the blueprint?
--------------------------------------------
``blueprint.py`` is the *measurement* contract: fields, formulas, limits. This file is
the *explanation* of that contract. Keeping them apart means a limit can change without
touching prose, and prose can be corrected without any risk of altering a verdict — the
reviewer can diff the two independently. ``test_reference_manual.py`` enforces the link:
every test code has an entry here, every ideal reading names a real field, every
evaluation note names a real metric, and every formula has an evaluation note.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class IdealReading:
    """One row of the "Required Readings" table: a field, and the ideal worked example."""

    field: str
    value: str
    note_en: str


@dataclass(frozen=True, slots=True)
class ManualEntry:
    overview_en: str
    ideal_readings: tuple[IdealReading, ...]
    #: metric key → how the metric is evaluated (Mean / SD / %RSD / R² / regression …)
    evaluation_en: tuple[tuple[str, str], ...]
    references: tuple[str, ...] = ()
    #: extra accepted sources quoted verbatim with the limit they justify
    limit_notes: tuple[str, ...] = field(default_factory=tuple)


# ════════════════════════════════════════════════════════════════════════════
# Documented procedures — English, laboratory wording
# ════════════════════════════════════════════════════════════════════════════

PROCEDURES_EN: dict[str, tuple[str, ...]] = {
    "T01": (
        "From the instrument keypad select Menu → Maintenance → Validation → Auto Validation, then choose the GRAD. mode and the flow-channel pairs A/B, A/C and A/D.",
        "Install the restrictor tube (Shimadzu P/N 228-38994) in the column oven in place of the analytical column; the auto-validation routine requires a defined back-pressure.",
        "Place caffeine solution 10 mg/L in reservoir A and HPLC-grade water in reservoirs B, C and D, and fill the wash port with the same water.",
        "Verify that ambient-temperature variation during the run is less than ±1 °C, press Start, and allow the complete validation cycle to finish without interruption.",
        "Press [Logged] to commit the results to the validation log, print the log page, and transcribe the displayed values into the fields on this screen.",
        "Attach the validation-log printout to the run record; the transcribed values must be traceable to the instrument's own log, never re-keyed from memory.",
    ),
    "T02": (
        "Set the pump to 1.000 mL/min with degassed HPLC-grade water as the mobile phase and allow the pressure to stabilise for at least 10 minutes.",
        "For each of the ten replicates, weigh a clean, dry 10 mL volumetric flask to 0.1 mg (W1), start the pump and a calibrated stopwatch together, and collect the eluate for the timed interval.",
        "Stop the pump and the timer together, re-weigh the flask (W2), convert the collected mass to volume with the water density at the recorded ambient temperature, and compute the delivered flow for that replicate.",
        "Enter the ten replicate flows (Runs 1–10) in mL/min for the 1.000 mL/min set point; the page recalculates the mean, SD, %RSD and %accuracy on every keystroke.",
        "Repeat steps 1 to 4 for the 1.500 mL/min and 2.000 mL/min set points, ten replicates each, and enter them in the corresponding row of the grid.",
        "Press Run Calibration to render the accuracy and control charts, then Save. The reported result is the worst absolute %accuracy and the worst %RSD across the three set points; acceptance is ±2.0 % accuracy and %RSD ≤ 1.0 %.",
    ),
    "T03": (
        "Equilibrate the pump at 1.0 mL/min with degassed water for 15 minutes and confirm a stable baseline pressure.",
        "Read the pressure pulsation amplitude from the instrument's pump monitor over a 5-minute window and record the maximum peak-to-peak value in MPa.",
        "Activate the upper pressure limiter and confirm that the pump stops or enters the error state at the configured limit; record PASS when the interlocks respond as designed.",
        "Activate the lower pressure limiter (leak/under-pressure detection) and confirm the same controlled response; record PASS accordingly.",
        "Reset both limiters to their validated operating values and confirm the system returns to normal operation before releasing the instrument.",
    ),
    "T04": (
        "Configure the quaternary gradient with water as channel A and a 0.1 % acetone aqueous solution as the trace channel, and select the channel pair under test (A/B, A/C or A/D).",
        "At 0 % trace channel, record the stable baseline absorbance height in mAU after equilibration.",
        "Step the trace channel to 10 %, 50 % and 90 %, allowing full equilibration at each step, and record the absorbance height in mAU.",
        "Step the trace channel to 100 % and record the plateau absorbance height.",
        "Linearise the four response points against the nominal proportions and calculate the deviation at each level; the largest absolute deviation, in percentage points, is the reported result.",
    ),
    "T05": (
        "Fill the autosampler vial with HPLC-grade water and set the injection volume to 50 µL with the sample cooler at the validated temperature.",
        "Weigh the vial, septa and cap assembly to 0.01 mg on a calibrated microbalance and record the pre-injection mass W1.",
        "Program 10 consecutive injections and run them without interruption so that evaporation from the vial is kept constant across the series.",
        "Remove the vial and re-weigh the assembly to 0.01 mg, recording the post-injection mass W2.",
        "Calculate the delivered volume from the mass difference and the water density at ambient temperature, compare it with the nominal volume for the series, and report the absolute percentage accuracy.",
    ),
    "T06": (
        "Prepare a caffeine standard solution and programme five injection volumes across the validated range (for example 5, 10, 15, 20 and 25 µL).",
        "Inject each volume once and record the peak area for the linearity series.",
        "Program five replicate injections at the nominal loop volume and record the peak areas for the loop-precision series.",
        "Fit an ordinary least-squares line of peak area against injection volume and record the coefficient of determination R² and the slope.",
        "Calculate the mean, standard deviation and relative standard deviation of the replicate areas; a %RSD above the SOP limit indicates loop or injector wear and the test fails.",
    ),
    "T07": (
        "Set the sample cooler to the validated operating temperature (4 °C) and allow at least 30 minutes for thermal equilibration.",
        "Insert the calibrated reference thermometer into the cooler block next to the sample tray, applying the certificate correction offset for the reference thermometer.",
        "Allow the reading to stabilise for 10 minutes and record the raw reference temperature.",
        "Record the corrected reference temperature and compare it with the set temperature; the absolute difference is the reported result.",
        "Verify that the cooler holds the set point for a further 15 minutes before returning the autosampler to routine use.",
    ),
    "T08": (
        "Set the column oven to each validated temperature (for example 30, 40, 50 and 60 °C), allowing 20 minutes of equilibration at each set point.",
        "At each set point record the temperature indicated by the instrument display and the temperature indicated by the calibrated reference thermometer placed in the oven's calibration port.",
        "Apply the reference-thermometer correction offset and calculate the difference between the set temperature and the corrected reference, and between the display and the corrected reference.",
        "Record the oven fluctuation (maximum deviation from the mean over a 10-minute window) at the nominal operating temperature.",
        "Verify the gas-sensor response by confirming that the sensor reports a normal atmosphere and that no alarm is latched; record PASS or FAIL.",
    ),
    "T09": (
        "With the UV detector at 220 nm and the flow cell filled with HPLC-grade water, record the deuterium (D2) lamp energy in mV after 30 minutes of lamp warm-up.",
        "Read the accumulated UV lamp hours from the detector's lamp-information screen.",
        "Run the detector's built-in wavelength check (D2 line) and record the deviation reported by the instrument.",
        "Scan a caffeine solution across 200–300 nm and record the wavelengths of the two maxima (approximately 205 nm and 273 nm) and of the minimum between them (approximately 245 nm).",
        "Compare each observed wavelength with its reference value; the absolute deviation for each feature is evaluated against the acceptance limits.",
    ),
    "T10": (
        "Insert the holmium-oxide or neutral-density verification filter, or use the internal filter set, and record the absorbance deviation reported by the detector.",
        "Prepare five caffeine calibration standards across the validated concentration range (for example 2, 5, 10, 20 and 50 mg/L).",
        "Inject each standard and record the peak height in mAU.",
        "Fit an ordinary least-squares line of peak height against concentration and record the coefficient of determination R².",
        "Calculate the relative sensitivity (response factor) at each level and report the largest absolute deviation from the mean response factor as the linearity criterion.",
    ),
    "T11": (
        "Equilibrate the detector with mobile phase at 1.0 mL/min for 30 minutes at the validated wavelength, with the flow cell filled and the lamp warmed up.",
        "Record the baseline noise over a 10-minute window at the instrument's standard noise integration interval, in mAU.",
        "Record the baseline drift over a 60-minute window (short-term drift), expressed in mAU/h.",
        "Evaluate both values against the approved limits for the adopted limit source; a drift failure usually indicates mobile-phase degassing, lamp ageing or thermal instability.",
        "Re-run the measurement after correcting ambient conditions before issuing a failing verdict, and record both attempts in the run comments.",
    ),
    "T12": (
        "Prepare a suitability standard at a concentration giving a peak of adequate height (for example 250 mg/L caffeine) and equilibrate the system to a stable baseline.",
        "Inject the standard six times consecutively and record the retention time and peak area of every injection.",
        "Inject a blank (mobile phase) immediately after the sixth injection and record the largest peak area in the blank window.",
        "Calculate the mean, standard deviation and %RSD for retention time and for peak area across the six injections.",
        "Calculate carryover as the blank peak area expressed as a percentage of the high-standard peak area, and compare all three results with the approved limits.",
    ),
    "T13": (
        "Inspect the detector, pump, and autosampler high-pressure and low-pressure valve leak sensors for residual liquid, and dry any traces before testing.",
        "Trigger each leak sensor in turn according to the service manual (simulated leak or sensor test function) and confirm that the instrument reports the alarm and stops the affected module.",
        "Reset each alarm and confirm that the module returns to a ready state without a latched error.",
        "Record PASS for each sensor that responded and FAIL for any sensor that did not; a failed leak sensor is a safety finding and the instrument must be taken out of service.",
    ),
    "T14": (
        "Verify the wavelength scale in the ultraviolet region using a certified reference material (for example a holmium-oxide filter or a potassium dichromate solution) with a certified wavelength within 200–400 nm.",
        "Record the certified wavelength of the reference material from its calibration certificate.",
        "Perform six replicate wavelength determinations at the certified line and record each measured wavelength.",
        "Calculate the mean measured wavelength, its absolute difference from the certified value (accuracy) and the standard deviation of the six replicates (repeatability).",
        "Compare the accuracy and repeatability results with the USP <857> acceptance criteria adopted by the laboratory.",
    ),
    "T15": (
        "Verify the wavelength scale in the visible region using a certified reference material with a certified line in 400–780 nm (for example a holmium-oxide filter at approximately 536 nm or 546 nm).",
        "Record the certified wavelength of the reference material from its calibration certificate.",
        "Perform six replicate wavelength determinations at the certified line and record each measured wavelength.",
        "Calculate the mean measured wavelength, the absolute deviation from the certified value and the standard deviation of the replicates.",
        "Compare the results with the visible-region acceptance criteria adopted from USP <857> Table 1.",
    ),
    "T16": (
        "Select a certified reference material with a certified absorbance below 1.0 AU at the validated wavelength.",
        "Record the certified absorbance value from the reference-material certificate.",
        "Perform six replicate absorbance readings of the reference material after cell equilibration, and record every value.",
        "Calculate the mean absorbance, the absolute deviation of the mean from the certified value, and the standard deviation of the replicates.",
        "Compare the accuracy and repeatability results with the limits adopted from USP <857> Table 4 for the low-absorbance range.",
    ),
    "T17": (
        "Select a certified reference material with a certified absorbance above 1.0 AU at the validated wavelength.",
        "Record the certified absorbance value from the reference-material certificate.",
        "Perform six replicate absorbance readings after thermal and optical equilibration and record every value.",
        "Calculate the mean absorbance, the relative accuracy error as a percentage of the certified value, and the repeatability as a percentage of the certified value.",
        "Compare the percentage results with the limits adopted from USP <857> Table 4 for the high-absorbance range.",
    ),
    "T18": (
        "Procedure A (absorbance ratio): measure the absorbance of the stray-light reference solution at the specified wavelength and calculate the absorbance difference ΔA against the reference blank.",
        "Procedure B (maximum absorbance): measure the maximum absorbance A_max of the saturated reference solution at the specified wavelength.",
        "Calculate the stray-light ratio S_λ from ΔA using the relationship adopted from USP <857>.",
        "Compare ΔA, S_λ and A_max with the acceptance criteria; a stray-light ratio above 1 % invalidates measurements made at the high-absorbance end of the scale.",
    ),
    "T19": (
        "Record the absorbance of the resolution reference solution at the wavelength of the peak maximum (approximately 269 nm).",
        "Record the absorbance at the wavelength of the minimum between the two lines (approximately 266 nm).",
        "Calculate the ratio of the peak absorbance to the minimum absorbance; this ratio is the spectral resolution criterion.",
        "Compare the ratio with the minimum acceptable value adopted from USP <857>; a ratio below the limit means the spectral bandwidth is too wide for the intended assay.",
    ),
    "T20": (
        "Prepare a system-suitability solution containing at least two components whose resolution is to be demonstrated, and equilibrate the system to a stable baseline.",
        "Record the peak height of the analyte (H) and the peak-to-peak noise height of a blank injection (h) over the same integration interval, and calculate S/N = 2H/h.",
        "Measure the peak width at 5 % height (W_0.05) and the leading half-width at 5 % height (d_leading), and calculate the symmetry factor A_s = W_0.05 / (2 · d_leading).",
        "Record the retention times and the widths at half height of the two components and calculate the number of theoretical plates N and the resolution R_s.",
        "Compare S/N, A_s, N and R_s with the system-suitability limits; the run is not valid for assay unless all four criteria are met.",
    ),
}


# ════════════════════════════════════════════════════════════════════════════
# Reference Manual entries
# ════════════════════════════════════════════════════════════════════════════

MANUAL: dict[str, ManualEntry] = {
    "T01": ManualEntry(
        overview_en=(
            "The automatic validation (GRAD. mode) is the instrument's own integrated qualification routine for a "
            "Shimadzu i-Series LC-2050C. In one unattended cycle it exercises the photometric, pumping, thermal and "
            "gradient subsystems and reports the key performance indicators that the integrity guide specifies for "
            "installation and routine qualification. It is the fastest way to demonstrate that the instrument is "
            "still within its validated performance envelope before a calibration campaign, and it is the first "
            "evidence an auditor asks for when the instrument's history is questioned."
        ),
        ideal_readings=(
            IdealReading("wavelength_dev", "0.12", "Holmium/D2 line deviation well inside the ±1.0 nm limit"),
            IdealReading("d2_energy", "1240", "D2 lamp at mid-life; anything below 400 mV means replacement"),
            IdealReading("pulsation", "0.08", "Peak-to-peak pressure ripple of a healthy single-piston pump"),
            IdealReading("oven_stability", "0.06", "Oven holds ±0.2 °C comfortably at the validated set point"),
            IdealReading("absorbance_dev", "0.4", "Internal filter deviation, percent of nominal absorbance"),
            IdealReading("noise", "0.008", "Baseline noise far below the 0.02 mAU limit"),
            IdealReading("drift", "0.15", "Short-term baseline drift, mAU per hour"),
            IdealReading("gradient_dev", "0.6", "Worst gradient-proportioning deviation across A/B, A/C, A/D"),
            IdealReading("pressure_limiter_pass", "PASS", "Both pump interlocks responded to the test trigger"),
        ),
        evaluation_en=(
            ("wavelength_dev_abs", "Absolute value of the reported wavelength deviation (|Δλ|), compared with the limit."),
            ("d2_energy", "Lamp energy read directly from the detector, compared with the lower limit (≥ 400 mV)."),
            ("pulsation", "Peak-to-peak pressure amplitude in MPa, compared with the upper limit."),
            ("oven_stability", "Maximum deviation of the oven temperature from its set point during the stability window."),
            ("absorbance_dev_abs", "Absolute absorbance deviation of the internal filter, as a percentage."),
            ("noise", "Peak-to-peak baseline noise in mAU over the integration interval."),
            ("drift_abs", "Absolute short-term baseline drift in mAU/h."),
            ("gradient_dev_abs", "Largest absolute deviation, in percentage points, between nominal and measured gradient composition."),
        ),
        references=(
            "Shimadzu i-Series LC-2050C Integrity Guide 228-93518D, Chapter 2 (Auto Validation).",
            "USP <1058> Analytical Instrument Qualification — installation and operational qualification.",
            "ISO/IEC 17025:2017 §6.4.4 — equipment performance verification before use.",
        ),
        limit_notes=(
            "The integrity guide and the authority limit agree for every criterion of this test, so the adopted "
            "limit is identical under either source.",
        ),
    ),
    "T02": ManualEntry(
            overview_en=(
                "Flow-rate accuracy is the gravimetric determination of the volume the pump actually delivers against "
                "the volume it is programmed to deliver. Because retention time, resolution and quantitative injection "
                "volume all depend on it, a pump that is 3 % high will silently shift every chromatogram and bias "
                "every assay derived from peak area. The laboratory adopted a three-point protocol (1.000, 1.500 and "
                "2.000 mL/min) with ten independent replicates at each set point, because a single determination "
                "cannot separate a genuine offset from random weighing noise: the mean carries the accuracy verdict, "
                "while the %RSD across the ten replicates carries the precision verdict. Acceptance is ±2.0 % "
                "accuracy (98.0–102.0 %) and %RSD ≤ 1.0 % at every set point."
            ),
            ideal_readings=(
                IdealReading("flow_p1000", "1.0000 mL/min × 10", "Ten replicates at the 1.000 mL/min set point; spread within ±0.005"),
                IdealReading("flow_p1500", "1.5000 mL/min × 10", "Ten replicates at the 1.500 mL/min set point; spread within ±0.007"),
                IdealReading("flow_p2000", "2.0000 mL/min × 10", "Ten replicates at the 2.000 mL/min set point; spread within ±0.010"),
            ),
            evaluation_en=(
                (
                    "mean_p1000 / mean_p1500 / mean_p2000",
                    "Mean flow of the ten replicates at each set point, mL/min — the value accuracy is judged on.",
                ),
                (
                    "sd_p1000 / sd_p1500 / sd_p2000",
                    "Sample standard deviation of the ten replicates (n − 1), mL/min.",
                ),
                (
                    "rsd_p1000 / rsd_p1500 / rsd_p2000",
                    "%RSD = (SD / mean) × 100 across the ten replicates of one set point.",
                ),
                (
                    "acc_p1000 / acc_p1500 / acc_p2000",
                    "%Accuracy = ((mean − nominal) / nominal) × 100 with the nominal 1.000, 1.500 or 2.000 mL/min.",
                ),
                ("max_abs_error", "The worst absolute %Accuracy of the three set points is compared with ±2.0 %."),
                ("max_rsd", "The worst %RSD of the three set points is compared with the ≤ 1.0 % limit."),
            ),
            references=(
                "USP <1058> Analytical Instrument Qualification — operational qualification of solvent delivery systems.",
                "Shimadzu i-Series LC-2050C Integrity Guide 228-93518D, Chapter 2 (pump).",
                "ISO/IEC 17025:2017 §7.7 — ensuring the validity of results by performance checks.",
            ),
            limit_notes=(
                "The v2.1.0 authority limit is ±2.0 % accuracy (98.0–102.0 %) with %RSD ≤ 1.0 % across the ten "
                "replicates, adopted on the board's request. The manufacturer ±1.0 % and the iOQ ±2.5 % rows remain "
                "in the limit table and can be selected as the run's limit-source policy; nothing was deleted.",
            ),
        ),
    "T03": ManualEntry(
            overview_en=(
                "Pressure pulsation is the residual ripple superimposed on the pump's delivery pressure by the piston "
                "stroke and the damper. Excessive pulsation degrades baseline stability, shortens column life and, at "
                "the detector, appears as noise that undermines low-level quantitation. This test records the "
                "pulsation amplitude and verifies that both the upper and lower pressure limiters still protect the "
                "column and the flow cell."
            ),
            ideal_readings=(
                IdealReading("pulsation", "0.08", "Comfortably below the 0.2 MPa limit"),
                IdealReading("upper_limiter_pass", "PASS", "Pump stopped at the configured upper pressure limit"),
                IdealReading("lower_limiter_pass", "PASS", "Pump stopped on under-pressure / leak detection"),
            ),
            evaluation_en=(
                ("pulsation", "Peak-to-peak pressure amplitude in MPa over a 5-minute window, compared with 0.2 MPa."),
                ("upper_limiter_pass", "Boolean; PASS requires the pump to stop or alarm at the configured upper limit."),
                ("lower_limiter_pass", "Boolean; PASS requires the same controlled response at the lower limit."),
            ),
            references=(
                "Shimadzu i-Series LC-2050C Integrity Guide 228-93518D, Chapter 2 (pump).",
                "USP <1058> — operational qualification, solvent delivery.",
            ),
    ),
    "T04": ManualEntry(
            overview_en=(
                "The gradient proportioning valve mixes up to four solvents at programmed ratios. A valve that "
                "delivers 8 % instead of 10 % of a modifier produces a systematically shifted retention pattern and "
                "invalidates method transfer and robustness studies. The test follows a tracer (0.1 % acetone) "
                "through four nominal proportions and compares the measured composition with the requested one."
            ),
            ideal_readings=(
                IdealReading("channel_pair", "A/B", "One pair per test; repeat for A/C and A/D"),
                IdealReading("height_0", "0.5", "Baseline at 0 % trace channel, mAU"),
                IdealReading("height_10", "118.5", "Response at 10 % — measured 10.2 %"),
                IdealReading("height_50", "580.0", "Response at 50 % — measured 50.2 %"),
                IdealReading("height_90", "1040.0", "Response at 90 % — measured 90.0 %"),
                IdealReading("height_100", "1155.0", "Full-scale plateau response, mAU"),
            ),
            evaluation_en=(
                ("actual_10 / actual_50 / actual_90", "Actual proportion = ((H_n − H_0) / (H_100 − H_0)) × 100."),
                ("dev_10 / dev_50 / dev_90 / dev_100", "Deviation at each level = actual proportion − nominal proportion."),
                ("max_abs_dev", "Largest absolute deviation in percentage points, compared with the adopted limit."),
            ),
            references=(
                "Shimadzu Integrity Guide 228-93518D, Chapter 2 and iOQ protocol Chapter 4.",
                "USP <1058> — solvent proportioning performance.",
            ),
            limit_notes=(
                "Manufacturer specification 0.5 %, integrity guide and iOQ 2.0 %. The adopted authority limit is 2.0 %.",
            ),
    ),
    "T05": ManualEntry(
            overview_en=(
                "Injection-volume accuracy is verified gravimetrically: the autosampler injects a known number of "
                "aliquots of water from a sealed vial, and the mass lost by the vial is converted to volume. This is "
                "the most direct evidence that the injection volume the method demands is the volume the sample loop "
                "delivers — the single largest source of systematic error in assay results."
            ),
            ideal_readings=(
                IdealReading("w1", "12.5432", "Pre-injection mass of vial + septum + cap, g"),
                IdealReading("w2", "12.0405", "Post-injection mass after 10 × 50 µL, g"),
                IdealReading("water_density", "0.9982", "Water density at the recorded ambient temperature, g/mL"),
                IdealReading("set_vol", "50", "Nominal injection volume, µL"),
                IdealReading("n_injections", "10", "Ten consecutive injections per weighing"),
            ),
            evaluation_en=(
                ("measured_vol", "V_measured = ((W1 − W2) × 1000) / ρ_water, in µL."),
                ("pct_accuracy", "%Accuracy = ((V_measured / (V_set × n)) − 1) × 100."),
                ("pct_accuracy_abs", "Absolute percentage accuracy compared with the adopted limit."),
            ),
            references=(
                "Shimadzu Integrity Guide 228-93518D, Chapter 2 (autosampler, 50 µL × 10, ±1.3 %).",
                "USP <1058> — autosampler operational qualification.",
            ),
            limit_notes=(
                "Manufacturer ±1.0 %, integrity guide ±1.3 %, iOQ ±2.0 %. The adopted authority limit is ±1.3 %.",
            ),
    ),
    "T06": ManualEntry(
            overview_en=(
                "Injection linearity and loop precision together describe how faithfully the autosampler reproduces "
                "volume from one injection to the next and across the working range. Non-linearity here masquerades "
                "as detector non-linearity in a calibration curve, and poor loop precision inflates the relative "
                "standard deviation of every replicate injection."
            ),
            ideal_readings=(
                IdealReading("volumes", "5 / 10 / 15 / 20 / 25", "Five injection volumes spanning the working range, µL"),
                IdealReading("linearity_areas", "512.4 / 1019.8 / 1531.2 / 2044.7 / 2552.1", "Areas proportional to volume (R² ≈ 0.99999)"),
                IdealReading("loop_areas", "1523.4 / 1524.1 / 1522.8 / 1523.9 / 1523.2", "Five replicates at the nominal volume (~0.03 % RSD)"),
            ),
            evaluation_en=(
                ("r2", "Ordinary least squares of area against volume; the coefficient of determination must be ≥ 0.999."),
                ("slope / intercept", "OLS slope and intercept of the same fit, reported for method-transfer purposes."),
                ("loop_rsd", "%RSD = (SD / mean) × 100 of the replicate areas, compared with 2.0 %."),
                ("loop_mean / loop_sd", "Mean and sample standard deviation of the replicate areas."),
            ),
            references=(
                "Shimadzu iOQ protocol Chapter 4 (R² ≥ 0.9990).",
                "USP <1058> — autosampler linearity and precision.",
                "ICH Q2(R1) §4.1 / 4.4 — linearity and repeatability evaluation.",
            ),
    ),
    "T07": ManualEntry(
            overview_en=(
                "The sample cooler protects thermolabile analytes during unattended sequences. If the block drifts "
                "above its set point, degradation products appear as extra peaks and as a loss of assay. The test "
                "compares the block temperature — corrected by the reference thermometer's certificate offset — with "
                "the temperature the instrument has been programmed to hold."
            ),
            ideal_readings=(
                IdealReading("t_set", "4.0", "Validated cooler set point, °C"),
                IdealReading("t_ref_raw", "4.3", "Reference thermometer reading, °C"),
                IdealReading("ref_offset", "-0.1", "Certificate correction of the reference thermometer, °C"),
            ),
            evaluation_en=(
                ("t_ref_corrected", "T_corrected = T_raw + offset, applying the calibration certificate."),
                ("error", "Signed difference between corrected reference and set point."),
                ("error_abs", "Absolute difference compared with the ±3.0 °C acceptance limit."),
            ),
            references=(
                "Shimadzu Integrity Guide 228-93518D, Chapter 2 (sample cooler 4 °C ± 3.0 °C).",
                "Shimadzu iOQ protocol Chapter 4.",
            ),
    ),
    "T08": ManualEntry(
            overview_en=(
                "Column-oven temperature governs retention, selectivity and, above all, the reproducibility of a "
                "method between instruments. The test establishes three things: that the true oven temperature "
                "matches the set point, that the displayed temperature is not misleading the analyst, and that the "
                "oven fluctuates within 0.2 °C at the working temperature. The gas sensor is verified at the same "
                "time because it is the oven's safety interlock."
            ),
            ideal_readings=(
                IdealReading("t_set", "30 / 40 / 50 / 60", "Four validated set points, °C"),
                IdealReading("t_display", "30.0 / 40.1 / 49.9 / 60.0", "Instrument display at each set point"),
                IdealReading("t_ref_raw", "30.2 / 40.3 / 50.1 / 60.25", "Raw reference thermometer readings"),
                IdealReading("ref_offset", "-0.05", "Certificate offset applied to every reference reading"),
                IdealReading("fluctuation", "0.08", "Maximum deviation from the mean over 10 minutes"),
                IdealReading("gas_sensor_pass", "PASS", "Sensor reports a normal atmosphere, no latched alarm"),
            ),
            evaluation_en=(
                ("t_ref_corrected", "Corrected reference temperature for each set point."),
                ("error_set", "max |T_set − T_ref,corrected| across the four set points (≤ 2.0 °C)."),
                ("error_display", "max |T_display − T_ref,corrected|, proving the display is trustworthy (≤ 2.0 °C)."),
                ("fluctuation", "Oven fluctuation at the working temperature (≤ 0.20 °C)."),
            ),
            references=(
                "Shimadzu Integrity Guide 228-93518D, Chapter 2 (oven ±2.0 °C, stability ≤ 0.20 °C).",
                "USP <1058> — column-oven operational qualification.",
            ),
            limit_notes=(
                "Manufacturer specification for |T_set − T_ref| is 0.8 °C; the adopted authority limit is the more "
                "conservative integrity-guide 2.0 °C so that a cooled or ambient-limited laboratory is not failed "
                "for a criterion the manufacturer states under full-load conditions.",
            ),
    ),
    "T09": ManualEntry(
            overview_en=(
                "The deuterium lamp is the detector's light source and its output decays with use; the wavelength "
                "scale is what converts a photometric signal into an identification. This test reports lamp energy "
                "and lamp hours as end-of-life indicators, checks the instrument's built-in wavelength deviation, and "
                "confirms the photometric wavelength scale against the well-known caffeine spectrum (two maxima and a "
                "minimum). It is the keyboard-level test that catches a failing lamp before it ruins a sequence."
            ),
            ideal_readings=(
                IdealReading("d2_energy", "1240", "Mid-life lamp energy at 220 nm, mV"),
                IdealReading("lamp_hours", "640", "Accumulated lamp hours; replacement at 2000 h"),
                IdealReading("wavelength_dev", "0.15", "Built-in D2 line deviation, nm"),
                IdealReading("peak_205", "205.2", "Caffeine maximum, reference 205 nm"),
                IdealReading("valley_245", "244.7", "Caffeine minimum, reference 245 nm"),
                IdealReading("peak_273", "273.3", "Caffeine second maximum, reference 273 nm"),
            ),
            evaluation_en=(
                ("d2_energy", "Lamp energy in mV, lower limit 400 mV."),
                ("lamp_hours", "Accumulated hours, upper limit 2000 h (headroom = 2000 − hours)."),
                ("wavelength_dev_abs", "|built-in deviation| ≤ 1.0 nm."),
                ("peak1_dev / valley_dev / peak2_dev", "|observed − reference| for each spectral feature, ≤ 2.0 nm."),
            ),
            references=(
                "Shimadzu Integrity Guide 228-93518D, Chapter 2 (detector).",
                "Shimadzu iOQ protocol Chapter 4.",
                "Ph. Eur. 2.2.25 / USP <857> — photometric wavelength verification.",
            ),
    ),
    "T10": ManualEntry(
            overview_en=(
                "Photometric accuracy and detector linearity determine whether an absorbance reading can be "
                "converted into a concentration. The filter check proves the photometric scale at a fixed wavelength; "
                "the caffeine calibration proves that response stays proportional to concentration across the working "
                "range. Together they answer the question an auditor asks about every quantitative HPLC result: is "
                "the detector linear where you use it?"
            ),
            ideal_readings=(
                IdealReading("absorbance_dev", "0.4", "Filter absorbance deviation, % of nominal"),
                IdealReading("concs", "2 / 5 / 10 / 20 / 50", "Caffeine concentrations, mg/L"),
                IdealReading("heights", "118.4 / 296.5 / 592.0 / 1184.8 / 2961.2", "Proportional peak heights, mAU"),
            ),
            evaluation_en=(
                ("absorbance_dev_abs", "|filter deviation| ≤ 3.0 %."),
                ("r2", "OLS R² of peak height against concentration ≥ 0.999."),
                ("slope / intercept", "Calibration slope (mAU per mg/L) and intercept, reported with the curve."),
                ("rs_dev_max", "Largest absolute deviation of the response factor from its mean sensitivity, ≤ 5.0 %."),
            ),
            references=(
                "USP <857> Ultraviolet-Visible Spectroscopy — photometric accuracy and linearity.",
                "Shimadzu Integrity Guide 228-93518D / iOQ Chapter 4.",
                "ICH Q2(R1) §4.1 — linearity.",
            ),
    ),
    "T11": ManualEntry(
            overview_en=(
                "Baseline noise and drift bound the smallest signal the detector can honestly quantify. Noise sets "
                "the limit of detection and the signal-to-noise criterion of system suitability; drift sets the "
                "practical limit of a long sequence. Both are measured under the same conditions the method uses, "
                "because a detector that is quiet in water but noisy in mobile phase is not qualified for the method."
            ),
            ideal_readings=(
                IdealReading("noise", "0.009", "Peak-to-peak noise over 10 minutes, mAU"),
                IdealReading("drift", "0.18", "Short-term drift over 60 minutes, mAU/h"),
            ),
            evaluation_en=(
                ("noise", "Peak-to-peak noise in mAU, compared with the adopted limit (0.02 mAU)."),
                ("drift_abs", "Absolute drift in mAU/h, compared with the adopted limit (0.6 mAU/h)."),
            ),
            references=(
                "Shimadzu Integrity Guide 228-93518D, Chapter 2 (noise and drift).",
                "ASTM E1657-98 — standard practice for testing variable-wavelength photometric detectors.",
                "USP <621> — system suitability, signal-to-noise.",
            ),
            limit_notes=(
                "Manufacturer specification 0.0025 mAU is a design figure measured with a dry cell; the adopted "
                "authority limit for a flowing system is the integrity-guide 0.02 mAU. Drift: integrity guide and "
                "authority 0.6 mAU/h, iOQ 0.5 mAU/h.",
            ),
    ),
    "T12": ManualEntry(
            overview_en=(
                "System repeatability proves that the whole flow path — pump, injector, column and detector — "
                "reproduces a result injection after injection, and carryover proves that one sample does not "
                "contaminate the next. Carryover is the more dangerous of the two: at 0.1 % it is invisible in a "
                "single chromatogram and decisive in a trace assay."
            ),
            ideal_readings=(
                IdealReading("rt_values", "4.812 / 4.809 / 4.815 / 4.811 / 4.808 / 4.813", "Six consecutive retention times, min"),
                IdealReading("areas", "1523.4 / 1524.1 / 1522.8 / 1523.9 / 1523.2 / 1523.6", "Six replicate peak areas"),
                IdealReading("area_blank", "0.12", "Largest peak area in the blank after the high standard"),
                IdealReading("area_sample_250", "1523.4", "Peak area of the 250 mg/L standard"),
            ),
            evaluation_en=(
                ("rt_mean / rt_rsd", "Mean retention time and its %RSD across six injections (≤ 0.5 %)."),
                ("area_mean / area_rsd", "Mean area and its %RSD (≤ 0.85 %, the stricter USP <621> criterion)."),
                ("carryover_pct", "(A_blank / A_standard) × 100, compared with 0.01 %."),
            ),
            references=(
                "USP <621> Chromatography, Table 2 — system-suitability repeatability.",
                "Shimadzu Integrity Guide 228-93518D, Chapter 2 (RT ≤ 0.5 %, carryover ≤ 0.01 %).",
            ),
            limit_notes=(
                "Carryover: the iOQ protocol states 0.1 %, the integrity guide and authority limit state 0.01 %. "
                "The iOQ figure is seeded as CONFLICT_REQUIRES_QA so it can never produce a silent PASS.",
            ),
    ),
    "T13": ManualEntry(
            overview_en=(
                "Leak sensors are the instrument's safety system: they protect the operator from solvent exposure and "
                "the instrument from flooding. This is a functional test, not a measurement — each sensor is "
                "triggered in turn and the expected controlled shutdown is observed. A sensor that does not respond "
                "is a safety finding, and the instrument leaves service until it is repaired, regardless of every "
                "other result in the run."
            ),
            ideal_readings=(
                IdealReading("leak_detector", "PASS", "Detector leak sensor alarmed and stopped the module"),
                IdealReading("leak_pump", "PASS", "Pump leak sensor alarmed and stopped the pump"),
                IdealReading("leak_hpv", "PASS", "Autosampler high-pressure valve sensor responded"),
                IdealReading("leak_lpv", "PASS", "Autosampler low-pressure valve sensor responded"),
            ),
            evaluation_en=(
                ("leak_detector / leak_pump / leak_hpv / leak_lpv", "Boolean observations: PASS requires an alarm and a controlled stop, then a clean reset."),
            ),
            references=(
                "Shimadzu Integrity Guide 228-93518D, Chapter 2 (other tests — leak sensors).",
                "ISO/IEC 17025:2017 §6.3 — laboratory safety and facility requirements.",
            ),
    ),
    "T14": ManualEntry(
            overview_en=(
                "USP <857> requires the wavelength scale to be verified with a certified reference material in the "
                "region where measurements are made. In the ultraviolet region the criterion is both accuracy (does "
                "the instrument find the line where the certificate says it is?) and repeatability (does it find the "
                "same place six times?). Accuracy bounds systematic bias; repeatability bounds the noise contribution "
                "to every subsequent measurement."
            ),
            ideal_readings=(
                IdealReading("crm_wavelength", "254.0", "Certified wavelength of the reference material, nm"),
                IdealReading("measured_wavelengths", "254.1 / 254.0 / 254.2 / 253.9 / 254.1 / 254.0", "Six replicate determinations"),
            ),
            evaluation_en=(
                ("uv_wl_mean", "Mean of the six measured wavelengths."),
                ("uv_wl_acc", "|mean − certified|, compared with 1.0 nm (USP <857> Table 1)."),
                ("uv_wl_sd", "Sample standard deviation of the six replicates, compared with 0.5 nm."),
            ),
            references=(
                "USP <857> Ultraviolet-Visible Spectroscopy, Table 1 (200–400 nm).",
                "ISO/IEC 17025:2017 §6.4 — traceability of measurement through certified reference materials.",
            ),
    ),
    "T15": ManualEntry(
            overview_en=(
                "The visible region is verified separately because the optical path, lamp and grating behaviour differ "
                "from the ultraviolet: a detector can be perfect at 254 nm and two nanometres out at 546 nm. USP "
                "<857> sets a looser accuracy criterion here (2.0 nm) and keeps the same tight repeatability "
                "requirement, reflecting the wider acceptance of visible-region filter standards."
            ),
            ideal_readings=(
                IdealReading("crm_wavelength", "546.1", "Certified visible wavelength (holmium filter), nm"),
                IdealReading("measured_wavelengths", "546.3 / 546.1 / 546.4 / 546.0 / 546.2 / 546.2", "Six replicate determinations"),
            ),
            evaluation_en=(
                ("vis_wl_mean", "Mean of the six measured wavelengths."),
                ("vis_wl_acc", "|mean − certified|, compared with 2.0 nm (USP <857> Table 1, 400–780 nm)."),
                ("vis_wl_sd", "Sample standard deviation of the replicates, compared with 0.5 nm."),
            ),
            references=(
                "USP <857> Ultraviolet-Visible Spectroscopy, Table 1 (400–780 nm).",
                "Ph. Eur. 2.2.25 — absorption spectrophotometry, visible range.",
            ),
    ),
    "T16": ManualEntry(
            overview_en=(
                "Photometric accuracy below 1.0 AU is where most pharmaceutical assays are read, and it is verified "
                "with a certified absorbance standard. USP <857> Table 4 sets an absolute accuracy criterion (0.01 "
                "AU) and an absolute repeatability criterion (0.005 AU) for this range because a percentage criterion "
                "at low absorbance would be unrealistically strict."
            ),
            ideal_readings=(
                IdealReading("crm_abs", "0.500", "Certified absorbance of the reference material, AU"),
                IdealReading("measured_abs", "0.501 / 0.500 / 0.502 / 0.499 / 0.501 / 0.500", "Six replicate readings"),
            ),
            evaluation_en=(
                ("abs_low_mean", "Mean of the six absorbance readings."),
                ("abs_low_acc", "|mean − certified| in AU, compared with 0.01 AU."),
                ("abs_low_sd", "Sample standard deviation of the replicates, compared with 0.005 AU."),
            ),
            references=(
                "USP <857> Ultraviolet-Visible Spectroscopy, Table 4 (< 1.0 AU).",
                "ISO/IEC 17025:2017 §7.7 — monitoring the validity of results.",
            ),
    ),
    "T17": ManualEntry(
            overview_en=(
                "Above 1.0 AU stray light and detector non-linearity both grow, so USP <857> expresses the criterion "
                "as a percentage of the certified absorbance rather than in absolute absorbance units. This test is "
                "the one that most often exposes an ageing lamp: readings remain plausible at low absorbance and "
                "collapse at the top of the scale."
            ),
            ideal_readings=(
                IdealReading("crm_abs", "1.500", "Certified high absorbance, AU"),
                IdealReading("measured_abs", "1.503 / 1.501 / 1.504 / 1.499 / 1.502 / 1.501", "Six replicate readings"),
            ),
            evaluation_en=(
                ("abs_high_mean", "Mean of the six readings."),
                ("abs_high_acc_pct", "|mean − certified| / certified × 100, compared with 1.0 %."),
                ("abs_high_sd_pct", "SD / certified × 100, compared with 0.5 %."),
            ),
            references=(
                "USP <857> Ultraviolet-Visible Spectroscopy, Table 4 (> 1.0 AU).",
            ),
    ),
    "T18": ManualEntry(
            overview_en=(
                "Stray light is the fraction of light that reaches the detector without passing through the sample. "
                "It compresses the top of the absorbance scale and eventually makes the instrument blind: a solution "
                "that should read 3 AU reads 2.1 and the analyst has no way to know. USP <857> gives two "
                "procedures — an absorbance-ratio procedure and a maximum-absorbance procedure — and either may be "
                "used to demonstrate compliance."
            ),
            ideal_readings=(
                IdealReading("delta_a", "0.78", "Absorbance difference of the reference solution, Procedure A"),
                IdealReading("a_max", "2.4", "Maximum absorbance reached, Procedure B"),
            ),
            evaluation_en=(
                ("delta_a", "ΔA ≥ 0.7 AU (Procedure A)."),
                ("stray_light_s", "S_λ = 0.25 × 10^(−2·ΔA), compared with ≤ 1 %."),
                ("a_max", "A_max ≥ 2.0 AU (Procedure B)."),
            ),
            references=(
                "USP <857> Ultraviolet-Visible Spectroscopy, Table 5 — stray light.",
            ),
    ),
    "T19": ManualEntry(
            overview_en=(
                "Spectral resolution is the ability of the monochromator to separate two wavelengths a few "
                "nanometres apart. It is verified with a solution whose spectrum has a sharp maximum and a nearby "
                "minimum: the ratio of the two absorbances must be at least 1.3, otherwise the spectral bandwidth is "
                "too wide for the instrument to be used for identification or for absorbance measurements that "
                "depend on peak shape."
            ),
            ideal_readings=(
                IdealReading("abs_269", "0.820", "Absorbance at the peak maximum (~269 nm), AU"),
                IdealReading("abs_266", "0.560", "Absorbance at the minimum (~266 nm), AU"),
            ),
            evaluation_en=(
                ("res_ratio", "A_peak / A_minimum ≥ 1.3 (USP <857>, control of resolution)."),
            ),
            references=(
                "USP <857> Ultraviolet-Visible Spectroscopy — control of resolution.",
                "Ph. Eur. 2.2.25 — resolution of the spectrophotometer.",
            ),
    ),
    "T20": ManualEntry(
            overview_en=(
                "System suitability is the gate every chromatographic run must pass before its results may be used. "
                "USP <621> names the four criteria measured here: signal-to-noise (can the method see the analyte?), "
                "symmetry (is the peak shape acceptable?), theoretical plates (is the column efficient?) and "
                "resolution (are the components separated?). A result that fails any of them is not a result, "
                "whatever the peak area says."
            ),
            ideal_readings=(
                IdealReading("peak_height_h", "1520", "Analyte peak height, mAU"),
                IdealReading("blank_noise_h", "21.5", "Peak-to-peak noise of the blank, mAU"),
                IdealReading("w_005", "0.092", "Peak width at 5 % height, min"),
                IdealReading("d_leading", "0.045", "Leading half-width at 5 % height, min"),
                IdealReading("tr1", "3.12", "Retention time of peak 1, min"),
                IdealReading("tr2", "5.46", "Retention time of peak 2, min"),
                IdealReading("wh1", "0.056", "Width at half height of peak 1, min"),
                IdealReading("wh2", "0.078", "Width at half height of peak 2, min"),
            ),
            evaluation_en=(
                ("sn_ratio", "S/N = 2H/h, ≥ 10."),
                ("as_factor", "A_s = W_0.05 / (2·d_leading), must lie between 0.8 and 1.8."),
                ("plate_n", "N = 5.54 × (t_r2 / w_h2)², ≥ 2000."),
                ("rs", "R_s = 1.18 × (t_r2 − t_r1) / (w_h1 + w_h2), ≥ 2.0."),
            ),
            references=(
                "USP <621> Chromatography — system suitability: S/N, symmetry, plates and resolution.",
                "ICH Q2(R1) §4.3 — system suitability testing.",
            ),
    ),
}
