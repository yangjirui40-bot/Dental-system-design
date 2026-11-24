"""Append linked synthetic clinic records using normal use-case operations."""
import argparse
from collections import Counter
from datetime import datetime, time, timedelta
import json
import os
from unittest.mock import patch
from uuid import uuid4
from zoneinfo import ZoneInfo

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "adc.settings")
django.setup()

from django.db import transaction
from django.test import Client
from django.utils import timezone

from core.db import one, rows
from core.security import scopes, token

MARK = "ADC-SHOWCASE-NOV26"
TZ = ZoneInfo("Asia/Shanghai")
NAMES = (
    "许言清", "程书禾", "叶子宁", "宋知遥", "周景明", "陈星宜",
    "沈亦安", "何云舒", "朱语澄", "陶泽宇", "唐晨晓", "林北辰",
    "顾清晏", "孙明薇", "罗南星", "杨若庭", "梁文川", "杜嘉茵",
)


def check(condition, message):
    if not condition:
        raise RuntimeError(message)


def main(commit):
    now = timezone.now()
    today = now.astimezone(TZ).date()
    session = Client(SERVER_NAME="localhost", secure=True)
    totals = Counter()
    with transaction.atomic():
        one("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", [MARK])
        clinic = one("SELECT * FROM clinic WHERE clinic_no='C001' AND email='clinic1@example.invalid' AND closed_on IS NULL")
        demo = one("SELECT * FROM patient WHERE account_no='P-DEMO-001' AND email='patient@example.invalid'")
        check(clinic and demo, "Missing established synthetic clinic identities")
        clinic_id = clinic["id"]
        sessions = {}
        for role in ("patient", "reception", "dentist", "business", "finance", "manager"):
            account = one("SELECT * FROM user_account WHERE login_name=%s AND is_enabled", [role])
            check(account, f"Missing teaching account {role}")
            scope = next((s for s in scopes(account["id"]) if s["role_code"] == role), None)
            check(scope, f"Missing teaching role {role}")
            if role == "patient":
                check(account["patient_id"] == demo["id"], "Teaching patient identity mismatch")
            else:
                employee = one("SELECT * FROM employee WHERE id=%s AND email=%s", [account["employee_id"], role + "@example.invalid"])
                check(employee, f"Teaching staff identity mismatch for {role}")
                if role in ("manager", "dentist", "reception"):
                    check(scope["clinic_id"] == clinic_id, f"Teaching scope mismatch for {role}")
            sessions[role] = {"Authorization": "Bearer " + token(account, scope["id"])}
            if role == "dentist":
                dentist_id = account["employee_id"]
        existing = one("SELECT count(*) AS n FROM patient WHERE email LIKE %s", [MARK.lower() + "-%@example.invalid"])["n"]
        if existing:
            check(existing == len(NAMES), "Partial synthetic marker detected")
            print(json.dumps({"already_seeded": True, "patients": existing}))
            return

        def call(role, case, **body):
            r = session.post("/api/use-cases/" + case, json.dumps(body, default=str),
                             content_type="application/json",
                             headers={**sessions[role], "Idempotency-Key": str(uuid4())})
            payload = r.json()
            check(r.status_code in (200, 201), f"{role} {case}/{body.get('action')} ({r.status_code}) {payload.get('message')}")
            return payload

        op = one("SELECT id FROM operatory WHERE clinic_id=%s AND resource_state='active' ORDER BY id LIMIT 1", [clinic_id])
        check(op, "No active teaching dental chair")
        exams = rows("""SELECT s.* FROM treatment_standard s JOIN treatment_catalog c ON c.id=s.treatment_id
                       WHERE s.approval_state='approved' AND s.valid_to IS NULL AND c.is_available
                       AND c.treatment_code IN ('T001','T002','T003')
                       AND s.valid_from < %s ORDER BY s.id""", [now - timedelta(days=15)])
        check(exams, "No original valid teaching treatment standard")
        people = []
        for i, name in enumerate(NAMES, 1):
            person = call("reception", "UC01", action="save", full_name=name + "（教学模拟）",
                          birth_date=f"{1990+i}-04-15", sex_code="female" if i % 2 else "male",
                          billing_address="教学模拟地址，无实际联系用途", phone=f"02000009{i:03}",
                          email=f"{MARK.lower()}-{i:02}@example.invalid", allergy_declaration="unknown",
                          emergency_name="模拟联系人", emergency_phone=f"02000008{i:03}",
                          emergency_relationship="亲属", identity_confirmed=True,
                          identity_check_basis="课堂合成身份，编号、出生日期及地址独立")
            people.append(person)
            totals["patients"] += 1
            totals["emergency_contacts"] += 1
        substance = one("SELECT id FROM allergy_substance ORDER BY id LIMIT 1")
        if substance:
            for person in people[:4]:
                call("reception", "UC01", action="allergy", id=person["id"], substance_id=substance["id"],
                     reaction_description="教学模拟：报告曾出现皮肤反应", report_source="课堂合成资料")
                totals["reported_allergies"] += 1

        def at(day, hour, minute=0):
            return datetime.combine(day, time(hour, minute), TZ)

        def duty_for(day):
            start, end = at(day, 9), at(day, 18)
            duty = one("""SELECT * FROM practice_duty WHERE clinic_id=%s AND dentist_id=%s
                          AND publication_state='published' AND starts_at<=%s AND ends_at>=%s
                          ORDER BY id LIMIT 1""", [clinic_id, dentist_id, at(day, 10), at(day, 16)])
            if duty:
                return duty
            if one("""SELECT id FROM practice_duty WHERE dentist_id=%s AND publication_state='published'
                      AND starts_at<%s AND ends_at>%s""", [dentist_id, end, start]):
                return None
            calendar = one("""SELECT * FROM clinic_calendar WHERE clinic_id=%s AND work_date=%s
                              AND is_open AND starts_at<=%s AND ends_at>=%s ORDER BY id LIMIT 1""",
                           [clinic_id, day, start, end])
            with patch("django.utils.timezone.now", return_value=start - timedelta(days=1)):
                if not calendar:
                    occupied = one("SELECT id FROM clinic_calendar WHERE clinic_id=%s AND work_date=%s", [clinic_id, day])
                    if occupied:
                        return None
                    calendar = call("business", "UC15", action="calendar", clinic_id=clinic_id, work_date=day,
                                    session_no=1, is_open=True, starts_at=start, ends_at=end)
                    totals["clinic_sessions"] += 1
                duty = call("business", "UC09", action="publish", clinic_id=clinic_id, dentist_id=dentist_id,
                            calendar_id=calendar["id"], starts_at=start, ends_at=end, qualification_kind_ids=[])
                totals["duties"] += 1
                return {**duty, "starts_at": start, "ends_at": end}

        def visit(person, day, status, standard):
            duty = duty_for(day)
            if duty is None:
                return False
            length = timedelta(minutes=int(standard["duration_minutes"]))
            for offset in range(0, 330, 30):
                start = at(day, 10) + timedelta(minutes=offset)
                end = start + length
                if start < duty["starts_at"] or end > duty["ends_at"]:
                    continue
                if (status == "booked" and start <= now) or (status != "booked" and end > now):
                    continue
                conflict = one("""SELECT id FROM appointment WHERE resolution IN ('booked','arrived','seen')
                    AND starts_at < %s AND ends_at > %s AND
                    (clinic_id=%s AND operatory_id=%s OR dentist_id=%s OR patient_id=%s)""",
                    [end,start,clinic_id,op["id"],dentist_id,person["id"]])
                if conflict:
                    continue
                break
            else:
                return False
            role = "patient" if person["id"] == demo["id"] else "reception"
            with patch("django.utils.timezone.now", return_value=min(now,start-timedelta(hours=1))):
                ap = call(role, "UC02", action="book", patient_id=person["id"], clinic_id=clinic_id,
                          dentist_id=dentist_id, duty_id=duty["id"], operatory_id=op["id"], starts_at=start,
                          ends_at=end, standard_ids=[standard["id"]], presenting_request="教学模拟：" + standard["treatment_name"])
            if status == "cancelled":
                with patch("django.utils.timezone.now", return_value=start-timedelta(minutes=30)):
                    call(role, "UC03", action="cancel", id=ap["id"], row_version=ap["row_version"], reason="教学模拟：患者行程有变")
            elif status in ("no_show","pending_fact"):
                if status == "no_show":
                    call("reception", "UC04", action="no_show", appointment_id=ap["id"], reason="教学模拟：核实未到店")
            elif status in ("arrived","signed","draft"):
                with patch("django.utils.timezone.now", return_value=start), patch("django.utils.timezone.localdate", return_value=day):
                    call(role, "UC04", action="arrive", appointment_id=ap["id"])
                    if status != "arrived":
                        en = call("dentist", "UC04", action="start", appointment_id=ap["id"], identity_confirmed=True, allergy_confirmed=True)
                if status in ("draft","signed"):
                    text = {
                        "chief_complaint":"课程模拟：希望了解本次就诊安排。",
                        "present_illness":"课堂情景，已核对主诉。",
                        "medical_history":"教学模拟：完成资料核对。",
                        "examination_summary":"课堂模拟检查记录。",
                        "tests_summary":"教学模拟：无辅助检查记录。",
                        "diagnosis_summary":"课堂演示用途，未形成实际临床诊断。",
                        "management_summary":"教学模拟：记录本次实际实施项目。",
                        "aftercare":"模拟流程，后续由负责牙医确认。",
                        "allergy_review":"教学模拟：已对照申报资料核实。",
                    }
                    with patch("django.utils.timezone.now", return_value=end), patch("django.utils.timezone.localdate", return_value=day):
                        call("dentist", "UC05", action="sign" if status=="signed" else "draft", encounter_id=en["id"], **text,
                             consent_scope="课堂模拟检查项目", evidence_reference="无真实患者或诊疗效力",
                             treatments=[{"standard_id":standard["id"],"actual_quantity":1,
                                          "charged_unit_price":standard["unit_price"],"implementation_result":"performed",
                                          "site_description":"教学模拟部位"}] if status=="signed" else [])
                    if status == "signed":
                        check(one("SELECT i.id FROM invoice i JOIN invoice_revision r ON r.invoice_id=i.id WHERE i.encounter_id=%s AND r.validity='current'", [en["id"]]),
                              "Signed demonstration visit lacks a current invoice")
                        totals["invoices"] += 1
            totals["appointments"] += 1
            totals["status_" + status] += 1
            if person["id"] == demo["id"]:
                totals["patient_portal_appointments"] += 1
            return True

        historical = [(person, "signed" if i < 9 else "cancelled" if i<11 else "no_show" if i<13 else "pending_fact")
                      for i, person in enumerate(people[:14])]
        historical += [(demo,"signed"), (demo,"signed"), (demo,"signed"), (demo,"cancelled")]
        for i,(person,status) in enumerate(historical):
            for distance in range(1 + i//2, 14):
                if visit(person,today-timedelta(days=distance),status,exams[i%len(exams)]):
                    break
            else:
                raise RuntimeError("No safe historic teaching slot")
        for person,status in [(people[14],"arrived"),(people[15],"draft"),(people[16],"arrived")]:
            if not visit(person,today,status,exams[0]):
                visit(person,today-timedelta(days=1),"signed",exams[0])
        for i,person in enumerate([demo,*people[10:]]):
            for distance in range(1+i//3,12):
                if visit(person,today+timedelta(days=distance),"booked",exams[i%len(exams)]):
                    break
            else:
                raise RuntimeError("No valid upcoming teaching slot")
        q = one("SELECT id FROM fiscal_quarter WHERE starts_on<=%s AND ends_before>%s", [today,today])
        if q:
            for i, amount in enumerate((120,180,260,360,480,620),1):
                revision = call("finance","UC11",action="source",source_document_no=f"{MARK}-{i:02}",
                                cost_category="supplies" if i%2 else "operating",document_date=today,
                                evidence_reference="合成教学凭据，无真实采购或付款",
                                source_amount=amount,allocations=[{"quarter_id":q["id"],"dentist_id":dentist_id,
                                    "clinic_id":clinic_id,"allocated_amount":amount,"allocation_basis":"教学模拟：归属天河门店"}])
                totals["cost_sources"] += 1
                allocation = one("SELECT id FROM cost_allocation WHERE cost_revision_id=%s", [revision["id"]])
                if i <= 3:
                    call("manager","UC11",action="review",id=allocation["id"],approved=True)
                    totals["cost_approved"] += 1
                else:
                    totals["cost_pending"] += 1
        print(json.dumps({"committed": commit, **totals}, ensure_ascii=False, sort_keys=True))
        if not commit:
            transaction.set_rollback(True)


if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--teaching-only", action="store_true", required=True)
    parser.add_argument("--commit", action="store_true")
    args=parser.parse_args()
    main(args.commit)
