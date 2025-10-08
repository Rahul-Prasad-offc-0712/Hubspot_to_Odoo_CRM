from flask import Flask, render_template, request, send_file, jsonify
import pdfkit, io, base64, requests, re, json
from odoo_client import OdooClient
import config

# ---------------- Flask App ----------------
app = Flask(__name__)
odoo = OdooClient()

# ---------------- PDFKit Config ----------------
PDFKIT_CONFIG = pdfkit.configuration(
    wkhtmltopdf=r"C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe"  # adjust path
)

# ---------------- Odoo JSON-RPC Config ----------------
ODOO_URL = "https://test321.odoo.com"
ODOO_DB = "test321"
ODOO_EMAIL = "rahul.prasad@stratvals.com"
ODOO_API_KEY = "3a5e6ced9003114060fd4ec0d0a4059654af2ceb"
RES_MODEL = "crm.lead"
ODOO_RPC_URL = f"{ODOO_URL}/jsonrpc"

# ---------------- HubSpot → Odoo Lead ----------------
def parse_values(values_list):
    result = {}
    for item in values_list:
        result[item["name"]] = item["value"]
    return result

def create_odoo_lead(values, lead_type="IQL"):
    name = f"{values.get('firstname', '')} {values.get('lastname', '')}".strip() or "Unknown"
    email = values.get("email", "No Email")
    phone = values.get("phone", "")
    city = values.get("city", "")

    lead_data = {
        "name": name,
        "email_from": email,
        "phone": phone,
        "city": city,
        "description": f"Lead from HubSpot ({lead_type})",
    }

    exists = odoo.search_lead_by_email(email)
    if exists:
        print(f"⚠️ Duplicate lead skipped: {name} ({email})")
        return

    lead_id = odoo.create_lead(lead_data)
    print(f"✅ Lead created: {name} ({email}), Type={lead_type}, ID={lead_id}")
    return lead_id

# ---------------- Routes ----------------

@app.route("/hubspot_webhook", methods=["POST"])
def hubspot_webhook():
    data = request.json
    print("🔥 Full HubSpot payload:", data)

    # HubSpot formSubmission structure
    values_list = []
    for event in data.get("events", []):
        values_list = event.get("formSubmission", {}).get("values", [])
        if values_list:
            break

    # fallback if 'properties' directly exists
    if not values_list and "properties" in data:
        values_list = [{"name": k, "value": v.get("value")} for k, v in data["properties"].items()]

    if not values_list:
        print("⚠️ No form values found in payload!")
        return jsonify({"status": "no data found"}), 400

    filtered_data = parse_values(values_list)
    print("✅ Parsed HubSpot data for Odoo:", filtered_data)

    create_odoo_lead(filtered_data, lead_type="IQL")  # or MQL
    return jsonify({"status": "success"})

# ---------------- Routes ----------------

# Project Details API
@app.route("/project/details", methods=["GET"])
def project_details():
    project_name = request.args.get("project_name")
    project_description = request.args.get("project_description")
    project_category = request.args.get("project_category")

    if not project_name or not project_description or not project_category:
        return jsonify({"status": "error", "message": "Missing project info in URL"})

    # Search domain — exact match
    domain = [
        ['x_studio_project_name_1', '=', project_name],
        ['x_studio_project_description_1', '=', project_description],
        ['x_studio_project_category_1', '=', project_category]
    ]

    print("🔹 Exact domain used:", domain)

    # ✅ CRM Lead model (not project.project)
    project_ids = odoo.models.execute_kw(
        odoo.DB, odoo.uid, odoo.PASSWORD,
        'crm.lead', 'search',
        [domain]
    )

    print("🔹 Lead IDs found:", project_ids)

    if not project_ids:
        return jsonify({"status": "not found", "data": []})

    project_data = odoo.models.execute_kw(
        odoo.DB, odoo.uid, odoo.PASSWORD,
        'crm.lead', 'read',
        [project_ids[:1]],
        {'fields': [
            'name',
            'x_studio_project_name_1',
            'x_studio_project_description_1',
            'x_studio_project_category_1'
        ]}
    )

    return jsonify({"status": "success", "data": project_data})





# Lead Won API
@app.route("/lead/won", methods=["GET"])
def lead_won():
    lead_name = request.args.get("lead_name", "").strip()
    
    # Stage name partial & case-insensitive
    domain = [['stage_id.name', 'ilike', 'won']]
    if lead_name:
        domain.append(['name', 'ilike', lead_name])
    
    print("🔹 Lead Won search domain:", domain)
    
    # Fetch IDs
    lead_ids = odoo.models.execute_kw(
        odoo.DB, odoo.uid, odoo.PASSWORD,
        'crm.lead', 'search',
        [domain]
    )
    print("🔹 Lead IDs found:", lead_ids)

    if lead_ids:
        return jsonify({"status": "success", "message": f"Lead {lead_name or ''} is won successfully"})
    else:
        return jsonify({"status": "not found", "message": "No won lead found"})


@app.route("/rfq/<int:lead_id>", methods=["GET"])
def rfq_form(lead_id):
    project_name = request.args.get("project_name", "") or ""
    description = request.args.get("project_description", "") or ""
    category = request.args.get("project_category", "") or ""
    return render_template("rfq_form.html",
                           lead_id=lead_id,
                           project_name=project_name,
                           description=description,
                           category=category)

@app.route("/submit-rfq", methods=["POST"])
def submit_rfq():
    lead_id = request.form.get("lead_id")
    try:
        lead_id = int(lead_id)
    except Exception:
        return "Invalid or missing lead_id", 400

    project_name = request.form.get("project_name", "Project")
    safe_project_name = re.sub(r'[^A-Za-z0-9_-]', '_', project_name.strip())

    field_names = request.form.getlist("field_name[]")
    field_values = request.form.getlist("field_value[]")

    pdf_html = f"""
    <html>
    <head><meta charset="utf-8" />
    <style>
        body {{ font-family: Arial, sans-serif; font-size: 12px; }}
        h2 {{ margin-bottom: 8px; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
        th, td {{ border: 1px solid #ccc; padding: 8px; text-align: left; vertical-align: top; }}
        th {{ background: #f4f4f4; }}
    </style>
    </head>
    <body>
    <h2>RFQ Document for {project_name}</h2>
    <table><tr><th>Field Name</th><th>Field Value</th></tr>
    """
    for name, value in zip(field_names, field_values):
        safe_name = (name or "").replace("<", "&lt;").replace(">", "&gt;")
        safe_val = (value or "").replace("<", "&lt;").replace(">", "&gt;")
        pdf_html += f"<tr><td>{safe_name}</td><td>{safe_val}</td></tr>"
    pdf_html += "</table></body></html>"

    pdf_filename = f"RFQ_{safe_project_name}_{lead_id}.pdf"

    try:
        pdf_bytes = pdfkit.from_string(pdf_html, False, configuration=PDFKIT_CONFIG)
    except Exception as e:
        return f"PDF generation failed: {e}", 500

    pdf_base64 = base64.b64encode(pdf_bytes).decode('utf-8')

    # Odoo authentication
    auth_payload = {"jsonrpc": "2.0", "method": "call",
                    "params": {"service": "common", "method": "authenticate",
                               "args": [ODOO_DB, ODOO_EMAIL, ODOO_API_KEY, {}]}, "id": 1}
    try:
        auth_resp = requests.post(ODOO_RPC_URL, json=auth_payload, timeout=30).json()
        uid = auth_resp.get("result")
    except Exception as e:
        return f"Odoo auth failed: {e}", 500

    # Attachment upload
    attach_payload = {"jsonrpc": "2.0", "method": "call",
                      "params": {"service": "object", "method": "execute_kw",
                                 "args": [ODOO_DB, uid, ODOO_API_KEY, "ir.attachment", "create",
                                          [{"name": pdf_filename, "type": "binary",
                                            "datas": pdf_base64, "res_model": RES_MODEL,
                                            "res_id": lead_id, "mimetype": "application/pdf"}]]},
                      "id": 2}
    try:
        attach_resp = requests.post(ODOO_RPC_URL, json=attach_payload, timeout=30).json()
        attachment_id = attach_resp.get("result")
    except Exception as e:
        return f"Attachment upload failed: {e}", 500

    # Send email
    try:
        recipients = "rahul.prasad@stratvals.com, rahul.prasad@strategysolutions.com"
        email_payload = {"jsonrpc": "2.0", "method": "call",
                         "params": {"service": "object", "method": "execute_kw",
                                    "args": [ODOO_DB, uid, ODOO_API_KEY, "mail.mail", "create",
                                             [{"subject": f"RFQ Document for {project_name}",
                                               "body_html": f"<p>Please find attached RFQ for <b>{project_name}</b>.</p>",
                                               "email_to": recipients,
                                               "attachment_ids": [(6, 0, [attachment_id])]}]]},
                         "id": 3}
        mail_id = requests.post(ODOO_RPC_URL, json=email_payload, timeout=30).json().get("result")
        send_payload = {"jsonrpc": "2.0", "method": "call",
                        "params": {"service": "object", "method": "execute_kw",
                                   "args": [ODOO_DB, uid, ODOO_API_KEY, "mail.mail", "send", [[mail_id]]]},
                        "id": 4}
        requests.post(ODOO_RPC_URL, json=send_payload, timeout=30)
    except Exception as e:
        print("⚠️ Failed to send email:", e)

    return send_file(io.BytesIO(pdf_bytes), download_name=pdf_filename, as_attachment=True)

# ---------------- Main ----------------
if __name__ == "__main__":
    print("🚀 Flask server running on http://0.0.0.0:5000")
    app.run(host="0.0.0.0", port=5000, debug=True)
