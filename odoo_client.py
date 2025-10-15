import xmlrpc.client
from config import ODOO_URL, ODOO_DB, ODOO_USERNAME, ODOO_PASSWORD

class OdooClient:
    def __init__(self):
        self.url = ODOO_URL
        self.db = ODOO_DB
        self.username = ODOO_USERNAME
        self.password = ODOO_PASSWORD

        # XML-RPC endpoints
        common = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/common")
        self.uid = common.authenticate(self.db, self.username, self.password, {})
        self.models = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/object")

    # Lead search by email
    def search_lead_by_email(self, email):
        ids = self.models.execute_kw(
            self.db, self.uid, self.password,
            'crm.lead', 'search', [[['email_from', '=', email]]]
        )
        return ids[0] if ids else None

    # Create lead
    def create_lead(self, vals):
        lead_id = self.models.execute_kw(
            self.db, self.uid, self.password,
            'crm.lead', 'create', [vals]
        )
        return lead_id

    # Optional: Get stage_id by name
    def _get_stage_id(self, stage_name):
        stage_ids = self.models.execute_kw(
            self.db, self.uid, self.password,
            'crm.stage', 'search', [[['name', '=', stage_name]]]
        )
        return stage_ids[0] if stage_ids else None
