"""Minimal Google Drive v3 client (requests only). Auth: OAuth refresh token."""
import os, time, requests

API = "https://www.googleapis.com/drive/v3"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SHORTCUT = "application/vnd.google-apps.shortcut"
FOLDER = "application/vnd.google-apps.folder"


class AuthError(Exception):
    """Credentials revoked/expired. Needs a human to re-consent."""


class AmbiguousWrite(Exception):
    """A write may or may not have happened (timeout / 5xx / dropped connection). Never blindly retried."""


class DriveError(Exception):
    def __init__(self, status, body):
        super().__init__(f"Drive API {status}: {body[:300]}")
        self.status = status


class Drive:
    def __init__(self, client_id, client_secret, refresh_token, session=None):
        self.cid, self.secret, self.rt = client_id, client_secret, refresh_token
        self.s = session or requests.Session()
        self._tok, self._exp = None, 0

    @classmethod
    def from_env(cls):
        try:
            return cls(os.environ["GOOGLE_CLIENT_ID"], os.environ["GOOGLE_CLIENT_SECRET"],
                       os.environ["GOOGLE_REFRESH_TOKEN"])
        except KeyError as e:
            raise AuthError(f"missing credential env var {e}")

    def _token(self):
        if self._tok and time.time() < self._exp - 60:
            return self._tok
        r = self.s.post(TOKEN_URL, data={"client_id": self.cid, "client_secret": self.secret,
                        "refresh_token": self.rt, "grant_type": "refresh_token"}, timeout=30)
        if r.status_code != 200:
            raise AuthError(f"token refresh failed {r.status_code}: {r.text[:200]}")
        j = r.json()
        self._tok, self._exp = j["access_token"], time.time() + j.get("expires_in", 3600)
        return self._tok

    def _req(self, method, path, idempotent=True, **kw):
        for attempt in range(6):
            h = {"Authorization": f"Bearer {self._token()}"}
            try:
                r = self.s.request(method, f"{API}{path}", headers=h, timeout=60, **kw)
            except requests.RequestException as e:
                if not idempotent: raise AmbiguousWrite(f"no response: {e}")
                time.sleep(min(2 ** attempt, 30)); continue
            if not idempotent and r.status_code in (500, 502, 503, 504):
                raise AmbiguousWrite(f"server error {r.status_code}")
            if r.status_code in (429, 500, 502, 503, 504) or (
                    r.status_code == 403 and "rateLimitExceeded" in r.text.lower().replace("userratelimitexceeded", "rateLimitExceeded")):
                time.sleep(min(2 ** attempt, 30)); continue
            if r.status_code == 401:
                self._tok = None
                if attempt == 0: continue
                raise AuthError("401 after token refresh")
            if r.status_code >= 400:
                raise DriveError(r.status_code, r.text)
            return r.json() if r.text else {}
        raise DriveError(r.status_code, "retries exhausted: " + r.text)

    def list(self, q, fields="id,name,mimeType,parents,md5Checksum,trashed,shortcutDetails,owners(emailAddress),modifiedTime"):
        """All pages. Supports shared drives."""
        out, tok = [], None
        while True:
            p = {"q": q, "pageSize": 1000, "supportsAllDrives": "true", "includeItemsFromAllDrives": "true",
                 "corpora": "allDrives", "fields": f"nextPageToken,files({fields})"}
            if tok: p["pageToken"] = tok
            j = self._req("GET", "/files", params=p)
            out += j.get("files", [])
            tok = j.get("nextPageToken")
            if not tok: return out

    def children(self, folder_id):
        return self.list(f"'{folder_id}' in parents and trashed=false")

    def get(self, file_id, fields="id,name,mimeType,parents,trashed,shortcutDetails,webViewLink,capabilities(canAddChildren)"):
        return self._req("GET", f"/files/{file_id}", params={"supportsAllDrives": "true", "fields": fields})

    def about(self):
        return self._req("GET", "/about", params={"fields": "user(emailAddress)"})

    def find_shortcuts(self, target_id):
        """Every live shortcut to this original, anywhere the account can see."""
        return self.list(f"mimeType='{SHORTCUT}' and trashed=false and shortcutDetails.targetId='{target_id}'",
                         "id,name,parents,shortcutDetails")

    def create_shortcut(self, name, target_id, parent_id):
        body = {"name": name, "mimeType": SHORTCUT, "parents": [parent_id],
                "shortcutDetails": {"targetId": target_id}}
        return self._req("POST", "/files", params={"supportsAllDrives": "true",
                         "fields": "id,name,parents,shortcutDetails,webViewLink"},
                         json=body, idempotent=False)
