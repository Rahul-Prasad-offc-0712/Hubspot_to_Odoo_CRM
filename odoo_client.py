import requests
from config import ODOO_URL, ODOO_DB, ODOO_USERNAME, ODOO_PASSWORD

class OdooClient:
    def __init__(self):
        self.ODOO_RPC_URL = f"{ODOO_URL}/jsonrpc"
        self.DB = ODOO_DB
        self.USER = ODOO_USERNAME
        self.PASSWORD = ODOO_PASSWORD
        self.uid = self.authenticate()
        if not self.uid:
            raise Exception("❌ Odoo authentication failed!")
        print(f"✅ Connected to Odoo DB '{ODOO_DB}' as '{ODOO_USERNAME}', UID={self.uid}")

    def authenticate(self):
        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {
                "service": "common",
                "method": "authenticate",
                "args": [self.DB, self.USER, self.PASSWORD, {}]
            },
            "id": 1
        }
        resp = requests.post(self.ODOO_RPC_URL, json=payload, timeout=30).json()
        return resp.get("result")

    def execute(self, model, method, args=None, kwargs=None):
        args = args or []
        kwargs = kwargs or {}
        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {
                "service": "object",
                "method": "execute_kw",
                "args": [self.DB, self.uid, self.PASSWORD, model, method, args, kwargs]
            },
            "id": 1
        }
        resp = requests.post(self.ODOO_RPC_URL, json=payload, timeout=30).json()
        return resp.get("result")

    # ---------------- CRM METHODS ----------------
    def _get_stage_id(self, stage_name="New"):
        stage_ids = self.execute('crm.stage', 'search', [[['name', '=', stage_name]]], {'limit': 1})
        return stage_ids[0] if stage_ids else False

    def create_lead(self, lead_data, stage_name="New"):
        lead_data['type'] = 'opportunity'
        if 'stage_id' not in lead_data:
            stage_id = self._get_stage_id(stage_name)
            if stage_id:
                lead_data['stage_id'] = stage_id
        if 'team_id' not in lead_data:
            lead_data['team_id'] = 1
        lead_id = self.execute('crm.lead', 'create', [lead_data])
        print(f"✅ Created Opportunity ID: {lead_id}")
        return lead_id

    def search_lead_by_email(self, email):
        return self.execute('crm.lead', 'search', [[['email_from', '=', email]]])

    def get_crm_lead_fields(self):
        return self.execute('crm.lead', 'fields_get', [], {'attributes': ['string', 'type']})
