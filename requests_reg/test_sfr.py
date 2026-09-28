"""
МЧД с кодами СФР / КАДРЫ_СФР_ВУ_МУ: после согласования исполняет не юротдел,
а отдел внедрения и разработки ПО (роль sfr_executor), в разделе «Работа ИТ».
"""

from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from core.models import Organization, Role, UserProfile
from documents import services as docsvc

from . import constants as C
from . import services, validators
from .models import RegulatoryRequest, RoleAssignment

INITIATOR, APPROVER, DEV, LAWYER, IT = 1, 10, 1535, 30, 40


def api(uid):
    c = APIClient()
    c.credentials(HTTP_X_B24_USER=str(uid))
    return c


def internal(uid, order=0):
    return {"type": "internal", "b24_user_id": uid, "order": order}


class SfrMchdTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(short_name="УК")
        RoleAssignment.objects.create(role_code=C.ROLE_SFR_EXECUTOR, user_b24_id=DEV, user_name="Букреев")
        RoleAssignment.objects.create(role_code=C.ROLE_IT_SPECIALIST, user_b24_id=IT, user_name="ИТ")
        UserProfile.objects.create(fio="Букреев Леонид", bitrix_id=DEV, email="dev@x.ru", is_active=True)
        p = UserProfile.objects.create(fio="Юрист", bitrix_id=LAWYER, email="law@x.ru", is_active=True)
        p.roles.add(Role.objects.get(code="lawyer"))

    def _approved(self, codes, rtype=C.TYPE_MCHD, **data):
        req = services.create_request(
            request_type=rtype, organization=self.org, initiator_b24_id=INITIATOR,
            data={"power_templates": codes, **data},
        )
        services.submit(req, [internal(APPROVER)])
        p = services.get_approval(req).rounds.first().participants.first()
        with self.captureOnCommitCallbacks(execute=True):
            services.decide(req, p.id, "approve", actor_b24_id=APPROVER)
        req.refresh_from_db()
        return req

    def _attach(self, req):
        doc = docsvc.create_document(title="МЧД", linked_object=req, created_by_b24_id=DEV)
        docsvc.add_version(doc, SimpleUploadedFile("mchd.xml", b"<x/>"), uploaded_by_b24_id=DEV)

    # --- куда уходит ---
    def test_detection(self):
        self.assertTrue(validators.is_sfr_mchd(C.TYPE_MCHD, {"power_templates": ["СФР"]}))
        self.assertTrue(validators.is_sfr_mchd(C.TYPE_MCHD, {"power_templates": ["ПОЧТА", "КАДРЫ_СФР_ВУ_МУ"]}))
        self.assertFalse(validators.is_sfr_mchd(C.TYPE_MCHD, {"power_templates": ["ПОЧТА"]}))
        # бумажная доверенность с кодом СФР — юристам; «МЧД» через тип в анкете — к отделу
        self.assertFalse(validators.is_sfr_mchd(C.TYPE_POA, {"power_templates": ["СФР"]}))
        self.assertTrue(validators.is_sfr_mchd(C.TYPE_POA, {"poa_type": "mchd", "power_templates": ["СФР"]}))

    def test_sfr_mchd_goes_to_dev_and_notifies_bukreev(self):
        mail.outbox.clear()
        req = self._approved(["СФР"])
        self.assertEqual(req.status, C.STATUS_TO_DEV)
        self.assertTrue(any("dev@x.ru" in m.to for m in mail.outbox
                            if m.subject == "Новая МЧД для СФР на исполнение"))
        # юристам в очередь НЕ падает
        legal_new = api(LAWYER).get("/api/reg/requests/legal_queue/?scope=new").json()
        self.assertNotIn(req.id, {r["id"] for r in legal_new})

    def test_ordinary_mchd_still_goes_to_legal(self):
        self.assertEqual(self._approved(["ПОЧТА"]).status, C.STATUS_TO_LEGAL)

    # --- «Работа ИТ» ---
    def test_dev_queue_take_execute_and_receipt(self):
        req = self._approved(["КАДРЫ_СФР_ВУ_МУ"])
        ecp = RegulatoryRequest.objects.create(
            request_type=C.TYPE_ECP, organization=self.org, status=C.STATUS_TO_IT, initiator_b24_id=2,
        )
        new = {r["id"] for r in api(DEV).get("/api/reg/requests/it_queue/?scope=new").json()}
        self.assertEqual(new, {req.id})  # ЭЦП Букрееву не показываем
        self.assertEqual({r["id"] for r in api(IT).get("/api/reg/requests/it_queue/?scope=new").json()},
                         {ecp.id})  # а ИТ-специалисту — только ЭЦП
        self.assertEqual(api(DEV).get(f"/api/reg/requests/{req.id}/").status_code, 200)

        r = api(DEV).post(f"/api/reg/requests/{req.id}/dev_take/")
        self.assertEqual(r.json()["status"], C.STATUS_DEV_WORK)
        # без файла МЧД исполнить нельзя
        r = api(DEV).post(f"/api/reg/requests/{req.id}/dev_execute/")
        self.assertEqual(r.status_code, 400)
        self._attach(req)
        r = api(DEV).post(f"/api/reg/requests/{req.id}/dev_execute/", {"comment": "выпущена"}, format="json")
        self.assertEqual(r.json()["status"], C.STATUS_EXECUTED)
        self.assertEqual(r.json()["executor_b24_id"], DEV)
        archive = {x["id"] for x in api(DEV).get("/api/reg/requests/it_queue/?scope=archive").json()}
        self.assertIn(req.id, archive)
        # дальше — как всегда: инициатор подтверждает получение
        self.assertIn(req.id, {x["id"] for x in api(INITIATOR).get("/api/reg/requests/todo/").json()})
        r = api(INITIATOR).post(f"/api/reg/requests/{req.id}/confirm_receipt/")
        self.assertEqual(r.json()["status"], C.STATUS_CLOSED)

    def test_only_dev_executor_can_act(self):
        req = self._approved(["СФР"])
        for uid in (LAWYER, IT):
            self.assertIn(api(uid).post(f"/api/reg/requests/{req.id}/dev_take/").status_code, (403, 404))

    def test_profile_shows_it_section_for_bukreev(self):
        from core.auth_views import _is_it_specialist

        self.assertTrue(_is_it_specialist(DEV))
