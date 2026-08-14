"""
Тесты версионирования документов.
"""

import json

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from approvals.models import Agreement
from .models import Document, DocumentVersion, EditSession
from . import editing, services


def upload(name, content=b"data"):
    return SimpleUploadedFile(name, content, content_type="application/octet-stream")


def api(uid=None):
    client = APIClient()
    if uid is not None:
        client.credentials(HTTP_X_B24_USER=str(uid))
    return client


class DocumentVersioningTests(TestCase):
    def test_create_and_add_versions(self):
        agreement = Agreement.objects.create(title="Договор", author_b24_id=1)
        doc = services.create_document(
            title="Договор поставки",
            linked_object=agreement,
            created_by_b24_id=1,
        )
        self.assertEqual(doc.linked_object, agreement)

        v1 = services.add_version(doc, upload("dogovor.pdf", b"v1"), uploaded_by_b24_id=1)
        doc.refresh_from_db()
        self.assertEqual(v1.version_number, 1)
        self.assertTrue(v1.is_current)
        self.assertEqual(doc.current_version_id, v1.id)
        self.assertEqual(v1.checksum, __import__("hashlib").sha256(b"v1").hexdigest())

        v2 = services.add_version(
            doc, upload("dogovor.pdf", b"v2-edited"),
            uploaded_by_b24_id=2, change_comment="после юриста",
        )
        doc.refresh_from_db()
        v1.refresh_from_db()

        # новая версия актуальна, старая сохранена но не актуальна
        self.assertEqual(v2.version_number, 2)
        self.assertTrue(v2.is_current)
        self.assertFalse(v1.is_current)
        self.assertEqual(doc.current_version_id, v2.id)
        self.assertEqual(doc.versions.count(), 2)

    def test_soft_delete_keeps_history(self):
        doc = services.create_document(title="Скан")
        services.add_version(doc, upload("scan.pdf"))
        services.soft_delete(doc)
        doc.refresh_from_db()
        self.assertTrue(doc.is_deleted)
        # версии на месте
        self.assertEqual(doc.versions.count(), 1)

    def test_unique_version_number_per_document(self):
        doc = services.create_document(title="X")
        services.add_version(doc, upload("a.pdf"))
        services.add_version(doc, upload("b.pdf"))
        numbers = list(doc.versions.values_list("version_number", flat=True))
        self.assertEqual(sorted(numbers), [1, 2])


class DocumentApiTests(TestCase):
    def test_requires_auth(self):
        self.assertIn(api().get("/api/documents/").status_code, (401, 403))

    def test_create_with_file_then_add_version_and_download(self):
        # создать документ с первым файлом
        r = api(1).post(
            "/api/documents/",
            {"title": "Договор", "file": upload("d.pdf", b"v1")},
            format="multipart",
        )
        self.assertEqual(r.status_code, 201)
        doc_id = r.json()["id"]
        self.assertEqual(r.json()["current_version_number"], 1)

        # добавить новую версию
        r = api(1).post(
            f"/api/documents/{doc_id}/versions/",
            {"file": upload("d.pdf", b"v2"), "change_comment": "правки"},
            format="multipart",
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["current_version_number"], 2)
        self.assertEqual(len(r.json()["versions"]), 2)

        # скачать конкретную версию
        v1 = next(v for v in r.json()["versions"] if v["version_number"] == 1)
        resp = api(1).get(v1["download_url"])
        self.assertEqual(resp.status_code, 200)

    def test_soft_delete_hides_from_list(self):
        r = api(1).post(
            "/api/documents/",
            {"title": "Скан", "file": upload("s.pdf")},
            format="multipart",
        )
        doc_id = r.json()["id"]
        self.assertEqual(api(1).delete(f"/api/documents/{doc_id}/").status_code, 204)
        listing = api(1).get("/api/documents/").json()
        self.assertEqual(len(listing), 0)


# Настройки включённого редактора для тестов (сервер документов не поднимаем —
# проверяем контракт нашей стороны: конфиг, токены, ключ, callback).
EDITOR_ON = dict(
    DOCS_EDITOR_ENABLED=True,
    DOCS_EDITOR_SERVER_URL="https://docs.test",
    DOCS_EDITOR_JWT_SECRET="test-secret",
    DOCS_EDITOR_CALLBACK_BASE_URL="https://minised.test",
    DOCS_EDITOR_EDITABLE_EXTS=["docx", "doc", "odt", "txt"],
)


@override_settings(**EDITOR_ON)
class OnlineEditorTests(TestCase):
    def _doc(self, name="dogovor.docx", content=b"word-bytes"):
        doc = services.create_document(title="Договор", created_by_b24_id=1)
        services.add_version(doc, upload(name, content), uploaded_by_b24_id=1)
        doc.refresh_from_db()
        return doc

    def test_jwt_roundtrip_and_tamper(self):
        token = editing.jwt_encode({"typ": "dl", "vid": 5})
        self.assertEqual(editing.jwt_decode(token)["vid"], 5)
        # подмена подписи не проходит
        self.assertIsNone(editing.jwt_decode(token[:-3] + "aaa"))

    def test_jwt_expiry(self):
        token = editing.jwt_encode({"typ": "cb", "exp": 1})  # в прошлом
        self.assertIsNone(editing.jwt_decode(token))

    @override_settings(
        DOCS_EDITOR_SERVER_URL="https://devmsed.nordhotels.ru/ds",
        DOCS_EDITOR_INTERNAL_URL="http://127.0.0.1:8082",
    )
    def test_internalize_ds_url_strips_subpath_and_host(self):
        ext = (
            "https://devmsed.nordhotels.ru/ds/cache/files/data/"
            "doc3-v1-abc/output.docx?md5=zzz&expires=1&shardkey=doc3-v1-abc"
        )
        got = editing.internalize_ds_url(ext)
        self.assertEqual(
            got,
            "http://127.0.0.1:8082/cache/files/data/doc3-v1-abc/output.docx"
            "?md5=zzz&expires=1&shardkey=doc3-v1-abc",
        )

    @override_settings(DOCS_EDITOR_INTERNAL_URL="")
    def test_internalize_ds_url_noop_without_internal(self):
        ext = "https://docs.example/cache/x.docx?md5=1"
        self.assertEqual(editing.internalize_ds_url(ext), ext)

    def test_editor_key_changes_with_content(self):
        doc = self._doc()
        k1 = editing.editor_key(doc.current_version)
        services.add_version(doc, upload("dogovor.docx", b"edited"), uploaded_by_b24_id=1)
        doc.refresh_from_db()
        k2 = editing.editor_key(doc.current_version)
        self.assertNotEqual(k1, k2)
        self.assertLessEqual(len(k2), 128)

    def test_editable_by_extension(self):
        self.assertTrue(editing.is_editable(self._doc("a.docx").current_version))
        self.assertFalse(editing.is_editable(self._doc("scan.pdf").current_version))

    def test_config_endpoint_signed(self):
        doc = self._doc()
        r = api(1).get(f"/api/documents/{doc.id}/editor-config/")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["serverUrl"], "https://docs.test")
        cfg = data["config"]
        self.assertEqual(cfg["documentType"], "word")
        self.assertIn("token", cfg)
        self.assertIn("callbackUrl", cfg["editorConfig"])
        # сессия создана
        self.assertTrue(EditSession.objects.filter(document=doc).exists())

    def test_config_reuses_session_for_same_version(self):
        doc = self._doc()
        api(1).get(f"/api/documents/{doc.id}/editor-config/")
        api(2).get(f"/api/documents/{doc.id}/editor-config/")
        # совместное редактирование: одна активная сессия на версию
        self.assertEqual(EditSession.objects.filter(document=doc).count(), 1)

    def test_config_rejects_non_editable(self):
        doc = self._doc("scan.pdf")
        r = api(1).get(f"/api/documents/{doc.id}/editor-config/")
        self.assertEqual(r.status_code, 409)

    def test_ds_download_requires_valid_token(self):
        doc = self._doc()
        v = doc.current_version
        # без токена — 404
        self.assertEqual(
            api().get(f"/api/documents/{doc.id}/versions/{v.id}/ds-download/").status_code,
            404,
        )
        good = editing._download_url(v)
        path = good.split("minised.test")[1]
        self.assertEqual(api().get(path).status_code, 200)

    def test_callback_status2_creates_new_version(self):
        doc = self._doc()
        session = editing.open_session(doc, b24_id=1)
        cb_url = editing._callback_url(session)
        token = cb_url.split("t=")[1]

        edited_url = "https://docs.test/cache/edited.docx"
        body = {"status": 2, "url": edited_url, "users": ["7"]}
        signed = {"token": editing.jwt_encode({"payload": body})}

        class _Resp:
            content = b"edited-docx-bytes"

            def raise_for_status(self):
                pass

        captured = {}

        def fake_get(url, timeout=0):
            captured["url"] = url
            return _Resp()

        # requests импортируется внутри _save_edited; патчим модуль requests
        import requests

        requests.get, saved = fake_get, requests.get
        try:
            r = api().post(
                f"/api/documents/{doc.id}/editor-callback/?t={token}",
                data=json.dumps(signed),
                content_type="application/json",
            )
        finally:
            requests.get = saved

        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"error": 0})
        self.assertEqual(captured["url"], edited_url)
        doc.refresh_from_db()
        self.assertEqual(doc.versions.count(), 2)
        self.assertEqual(doc.current_version.version_number, 2)
        self.assertEqual(doc.current_version.uploaded_by_b24_id, 7)
        session.refresh_from_db()
        self.assertEqual(session.status, EditSession.STATUS_CLOSED)

    def test_callback_rejects_bad_token(self):
        doc = self._doc()
        r = api().post(
            f"/api/documents/{doc.id}/editor-callback/?t=garbage",
            data=json.dumps({"status": 2}),
            content_type="application/json",
        )
        self.assertEqual(r.json(), {"error": 1})


@override_settings(
    DOCS_EDITOR_ENABLED=False, DOCS_EDITOR_SERVER_URL="", DOCS_EDITOR_JWT_SECRET=""
)
class EditorDisabledTests(TestCase):
    def test_config_gated_when_disabled(self):
        doc = services.create_document(title="Д", created_by_b24_id=1)
        services.add_version(doc, upload("a.docx"), uploaded_by_b24_id=1)
        r = api(1).get(f"/api/documents/{doc.id}/editor-config/")
        self.assertEqual(r.status_code, 409)

    def test_can_edit_online_false_in_serializer(self):
        doc = services.create_document(title="Д", created_by_b24_id=1)
        services.add_version(doc, upload("a.docx"), uploaded_by_b24_id=1)
        data = api(1).get(f"/api/documents/{doc.id}/").json()
        self.assertFalse(data["can_edit_online"])
