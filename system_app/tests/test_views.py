"""ビューのスモークテスト（認証・ページ疎通確認）"""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse


class UnauthenticatedRedirectTest(TestCase):
    """未ログイン時はログインページへリダイレクトされること"""

    def _assert_redirects_to_login(self, url_name):
        url = reverse(url_name)
        response = self.client.get(url)
        self.assertRedirects(
            response,
            f"/login/?next={url}",
            fetch_redirect_response=False,
        )

    def test_dashboard_requires_login(self):
        self._assert_redirects_to_login("dashboard")

    def test_invoice_list_requires_login(self):
        self._assert_redirects_to_login("invoice_list")

    def test_timesheet_dashboard_requires_login(self):
        self._assert_redirects_to_login("timesheet_dashboard")

    def test_party_list_requires_login(self):
        self._assert_redirects_to_login("party_list")

    def test_ar_list_requires_login(self):
        self._assert_redirects_to_login("ar_list")

    def test_ap_list_requires_login(self):
        self._assert_redirects_to_login("ap_list")


class AuthenticatedSmokeTest(TestCase):
    """ログイン済みユーザーが主要ページへアクセスして 200 が返ること"""

    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="testpass")
        self.client.login(username="testuser", password="testpass")

    def _assert_200(self, url_name):
        response = self.client.get(reverse(url_name))
        self.assertEqual(
            response.status_code,
            200,
            msg=f"{url_name} returned {response.status_code}",
        )

    def test_dashboard(self):
        self._assert_200("dashboard")

    def test_party_list(self):
        self._assert_200("party_list")

    def test_invoice_list(self):
        self._assert_200("invoice_list")

    def test_timesheet_dashboard(self):
        self._assert_200("timesheet_dashboard")

    def test_ar_list(self):
        self._assert_200("ar_list")

    def test_ap_list(self):
        self._assert_200("ap_list")

    def test_purchase_order_list(self):
        self._assert_200("purchase_order_list")
