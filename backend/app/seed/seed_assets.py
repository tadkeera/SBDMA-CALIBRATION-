"""Seed the reference instrument and reference items from the source report.

Values (part number, serial number, calibration frequency, accessory list) come
from the Shimadzu LC-2050C installation documents summarised in the report.
No fabricated readings are inserted: technical data rows start empty and are
filled by real calibrations.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assets import Instrument, ReferenceEquipment, ReferenceStandard
from app.models.rbac import LabDepartment

INSTRUMENT = {
    "asset_code": "HPLC-UV-001",
    "category": "HPLC-UV",
    "manufacturer": "Shimadzu",
    "model": "i-Series LC-2050C",
    "part_number": "S228-65821-58",
    "serial_number": "L22976302572",
    "software_version": "LabSolutions",
    "calibration_freq_days": 180,
    "configuration_jsonb": {
        "detector": "SPD-M30A (UV-VIS PDA)",
        "pump": "LC-2050C quaternary low-pressure gradient",
        "autosampler": "SIL-40C",
        "column_oven": "CTO-40C",
        "sample_cooler": "Sample Cooler installed",
        "d2_lamp": "228-34016-42",
        "max_lamp_hours": 2000,
    },
}

REFERENCE_EQUIPMENT = (
    {
        "equipment_code": "REF-THERMO-001",
        "name_ar": "مقياس حرارة مرجعي معتمد",
        "name_en": "Certified reference thermometer",
        "serial_number": "RT-2024-0157",
        "certificate_no": "CAL-2024-0157",
        "calibrated_by": "مركز المعايرة الوطني",
        "uncertainty": "0.05",
    },
    {
        "equipment_code": "REF-STOPWATCH-001",
        "name_ar": "مؤقت مرجعي معتمد",
        "name_en": "Certified reference stopwatch",
        "serial_number": "SW-2024-0042",
        "certificate_no": "CAL-2024-0042",
        "calibrated_by": "مركز المعايرة الوطني",
        "uncertainty": "0.01",
    },
    {
        "equipment_code": "REF-BALANCE-001",
        "name_ar": "ميزان تحليلي مرجعي",
        "name_en": "Analytical reference balance",
        "serial_number": "BL-2024-0091",
        "certificate_no": "CAL-2024-0091",
        "calibrated_by": "مركز المعايرة الوطني",
        "uncertainty": "0.0001",
    },
)

REFERENCE_STANDARDS = (
    {
        "name": "Caffeine standard 10 mg/L",
        "part_or_cat_no": "228-01234",
        "lot_number": "CAF-2026-0114",
        "purity_percent": "99.5",
        "expiry_days": 365,
    },
    {
        "name": "Uracil / Acenaphthene system suitability mix",
        "part_or_cat_no": "228-05678",
        "lot_number": "SST-2026-0031",
        "purity_percent": "99.0",
        "expiry_days": 180,
    },
)


async def seed_assets(session: AsyncSession) -> dict[str, int]:
    created = {"instruments": 0, "reference_equipment": 0, "reference_standards": 0}

    department = (
        await session.execute(select(LabDepartment).where(LabDepartment.code == "PHYS"))
    ).scalar_one_or_none()
    if department is None:
        raise RuntimeError("department PHYS must be seeded before assets")

    exists = (
        await session.execute(
            select(Instrument).where(Instrument.asset_code == INSTRUMENT["asset_code"])
        )
    ).scalar_one_or_none()
    if exists is None:
        today = date.today()
        session.add(
            Instrument(
                id=uuid.uuid4(),
                department_id=department.id,
                calibration_freq_days=INSTRUMENT["calibration_freq_days"],
                # first calibration is due at installation; left NULL until the
                # first approved run sets it
                last_calibration_date=None,
                next_due_date=None,
                status="ACTIVE",
                d2_lamp_hours=0,
                configuration_jsonb=INSTRUMENT["configuration_jsonb"],
                **{k: INSTRUMENT[k] for k in (
                    "asset_code", "category", "manufacturer", "model",
                    "part_number", "serial_number", "software_version",
                )},
            )
        )
        created["instruments"] += 1

    today = date.today()
    for ref in REFERENCE_EQUIPMENT:
        exists = (
            await session.execute(
                select(ReferenceEquipment).where(
                    ReferenceEquipment.equipment_code == ref["equipment_code"]
                )
            )
        ).scalar_one_or_none()
        if exists is None:
            session.add(
                ReferenceEquipment(
                    id=uuid.uuid4(),
                    department_id=department.id,
                    equipment_code=ref["equipment_code"],
                    name_ar=ref["name_ar"],
                    name_en=ref["name_en"],
                    serial_number=ref["serial_number"],
                    certificate_no=ref["certificate_no"],
                    calibrated_by=ref["calibrated_by"],
                    calibration_date=today - timedelta(days=120),
                    expiry_date=today + timedelta(days=245),
                    uncertainty=ref["uncertainty"],
                    correction_table_jsonb=[],
                    is_active=True,
                )
            )
            created["reference_equipment"] += 1

    for std in REFERENCE_STANDARDS:
        exists = (
            await session.execute(
                select(ReferenceStandard).where(ReferenceStandard.lot_number == std["lot_number"])
            )
        ).scalar_one_or_none()
        if exists is None:
            session.add(
                ReferenceStandard(
                    id=uuid.uuid4(),
                    department_id=department.id,
                    name=std["name"],
                    part_or_cat_no=std["part_or_cat_no"],
                    lot_number=std["lot_number"],
                    purity_percent=std["purity_percent"],
                    prepared_at=today,
                    expiry_date=today + timedelta(days=std["expiry_days"]),
                )
            )
            created["reference_standards"] += 1

    await session.flush()
    return created
