import xmlrpc.client
from config import ODOO_URL, ODOO_DB, ODOO_USERNAME, ODOO_PASSWORD

class OdooClient:
    def __init__(self):
        """Authenticate and setup XML-RPC connection with HTTPS support"""
        try:
            transport = xmlrpc.client.SafeTransport()
            # Common endpoint for authentication
            common = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/common", transport=transport)
            self.uid = common.authenticate(ODOO_DB, ODOO_USERNAME, ODOO_PASSWORD, {})

            if not self.uid:
                raise Exception("❌ Odoo authentication failed!")

            # Object endpoint for CRUD operations
            self.models = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/object", transport=transport)
            self.DB = ODOO_DB
            self.PASSWORD = ODOO_PASSWORD
            print(f"✅ Connected to Odoo DB '{ODOO_DB}' as '{ODOO_USERNAME}', UID={self.uid}")

        except Exception as e:
            print(f"❌ Failed to connect to Odoo: {e}")
            raise e

    # ------------------- Utilities -------------------
    def _get_stage_id(self, stage_name="New"):
        """Get stage_id by name"""
        try:
            stage_ids = self.models.execute_kw(
                self.DB, self.uid, self.PASSWORD,
                'crm.stage', 'search',
                [[['name', '=', stage_name]]],
                {'limit': 1}
            )
            return stage_ids[0] if stage_ids else False
        except:
            return False

    # ------------------- CRM Methods -------------------
    def create_lead(self, lead_data, stage_name="New"):
        """Create CRM Opportunity"""
        try:
            lead_data['type'] = 'opportunity'
            if 'stage_id' not in lead_data:
                stage_id = self._get_stage_id(stage_name)
                if stage_id:
                    lead_data['stage_id'] = stage_id
            if 'team_id' not in lead_data:
                lead_data['team_id'] = 1  # Default Sales Team
            lead_id = self.models.execute_kw(
                self.DB, self.uid, self.PASSWORD,
                'crm.lead', 'create', [lead_data]
            )
            print(f"✅ Created Lead ID: {lead_id}")
            return lead_id
        except Exception as e:
            print(f"❌ Error creating lead: {e}")
            return None

    def search_lead_by_email(self, email):
        """Search leads by email"""
        try:
            lead_ids = self.models.execute_kw(
                self.DB, self.uid, self.PASSWORD,
                'crm.lead', 'search',
                [[['email_from', '=', email]]]
            )
            return lead_ids
        except:
            return []

    def get_crm_lead_fields(self):
        """Return list of valid fields in crm.lead"""
        try:
            fields_dict = self.models.execute_kw(
                self.DB, self.uid, self.PASSWORD,
                'crm.lead', 'fields_get',
                [], {'attributes': ['string', 'type']}
            )
            return list(fields_dict.keys())
        except:
            return []
