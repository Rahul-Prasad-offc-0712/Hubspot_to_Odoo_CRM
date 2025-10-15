import xmlrpc.client
import base64
import traceback

# -----------------------------
# Odoo Config
# -----------------------------
from config import ODOO_URL, ODOO_DB, ODOO_USERNAME, ODOO_PASSWORD


class OdooClient:
    def __init__(self):
        """Authenticate with Odoo XML-RPC"""
        try:
            print("🔗 Connecting to Odoo...")

            # Common endpoint for login
            common = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/common")
            self.uid = common.authenticate(ODOO_DB, ODOO_USERNAME, ODOO_PASSWORD, {})
            if not self.uid:
                raise Exception("❌ Authentication failed. Check credentials or Odoo URL.")

            # Object endpoint for model operations
            self.models = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/object")
            self.db = ODOO_DB
            self.password = ODOO_PASSWORD

            print(f"✅ Connected to Odoo as {ODOO_USERNAME} (uid={self.uid})")

        except Exception as e:
            print(f"🚨 Odoo connection failed: {e}")
            traceback.print_exc()

    # ---------------------------------------------------------
    # Upload PDF to Chatter (for RFQ Form)
    # ---------------------------------------------------------
    def upload_pdf_to_chatter(self, lead_id, pdf_bytes, filename="RFQ_Form.pdf"):
        """
        Uploads PDF as an attachment to the chatter of a given Lead (crm.lead)
        and posts a message linking it.
        """
        try:
            print(f"📎 Uploading PDF '{filename}' to Odoo chatter for lead ID {lead_id}...")

            # Step 1: Encode PDF
            encoded_pdf = base64.b64encode(pdf_bytes).decode("utf-8")

            # Step 2: Create attachment record
            attachment_id = self.models.execute_kw(
                self.db, self.uid, self.password,
                'ir.attachment', 'create',
                [{
                    'name': filename,
                    'type': 'binary',
                    'datas': encoded_pdf,
                    'res_model': 'crm.lead',
                    'res_id': lead_id,
                    'mimetype': 'application/pdf',
                }]
            )

            print(f"✅ Attachment created in Odoo (ID: {attachment_id})")

            # Step 3: Post message in chatter with attachment
            self.models.execute_kw(
                self.db, self.uid, self.password,
                'crm.lead', 'message_post',
                [[lead_id], {  # ✅ Important: record IDs in list
                    'body': f"<p>RFQ Form PDF generated successfully.</p>",
                    'message_type': 'comment',
                    'subtype_id': 1,  # internal discussion subtype
                    'attachment_ids': [(4, attachment_id)],
                }]
            )

            print("💬 Message with PDF successfully posted to chatter.")

            return True

        except Exception as e:
            print(f"⚠️ Failed to upload PDF to Odoo chatter: {e}")
            traceback.print_exc()
            return False

    # ---------------------------------------------------------
    # Generic utility: Create lead or update (if needed)
    # ---------------------------------------------------------
    def create_lead(self, values):
        """Example method to create a CRM lead"""
        try:
            lead_id = self.models.execute_kw(
                self.db, self.uid, self.password,
                'crm.lead', 'create', [values]
            )
            print(f"✅ Lead created with ID: {lead_id}")
            return lead_id
        except Exception as e:
            print(f"⚠️ Error creating lead: {e}")
            traceback.print_exc()
            return None

    def update_lead(self, lead_id, values):
        """Example method to update a CRM lead"""
        try:
            self.models.execute_kw(
                self.db, self.uid, self.password,
                'crm.lead', 'write', [[lead_id], values]
            )
            print(f"✏️ Lead {lead_id} updated successfully.")
            return True
        except Exception as e:
            print(f"⚠️ Error updating lead {lead_id}: {e}")
            traceback.print_exc()
            return False
