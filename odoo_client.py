import xmlrpc.client
from config import ODOO_URL, ODOO_DB, ODOO_USERNAME, ODOO_PASSWORD


class OdooClient:
    def __init__(self):
        """Authenticate and setup XML-RPC connection"""
        try:
            common = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/common")
            self.uid = common.authenticate(ODOO_DB, ODOO_USERNAME, ODOO_PASSWORD, {})
            if not self.uid:
                raise Exception("❌ Odoo authentication failed!")

            self.models = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/object")
            self.DB = ODOO_DB
            self.PASSWORD = ODOO_PASSWORD

            print(f"✅ Connected to Odoo DB '{ODOO_DB}' as '{ODOO_USERNAME}', UID={self.uid}")
        except Exception as e:
            print(f"❌ Failed to connect to Odoo: {e}")
            raise e

    # ------------------- UTILITIES -------------------
    def _get_stage_id(self, stage_name="New"):
        """Get the stage_id for a given stage name (default: 'New')"""
        try:
            stage_ids = self.models.execute_kw(
                self.DB, self.uid, self.PASSWORD,
                'crm.stage', 'search',
                [[['name', '=', stage_name]]],
                {'limit': 1}
            )
            return stage_ids[0] if stage_ids else False
        except Exception as e:
            print(f"⚠️ Couldn't find stage '{stage_name}': {e}")
            return False

    # ------------------- CRM METHODS -------------------
    def create_lead(self, lead_data, stage_name="New"):
        """
        Create a CRM Opportunity (shows in pipeline).
        - Ensures record type is 'opportunity'
        - Assigns a default stage and sales team
        """
        try:
            # Force to create an Opportunity, not just a Lead
            lead_data['type'] = 'opportunity'

            # Assign stage automatically if not provided
            if 'stage_id' not in lead_data:
                stage_id = self._get_stage_id(stage_name)
                if stage_id:
                    lead_data['stage_id'] = stage_id

            # Optionally assign Sales Team (default team_id=1 if it exists)
            if 'team_id' not in lead_data:
                lead_data['team_id'] = 1

            lead_id = self.models.execute_kw(
                self.DB, self.uid, self.PASSWORD,
                'crm.lead', 'create',
                [lead_data]
            )
            print(f"✅ Created Opportunity ID: {lead_id}")
            return lead_id
        except Exception as e:
            print(f"❌ Error creating lead in Odoo: {e}")
            return None

    def search_lead_by_email(self, email):
        """Return lead IDs matching email"""
        try:
            lead_ids = self.models.execute_kw(
                self.DB, self.uid, self.PASSWORD,
                'crm.lead', 'search',
                [[['email_from', '=', email]]]
            )
            return lead_ids
        except Exception as e:
            print(f"❌ Error searching lead by email: {e}")
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
        except Exception as e:
            print(f"❌ Error fetching CRM lead fields: {e}")
            return []
